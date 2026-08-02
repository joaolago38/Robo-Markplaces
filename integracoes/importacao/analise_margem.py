"""
integracoes/importacao/analise_margem.py
Cruza Alibaba + câmbio + custo landed + preços de marketplace.
"""
from __future__ import annotations

import logging
from statistics import median
from typing import Any

from core.config import (
    ALIBABA_MARGEM_MIN_PCT,
    ALIBABA_MARGEM_MIN_REAIS,
    IMPORTACAO_AEREO_FORMAL,
    IMPORTACAO_COFINS_PCT,
    IMPORTACAO_DESEMBARACO_BRL,
    IMPORTACAO_FRETE_AEREO_USD_KG,
    IMPORTACAO_FRETE_MARITIMO_USD_KG,
    IMPORTACAO_FRETE_NACIONAL_BRL,
    IMPORTACAO_ICMS_PCT,
    IMPORTACAO_II_PCT_DEFAULT,
    IMPORTACAO_IPI_PCT_DEFAULT,
    IMPORTACAO_PIS_PCT,
    IMPORTACAO_SEGURO_PCT,
    IMPORTACAO_SISCOMEX_BRL,
    REGRAS,
)
from integracoes.importacao.calculo_importacao_aerea import calcular_para_produto_alibaba
from integracoes.importacao.custo_landed import calcular_cenarios_frete, calcular_margem_revenda
from integracoes.importacao.normalizar_unidades import (
    custo_para_comparacao_marketplace,
    normalizar_preco_usd,
    unidade_marketplace_qtd,
)

logger = logging.getLogger("analise_margem_importacao")


def _termo_marketplace(produto: dict[str, Any]) -> str:
    for chave in ("termo_marketplace", "termo_busca_pt", "nome"):
        t = str(produto.get(chave) or "").strip()
        if t:
            return t
    return ""


def _params_imposto(produto: dict[str, Any]) -> dict[str, float]:
    def _f(chave: str, padrao: float) -> float:
        v = produto.get(chave)
        if v is None:
            return padrao
        try:
            return float(v)
        except (TypeError, ValueError):
            return padrao

    from integracoes.importacao.siscomex import taxa_siscomex_brl

    try:
        adicoes = int(produto.get("siscomex_adicoes") or 1)
    except (TypeError, ValueError):
        adicoes = 1
    adicoes = max(1, adicoes)
    siscomex = _f("siscomex_brl", IMPORTACAO_SISCOMEX_BRL)
    # Legado 214.50 ou override vazio → regra vigente
    if abs(siscomex - 214.50) < 0.01 or siscomex <= 0:
        siscomex = taxa_siscomex_brl(adicoes=adicoes)

    out: dict[str, Any] = {
        "ii_pct": _f("ii_pct", IMPORTACAO_II_PCT_DEFAULT),
        "ipi_pct": _f("ipi_pct", IMPORTACAO_IPI_PCT_DEFAULT),
        "pis_pct": IMPORTACAO_PIS_PCT,
        "cofins_pct": IMPORTACAO_COFINS_PCT,
        "icms_pct": _f("icms_pct", IMPORTACAO_ICMS_PCT),
        "seguro_pct": IMPORTACAO_SEGURO_PCT,
        "siscomex_brl": siscomex,
        "siscomex_adicoes": adicoes,
        "desembaraco_brl": _f("desembaraco_brl", IMPORTACAO_DESEMBARACO_BRL),
        "frete_nacional_brl_unit": _f("frete_nacional_brl", IMPORTACAO_FRETE_NACIONAL_BRL),
        "frete_maritimo_usd_kg": IMPORTACAO_FRETE_MARITIMO_USD_KG,
        "frete_aereo_usd_kg": IMPORTACAO_FRETE_AEREO_USD_KG,
    }
    # AFRMM só no marítimo — landed aplica por modo_frete; passa % padrão
    try:
        from core.config import IMPORTACAO_AFRMM_PCT

        out["afrmm_pct"] = float(IMPORTACAO_AFRMM_PCT)
    except Exception:
        out["afrmm_pct"] = 8.0
    return out


def consultar_precos_marketplace(termo: str, *, limite: int = 12) -> dict[str, Any]:
    from integracoes.ml.ml_client import buscar_concorrentes_por_termo

    termo = (termo or "").strip()
    if not termo:
        return {"ok": False, "motivo": "termo vazio", "termo": ""}

    try:
        concorrentes = buscar_concorrentes_por_termo(termo, limite=limite)
    except Exception as exc:
        logger.warning("Marketplace busca falhou termo=%r: %s", termo[:50], exc)
        concorrentes = []

    precos = [float(c["preco"]) for c in concorrentes if c.get("preco", 0) > 0]
    return {
        "ok": bool(precos),
        "termo": termo,
        "marketplace": "mercadolivre",
        "total_anuncios": len(concorrentes),
        "preco_min_brl": round(min(precos), 2) if precos else None,
        "preco_medio_brl": round(sum(precos) / len(precos), 2) if precos else None,
        "preco_mediana_brl": round(median(precos), 2) if precos else None,
        "preco_max_brl": round(max(precos), 2) if precos else None,
        "amostra": concorrentes[:3],
    }


def analisar_oportunidade(
    produto: dict[str, Any],
    oportunidade: dict[str, Any],
    *,
    cambio_usd_brl: float,
    precos_marketplace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preco_usd = oportunidade.get("preco_usd")
    if preco_usd is None:
        return {"ok": False, "motivo": "sem preço USD"}

    try:
        preco_usd_f = float(preco_usd)
        moq = int(oportunidade.get("moq") or produto.get("moq_referencia") or 1)
        peso = float(produto.get("peso_kg") or 1.0)
    except (TypeError, ValueError):
        return {"ok": False, "motivo": "preço/MOQ/peso inválido"}

    preco_norm = normalizar_preco_usd(produto, preco_usd_f)
    preco_usd_unit = float(preco_norm["preco_usd_unit"])
    unidade_mk = unidade_marketplace_qtd(produto)

    impostos = _params_imposto(produto)
    cenarios = calcular_cenarios_frete(
        preco_usd_unit,
        cambio_usd_brl=cambio_usd_brl,
        peso_kg_unit=peso,
        quantidade=max(1, moq),
        **impostos,
    )

    mk = precos_marketplace or {}
    preco_ref = mk.get("preco_mediana_brl") or mk.get("preco_min_brl")
    taxa_mk = float(REGRAS.get("taxa_marketplace_pct", 14))
    margem_min_pct = float(produto.get("margem_minima_pct") or ALIBABA_MARGEM_MIN_PCT)
    margem_min_reais = float(produto.get("margem_minima_reais") or ALIBABA_MARGEM_MIN_REAIS)

    calculo_aereo_formal: dict[str, Any] | None = None
    if IMPORTACAO_AEREO_FORMAL:
        calculo_aereo_formal = calcular_para_produto_alibaba(
            produto,
            oportunidade,
            cambio_usd_brl=cambio_usd_brl,
        )

    margens: dict[str, Any] = {}
    for modo in ("maritimo", "aereo"):
        custo = (cenarios.get(modo) or {}).get("custo_unitario_brl")
        if modo == "aereo" and calculo_aereo_formal and calculo_aereo_formal.get("ok"):
            custo = calculo_aereo_formal.get("custo_unitario_brl")
        if custo is None or preco_ref is None:
            margens[modo] = {"ok": False}
            continue
        custo_pack = custo_para_comparacao_marketplace(float(custo), produto)
        margens[modo] = calcular_margem_revenda(
            float(preco_ref),
            custo_pack,
            taxa_marketplace_pct=taxa_mk,
            margem_minima_pct=margem_min_pct,
            margem_minima_reais=margem_min_reais,
        )

    melhor_frete = "aereo" if IMPORTACAO_AEREO_FORMAL else cenarios.get("melhor_frete")
    margem_melhor = margens.get(melhor_frete or "") if melhor_frete else None
    lucro_razoavel = bool(
        margem_melhor and margem_melhor.get("ok") and margem_melhor.get("lucro_razoavel")
    )

    return {
        "ok": True,
        "titulo": oportunidade.get("titulo"),
        "url": oportunidade.get("url"),
        "preco_usd": preco_usd_f,
        "preco_usd_unit": preco_usd_unit,
        "preco_normalizado": preco_norm,
        "unidade_marketplace_qtd": unidade_mk,
        "moq": moq,
        "peso_kg": peso,
        "cenarios_frete": cenarios,
        "calculo_aereo_formal": calculo_aereo_formal,
        "precos_marketplace": mk,
        "margens": margens,
        "melhor_frete": melhor_frete,
        "lucro_razoavel": lucro_razoavel,
        "margem_melhor": margem_melhor,
    }


def analisar_produto_catalogo(
    produto: dict[str, Any],
    oportunidades: list[dict[str, Any]],
    *,
    cambio_usd_brl: float,
    max_oportunidades: int = 3,
    precos_marketplace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    termo_mk = _termo_marketplace(produto)
    precos_mk = precos_marketplace if precos_marketplace is not None else consultar_precos_marketplace(termo_mk)

    com_preco = [o for o in oportunidades if o.get("preco_usd") is not None]
    com_preco.sort(key=lambda x: float(x.get("preco_usd") or 9999))
    analises: list[dict[str, Any]] = []

    for op in com_preco[:max_oportunidades]:
        analises.append(
            analisar_oportunidade(
                produto,
                op,
                cambio_usd_brl=cambio_usd_brl,
                precos_marketplace=precos_mk,
            )
        )

    lucrativas = [a for a in analises if a.get("lucro_razoavel")]
    melhor = None
    for a in analises:
        m = a.get("margem_melhor") or {}
        if not m.get("ok"):
            continue
        if melhor is None or (m.get("margem_brl") or 0) > (melhor.get("margem_melhor") or {}).get("margem_brl", 0):
            melhor = a

    return {
        "id": produto.get("id"),
        "produto": produto.get("nome"),
        "termo_marketplace": termo_mk,
        "precos_marketplace": precos_mk,
        "total_oportunidades": len(oportunidades),
        "analises": analises,
        "lucrativas": len(lucrativas),
        "melhor_analise": melhor,
        "ok": True,
    }
