"""
integracoes/esmaltes/kits_concorrentes_unificado.py
Junta os snapshots de kits (rivais + nossos + filamento) num JSON só.

Não busca ML. Não publica anúncio. Lê logs/*_ultima.json já gravados.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar

logger = logging.getLogger("kits_concorrentes_unificado")

SNAPSHOT_PATH = ROOT / "logs" / "kits_concorrentes_unificado_ultima.json"

FONTES: tuple[tuple[str, str, str], ...] = (
    ("radar", "logs/radar_diferencial_impala_ultima.json", "Rivais Impala (qtd kit, extras)"),
    ("marca_kit", "logs/esmaltes_marca_kit_ultima.json", "Marca × tamanho de kit"),
    ("mercado", "logs/esmaltes_mercado_ultima.json", "Mercado esmaltes consolidado"),
    ("nossos", "logs/kits_compativeis_manicures_ultima.json", "Nossos kits vs ML"),
    ("anita", "logs/anita_esmaltes_ultima.json", "Anita vs Impala (qtd kit)"),
    ("anuncio", "logs/analise_anuncio_concorrente_ultima.json", "Anúncio rival pontual"),
    ("kits_monitor", "logs/esmaltes_kits_monitor_ultima.json", "Varredura kit 3/5/6/10"),
    ("petg", "logs/masterprint_petg_ultima.json", "PETG Masterprint (kit no título)"),
)

_RIVAIS_MAX = 15
_MARCA_KIT_MAX = 12


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _i(val: Any, default: int = 0) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def _idade_h(ts: str) -> float | None:
    s = str(ts or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600.0, 1)
    except Exception:
        return None


def _carregar(fid: str, rel: str, blobs: dict[str, Any] | None) -> dict[str, Any]:
    if blobs is not None and fid in blobs:
        raw = blobs[fid]
        return raw if isinstance(raw, dict) else {}
    data = ler_json(ROOT / rel, default={})
    return data if isinstance(data, dict) else {}


def _meta_fonte(fid: str, rel: str, rotulo: str, blob: dict[str, Any]) -> dict[str, Any]:
    ts = str(blob.get("timestamp") or blob.get("gerado_em") or blob.get("coletado_em") or "")
    idade = _idade_h(ts)
    presente = bool(blob)
    stale = bool(blob.get("cache_stale"))
    if idade is not None and idade >= 48:
        stale = True
    return {
        "id": fid,
        "path": rel.replace("\\", "/"),
        "rotulo": rotulo,
        "presente": presente,
        "ok": bool(blob.get("ok", presente)),
        "timestamp": ts or None,
        "idade_h": idade,
        "stale": stale,
    }


def _rivais(radar: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in radar.get("rivais") or []:
        if not isinstance(r, dict):
            continue
        extras = r.get("extras") if isinstance(r.get("extras"), list) else []
        out.append(
            {
                "item_id": str(r.get("item_id") or ""),
                "titulo": str(r.get("titulo") or "")[:120],
                "preco": _f(r.get("preco")),
                "qtd_kit": r.get("qtd_kit"),
                "extras": [str(x) for x in extras[:6]],
            }
        )
        if len(out) >= _RIVAIS_MAX:
            break
    return out


def _marca_kit(blob: dict[str, Any]) -> list[dict[str, Any]]:
    ranking = blob.get("ranking")
    if not isinstance(ranking, list):
        cons = blob.get("consolidado") if isinstance(blob.get("consolidado"), dict) else {}
        ranking = cons.get("oportunidades_marca_kit") or cons.get("ranking_marcas_global") or []
    out: list[dict[str, Any]] = []
    for row in ranking:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "marca": str(row.get("marca") or ""),
                "qtd_kit": _i(row.get("qtd_kit")),
                "anuncios": _i(row.get("anuncios")),
                "preco_medio": _f(row.get("preco_medio")),
                "preco_por_unidade": _f(row.get("preco_por_unidade")),
                "vendidos": _i(row.get("vendidos") or row.get("volume_proxy")),
            }
        )
        if len(out) >= _MARCA_KIT_MAX:
            break
    return out


def _nossos(blob: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in blob.get("ofertas") or []:
        if not isinstance(row, dict):
            continue
        eco = row.get("economia") if isinstance(row.get("economia"), dict) else {}
        out.append(
            {
                "sku": str(row.get("sku") or ""),
                "qtd_kit": _i(row.get("qtd_kit")),
                "preco": _f(row.get("preco")),
                "margem_pct": _f(row.get("margem_pct")),
                "condicao_ok": bool(row.get("condicao_ok")),
                "preco_por_unidade": _f(eco.get("preco_por_unidade")),
                "compativeis_ml_n": len(row.get("compativeis_ml") or [])
                if isinstance(row.get("compativeis_ml"), list)
                else 0,
            }
        )
        if len(out) >= 8:
            break
    return out


def _anita(blob: dict[str, Any]) -> dict[str, Any]:
    cons = blob.get("consolidado_impala") if isinstance(blob.get("consolidado_impala"), dict) else {}
    kits: list[dict[str, Any]] = []
    for res in blob.get("resultados") or []:
        if not isinstance(res, dict):
            continue
        kits.append(
            {
                "nome": str(res.get("nome") or res.get("id") or ""),
                "qtd_kit": _i(res.get("qtd_kit_preferencia") or res.get("qtd_kit")),
                "total_anuncios": _i(res.get("total_anuncios")),
                "menor_preco_impala": _f(res.get("menor_preco_impala")),
                "menor_preco_anita": _f(res.get("menor_preco_anita")),
            }
        )
        for an in res.get("analises") or []:
            if isinstance(an, dict) and not kits[-1].get("qtd_kit"):
                kits[-1]["qtd_kit"] = _i(an.get("qtd_kit_detectada"))
        if len(kits) >= 6:
            break
    return {
        "share_impala_pct": _f(cons.get("share_impala_global_pct")),
        "unidades_impala": _i(cons.get("unidades_vendidas_impala")),
        "unidades_anita": _i(cons.get("unidades_vendidas_anita")),
        "segmentos": kits,
    }


def _anuncio(blob: dict[str, Any]) -> dict[str, Any] | None:
    ads = blob.get("anuncios")
    if not isinstance(ads, list) or not ads:
        return None
    top = ads[0] if isinstance(ads[0], dict) else None
    if not top:
        return None
    met = top.get("metricas") if isinstance(top.get("metricas"), dict) else {}
    return {
        "termo": str(blob.get("termo") or ""),
        "item_id": str(top.get("item_id") or ""),
        "titulo": str(top.get("titulo") or "")[:120],
        "preco": _f(top.get("preco")),
        "avaliacoes": _i(met.get("avaliacoes") or top.get("avaliacoes")),
        "nota": _f(met.get("nota") or top.get("nota")),
    }


def _filamento_kits(blob: dict[str, Any]) -> dict[str, Any]:
    cons = blob.get("consolidado") if isinstance(blob.get("consolidado"), dict) else blob
    produtos = cons.get("produtos") if isinstance(cons.get("produtos"), list) else []
    kits: list[dict[str, Any]] = []
    for p in produtos:
        if not isinstance(p, dict):
            continue
        tit = str(p.get("titulo") or "")
        if "kit" not in tit.lower():
            continue
        kits.append(
            {
                "item_id": str(p.get("item_id") or ""),
                "titulo": tit[:120],
                "preco": _f(p.get("preco")),
                "seller_id": str(p.get("seller_id") or ""),
                "cor": str(p.get("cor") or ""),
            }
        )
    return {
        "anuncios_petg": _i(cons.get("total_anuncios_ativos"), len(produtos)),
        "kits_no_titulo": len(kits),
        "exemplos": kits[:8],
    }


def montar_unificado(*, blobs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Consolida. Aceita blobs injetados (testes). Nunca lança."""
    fontes_out: list[dict[str, Any]] = []
    loaded: dict[str, dict[str, Any]] = {}
    for fid, rel, rotulo in FONTES:
        blob = _carregar(fid, rel, blobs)
        loaded[fid] = blob
        fontes_out.append(_meta_fonte(fid, rel, rotulo, blob))

    radar = loaded.get("radar") or {}
    petg = _filamento_kits(loaded.get("petg") or {})
    presentes = sum(1 for f in fontes_out if f.get("presente"))
    stale_n = sum(1 for f in fontes_out if f.get("stale"))

    return {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "onde": {
            "unico": "logs/kits_concorrentes_unificado_ultima.json",
            "nota": "Índice. Os agentes originais continuam gravando os arquivos-fonte.",
        },
        "fontes": fontes_out,
        "fontes_presentes": presentes,
        "fontes_total": len(FONTES),
        "fontes_stale": stale_n,
        "esmaltes": {
            "radar_stale": bool(radar.get("cache_stale")),
            "radar_idade_h": _f(radar.get("cache_idade_h")) or _idade_h(str(radar.get("timestamp") or "")),
            "n_rivais": _i(radar.get("n_anuncios")) or len(radar.get("rivais") or []),
            "n_comparaveis": _i(radar.get("n_comparaveis")),
            "extras": radar.get("extras") if isinstance(radar.get("extras"), dict) else {},
            "rivais": _rivais(radar),
            "marca_kit": _marca_kit(loaded.get("marca_kit") or loaded.get("mercado") or {}),
            "nossos": _nossos(loaded.get("nossos") or {}),
            "anita": _anita(loaded.get("anita") or {}),
            "anuncio_exemplo": _anuncio(loaded.get("anuncio") or {}),
        },
        "filamentos": petg,
    }


def emitir_metricas(payload: dict[str, Any] | None) -> None:
    data = payload if isinstance(payload, dict) else {}
    esm = data.get("esmaltes") if isinstance(data.get("esmaltes"), dict) else {}
    extras = esm.get("extras") if isinstance(esm.get("extras"), dict) else {}
    fil = data.get("filamentos") if isinstance(data.get("filamentos"), dict) else {}
    gauge("kits.unificado.fontes_presentes", float(_i(data.get("fontes_presentes"))))
    gauge("kits.unificado.fontes_total", float(_i(data.get("fontes_total"), len(FONTES))))
    gauge("kits.unificado.fontes_stale", float(_i(data.get("fontes_stale"))))
    gauge("kits.unificado.rivais_n", float(_i(esm.get("n_rivais"))))
    gauge("kits.unificado.rivais_comparaveis", float(_i(esm.get("n_comparaveis"))))
    gauge("kits.unificado.francesinha", float(_i(extras.get("francesinha"))))
    gauge("kits.unificado.marca_kit_n", float(len(esm.get("marca_kit") or [])))
    gauge("kits.unificado.nossos_n", float(len(esm.get("nossos") or [])))
    gauge("kits.unificado.filamento_kit_n", float(_i(fil.get("kits_no_titulo"))))
    gauge("kits.unificado.radar_stale", 1.0 if esm.get("radar_stale") else 0.0)


def processar(*, blobs: dict[str, Any] | None = None, persistir: bool = True) -> dict[str, Any]:
    """Monta, grava e emite gauges. Nunca lança."""
    try:
        snap = montar_unificado(blobs=blobs)
        if persistir and blobs is None:
            escrever_json_atomico(SNAPSHOT_PATH, snap)
        emitir_metricas(snap)
        incrementar("kits.unificado.ok")
        return snap
    except Exception as exc:
        logger.warning("kits_concorrentes_unificado: %s", exc)
        incrementar("kits.unificado.erro")
        return {"ok": False, "erro": str(exc)}
