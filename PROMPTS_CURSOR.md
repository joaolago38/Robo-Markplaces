Implemente as Etapas 1 e 2 do modo multi-tenant (toggle), e NADA além
disso — sem tocar em agendamento, sem tocar em catálogo por loja, sem
tocar em nenhum agente/integração existente. Crie a branch
`feature/multi-tenant-toggle-etapa-1-2` antes de começar. Se algo não
bater exatamente com o arquivo atual, pare e mostre o trecho real antes
de aplicar.

═══════════════════════════════════════════════════════════════
GARANTIA OBRIGATÓRIA (não é opcional — é o requisito principal deste prompt)
═══════════════════════════════════════════════════════════════

A operação atual da loja de esmaltes NÃO PODE mudar em nenhuma hipótese.
Isso precisa ser verdade por construção, não por promessa:

1. Os dois arquivos novos (`core/tenant_context.py` e
   `core/config_resolver.py`) não são importados por NENHUM agente,
   integração ou script existente neste prompt. Eles só existem como
   base — ninguém os chama ainda. Logo, é estruturalmente impossível
   que mudem o comportamento de hoje.
2. Mesmo que algo importe esses módulos no futuro, com
   `ROBO_MULTI_TENANT` ausente ou diferente de `"true"` (o padrão), o
   sistema deve devolver SEMPRE o tenant fixo `"esmaltes"` e SEMPRE os
   valores de `core/config.py` como já são lidos hoje — sem exceção.
3. Ao final, rode a suíte de testes completa (`pytest -q`) e confirme
   que os 626 testes que já existiam continuam passando, sem nenhuma
   alteração de comportamento neles. Cole o resultado.

═══════════════════════════════════════════════════════════════
ETAPA 1 — core/tenant_context.py (novo arquivo)
═══════════════════════════════════════════════════════════════

Criar `core/tenant_context.py`:

```python
"""
core/tenant_context.py
Contexto de tenant (loja) — base para suportar múltiplas lojas no
futuro, SEM alterar o comportamento atual.

Trava de segurança: enquanto ROBO_MULTI_TENANT não for exatamente a
string "true", tenant_atual() sempre devolve TENANT_PADRAO ("esmaltes").
Não existe, neste módulo, nenhum caminho de código que rode outra loja
sem essa flag estar explicitamente ligada.
"""
from __future__ import annotations

import os

TENANT_PADRAO = "esmaltes"


def multi_tenant_ativo() -> bool:
    """True somente se ROBO_MULTI_TENANT estiver definida como 'true' (case-insensitive)."""
    return (os.getenv("ROBO_MULTI_TENANT", "") or "").strip().lower() == "true"


def tenant_atual() -> str:
    """
    Devolve o tenant ativo no processo atual.

    - Multi-tenant desligado (padrão) -> sempre TENANT_PADRAO, ignorando
      qualquer outra variável de ambiente. Esta é a trava de segurança
      que garante que a loja de esmaltes nunca seja afetada por engano.
    - Multi-tenant ligado -> lê ROBO_TENANT_ATUAL; se vazio, cai em
      TENANT_PADRAO também.
    """
    if not multi_tenant_ativo():
        return TENANT_PADRAO
    valor = (os.getenv("ROBO_TENANT_ATUAL", "") or "").strip()
    return valor or TENANT_PADRAO
```

═══════════════════════════════════════════════════════════════
ETAPA 2 — core/config_resolver.py (novo arquivo)
═══════════════════════════════════════════════════════════════

Criar `core/config_resolver.py`:

```python
"""
core/config_resolver.py
Camada de resolução de configuração "tenant-aware", com fallback total
para core/config.py quando o modo multi-tenant está desligado ou quando
o tenant é o padrão (esmaltes).

IMPORTANTE: este módulo não troca, remove nem reescreve nenhuma
variável de core/config.py. Ele só oferece uma forma OPCIONAL de buscar
valor por tenant — e hoje nenhum outro módulo do projeto chama
`obter_config`, então isso não tem efeito algum na operação atual.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import core.config as cfg
from core.tenant_context import TENANT_PADRAO, multi_tenant_ativo, tenant_atual

logger = logging.getLogger("config_resolver")

ROOT = Path(__file__).parent.parent
TENANTS_DIR = ROOT / "tenants"


def _config_tenant(tenant_id: str) -> dict:
    """
    Lê o override de config de um tenant em tenants/{tenant_id}/config.json.
    Se o arquivo não existir ou estiver corrompido, devolve {} (sem
    override -> quem chamou cai no valor de core/config.py).
    Nunca lança exceção.
    """
    caminho = TENANTS_DIR / tenant_id / "config.json"
    if not caminho.is_file():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except Exception as exc:
        logger.error("Falha ao ler config do tenant %s: %s", tenant_id, exc)
        return {}


def obter_config(nome_var: str, tenant_id: str | None = None) -> str:
    """
    Resolve um valor de configuração (ex.: "ML_ACCESS_TOKEN").

    Ordem de resolução:
      1. Multi-tenant desligado            -> cfg.<nome_var> (idêntico a hoje)
      2. tenant == TENANT_PADRAO ("esmaltes") -> cfg.<nome_var> (idêntico a hoje)
      3. Outro tenant, com override válido em tenants/{tenant_id}/config.json -> usa o override
      4. Outro tenant, sem override         -> cfg.<nome_var> (fallback seguro)

    Nunca lança exceção. Nunca é chamado por nenhum agente/integração
    nesta etapa — existe só como base para a próxima etapa.
    """
    tid = (tenant_id or tenant_atual()).strip() or TENANT_PADRAO
    valor_padrao = getattr(cfg, nome_var, "")

    if not multi_tenant_ativo() or tid == TENANT_PADRAO:
        return valor_padrao

    overrides = _config_tenant(tid)
    valor_override = overrides.get(nome_var)
    if valor_override:
        return valor_override
    return valor_padrao
```

═══════════════════════════════════════════════════════════════
ETAPA 3 — Documentação mínima (não é código de execução, só explica o toggle)
═══════════════════════════════════════════════════════════════

3a. Adicionar ao `.env.example` (criar o arquivo se não existir, só com
estas 2 linhas comentadas — não sobrescrever um `.env.example` existente
com conteúdo, só adicionar ao final):

```
# Multi-tenant (em construção — manter desligado em produção por enquanto)
# ROBO_MULTI_TENANT=false
# ROBO_TENANT_ATUAL=esmaltes
```

3b. Adicionar uma seção curta no README, perto de outras seções de
configuração, explicando: "Em desenvolvimento: suporte a múltiplas
lojas via `ROBO_MULTI_TENANT`. Desligado por padrão — a operação atual
(loja única, esmaltes) não é afetada. Ainda não há nenhum agente
usando esse modo."

═══════════════════════════════════════════════════════════════
ETAPA 4 — Testes (obrigatório manter cobertura ≥ 90%)
═══════════════════════════════════════════════════════════════

Criar `tests/test_tenant_context.py`:

- `multi_tenant_ativo()` é `False` quando `ROBO_MULTI_TENANT` não está
  definida.
- `multi_tenant_ativo()` é `False` para valores como `"1"`, `"TRUE "`
  com espaço sobrando tratado, `"sim"` — só `"true"` (case-insensitive,
  sem espaço) deve ativar. Testar esse limite explicitamente.
- `tenant_atual()` devolve `"esmaltes"` mesmo se `ROBO_TENANT_ATUAL`
  estiver definida, quando `ROBO_MULTI_TENANT` está desligada — este é
  o teste mais importante do arquivo, é a prova da trava de segurança.
- Com `ROBO_MULTI_TENANT=true` e `ROBO_TENANT_ATUAL=loja_x`,
  `tenant_atual()` devolve `"loja_x"`.
- Com `ROBO_MULTI_TENANT=true` e `ROBO_TENANT_ATUAL` vazia,
  `tenant_atual()` cai em `"esmaltes"`.

Criar `tests/test_config_resolver.py`:

- `obter_config("ANTHROPIC_API_KEY")` com multi-tenant desligado devolve
  exatamente `cfg.ANTHROPIC_API_KEY` (mockar/monkeypatch `cfg` e
  conferir igualdade).
- Com multi-tenant ligado e `tenant_id="esmaltes"`, devolve igual a
  `cfg.<var>` também (a trava vale mesmo com a flag ligada).
- Com multi-tenant ligado e `tenant_id="loja_x"` e um
  `tenants/loja_x/config.json` (usar `tmp_path`/fixture, não escrever
  no repo de verdade) contendo a chave -> devolve o valor do override.
- Mesmo cenário, mas a chave não está no JSON -> cai no valor de
  `cfg.<var>`.
- `tenants/loja_x/config.json` não existe -> cai no valor de `cfg.<var>`,
  sem lançar exceção.
- `tenants/loja_x/config.json` com JSON corrompido -> cai no valor de
  `cfg.<var>`, loga erro, não lança exceção.

Rodar no final:

```bash
pytest -q
ruff check .
```

Cole o resultado. Se a suíte completa (os 626 testes antigos + os novos)
não passar 100%, ou se a cobertura cair abaixo de 90%, pare e me avise
antes de qualquer commit.

═══════════════════════════════════════════════════════════════
NÃO FAZER (fora de escopo deste prompt — propositalmente)
═══════════════════════════════════════════════════════════════

- Não importar `tenant_context` ou `config_resolver` em nenhum agente,
  integração, `api/app.py` ou workflow existente.
- Não criar a pasta `tenants/` de verdade no repositório (ela só
  precisa existir nos testes, via `tmp_path`).
- Não mexer em `core/config.py` — esse arquivo continua exatamente como
  está.
- Não mexer em agendamento (GitHub Actions) nem em catálogo por loja —
  isso é Etapa 3/4 do plano maior, não deste prompt.

═══════════════════════════════════════════════════════════════
CHECKLIST FINAL
═══════════════════════════════════════════════════════════════

- [ ] Branch `feature/multi-tenant-toggle-etapa-1-2` criada
- [ ] `core/tenant_context.py` criado, não importado por mais ninguém
- [ ] `core/config_resolver.py` criado, não importado por mais ninguém
- [ ] `.env.example` e README atualizados (só documentação)
- [ ] Testes novos criados e passando
- [ ] Os 626 testes antigos continuam passando, sem alteração de
      comportamento — confirmar explicitamente
- [ ] Cobertura total ≥ 90%
- [ ] `ruff check .` sem erros
- [ ] `git diff --stat` colado para revisão antes de qualquer commit