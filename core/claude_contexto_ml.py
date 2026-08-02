"""
core/claude_contexto_ml.py
Estado atual do Mercado Livre + dosagem de profundidade para análises Claude.

Objetivo: toda análise Claude de produto/nicho no ML deve:
  1) enxergar como a conta/ecossistema ML está agora (saúde, score, alertas);
  2) cruzar isso com a situação do produto/nicho da rodada;
  3) dosar tokens/instruções para favorecer decisão (FAZER / NÃO FAZER / ATENÇÃO).

Fail-soft: lê snapshots em logs; ao_vivo opcional (API). Nunca lança.
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import ler_json
from core.config import ROOT

logger = logging.getLogger("claude_contexto_ml")

_PROFUNDIDADE_TOKENS = {
    "minima": 0.55,
    "padrao": 1.0,
    "ampliada": 1.35,
}

_SYSTEM_DECISAO = (
    "Sempre interprete o produto/nicho À LUZ de estado_ml (como a conta e o "
    "ecossistema Mercado Livre estão agora). "
    "Se ML estiver em atenção/crítico, priorize ações defensivas e curtas "
    "(reputação, perguntas, margem, exposição). "
    "Se ML estiver ok e o produto sem stress, seja breve: só aponte decisão "
    "clara (FAZER / NÃO FAZER / OBSERVAR) com 1–2 ações no máximo. "
    "Nunca invente métricas de saúde, vendas ou preços ausentes no JSON."
)


def _cfg_bool(nome: str, default: bool = True) -> bool:
    from core import config as cfg

    raw = getattr(cfg, nome, default)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in ("0", "false", "no", "")


def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _snapshot(nome: str) -> dict[str, Any]:
    data = ler_json(ROOT / "logs" / nome, default={})
    return data if isinstance(data, dict) else {}


def _nivel_de_score(score: float | None) -> str:
    if score is None:
        return "desconhecido"
    if score >= 75:
        return "ok"
    if score >= 50:
        return "atencao"
    return "critico"


def carregar_estado_ml(*, ao_vivo: bool = False) -> dict[str, Any]:
    """
    Monta um bloco compacto do 'como o ML está'.
    Preferência: snapshots locais (rápido, sem custo). ao_vivo=True tenta saúde API.
    """
    hist = _snapshot("marketplace_algorithm_history.json")
    pontos_ml = hist.get("mercadolivre") if isinstance(hist, dict) else None
    ultimo_algo: dict[str, Any] = {}
    if isinstance(pontos_ml, list) and pontos_ml:
        ultimo = pontos_ml[-1]
        if isinstance(ultimo, dict):
            ultimo_algo = ultimo

    resumo_conta = _snapshot("resumo_conta_ml_ultima.json")
    margem = _snapshot("margem_vendas_ultima.json")
    sem_venda = _snapshot("sem_venda_ml_ultima.json")
    estrategia = _snapshot("relatorio_estrategia_ml_ultima.json")
    manha = _snapshot("relatorio_manha_ml_ultima.json")
    decisao = _snapshot("decisao_dia_esmaltes_ultima.json")
    eco = _snapshot("ecossistema_esmaltes_ultima.json")

    score = ultimo_algo.get("score")
    if score is None:
        score = (resumo_conta.get("score") or resumo_conta.get("score_ml"))
    score_f = _num(score, default=-1)
    score_opt = None if score_f < 0 else score_f
    nivel = _nivel_de_score(score_opt)

    alertas: list[str] = []
    metrics = ultimo_algo.get("metrics") if isinstance(ultimo_algo.get("metrics"), dict) else {}
    pendencias = metrics.get("pendencias")
    claims = metrics.get("claims_rate")
    if pendencias is None:
        pendencias = resumo_conta.get("pendencias") or resumo_conta.get("perguntas_pendentes")
    if claims is None:
        claims = resumo_conta.get("claims_rate")

    if _num(pendencias) >= 5:
        alertas.append(f"perguntas/pendências altas ({int(_num(pendencias))})")
    if _num(claims) >= 0.02:
        alertas.append(f"claims_rate elevado ({_num(claims):.3f})")

    _ord = {"desconhecido": 0, "ok": 1, "atencao": 2, "critico": 3}

    def _subir(atual: str, alvo: str) -> str:
        return alvo if _ord.get(alvo, 0) > _ord.get(atual, 0) else atual

    if _num(pendencias) >= 5:
        nivel = _subir(nivel, "atencao")
    if _num(claims) >= 0.05:
        nivel = _subir(nivel, "critico")
    elif _num(claims) >= 0.02:
        nivel = _subir(nivel, "atencao")

    saude_vivo: dict[str, Any] | None = None
    if ao_vivo:
        try:
            from integracoes.ml.ml_client import obter_saude_conta

            saude_vivo = obter_saude_conta()
            if isinstance(saude_vivo, dict) and saude_vivo.get("configurado"):
                if _num(saude_vivo.get("pendencias")) >= 5:
                    nivel = _subir(nivel, "atencao")
                if _num(saude_vivo.get("claims_rate")) >= 0.05:
                    nivel = _subir(nivel, "critico")
                elif _num(saude_vivo.get("claims_rate")) >= 0.02:
                    nivel = _subir(nivel, "atencao")
        except Exception as exc:
            logger.debug("estado_ml ao_vivo falhou: %s", exc)

    return {
        "marketplace": "mercadolivre",
        "nivel": nivel,
        "score_algoritmo": score_opt,
        "status_algoritmo": ultimo_algo.get("status") or nivel,
        "metrics_algoritmo": {
            "pendencias": pendencias,
            "claims_rate": claims,
            "dias_sem_acesso": metrics.get("dias_sem_acesso"),
        },
        "saude_ao_vivo": saude_vivo,
        "alertas": alertas[:6],
        "sinais_recentes": {
            "margem_vendas": {
                "margem_media_pct": margem.get("margem_media_pct") or margem.get("margem_media"),
                "vendas": margem.get("total_vendas") or margem.get("vendas"),
                "alerta": margem.get("alerta") or margem.get("status"),
            },
            "sem_venda": {
                "itens": sem_venda.get("total") or sem_venda.get("quantidade") or sem_venda.get("itens_sem_venda"),
                "alerta": sem_venda.get("alerta"),
            },
            "decisao_esmaltes_score": decisao.get("score") or decisao.get("score_dia"),
            "ecossistema_score": eco.get("score_ecossistema") or eco.get("score"),
            "estrategia_resumo": str(
                estrategia.get("resumo") or estrategia.get("titulo") or ""
            )[:160]
            or None,
            "manha_tem_dados": bool(manha),
        },
        "fonte": "snapshots_logs" + ("+api" if saude_vivo else ""),
    }


def _primeiro_num(*vals: Any, default: float = 0.0) -> float:
    for v in vals:
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return default


def stress_produto(
    consolidado: dict[str, Any] | None = None,
    *,
    produto: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Termômetro do produto/nicho da rodada (0–100) + fatores."""
    score = 0
    fatores: list[str] = []
    c = consolidado if isinstance(consolidado, dict) else {}
    p = produto if isinstance(produto, dict) else {}

    margem = p.get("margem_pct")
    if margem is None:
        margem = c.get("margem_media_pct")
    if margem is None and c.get("margem_media_brl") is not None and c.get("margem_media_pct") is None:
        if _num(c.get("margem_media_brl")) < 8:
            score += 25
            fatores.append("margem_brl_baixa:+25")
    elif margem is not None:
        m = _num(margem)
        if m < 12:
            score += 35
            fatores.append("margem_pct_critica:+35")
        elif m < 20:
            score += 18
            fatores.append("margem_pct_apertada:+18")

    ganhos = c.get("maior_ganho") or []
    if isinstance(ganhos, list) and ganhos:
        d0 = ganhos[0] if isinstance(ganhos[0], dict) else {}
        delta = _num(d0.get("delta_vendas"))
        if delta < 0:
            score += 20
            fatores.append("delta_vendas_negativo:+20")
        elif delta == 0 and d0.get("ganho_fonte") == "sem_historico_usa_vendas":
            score += 8
            fatores.append("sem_historico_delta:+8")

    anuncios = _primeiro_num(
        c.get("total_anuncios_ativos"),
        c.get("total_produtos_unicos"),
    )
    vendas = _primeiro_num(
        c.get("vendas_totais"),
        c.get("total_vendas"),
        p.get("quantidade_vendida"),
    )
    if anuncios > 0 and vendas == 0:
        score += 40
        fatores.append("anuncios_sem_venda:+40")
    elif anuncios >= 10 and vendas < anuncios:
        score += 12
        fatores.append("vendas_baixas_vs_catalogo:+12")

    preco = _primeiro_num(p.get("preco"), c.get("preco_medio"))
    custo = _primeiro_num(p.get("custo_unitario_brl"), p.get("custo"))
    if preco > 0 and custo > 0 and preco <= custo * 1.15:
        score += 25
        fatores.append("preco_perto_custo:+25")

    score = max(0, min(100, int(score)))
    if score >= 40:
        nivel = "alto"
    elif score >= 20:
        nivel = "medio"
    else:
        nivel = "baixo"

    return {"score": score, "nivel": nivel, "fatores": fatores}


def dosar_analise_para_decisao(
    *,
    estado_ml: dict[str, Any] | None = None,
    stress: dict[str, Any] | None = None,
    proposito: str = "analise_ml",
) -> dict[str, Any]:
    """
    Decide profundidade da análise Claude visando tomada de decisão.
    minima | padrao | ampliada
    """
    if not _cfg_bool("CLAUDE_ML_DOSAGEM_ATIVA", True):
        return {
            "profundidade": "padrao",
            "fator_tokens": 1.0,
            "motivo": "dosagem_desligada",
            "foco_decisao": ["FAZER", "NAO_FAZER", "OBSERVAR"],
            "instrucoes": _SYSTEM_DECISAO,
        }

    estado = estado_ml or {}
    st = stress or {"score": 0, "nivel": "baixo"}
    nivel_ml = str(estado.get("nivel") or "desconhecido")
    stress_n = str(st.get("nivel") or "baixo")
    prop = (proposito or "").lower()

    profundidade = "padrao"
    motivos: list[str] = []

    if nivel_ml == "critico" or (nivel_ml == "atencao" and stress_n == "alto"):
        profundidade = "ampliada"
        motivos.append("ml_sob_pressao_ou_stress_alto")
    elif nivel_ml == "ok" and stress_n == "baixo" and "listing" not in prop:
        profundidade = "minima"
        motivos.append("ml_estavel_produto_calmo")
    elif stress_n == "alto":
        profundidade = "ampliada"
        motivos.append("produto_stress_alto")
    else:
        motivos.append("equilibrio_padrao")

    foco = ["FAZER", "NAO_FAZER", "OBSERVAR"]
    if nivel_ml in ("atencao", "critico"):
        foco = ["DEFENDER_REPUTACAO", "PROTEGER_MARGEM", "NAO_ESCALAR_ADS", "FAZER_SO_SE_CLARO"]
    elif stress_n == "alto":
        foco = ["AJUSTAR_PRECO_OU_ESTOQUE", "PRIORIZAR_SKU_MARGEM", "NAO_FAZER_SE_GUERRA"]

    return {
        "profundidade": profundidade,
        "fator_tokens": _PROFUNDIDADE_TOKENS[profundidade],
        "motivo": ",".join(motivos),
        "nivel_ml": nivel_ml,
        "stress_produto": stress_n,
        "foco_decisao": foco,
        "instrucoes": _SYSTEM_DECISAO,
    }


def max_tokens_dosados(base: int, dosagem: dict[str, Any] | None) -> int:
    fator = _num((dosagem or {}).get("fator_tokens"), 1.0)
    out = int(max(120, round(base * fator)))
    return min(out, int(base * 1.5) if base else out)


def enriquecer_contexto_claude(
    contexto: dict[str, Any] | str | None,
    *,
    consolidado: dict[str, Any] | None = None,
    produto: dict[str, Any] | None = None,
    proposito: str = "analise_ml",
    ao_vivo: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Devolve (contexto_enriquecido, dosagem).
    Se CLAUDE_ML_CONTEXTO_ATIVO=0, só empacota o contexto original.
    """
    if isinstance(contexto, str):
        base: dict[str, Any] = {"contexto_texto": contexto}
    elif isinstance(contexto, dict):
        base = dict(contexto)
    else:
        base = {}

    if not _cfg_bool("CLAUDE_ML_CONTEXTO_ATIVO", True):
        dosagem = dosar_analise_para_decisao(proposito=proposito)
        return base, dosagem

    try:
        estado = carregar_estado_ml(ao_vivo=ao_vivo)
    except Exception as exc:
        logger.warning("carregar_estado_ml falhou: %s", exc)
        estado = {"marketplace": "mercadolivre", "nivel": "desconhecido", "alertas": []}

    st = stress_produto(consolidado, produto=produto)
    dosagem = dosar_analise_para_decisao(
        estado_ml=estado, stress=st, proposito=proposito
    )

    empresa_bloco: dict[str, Any] = {}
    dois_cnpjs: dict[str, Any] = {}
    try:
        from core.empresa_contexto import empresa_para_proposito, mapa_dois_cnpjs

        emp = empresa_para_proposito(proposito)
        dois_cnpjs = mapa_dois_cnpjs()
        if emp:
            empresa_bloco = {
                "id": emp.get("id"),
                "nome_fantasia": emp.get("nome_fantasia"),
                "cnpj": emp.get("cnpj"),
                "cnpj_formatado": emp.get("cnpj_formatado"),
                "cnae_principal": emp.get("cnae_principal"),
                "ramos": emp.get("ramos") or [],
                "prioriza_mercadolivre": emp.get("prioriza_mercadolivre", True),
            }
    except Exception as exc:
        logger.debug("empresa no contexto Claude: %s", exc)

    base["estado_ml"] = estado
    base["situacao_produto"] = st
    base["empresa_cnpj"] = empresa_bloco
    base["dois_cnpjs_operacao"] = dois_cnpjs
    base["dosagem_analise"] = {
        "profundidade": dosagem["profundidade"],
        "motivo": dosagem["motivo"],
        "foco_decisao": dosagem["foco_decisao"],
    }
    cnpj_txt = empresa_bloco.get("cnpj_formatado") or empresa_bloco.get("cnpj") or "?"
    base["orientacao_decisao"] = (
        f"CNPJ={cnpj_txt} | ML={dosagem.get('nivel_ml')} | "
        f"produto_stress={dosagem.get('stress_produto')} | "
        f"profundidade={dosagem['profundidade']} | foque em: "
        + ", ".join(dosagem["foco_decisao"][:4])
    )
    return base, dosagem


def system_com_decisao(system: str | None, dosagem: dict[str, Any] | None) -> str:
    base = (system or "").strip()
    extra = (dosagem or {}).get("instrucoes") or _SYSTEM_DECISAO
    if not base:
        return extra
    if "À LUZ de estado_ml" in base or "estado_ml" in base.lower():
        return base
    return f"{base}\n\n{extra}"
