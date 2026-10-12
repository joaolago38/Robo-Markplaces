"""
integracoes/ml/monitor_buybox.py
Ofertas de catálogo compartilhado (GET /products/{id}/items) e histórico
de quem aparece na posição 0 — proxy de buy box, não dado oficial do ML.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT
from core.datadog_metrics import gauge, tag_produto
from integracoes.ml import ml_client

logger = logging.getLogger("monitor_buybox")

HISTORY_PATH = ROOT / "logs" / "buybox_history.json"
_MAX_SNAPSHOTS = 400


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(raw: Any) -> datetime | None:
    texto = str(raw or "").strip()
    if not texto:
        return None
    try:
        dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def consultar_ofertas_catalogo(catalog_product_id: str) -> list[dict[str, Any]]:
    """
    Lista ofertas ativas do catálogo. Nunca lança.
    posicao_na_lista=0 é inferência de destaque (buy box), não campo oficial.
    """
    pid = str(catalog_product_id or "").strip().upper().replace("-", "")
    if not pid:
        return []
    try:
        if not ml_client._enabled():
            return []
        r = ml_client._request_ml(
            "GET",
            f"{ml_client.BASE}/products/{pid}/items",
            params={"status": "active"},
            timeout=20,
        )
        if r.status_code != 200:
            logger.warning(
                "ofertas catálogo %s HTTP %s",
                pid,
                r.status_code,
            )
            return []
        body = r.json() or {}
        results = body.get("results") or body.get("items") or []
        ts = _agora_iso()
        ofertas: list[dict[str, Any]] = []
        for i, row in enumerate(results):
            if not isinstance(row, dict):
                continue
            item_id = str(row.get("item_id") or row.get("id") or "").strip().upper()
            seller = row.get("seller_id")
            if seller is None and isinstance(row.get("seller"), dict):
                seller = row["seller"].get("id")
            ofertas.append(
                {
                    "item_id": item_id,
                    "seller_id": str(seller or "").strip(),
                    "preco": round(_f(row.get("price") or row.get("preco")), 2),
                    "posicao_na_lista": i,
                    "listing_type_id": str(row.get("listing_type_id") or ""),
                    "timestamp_coleta": ts,
                }
            )
        return ofertas
    except Exception as exc:
        logger.warning("consultar ofertas catálogo %s: %s", pid, exc)
        return []


def detectar_vencedor_buybox(ofertas: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Oferta na posição 0. metodo deixa explícito que é inferência pela ordem da API."""
    if not ofertas:
        return None
    ordenadas = sorted(
        [o for o in ofertas if isinstance(o, dict)],
        key=lambda o: int(o.get("posicao_na_lista") or 0),
    )
    if not ordenadas:
        return None
    vencedor = dict(ordenadas[0])
    vencedor["metodo"] = "posicao_lista_api"
    return vencedor


def _carregar_historico() -> dict[str, Any]:
    data = ler_json(HISTORY_PATH, default={})
    return data if isinstance(data, dict) else {}


def registrar_snapshot_buybox(
    catalog_product_id: str,
    ofertas: list[dict[str, Any]],
) -> dict[str, Any]:
    """Append de snapshot em logs/buybox_history.json. Nunca lança."""
    pid = str(catalog_product_id or "").strip().upper().replace("-", "")
    vazio = {
        "catalog_product_id": pid,
        "timestamp": _agora_iso(),
        "ofertas": [],
        "vencedor_atual": None,
    }
    if not pid:
        return vazio
    try:
        snapshot = {
            "catalog_product_id": pid,
            "timestamp": _agora_iso(),
            "ofertas": [dict(o) for o in ofertas if isinstance(o, dict)],
            "vencedor_atual": detectar_vencedor_buybox(ofertas),
        }
        hist = _carregar_historico()
        bloco = hist.get(pid) if isinstance(hist.get(pid), dict) else {}
        snaps = list(bloco.get("snapshots") or [])
        snaps.append(snapshot)
        hist[pid] = {"snapshots": snaps[-_MAX_SNAPSHOTS:]}
        escrever_json_atomico(HISTORY_PATH, hist)
        return snapshot
    except Exception as exc:
        logger.warning("registrar snapshot buybox %s: %s", pid, exc)
        return vazio


def analisar_estabilidade_vencedor(
    catalog_product_id: str,
    dias: int = 7,
) -> dict[str, Any]:
    """
    % do tempo na posição 0 por seller nos últimos N dias.
    Sem histórico suficiente: ok=False, sem inventar percentual.
    """
    pid = str(catalog_product_id or "").strip().upper().replace("-", "")
    insuficiente = {"ok": False, "motivo": "historico insuficiente"}
    if not pid:
        return insuficiente
    try:
        hist = _carregar_historico()
        bloco = hist.get(pid) if isinstance(hist.get(pid), dict) else {}
        snaps = [s for s in (bloco.get("snapshots") or []) if isinstance(s, dict)]
        corte = datetime.now(timezone.utc) - timedelta(days=max(1, int(dias)))
        janela: list[dict[str, Any]] = []
        for snap in snaps:
            ts = _parse_ts(snap.get("timestamp"))
            if ts is None or ts < corte:
                continue
            janela.append(snap)
        if len(janela) < 2:
            return insuficiente
        janela.sort(key=lambda s: _parse_ts(s.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc))

        contagem: dict[str, int] = {}
        precos_vencedor: list[float] = []
        precos_por_seller: dict[str, list[float]] = {}
        for snap in janela:
            vencedor = snap.get("vencedor_atual")
            if not isinstance(vencedor, dict):
                vencedor = detectar_vencedor_buybox(snap.get("ofertas") or [])
            if not isinstance(vencedor, dict):
                continue
            sid = str(vencedor.get("seller_id") or "").strip() or "?"
            preco = _f(vencedor.get("preco"))
            contagem[sid] = contagem.get(sid, 0) + 1
            if preco > 0:
                precos_vencedor.append(preco)
                precos_por_seller.setdefault(sid, []).append(preco)

        total = sum(contagem.values())
        if total < 2:
            return insuficiente

        pct = {
            sid: round(100.0 * n / total, 1)
            for sid, n in sorted(contagem.items(), key=lambda x: -x[1])
        }
        vencedor_recente = janela[-1].get("vencedor_atual")
        if not isinstance(vencedor_recente, dict):
            vencedor_recente = detectar_vencedor_buybox(janela[-1].get("ofertas") or [])
        preco_atual = _f((vencedor_recente or {}).get("preco"))
        preco_medio = (
            round(sum(precos_vencedor) / len(precos_vencedor), 2) if precos_vencedor else None
        )
        seller_freq = next(iter(pct)) if pct else ""
        precos_freq = precos_por_seller.get(seller_freq) or []
        base_rec = precos_freq[-1] if precos_freq else preco_atual
        recomendacao = round(base_rec - 0.01, 2) if base_rec > 0.01 else None
        return {
            "ok": True,
            "catalog_product_id": pid,
            "snapshots_janela": len(janela),
            "dias": int(dias),
            "pct_tempo_cada_seller": pct,
            "preco_medio_vencedor": preco_medio,
            "preco_atual_vencedor": preco_atual if preco_atual > 0 else None,
            "vencedor_atual": vencedor_recente,
            "recomendacao_preco": recomendacao,
            "aviso_recomendacao": (
                "Sugestão: preço do vencedor mais frequente menos R$ 0,01. "
                "Não é decisão automática nem dado oficial de buy box."
            ),
        }
    except Exception as exc:
        logger.warning("analisar estabilidade buybox %s: %s", pid, exc)
        return insuficiente


def emitir_metricas_buybox(
    catalog_product_id: str,
    ofertas: list[dict[str, Any]],
    vencedor: dict[str, Any] | None,
    analise: dict[str, Any],
    *,
    produto_id: str = "",
    nosso_seller_id: str = "",
) -> None:
    """Gauges robo.buybox.* — preço, ofertas, % tempo e se somos o vencedor."""
    tags: list[str] = []
    pid = str(catalog_product_id or "").strip()
    if pid:
        tags.append(f"catalog:{pid[:80]}")
    tp = tag_produto(produto_id)
    if tp:
        tags.append(tp)
    n = len([o for o in (ofertas or []) if isinstance(o, dict)])
    gauge("buybox.n_ofertas", float(n), tags=tags)
    vin = vencedor if isinstance(vencedor, dict) else None
    if vin and vin.get("preco") is not None:
        try:
            gauge("buybox.preco_vencedor", float(vin["preco"]), tags=tags)
        except (TypeError, ValueError):
            pass
    sid = str((vin or {}).get("seller_id") or "").strip()
    nosso = str(nosso_seller_id or "").strip()
    if nosso:
        gauge("buybox.ganhando", 1.0 if sid and sid == nosso else 0.0, tags=tags)
    bloco = analise if isinstance(analise, dict) else {}
    hist_ok = 1.0 if bloco.get("ok") else 0.0
    gauge("buybox.historico_ok", hist_ok, tags=tags)
    if not hist_ok:
        return
    pct_map = bloco.get("pct_tempo_cada_seller")
    if isinstance(pct_map, dict) and sid and sid in pct_map:
        try:
            gauge("buybox.pct_tempo_vencedor", float(pct_map[sid]), tags=tags)
        except (TypeError, ValueError):
            pass
    if isinstance(pct_map, dict) and pct_map:
        try:
            max_pct = max(float(v) for v in pct_map.values())
            gauge("buybox.estavel", 1.0 if max_pct >= 70.0 else 0.0, tags=tags)
        except (TypeError, ValueError):
            pass
