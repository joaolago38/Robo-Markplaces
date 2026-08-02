"""
core/claude_ml/dosagem.py — Strategy: profundidade da análise Claude.
"""
from __future__ import annotations

from typing import Any

from core.claude_ml.numeros import cfg_bool, num

PROFUNDIDADE_TOKENS = {
    "minima": 0.55,
    "padrao": 1.0,
    "ampliada": 1.35,
}

SYSTEM_DECISAO = (
    "Sempre interprete o produto/nicho À LUZ de estado_ml (como a conta e o "
    "ecossistema Mercado Livre estão agora). "
    "Se ML estiver em atenção/crítico, priorize ações defensivas e curtas "
    "(reputação, perguntas, margem, exposição). "
    "Se ML estiver ok e o produto sem stress, seja breve: só aponte decisão "
    "clara (FAZER / NÃO FAZER / OBSERVAR) com 1–2 ações no máximo. "
    "Nunca invente métricas de saúde, vendas ou preços ausentes no JSON."
)


def dosar_analise_para_decisao(
    *,
    estado_ml: dict[str, Any] | None = None,
    stress: dict[str, Any] | None = None,
    proposito: str = "analise_ml",
) -> dict[str, Any]:
    """Strategy: minima | padrao | ampliada conforme ML × produto."""
    if not cfg_bool("CLAUDE_ML_DOSAGEM_ATIVA", True):
        return {
            "profundidade": "padrao",
            "fator_tokens": 1.0,
            "motivo": "dosagem_desligada",
            "foco_decisao": ["FAZER", "NAO_FAZER", "OBSERVAR"],
            "instrucoes": SYSTEM_DECISAO,
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
        foco = [
            "DEFENDER_REPUTACAO",
            "PROTEGER_MARGEM",
            "NAO_ESCALAR_ADS",
            "FAZER_SO_SE_CLARO",
        ]
    elif stress_n == "alto":
        foco = ["AJUSTAR_PRECO_OU_ESTOQUE", "PRIORIZAR_SKU_MARGEM", "NAO_FAZER_SE_GUERRA"]

    return {
        "profundidade": profundidade,
        "fator_tokens": PROFUNDIDADE_TOKENS[profundidade],
        "motivo": ",".join(motivos),
        "nivel_ml": nivel_ml,
        "stress_produto": stress_n,
        "foco_decisao": foco,
        "instrucoes": SYSTEM_DECISAO,
    }


def max_tokens_dosados(base: int, dosagem: dict[str, Any] | None) -> int:
    fator = num((dosagem or {}).get("fator_tokens"), 1.0)
    out = int(max(120, round(base * fator)))
    return min(out, int(base * 1.5) if base else out)


def system_com_decisao(system: str | None, dosagem: dict[str, Any] | None) -> str:
    base = (system or "").strip()
    extra = (dosagem or {}).get("instrucoes") or SYSTEM_DECISAO
    if not base:
        return extra
    if "À LUZ de estado_ml" in base or "estado_ml" in base.lower():
        return base
    return f"{base}\n\n{extra}"
