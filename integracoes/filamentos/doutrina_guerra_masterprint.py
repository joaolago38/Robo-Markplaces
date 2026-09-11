"""
integracoes/filamentos/doutrina_guerra_masterprint.py
Mesma regra de engajamento da Impala, no CNPJ Masterprint (filamento PETG).
Só 231020002 (branco) iguala preço.
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import ler_json
from core.config import DOUTRINA_GUERRA_MASTERPRINT_CATALOGO, ROOT
from core.datadog_metrics import gauge
from integracoes.esmaltes.crescimento_esmaltes import _mlb_valido
from integracoes.esmaltes.decisao_dia_esmaltes import _item_id
from integracoes.esmaltes.doutrina_guerra_impala import (
    CLASSIF_DIFERENCIAR,
    CLASSIF_IGNORAR,
    CLASSIF_IGUALAR,
    CLASSIF_NAO_PERSEGUIR,
    _f,
    _id_fase,
    carregar_doutrina as _carregar,
    classificar_golpe,
    frente_skus,
    piso_preco,
    sku_preco_guerra,
)

logger = logging.getLogger("doutrina_guerra_masterprint")

CNPJ_MASTERPRINT = "23811261000197"
TAGS_CNPJ = [f"cnpj:{CNPJ_MASTERPRINT}", "ramo:masterprint"]
SKU_ENTRADA = "231020001"
SKU_PRECO = "231020002"
SKU_GIRO = "231020003"


def carregar_doutrina(caminho: str | None = None) -> dict[str, Any]:
    return _carregar(caminho or DOUTRINA_GUERRA_MASTERPRINT_CATALOGO)


def _estoque(produto: dict[str, Any] | None) -> int:
    if not isinstance(produto, dict):
        return 0
    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    try:
        return max(int(produto.get("estoque_total") or 0), int(ml.get("estoque") or 0))
    except (TypeError, ValueError):
        return 0


def _mlb_ok(produto: dict[str, Any] | None) -> bool:
    if not isinstance(produto, dict):
        return False
    return bool(_mlb_valido(_item_id(produto)))


def _reviews_nota(conta: dict[str, Any]) -> tuple[int, float]:
    reviews = int(conta.get("avaliacoes") or conta.get("quantidade_avaliacoes") or 0)
    nota = _f(conta.get("nota") or conta.get("nota_media") or 0.0)
    return reviews, nota


def sku_pode_publicar_agora(
    sku: str,
    *,
    condicoes: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Preto → Branco (preto no ar) → Azul (1º pedido)."""
    sku_u = (sku or "").strip().upper()
    if not sku_u:
        return False, "sku_vazio"
    d = carregar_doutrina()
    if sku_u not in frente_skus(d):
        return False, "fora_frente_filamento"
    cond = condicoes if isinstance(condicoes, dict) else avaliar_condicoes_guerra()
    checks = cond.get("checks") if isinstance(cond.get("checks"), dict) else {}
    if sku_u == SKU_ENTRADA:
        if checks.get("mlb_entrada"):
            return False, "preto_ja_no_ar"
        return True, "abrir_frente_petg_preto"
    if sku_u == SKU_PRECO:
        if not checks.get("mlb_entrada") or int(checks.get("estoque_entrada") or 0) <= 0:
            return False, "esperar_preto_no_ar"
        if checks.get("mlb_preco"):
            return False, "branco_ja_no_ar"
        return True, "branco_mesmo_ciclo"
    if sku_u == SKU_GIRO:
        if int(checks.get("reviews") or 0) < 1:
            return False, "esperar_primeiro_pedido"
        if checks.get("mlb_giro"):
            return False, "azul_ja_no_ar"
        return True, "giro_apos_pedido"
    return False, "fora_frente_nao_abrir_4o_sku"


def avaliar_condicoes_guerra(
    *,
    produtos: list[dict[str, Any]] | None = None,
    radar: dict[str, Any] | None = None,
    resumo_conta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fases 0–5 no CNPJ Masterprint. Não inventa MLB."""
    from core.catalogo_produtos import carregar_produtos_catalogo

    d = carregar_doutrina()
    gat = d.get("gatilhos") or {}
    est_min = int(gat.get("estoque_ml_min") or 30)
    reviews_ads = int(gat.get("reviews_ads") or 20)
    nota_ads = _f(gat.get("nota_ads"), 4.8)
    prods = produtos if produtos is not None else carregar_produtos_catalogo()
    por = {
        str(p.get("sku") or "").strip().upper(): p
        for p in prods
        if isinstance(p, dict) and p.get("sku")
    }
    entrada = por.get(SKU_ENTRADA)
    preco = por.get(SKU_PRECO)
    giro = por.get(SKU_GIRO)
    radar = radar if isinstance(radar, dict) else {}
    conta = resumo_conta if isinstance(resumo_conta, dict) else {}
    reviews, nota = _reviews_nota(conta if isinstance(conta, dict) else {})
    checks = {
        "mlb_entrada": _mlb_ok(entrada),
        "mlb_preco": _mlb_ok(preco),
        "mlb_giro": _mlb_ok(giro),
        "estoque_entrada": _estoque(entrada),
        "mercado_confiavel": bool(radar.get("mercado_confiavel")),
        "reviews": reviews,
        "nota": nota,
    }
    est = int(checks["estoque_entrada"])
    ads_ok = reviews >= reviews_ads and nota >= nota_ads
    if not checks["mlb_entrada"] or est <= 0:
        fase = 0
    elif not checks["mlb_preco"] or reviews < 1:
        fase = 1
    elif not checks["mlb_giro"] or not ads_ok:
        fase = 2
    elif not checks["mercado_confiavel"]:
        fase = 3
    elif est < est_min:
        fase = 4
    else:
        fase = 5
    fases = d.get("fases") or []
    atual = next((f for f in fases if _id_fase(f) == fase), {})
    proxima = next((f for f in fases if _id_fase(f) == fase + 1), {})
    return {
        "ok": True,
        "ramo": "masterprint",
        "cnpj": CNPJ_MASTERPRINT,
        "cenario": str(d.get("cenario_mais_possivel") or "abrir_frente_petg_preto"),
        "fase": fase,
        "fase_nome": str(atual.get("nome") or f"fase_{fase}"),
        "fazer": str(atual.get("fazer") or ""),
        "proxima_fase": str(proxima.get("nome") or ""),
        "agentes": list(atual.get("agentes") or []),
        "checks": checks,
        "estoque_min_guerra": est_min,
        "liberar": {
            "entrada": not bool(checks["mlb_entrada"]),
            "preco_sku": bool(checks["mlb_entrada"] and est > 0 and not checks["mlb_preco"]),
            "giro": fase >= 2 and not bool(checks["mlb_giro"]),
            "ads": fase >= 3,
            "golpe_preco": fase >= 4,
            "ruptura": fase >= 5,
        },
        "nao_fazer": list(d.get("nao_fazer_global") or []),
    }


def emitir_metricas_condicoes(condicoes: dict[str, Any] | None = None) -> dict[str, Any]:
    """Gauges robo.masterprint.guerra.* com tag do 2º CNPJ."""
    try:
        cond = (
            condicoes
            if isinstance(condicoes, dict) and condicoes.get("fase") is not None
            else avaliar_condicoes_guerra()
        )
        tags = list(TAGS_CNPJ)
        gauge("masterprint.guerra.fase", float(cond.get("fase") or 0), tags=tags)
        lib = cond.get("liberar") if isinstance(cond.get("liberar"), dict) else {}
        for chave in ("entrada", "preco_sku", "giro", "ads", "golpe_preco", "ruptura"):
            gauge(
                f"masterprint.guerra.liberar_{chave}",
                1.0 if lib.get(chave) else 0.0,
                tags=tags,
            )
        n_pub = 0.0
        for sku in (SKU_ENTRADA, SKU_PRECO, SKU_GIRO):
            ok, _motivo = sku_pode_publicar_agora(sku, condicoes=cond)
            if ok:
                n_pub += 1.0
        gauge("masterprint.guerra.publicar_agora", n_pub, tags=tags)
        checks = cond.get("checks") if isinstance(cond.get("checks"), dict) else {}
        gauge(
            "masterprint.guerra.mercado_confiavel",
            1.0 if checks.get("mercado_confiavel") else 0.0,
            tags=tags,
        )
        mlb_n = sum(
            1.0
            for k in ("mlb_entrada", "mlb_preco", "mlb_giro")
            if checks.get(k)
        )
        gauge("masterprint.guerra.mlb_frente", mlb_n, tags=tags)
        return {"ok": True, **cond}
    except Exception as exc:
        logger.warning("emitir_metricas_condicoes masterprint: %s", exc)
        return {"ok": False, "erro": str(exc)}


def carregar_skus_guerra() -> list[dict[str, Any]]:
    from core.config import SKUS_GUERRA_MASTERPRINT_CATALOGO

    data = ler_json(ROOT / SKUS_GUERRA_MASTERPRINT_CATALOGO, default=[])
    return data if isinstance(data, list) else []
