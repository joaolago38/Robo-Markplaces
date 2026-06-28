Crie as 3 extensões abaixo (faixa de preço sugerida, radar de
oportunidade de nicho, e o scaffold do painel consolidado de 4 canais),
cada uma atrás do seu próprio toggle, desligado por padrão. Aplique
literalmente, na ordem dos passos. Crie a branch
`feature/extensoes-toggle-preco-nicho-painel` antes de começar. Se algo
não bater exatamente com o arquivo atual, pare e mostre o trecho real
antes de aplicar.

═══════════════════════════════════════════════════════════════
GARANTIA OBRIGATÓRIA (mesmo princípio do toggle multi-tenant)
═══════════════════════════════════════════════════════════════

Com os 3 toggles desligados (padrão), o comportamento atual do robô
não muda em NADA — nenhum agente existente é modificado, e os 3 agentes
novos saem (no-op) na primeira linha se a própria flag estiver
desligada, sem chamar nenhuma API de marketplace. Ao final, confirme
que os testes que já existiam continuam passando sem alteração.

═══════════════════════════════════════════════════════════════
PASSO 1 — core/feature_flags.py (novo arquivo — base para os 3 toggles)
═══════════════════════════════════════════════════════════════

```python
"""
core/feature_flags.py
Toggles de funcionalidades em construção. Cada flag é lida de
ROBO_FEATURE_<NOME> e, por padrão (variável ausente), é considerada
desligada — comportamento seguro por padrão.
"""
from __future__ import annotations

import os


def feature_ativa(nome: str) -> bool:
    """True somente se ROBO_FEATURE_<nome> estiver definida como 'true' (case-insensitive)."""
    return (os.getenv(f"ROBO_FEATURE_{nome}", "") or "").strip().lower() == "true"
```

═══════════════════════════════════════════════════════════════
PASSO 2 — Extensão 1: agentes/precificacao/agente_faixa_preco_sugerida.py
Toggle: ROBO_FEATURE_FAIXA_PRECO_SUGERIDA
Só leitura + sugestão — nunca chama atualizar_preco_item.
═══════════════════════════════════════════════════════════════

Criar a pasta `agentes/precificacao/` com `__init__.py` vazio, e:

```python
"""
agentes/precificacao/agente_faixa_preco_sugerida.py
Sugere uma faixa de preço (piso de margem + média de concorrentes) por
SKU ativo no ML, comparando com o preço atual. Somente leitura e
notificação — NUNCA altera preço. Atrás de feature flag desligada por
padrão (ROBO_FEATURE_FAIXA_PRECO_SUGERIDA).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.config import TAXA_CANAL_PADRAO_PCT, MARGEM_FASE_1_PCT, MARGEM_FASE_2_PCT, MARGEM_FASE_3_PCT
from core.feature_flags import feature_ativa
from core.notificador import alertar_gestor
from integracoes.ml import ml_client

logger = logging.getLogger("agente_faixa_preco_sugerida")

ROOT = Path(__file__).resolve().parent.parent.parent
CATALOGO_PATH = ROOT / "catalogo" / "produtos.json"


def _margem_minima_por_fase(fase_atual) -> float:
    fase = str(fase_atual or "1").strip()
    if fase == "2":
        return MARGEM_FASE_2_PCT
    if fase == "3":
        return MARGEM_FASE_3_PCT
    return MARGEM_FASE_1_PCT


def _calcular_preco_piso(custo: float, taxa_canal_pct: float, margem_minima_pct: float) -> float:
    taxa = max(0.0, min(99.0, taxa_canal_pct)) / 100.0
    margem = max(0.0, min(99.0, margem_minima_pct)) / 100.0
    denominador = 1 - taxa - margem
    if custo <= 0 or denominador <= 0:
        return 0.0
    return custo / denominador


def _carregar_catalogo() -> list[dict]:
    try:
        if not CATALOGO_PATH.is_file():
            logger.warning("catalogo/produtos.json não encontrado")
            return []
        with CATALOGO_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.error("Erro ao carregar catalogo: %s", exc)
        return []


def analisar_sku(produto: dict) -> dict | None:
    """
    Compara preço atual x piso de margem x concorrentes para 1 SKU.
    Devolve dict de sugestão, ou None se não houver item_id ML válido.
    Nunca lança exceção.
    """
    canais = produto.get("canais") or {}
    ml = canais.get("mercadolivre") or {} if isinstance(canais, dict) else {}
    item_id = str(ml.get("item_id") or "").strip()
    if not item_id or "PREENCHER" in item_id.upper() or not ml.get("ativo"):
        return None

    try:
        custo = float(produto.get("custo_total", 0) or 0)
        preco_atual = float(produto.get("preco", 0) or 0)
        margem_min = _margem_minima_por_fase(produto.get("fase_atual"))
        piso = _calcular_preco_piso(custo, TAXA_CANAL_PADRAO_PCT, margem_min)

        concorrentes = ml_client.buscar_detalhes_concorrentes(item_id, limite=5)
        precos_concorrentes = [
            float(c.get("preco", 0) or 0) for c in concorrentes if float(c.get("preco", 0) or 0) > 0
        ]

        media_concorrente = (
            round(sum(precos_concorrentes) / len(precos_concorrentes), 2) if precos_concorrentes else 0.0
        )
        min_concorrente = round(min(precos_concorrentes), 2) if precos_concorrentes else 0.0

        alerta = None
        if piso > 0 and preco_atual < piso:
            alerta = f"preço atual (R$ {preco_atual:.2f}) está ABAIXO do piso de margem (R$ {piso:.2f})"
        elif media_concorrente > 0 and preco_atual > media_concorrente * 1.15:
            alerta = (
                f"preço atual (R$ {preco_atual:.2f}) está 15%+ acima da média dos "
                f"concorrentes (R$ {media_concorrente:.2f}) — risco de perder competitividade"
            )

        return {
            "sku": produto.get("sku", ""),
            "item_id": item_id,
            "preco_atual": preco_atual,
            "piso_margem": piso,
            "media_concorrente": media_concorrente,
            "min_concorrente": min_concorrente,
            "concorrentes_analisados": len(precos_concorrentes),
            "alerta": alerta,
        }
    except Exception as exc:
        logger.error("analisar_sku erro sku=%s: %s", produto.get("sku"), exc)
        return None


def _montar_resumo(analises: list[dict]) -> str:
    relevantes = [a for a in analises if a.get("alerta")]
    if not relevantes:
        return "💰 Faixa de preço sugerida — Robo-Markplaces\n\nNenhum SKU fora da faixa recomendada hoje."
    linhas = ["💰 Faixa de preço sugerida — Robo-Markplaces", ""]
    for a in relevantes:
        linhas.append(f"• {a['sku']} ({a['item_id']})")
        linhas.append(f"  {a['alerta']}")
        linhas.append("")
    return "\n".join(linhas).strip()


def executar() -> dict:
    """Entrada para cron/workflow. Nunca lança exceção."""
    if not feature_ativa("FAIXA_PRECO_SUGERIDA"):
        logger.info("Feature FAIXA_PRECO_SUGERIDA desligada — nada a fazer.")
        return {"ok": True, "ativo": False}

    logger.info("=== Agente de faixa de preço sugerida (somente leitura) ===")
    catalogo = _carregar_catalogo()
    analises = [a for a in (analisar_sku(p) for p in catalogo if isinstance(p, dict)) if a is not None]

    msg = _montar_resumo(analises)
    alerta_enviado = bool(alertar_gestor(msg))

    return {"ok": True, "ativo": True, "total_analisados": len(analises), "alerta_enviado": alerta_enviado}


def main() -> int:
    resultado = executar()
    return 0 if resultado.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

═══════════════════════════════════════════════════════════════
PASSO 3 — Extensão 2: agentes/inteligencia/agente_radar_nicho.py
Toggle: ROBO_FEATURE_RADAR_NICHO
Só leitura + notificação. Score simples e explícito, sem prometer
precisão que a API não entrega.
═══════════════════════════════════════════════════════════════

3a. Adicionar em `spec/spec.yaml`, no final do arquivo:

```yaml
radar_nicho:
  termos:
    - "esmalte impala"
    - "kit esmalte"
    - "removedor esmalte"
  limite_concorrentes_por_termo: 10
  vendas_concorrente_forte: 500   # quantidade_vendida acima disso conta como "concorrente forte"
  score_minimo_para_alertar: 0.5
```

3b. Criar a pasta `agentes/inteligencia/` com `__init__.py` vazio, e:

```python
"""
agentes/inteligencia/agente_radar_nicho.py
Varre termos de busca do nicho configurado e calcula um score simples
de oportunidade: quanto menos concorrentes "fortes" (alto volume de
vendas) aparecerem pra um termo, maior o score. NÃO mede volume de
busca real (a API do ML não expõe isso) — é um proxy de saturação de
oferta, não de demanda. Atrás de feature flag desligada por padrão
(ROBO_FEATURE_RADAR_NICHO).
"""
from __future__ import annotations

import logging

from core.config import SPEC
from core.feature_flags import feature_ativa
from core.notificador import alertar_gestor
from integracoes.ml import ml_client

logger = logging.getLogger("agente_radar_nicho")

_CONFIG_RADAR = SPEC.get("radar_nicho", {}) if isinstance(SPEC, dict) else {}
TERMOS = _CONFIG_RADAR.get("termos") or []
LIMITE_POR_TERMO = int(_CONFIG_RADAR.get("limite_concorrentes_por_termo", 10) or 10)
VENDAS_CONCORRENTE_FORTE = int(_CONFIG_RADAR.get("vendas_concorrente_forte", 500) or 500)
SCORE_MINIMO_ALERTA = float(_CONFIG_RADAR.get("score_minimo_para_alertar", 0.5) or 0.5)


def analisar_termo(termo: str) -> dict:
    """
    Busca um termo no ML e calcula o score de oportunidade.
    score = 1 / (1 + numero_de_concorrentes_fortes)
    Nunca lança exceção.
    """
    try:
        resultados = ml_client.buscar_concorrentes_por_termo(termo, limite=LIMITE_POR_TERMO)
        fortes = [
            r for r in resultados if int(r.get("quantidade_vendida", 0) or 0) >= VENDAS_CONCORRENTE_FORTE
        ]
        score = round(1.0 / (1 + len(fortes)), 3)
        return {
            "termo": termo,
            "total_resultados": len(resultados),
            "concorrentes_fortes": len(fortes),
            "score": score,
        }
    except Exception as exc:
        logger.error("analisar_termo erro termo=%s: %s", termo, exc)
        return {"termo": termo, "total_resultados": 0, "concorrentes_fortes": 0, "score": 0.0, "erro": str(exc)}


def _montar_resumo(analises: list[dict]) -> str:
    relevantes = [a for a in analises if a.get("score", 0) >= SCORE_MINIMO_ALERTA]
    if not relevantes:
        return "🧭 Radar de oportunidade de nicho — Robo-Markplaces\n\nNenhum termo com sinal de oportunidade hoje."
    linhas = ["🧭 Radar de oportunidade de nicho — Robo-Markplaces", ""]
    for a in sorted(relevantes, key=lambda x: x["score"], reverse=True):
        linhas.append(f"• {a['termo']} — score {a['score']} ({a['concorrentes_fortes']} concorrentes fortes)")
    return "\n".join(linhas).strip()


def executar() -> dict:
    """Entrada para cron/workflow. Nunca lança exceção."""
    if not feature_ativa("RADAR_NICHO"):
        logger.info("Feature RADAR_NICHO desligada — nada a fazer.")
        return {"ok": True, "ativo": False}

    if not TERMOS:
        logger.warning("radar_nicho.termos vazio em spec.yaml — nada a analisar.")
        return {"ok": True, "ativo": True, "total_termos": 0}

    logger.info("=== Agente radar de oportunidade de nicho (somente leitura) ===")
    analises = [analisar_termo(t) for t in TERMOS]
    msg = _montar_resumo(analises)
    alerta_enviado = bool(alertar_gestor(msg))

    return {"ok": True, "ativo": True, "total_termos": len(analises), "alerta_enviado": alerta_enviado}


def main() -> int:
    resultado = executar()
    return 0 if resultado.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

═══════════════════════════════════════════════════════════════
PASSO 4 — Extensão 3 (SCAFFOLD, não a feature completa):
agentes/panorama/agente_panorama.py
Toggle: ROBO_FEATURE_PAINEL_4_CANAIS
═══════════════════════════════════════════════════════════════

IMPORTANTE: hoje só o `ml_client` tem uma função de status por anúncio
(`obter_status_anuncio`). Shopee, Magalu e Amazon ainda não têm
equivalente — então este passo é DELIBERADAMENTE só o scaffold (toggle
+ checagem de pré-requisito), não o painel completo. O painel real
(por SKU, nos 4 canais) é uma etapa futura, depois que Amazon/Shopee
tiverem token resolvido E as funções de status por anúncio existirem
nesses 3 clientes.

Adicionar em `agentes/panorama/agente_panorama.py` (sem remover nada
existente), uma função nova:

```python
def _resumo_conectividade_4_canais() -> dict | None:
    """
    Scaffold da Extensão 3 (painel consolidado). Hoje só verifica
    conectividade (probe) dos 4 canais — NÃO é o painel por SKU, que
    depende de Amazon/Shopee terem token resolvido e funções de status
    por anúncio equivalentes às do ML. Atrás de feature flag
    (ROBO_FEATURE_PAINEL_4_CANAIS). Nunca lança exceção.
    """
    from core.feature_flags import feature_ativa

    if not feature_ativa("PAINEL_4_CANAIS"):
        return None

    from integracoes.ml import ml_client
    from integracoes.shopee import shopee_client
    from integracoes.magalu import magalu_client
    from integracoes.amazon import amazon_client

    canais = {
        "mercadolivre": ml_client,
        "shopee": shopee_client,
        "magalu": magalu_client,
        "amazon": amazon_client,
    }
    resultado = {}
    for nome, cliente in canais.items():
        try:
            resultado[nome] = cliente.probe_conexao()
        except Exception as exc:
            resultado[nome] = {"ok": False, "msg": str(exc)}
    return resultado
```

Chamar essa função dentro do fluxo já existente de `agente_panorama.py`
(no ponto que fizer mais sentido junto ao restante do relatório), e
incluir o resultado no relatório final SOMENTE quando não for `None`
(ou seja, só aparece no relatório se a flag estiver ligada — se estiver
desligada, o relatório fica idêntico ao de hoje).

═══════════════════════════════════════════════════════════════
PASSO 5 — Documentação e .env.example
═══════════════════════════════════════════════════════════════

Adicionar ao `.env.example`:

```
# Extensões em construção (desligadas por padrão)
# ROBO_FEATURE_FAIXA_PRECO_SUGERIDA=false
# ROBO_FEATURE_RADAR_NICHO=false
# ROBO_FEATURE_PAINEL_4_CANAIS=false
```

═══════════════════════════════════════════════════════════════
PASSO 6 — Workflows (criados, mas inofensivos com toggle desligado)
═══════════════════════════════════════════════════════════════

Criar `.github/workflows/faixa_preco_sugerida.yml` e
`.github/workflows/radar_nicho.yml`, seguindo exatamente o mesmo
formato de `.github/workflows/otimizar_listing.yml` (mesmas envs de
ML_*, TELEGRAM_*, DD_*), trocando só o `cron` (sugestão: 1x por dia
pros dois) e o comando (`python -m agentes.precificacao.agente_faixa_preco_sugerida`
e `python -m agentes.inteligencia.agente_radar_nicho`). Como o agente
sai imediatamente se a flag estiver desligada, esses workflows não têm
custo nem risco mesmo antes de você decidir ativar.

═══════════════════════════════════════════════════════════════
PASSO 7 — Testes (cobertura ≥ 90%)
═══════════════════════════════════════════════════════════════

Criar `tests/test_feature_flags.py`:
- `feature_ativa` é `False` por padrão (env ausente).
- `feature_ativa` só é `True` com valor exatamente `"true"` (case-insensitive).

Criar `tests/test_agente_faixa_preco_sugerida.py`:
- `executar()` com flag desligada devolve `{"ok": True, "ativo": False}`
  e NÃO chama `ml_client.buscar_detalhes_concorrentes` nem `alertar_gestor`
  (mockar e afirmar não-chamado).
- `_calcular_preco_piso`: custo zero, denominador zero/negativo (margem+taxa >= 100%) -> 0.0.
- `analisar_sku`: sem item_id válido -> `None`; preço abaixo do piso -> alerta de piso;
  preço 15%+ acima da média -> alerta de competitividade; preço dentro da faixa -> sem alerta.
- `executar()` com flag ligada (mockar catálogo e `ml_client`) chama `alertar_gestor` uma vez.

Criar `tests/test_agente_radar_nicho.py`:
- `executar()` com flag desligada não chama `buscar_concorrentes_por_termo`.
- `analisar_termo`: 0 concorrentes fortes -> score 1.0; vários concorrentes fortes -> score menor.
- `_montar_resumo`: nenhum termo acima do score mínimo -> mensagem de "nenhum sinal".
- `executar()` com `TERMOS` vazio -> não chama `alertar_gestor`, devolve `total_termos=0`.

Criar `tests/test_agente_panorama_painel_4_canais.py` (ou adicionar ao
arquivo de teste do panorama já existente):
- `_resumo_conectividade_4_canais()` com flag desligada devolve `None`
  e não chama nenhum `probe_conexao`.
- Com flag ligada (mockar os 4 `probe_conexao`), devolve dict com as
  4 chaves.
- Se um `probe_conexao` lançar exceção, essa chave vem com
  `{"ok": False, "msg": ...}` em vez de propagar.

Rodar no final:

```bash
pytest -q
ruff check .
```

═══════════════════════════════════════════════════════════════
NÃO FAZER (fora de escopo deste prompt — propositalmente)
═══════════════════════════════════════════════════════════════

- Não implementar o painel por SKU dos 4 canais de verdade — isso
  depende de Amazon/Shopee terem função de status por anúncio, que
  ainda não existe. Este prompt só entrega o scaffold de conectividade.
- Não chamar `atualizar_preco_item` em nenhum lugar da Extensão 1 —
  ela é só sugestão.
- Não criar agendamento de alta frequência pros 2 novos workflows —
  1x por dia é suficiente, já que são sugestões, não tempo real.

═══════════════════════════════════════════════════════════════
CHECKLIST FINAL
═══════════════════════════════════════════════════════════════

- [ ] Branch `feature/extensoes-toggle-preco-nicho-painel` criada
- [ ] `core/feature_flags.py` criado e testado
- [ ] Extensão 1 (`agente_faixa_preco_sugerida.py`) criada, testada, atrás do toggle
- [ ] Extensão 2 (`agente_radar_nicho.py`) criada, testada, atrás do toggle, com termos em spec.yaml
- [ ] Extensão 3 (scaffold `_resumo_conectividade_4_canais`) criada, testada, atrás do toggle
- [ ] `.env.example` atualizado com os 3 toggles (comentados, default false)
- [ ] 2 workflows novos criados (`faixa_preco_sugerida.yml`, `radar_nicho.yml`)
- [ ] Todos os testes antigos continuam passando, sem alteração de comportamento
- [ ] Cobertura total ≥ 90%
- [ ] `ruff check .` sem erros
- [ ] `git diff --stat` colado para revisão antes de qualquer commit