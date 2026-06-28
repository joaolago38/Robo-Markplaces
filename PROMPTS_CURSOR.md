Crie um agente de observabilidade que mede, para CADA marketplace
(ML, Bling, Shopee, Magalu, Amazon), a sequência de verificações sem
quebra da cadeia de token (probe de conexão usando o token
atualmente configurado — sem forçar renovação), grava essa série
histórica (streak atual, maior streak já visto, falhas consecutivas),
envia log estruturado pro Datadog a cada execução, e alerta o gestor
ANTES que a "surpresa" aconteça (ou seja, no primeiro sinal de quebra,
não depois de já ter causado problema operacional). Aplique
literalmente. Crie a branch `feature/agente-saude-tokens` antes de
começar. Se algo não bater exatamente com o arquivo atual, pare e
mostre o trecho real antes de aplicar.

═══════════════════════════════════════════════════════════════
DECISÃO DE DESIGN — IMPORTANTE, NÃO MUDAR
═══════════════════════════════════════════════════════════════

Este agente NÃO deve chamar get_token_ml()/get_token_bling()/etc. com
`forcar=True`, e não deve fazer nada que force uma renovação. Ele só
chama as funções `probe_conexao()` (ou `probe_produtos()` no caso do
Bling, que não tem `probe_conexao`) de cada cliente — essas funções
usam o token JÁ CONFIGURADO no ambiente, sem disparar renovação. Isso é
proposital: se o agente forçasse renovação a cada execução (e ele vai
rodar com frequência), ele mesmo causaria rotação desnecessária de
refresh_token e poderia ser a causa do problema que deveria estar
monitorando.

A leitura correta do sinal é: "o token que está configurado AGORA
funciona?" — se sim, a cadeia de renovação anterior funcionou e
sincronizou corretamente. Se não (401/erro), a cadeia quebrou em algum
ponto anterior (renovação falhou, ou renovou mas não sincronizou no
Secret) — e é exatamente isso que deve gerar alerta.

═══════════════════════════════════════════════════════════════
PASSO 1 — core/saude_tokens.py (novo arquivo: estado persistido)
═══════════════════════════════════════════════════════════════

Seguir o mesmo padrão de `core/marketplace_keepalive.py` (arquivo JSON
em `logs/`), mas guardando sequência/streak por provider, não só
timestamp:

```python
"""
core/saude_tokens.py
Histórico de saúde da cadeia de renovação de token, por marketplace.
Mede sequência de verificações sem quebra (streak), maior streak já
visto, e falhas consecutivas — para detectar degradação antes que
vire problema operacional. Nunca lança exceção.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("saude_tokens")

ROOT = Path(__file__).parent.parent
STATE_FILE = ROOT / "logs" / "saude_tokens.json"


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as exc:
        logger.error("Falha ao ler saude_tokens.json: %s", exc)
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.error("Falha ao gravar saude_tokens.json: %s", exc)


def registrar_verificacao(provider: str, ok: bool, detalhe: str = "") -> dict:
    """
    Atualiza o estado de um provider após uma verificação (probe) e
    devolve o registro atualizado:
        {
          "ok": bool,
          "detalhe": str,
          "ultima_verificacao": iso8601,
          "sequencia_atual": int,       # verificações OK consecutivas
          "maior_sequencia": int,       # maior streak já visto
          "falhas_consecutivas": int,
          "houve_quebra_agora": bool,   # True só no instante em que streak > 0 zera
        }
    Nunca lança exceção.
    """
    state = _load_state()
    anterior = state.get(provider, {})
    seq_anterior = int(anterior.get("sequencia_atual", 0) or 0)
    maior_anterior = int(anterior.get("maior_sequencia", 0) or 0)
    falhas_anteriores = int(anterior.get("falhas_consecutivas", 0) or 0)

    houve_quebra_agora = bool(ok is False and seq_anterior > 0)

    if ok:
        seq_atual = seq_anterior + 1
        falhas_atual = 0
    else:
        seq_atual = 0
        falhas_atual = falhas_anteriores + 1

    maior_atual = max(maior_anterior, seq_atual)

    registro = {
        "ok": bool(ok),
        "detalhe": str(detalhe or "")[:300],
        "ultima_verificacao": datetime.now(timezone.utc).isoformat(),
        "sequencia_atual": seq_atual,
        "maior_sequencia": maior_atual,
        "falhas_consecutivas": falhas_atual,
        "houve_quebra_agora": houve_quebra_agora,
    }

    state[provider] = registro
    _save_state(state)
    return registro


def obter_estado_completo() -> dict:
    """Devolve o estado atual de todos os providers já registrados. Nunca lança exceção."""
    return _load_state()
```

═══════════════════════════════════════════════════════════════
PASSO 2 — agentes/observabilidade/agente_saude_tokens.py (novo)
═══════════════════════════════════════════════════════════════

Criar a pasta `agentes/observabilidade/` com `__init__.py` vazio, e o
agente:

```python
"""
agentes/observabilidade/agente_saude_tokens.py
Verifica, para cada marketplace, se o token atualmente configurado
ainda autentica (sem forçar renovação), atualiza a sequência histórica
de verificações sem quebra, loga estruturado para o Datadog, e alerta
o gestor no instante em que uma sequência se quebra ou em que falhas
se acumulam — antes que isso vire um problema operacional silencioso.
"""
from __future__ import annotations

import logging

from core.saude_tokens import registrar_verificacao
from core.notificador import alertar_critico
from integracoes.ml import ml_client
from integracoes.bling import bling_client
from integracoes.shopee import shopee_client
from integracoes.magalu import magalu_client
from integracoes.amazon import amazon_client

logger = logging.getLogger("agente_saude_tokens")

LIMITE_FALHAS_PARA_ALERTA = 2  # alerta já na 2ª falha consecutiva, não espera acumular


def _probe(provider: str) -> dict:
    """Executa o probe correto por provider. Nunca lança exceção."""
    try:
        if provider == "bling":
            r = bling_client.probe_produtos()
        elif provider == "mercadolivre":
            r = ml_client.probe_conexao()
        elif provider == "shopee":
            r = shopee_client.probe_conexao()
        elif provider == "magalu":
            r = magalu_client.probe_conexao()
        elif provider == "amazon":
            r = amazon_client.probe_conexao()
        else:
            return {"ok": False, "msg": f"provider desconhecido: {provider}"}
        return r if isinstance(r, dict) else {"ok": False, "msg": "resposta inesperada do probe"}
    except Exception as exc:
        logger.error("Probe de %s levantou exceção: %s", provider, exc)
        return {"ok": False, "msg": str(exc)}


def verificar_provider(provider: str) -> dict:
    """
    Roda o probe de um provider, atualiza o histórico de sequência, loga
    estruturado, e alerta se necessário. Devolve o registro atualizado.
    Nunca lança exceção.
    """
    resultado_probe = _probe(provider)
    ok = bool(resultado_probe.get("ok"))
    detalhe = str(resultado_probe.get("msg", "") or resultado_probe.get("status", ""))

    registro = registrar_verificacao(provider, ok, detalhe)

    logger.info(
        "saude_token provider=%s ok=%s sequencia_atual=%s maior_sequencia=%s "
        "falhas_consecutivas=%s houve_quebra_agora=%s detalhe=%s",
        provider,
        registro["ok"],
        registro["sequencia_atual"],
        registro["maior_sequencia"],
        registro["falhas_consecutivas"],
        registro["houve_quebra_agora"],
        registro["detalhe"],
    )

    if registro["houve_quebra_agora"]:
        alertar_critico(
            f"⚠️ Token de {provider} parou de autenticar agora (sequência anterior "
            f"quebrada). Detalhe: {registro['detalhe']}. Verifique a renovação/sync "
            f"do refresh_token antes que afete operações."
        )
    elif registro["falhas_consecutivas"] >= LIMITE_FALHAS_PARA_ALERTA:
        alertar_critico(
            f"🚨 Token de {provider} sem autenticar há {registro['falhas_consecutivas']} "
            f"verificações consecutivas. Detalhe: {registro['detalhe']}."
        )

    return registro


PROVIDERS = ["mercadolivre", "bling", "shopee", "magalu", "amazon"]


def executar() -> dict:
    """Entrada para cron/workflow — verifica todos os providers. Nunca lança exceção."""
    logger.info("=== Agente de saúde dos tokens (sequência sem quebra) ===")
    resultados: dict[str, dict] = {}
    for provider in PROVIDERS:
        resultados[provider] = verificar_provider(provider)
    return resultados


def main() -> int:
    resultados = executar()
    falhou_algum = any(not r.get("ok") for r in resultados.values())
    return 1 if falhou_algum else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

═══════════════════════════════════════════════════════════════
PASSO 3 — core/datadog_logger.py: registrar o novo logger
═══════════════════════════════════════════════════════════════

No dict `_MARKETPLACE_POR_LOGGER`, adicionar:

```python
    "agente_saude_tokens": "saude_tokens_todos_marketplaces",
    "saude_tokens": "saude_tokens_todos_marketplaces",
```

(mantendo todas as entradas já existentes — só adicionar essas 2 linhas)

═══════════════════════════════════════════════════════════════
PASSO 4 — Workflow dedicado, rodando com frequência, com persistência
real do histórico entre execuções
═══════════════════════════════════════════════════════════════

IMPORTANTE: `logs/saude_tokens.json` precisa sobreviver entre execuções
do GitHub Actions (cada execução é um runner novo, sem disco
compartilhado) — senão a "sequência" reseta toda hora e a métrica não
significa nada. A solução é o próprio workflow commitar o arquivo
atualizado de volta no repositório a cada execução.

Criar `.github/workflows/saude_tokens.yml`:

```yaml
name: Saude dos Tokens (todos marketplaces)

on:
  workflow_dispatch:
  schedule:
    # a cada 30 minutos
    - cron: "*/30 * * * *"

permissions:
  contents: write

env:
  PYTHON_VERSION: "3.11"
  DD_API_KEY: ${{ secrets.DD_API_KEY }}
  DD_SITE: ${{ secrets.DD_SITE }}
  DD_LOGS_ENABLED: ${{ secrets.DD_LOGS_ENABLED }}

jobs:
  saude_tokens:
    name: Verificar sequencia sem quebra de token (ML, Bling, Shopee, Magalu, Amazon)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip

      - name: Instalar dependencias
        run: pip install -r requirements.txt

      - name: Rodar agente de saude dos tokens
        run: python -m agentes.observabilidade.agente_saude_tokens
        env:
          GH_TOKEN: ${{ secrets.GH_TOKEN }}
          GH_REPO: ${{ github.repository }}
          ML_ACCESS_TOKEN:      ${{ secrets.ML_ACCESS_TOKEN }}
          ML_REFRESH_TOKEN:     ${{ secrets.ML_REFRESH_TOKEN }}
          ML_SELLER_ID:         ${{ secrets.ML_SELLER_ID }}
          BLING_ACCESS_TOKEN:   ${{ secrets.BLING_ACCESS_TOKEN }}
          BLING_CLIENT_ID:      ${{ secrets.BLING_CLIENT_ID }}
          BLING_CLIENT_SECRET:  ${{ secrets.BLING_CLIENT_SECRET }}
          SHOPEE_PARTNER_ID:    ${{ secrets.SHOPEE_PARTNER_ID }}
          SHOPEE_PARTNER_KEY:   ${{ secrets.SHOPEE_PARTNER_KEY }}
          SHOPEE_SHOP_ID:       ${{ secrets.SHOPEE_SHOP_ID }}
          SHOPEE_ACCESS_TOKEN:  ${{ secrets.SHOPEE_ACCESS_TOKEN }}
          SHOPEE_REFRESH_TOKEN: ${{ secrets.SHOPEE_REFRESH_TOKEN }}
          MAGALU_ACCESS_TOKEN:  ${{ secrets.MAGALU_ACCESS_TOKEN }}
          MAGALU_REFRESH_TOKEN: ${{ secrets.MAGALU_REFRESH_TOKEN }}
          MAGALU_MERCHANT_ID:   ${{ secrets.MAGALU_MERCHANT_ID }}
          AMAZON_ACCESS_TOKEN:  ${{ secrets.AMAZON_ACCESS_TOKEN }}
          TELEGRAM_TOKEN:           ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_GESTOR_CHAT_ID:  ${{ secrets.TELEGRAM_GESTOR_CHAT_ID }}
          TELEGRAM_CHAT_ID:         ${{ secrets.TELEGRAM_CHAT_ID }}

      - name: Persistir historico de sequencia (commit do logs/saude_tokens.json)
        run: |
          git config user.name "robo-markplaces-bot"
          git config user.email "actions@users.noreply.github.com"
          git add logs/saude_tokens.json
          git diff --cached --quiet || git commit -m "chore: atualiza saude_tokens.json [skip ci]"
          git push
```

Adicione `[skip ci]` exatamente como mostrado, para esse commit
automático não disparar outros workflows em loop.

═══════════════════════════════════════════════════════════════
PASSO 5 — Testes (cobertura ≥ 90%, mesmo padrão já adotado no projeto)
═══════════════════════════════════════════════════════════════

Criar `tests/test_saude_tokens.py`:

- `registrar_verificacao` com `ok=True` repetido 3x incrementa
  `sequencia_atual` 1,2,3 e mantém `falhas_consecutivas=0`.
- `ok=False` após uma sequência positiva zera `sequencia_atual`,
  incrementa `falhas_consecutivas`, e marca `houve_quebra_agora=True`
  só nessa transição (não nas falhas seguintes).
- `ok=False` repetido (já sem sequência prévia) NÃO marca
  `houve_quebra_agora=True` de novo — só na transição inicial.
- `maior_sequencia` nunca diminui mesmo após quebra.
- Estado persiste corretamente entre chamadas (usar `tmp_path`/
  monkeypatch no `STATE_FILE`, não escrever no repo de verdade).
- Arquivo JSON corrompido ou ausente -> `_load_state` devolve `{}`,
  sem lançar exceção.

Criar `tests/test_agente_saude_tokens.py`:

- `verificar_provider` para cada um dos 5 providers chama o probe
  certo (mockar `ml_client.probe_conexao`, `bling_client.probe_produtos`,
  `shopee_client.probe_conexao`, `magalu_client.probe_conexao`,
  `amazon_client.probe_conexao` individualmente) e NUNCA chama
  `get_token_*` nem qualquer função de renovação — testar isso
  explicitamente (mockar e afirmar que não foi chamado).
- Quando o probe levanta exceção, `verificar_provider` não propaga
  (captura e trata como falha).
- `alertar_critico` é chamado quando `houve_quebra_agora=True`.
- `alertar_critico` é chamado quando `falhas_consecutivas >= 2`, mesmo
  sem quebra "agora" (cenário de degradação persistente).
- `alertar_critico` NÃO é chamado quando está tudo ok.
- `executar()` roda os 5 providers e devolve dict com 5 chaves.
- `main()` devolve `1` se qualquer provider falhou, `0` se todos ok.

Rodar no final:

```bash
pytest -q
ruff check .
```

═══════════════════════════════════════════════════════════════
NÃO FAZER (fora de escopo)
═══════════════════════════════════════════════════════════════

- Não chamar `get_token_*`/`_renovar_token_*` de nenhum provider —
  reforçando o Passo de design acima.
- Não duplicar a lógica de `core/marketplace_keepalive.py` — são
  propósitos diferentes (keepalive = "faz tempo que não chamamos a
  API"; saude_tokens = "sequência sem quebra de autenticação").
- Não mexer em nenhum cliente de marketplace (`ml_client.py`,
  `bling_client.py`, etc.) — eles só são consumidos via
  `probe_conexao`/`probe_produtos`, que já existem.

═══════════════════════════════════════════════════════════════
CHECKLIST FINAL
═══════════════════════════════════════════════════════════════

- [ ] Branch `feature/agente-saude-tokens` criada
- [ ] `core/saude_tokens.py` criado e testado
- [ ] `agentes/observabilidade/agente_saude_tokens.py` criado e testado
- [ ] `core/datadog_logger.py` atualizado (2 linhas no dict)
- [ ] `.github/workflows/saude_tokens.yml` criado, com `permissions: contents: write`
      e step de commit do `logs/saude_tokens.json`
- [ ] Testes novos passando
- [ ] Cobertura total ≥ 90%
- [ ] `ruff check .` sem erros
- [ ] `git diff --stat` colado para revisão antes de qualquer commit