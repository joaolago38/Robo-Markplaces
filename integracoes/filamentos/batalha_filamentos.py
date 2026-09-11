"""
integracoes/filamentos/batalha_filamentos.py
Compara a frente PETG Masterprint com a amostra do monitor (rivais ao vivo).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar
from integracoes.filamentos.custos_masterprint_petg import carregar_tabela_custos
from integracoes.filamentos.doutrina_guerra_masterprint import (
    CNPJ_MASTERPRINT,
    SKU_ENTRADA,
    SKU_GIRO,
    SKU_PRECO,
    TAGS_CNPJ,
    carregar_doutrina,
    emitir_metricas_condicoes,
)
from integracoes.filamentos.golpe_guerra_masterprint import processar_golpe_batalha

logger = logging.getLogger("batalha_filamentos")

SNAPSHOT_PATH = ROOT / "logs" / "filamentos_batalha_ultima.json"
_ITEM_LIXO = re.compile(r"^MLB\d{1,2}$", re.I)


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _item_ok(item_id: str) -> bool:
    iid = (item_id or "").strip().upper()
    if not iid.startswith("MLB") or "PREENCHER" in iid:
        return False
    return _ITEM_LIXO.fullmatch(iid) is None


def _custo_sku(sku: str) -> float:
    tab = carregar_tabela_custos()
    alvo = (sku or "").strip()
    for it in tab.get("itens") or []:
        if str(it.get("sku") or "").strip() == alvo:
            return _f(it.get("custo_unitario_brl") or tab.get("custo_padrao_1kg_brl"), 45.96)
    return _f(tab.get("custo_padrao_1kg_brl"), 45.96)


def _cor_titulo(titulo: str, cor: str) -> bool:
    t = str(titulo or "").lower()
    c = str(cor or "").lower()
    if not c:
        return False
    aliases = {
        "preto": ("preto", "black"),
        "branco": ("branco", "white"),
        "azul": ("azul", "blue"),
    }
    return any(a in t for a in aliases.get(c, (c,)))


def _petg_1kg(anuncio: dict[str, Any]) -> bool:
    t = str(anuncio.get("titulo") or "").lower()
    if "petg" not in t:
        return False
    if "1kg" in t or "1 kg" in t or "1000g" in t:
        return True
    try:
        return float(anuncio.get("peso_kg") or 0) == 1.0
    except (TypeError, ValueError):
        return True


def montar_batalha(
    anuncios: list[dict[str, Any]] | None,
    *,
    produtos: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    d = carregar_doutrina()
    kits = d.get("kits") if isinstance(d.get("kits"), dict) else {}
    amostra = [a for a in (anuncios or []) if isinstance(a, dict) and _item_ok(str(a.get("item_id") or ""))]
    por_sku = {
        str(p.get("sku") or "").strip().upper(): p
        for p in (produtos or [])
        if isinstance(p, dict)
    }
    comparacoes: list[dict[str, Any]] = []
    for sku in (SKU_ENTRADA, SKU_PRECO, SKU_GIRO):
        spec = kits.get(sku) if isinstance(kits.get(sku), dict) else {}
        cor = str(spec.get("cor") or "")
        rivais = [
            a
            for a in amostra
            if _petg_1kg(a) and _cor_titulo(str(a.get("titulo") or ""), cor)
        ]
        precos = [_f(a.get("preco")) for a in rivais if _f(a.get("preco")) > 0]
        rival_min = min(precos) if precos else None
        prod = por_sku.get(sku) or {}
        ml = (prod.get("canais") or {}).get("mercadolivre") or {}
        nosso = _f(ml.get("preco") or spec.get("preco_fase1"))
        mlb_ok = bool(str(ml.get("item_id") or "").upper().startswith("MLB") and "PREENCHER" not in str(ml.get("item_id") or "").upper())
        gap = None
        if rival_min and nosso > 0:
            gap = round((nosso - rival_min) / rival_min * 100.0, 2)
        ao_vivo = bool(rivais)
        comparacoes.append(
            {
                "sku": sku,
                "kit_tag": f"kit:{cor or sku.lower()}",
                "papel": spec.get("papel") or "catalogo",
                "prio": "p0",
                "nosso_preco": nosso,
                "rival_min": rival_min,
                "fonte_rival": "ao_vivo" if ao_vivo else "ausente",
                "rivais_no_tam": len(rivais),
                "gap_pct": gap,
                "mlb_ok": mlb_ok,
                "custo_total": _custo_sku(sku),
            }
        )
    return {
        "ok": True,
        "ramo": "masterprint",
        "cnpj": CNPJ_MASTERPRINT,
        "anuncios_unicos": len(amostra),
        "comparacoes": comparacoes,
        "nossos_acima_rival": sum(
            1 for c in comparacoes if c.get("gap_pct") is not None and float(c["gap_pct"]) >= 3
        ),
    }


def emitir_metricas_batalha(batalha: dict[str, Any] | None) -> None:
    bat = batalha if isinstance(batalha, dict) else {}
    tags = list(TAGS_CNPJ)
    gauge("masterprint.batalha.anuncios_unicos", float(bat.get("anuncios_unicos") or 0), tags=tags)
    gauge(
        "masterprint.batalha.nossos_acima_rival",
        float(bat.get("nossos_acima_rival") or 0),
        tags=tags,
    )
    for c in bat.get("comparacoes") or []:
        if not isinstance(c, dict):
            continue
        kt = [str(c.get("kit_tag") or "kit:x")] + tags
        if c.get("gap_pct") is not None:
            gauge("masterprint.batalha.gap_pct", float(c["gap_pct"]), tags=kt)
        gauge("masterprint.batalha.mlb_ok", 1.0 if c.get("mlb_ok") else 0.0, tags=kt)
    incrementar("masterprint.batalha.rodadas", tags=tags)


def produtos_desde_comparacoes(batalha: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in batalha.get("comparacoes") or []:
        if not isinstance(c, dict):
            continue
        out.append(
            {
                "sku": c.get("sku"),
                "custo_total": c.get("custo_total") or 45.96,
                "fase_atual": 1,
                "preco": c.get("nosso_preco"),
                "canais": {
                    "mercadolivre": {
                        "preco": c.get("nosso_preco"),
                        "item_id": "MLB12345678" if c.get("mlb_ok") else "MLB_PREENCHER",
                    }
                },
            }
        )
    return out


def processar_guerra_petg(
    consolidado: dict[str, Any] | None,
    *,
    produtos: list[dict[str, Any]] | None = None,
    enviar_alerta: bool = False,
) -> dict[str, Any]:
    """Monta batalha a partir do consolidado PETG, golpe + gauges do 2º CNPJ."""
    cons = consolidado if isinstance(consolidado, dict) else {}
    anuncios = cons.get("produtos") or cons.get("mais_vendidos") or cons.get("anuncios") or []
    batalha = montar_batalha(anuncios, produtos=produtos)
    emitir_metricas_batalha(batalha)
    prods = produtos if produtos is not None else produtos_desde_comparacoes(batalha)
    radar = {
        "mercado_confiavel": bool(batalha.get("anuncios_unicos"))
        and any(
            (c.get("fonte_rival") == "ao_vivo")
            for c in batalha.get("comparacoes") or []
            if isinstance(c, dict)
        )
    }
    cond: dict[str, Any] = {}
    try:
        from integracoes.filamentos.doutrina_guerra_masterprint import avaliar_condicoes_guerra

        cond = emitir_metricas_condicoes(
            avaliar_condicoes_guerra(produtos=prods, radar=radar)
        )
    except Exception as exc:
        logger.debug("condicoes guerra petg: %s", exc)
    golpe = processar_golpe_batalha(batalha, produtos=prods, enviar_alerta=enviar_alerta)
    payload = {
        "ok": True,
        "batalha": batalha,
        "golpe": {
            "disparar": golpe.get("disparar"),
            "classificacao": (golpe.get("golpe") or {}).get("classificacao"),
            "sku": (golpe.get("golpe") or {}).get("sku"),
        },
        "condicoes": {
            "fase": (cond or {}).get("fase"),
            "liberar_golpe_preco": ((cond or {}).get("liberar") or {}).get("golpe_preco"),
        },
        "cnpj": CNPJ_MASTERPRINT,
    }
    try:
        escrever_json_atomico(SNAPSHOT_PATH, payload)
    except Exception as exc:
        logger.warning("snapshot batalha filamentos: %s", exc)
    return payload
