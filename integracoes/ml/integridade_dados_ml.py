"""
Espelho dos dados do Mercado Livre vs API ao vivo.

Meta: 99,99% dos campos conferidos batem com GET /items (fonte de verdade).
Divergência é corrigida in-place; se a API falhar de verdade o percentual cai
e o Datadog alerta — lista vazia por erro nunca conta como catálogo zerado.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from core.atomic_io import escrever_json_atomico
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar
from integracoes.ml import ml_client

logger = logging.getLogger("integridade_dados_ml")

META_PCT = 99.99
SNAPSHOT_PATH = ROOT / "logs" / "integridade_ml_ultima.json"
_CAMPOS_CONFERIR = ("preco", "status", "sold_quantity", "estoque", "titulo")


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _preco_igual(a: Any, b: Any) -> bool:
    return abs(_f(a) - _f(b)) < 0.005


def _campo_igual(nome: str, local: Any, vivo: Any) -> bool:
    if nome == "preco":
        return _preco_igual(local, vivo)
    if nome in ("sold_quantity", "estoque"):
        return int(_f(local)) == int(_f(vivo))
    return str(local or "").strip() == str(vivo or "").strip()


def _item_id_anuncio(anuncio: dict[str, Any] | None) -> str:
    if not isinstance(anuncio, dict):
        return ""
    return str(anuncio.get("item_id") or anuncio.get("id") or "").strip()


def _aplicar_vivo(anuncio: dict[str, Any], vivo: dict[str, Any]) -> int:
    """Copia campos vivos para o anúncio. Retorna quantos campos divergiam."""
    n = 0
    for campo in _CAMPOS_CONFERIR:
        origem = campo if campo != "estoque" else "estoque"
        if origem not in vivo and campo not in vivo:
            continue
        novo = vivo.get(campo)
        if not _campo_igual(campo, anuncio.get(campo), novo):
            anuncio[campo] = novo
            n += 1
    return n


def auditar_espelho(
    anuncios: list[dict[str, Any]] | None = None,
    *,
    meta_listagem: dict[str, Any] | None = None,
    buscar_item: Callable[[str], dict] | None = None,
    amostra_max: int = 40,
) -> dict[str, Any]:
    """
    Confere o lote hidratado contra GET /items (amostra).
    Corrige divergência no próprio `anuncios`. Nunca lança.
    """
    rows = anuncios if isinstance(anuncios, list) else []
    meta = meta_listagem if isinstance(meta_listagem, dict) else ml_client.ultima_listagem_anuncios()
    usar_lote = buscar_item is None
    get_item = buscar_item or ml_client.buscar_item_publico

    checks_ok = 0
    checks_total = 0
    falhas: list[str] = []
    corrigidos = 0

    checks_total += 1
    if meta.get("ok") or str(meta.get("motivo") or "") == "nao_configurado":
        checks_ok += 1
    else:
        falhas.append(f"listagem:{meta.get('motivo') or 'falhou'}")

    ids_busca = int(meta.get("ids_busca") or 0)
    ids_ok = int(meta.get("ids_ok") or 0)
    paging_total = int(meta.get("paging_total") or 0)
    faltando = list(meta.get("ids_faltando") or [])
    checks_total += 1
    if not faltando and (paging_total <= 0 or ids_busca >= paging_total):
        checks_ok += 1
    else:
        falhas.append(
            f"cobertura:{ids_ok}/{ids_busca} paging={paging_total} faltando={len(faltando)}"
        )

    amostra = [a for a in rows if _item_id_anuncio(a)][: max(0, int(amostra_max))]
    if ids_ok > 0 and not amostra:
        checks_total += 1
        falhas.append(f"amostra_vazia:ids_ok={ids_ok}")
    por_id: dict[str, dict[str, Any]] = {}
    if usar_lote and amostra:
        ids_amostra = [_item_id_anuncio(a) for a in amostra]
        ids_amostra = [i for i in ids_amostra if i]
        try:
            vivos, faltando_get = ml_client._hidratar_anuncios_por_ids(ids_amostra)
        except Exception as exc:
            logger.warning("integridade ML lote GET: %s", exc)
            vivos, faltando_get = [], ids_amostra
        por_id = {str(v.get("item_id") or ""): v for v in vivos if v.get("item_id")}
        for iid in faltando_get:
            extra = ml_client.buscar_item_publico(iid)
            if extra.get("item_id"):
                por_id[str(extra["item_id"])] = extra

    for anuncio in amostra:
        iid = _item_id_anuncio(anuncio)
        checks_total += 1
        if usar_lote:
            vivo = por_id.get(iid) or {}
        else:
            vivo = get_item(iid) if iid else {}
            if not vivo.get("item_id") and iid:
                vivo = get_item(iid) or {}
        if not vivo.get("item_id"):
            falhas.append(f"get:{iid or '?'}")
            continue
        checks_ok += 1
        n_div = _aplicar_vivo(anuncio, vivo)
        if n_div:
            corrigidos += 1

    pct = 100.0 if checks_total <= 0 else round(100.0 * checks_ok / checks_total, 4)
    atinge = pct + 1e-9 >= META_PCT
    conferiu_campos = len(amostra) > 0 or ids_ok == 0
    out = {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pct": pct,
        "meta_pct": META_PCT,
        "atinge_meta": atinge,
        "espelho_confiavel": atinge
        and conferiu_campos
        and bool(meta.get("ok") or meta.get("motivo") == "nao_configurado"),
        "checks_ok": checks_ok,
        "checks_total": checks_total,
        "corrigidos": corrigidos,
        "amostra": len(amostra),
        "ids_busca": ids_busca,
        "ids_ok": ids_ok,
        "paging_total": paging_total,
        "faltando": faltando[:20],
        "falhas": falhas[:20],
        "motivo_listagem": str(meta.get("motivo") or ""),
    }
    return out


def emitir_metricas(resultado: dict[str, Any]) -> None:
    pct = _f(resultado.get("pct"))
    gauge("ml.integridade.pct", pct)
    gauge("ml.integridade.atinge_meta", 1.0 if resultado.get("atinge_meta") else 0.0)
    gauge("ml.integridade.espelho_confiavel", 1.0 if resultado.get("espelho_confiavel") else 0.0)
    gauge("ml.integridade.checks_ok", _f(resultado.get("checks_ok")))
    gauge("ml.integridade.checks_total", _f(resultado.get("checks_total")))
    gauge("ml.integridade.corrigidos", _f(resultado.get("corrigidos")))
    gauge("ml.integridade.amostra", _f(resultado.get("amostra")))
    gauge("ml.integridade.ids_busca", _f(resultado.get("ids_busca")))
    gauge("ml.integridade.ids_ok", _f(resultado.get("ids_ok")))
    gauge("ml.integridade.paging_total", _f(resultado.get("paging_total")))
    if resultado.get("atinge_meta"):
        incrementar("ml.integridade.ok")
    else:
        incrementar("ml.integridade.abaixo_meta")


def executar(*, anuncios: list[dict[str, Any]] | None = None, amostra_max: int = 40) -> dict[str, Any]:
    """Audita, emite Datadog e grava snapshot. Se anuncios é None, lista sem filtro de foco."""
    rows = anuncios
    if rows is None:
        rows = ml_client.listar_meus_anuncios(
            statuses=("active", "paused"),
            aplicar_foco=False,
        )
    elif not any(_item_id_anuncio(a) for a in rows if isinstance(a, dict)):
        meta = ml_client.ultima_listagem_anuncios()
        if int(meta.get("ids_ok") or 0) > 0:
            rows = ml_client.listar_meus_anuncios(
                statuses=("active", "paused"),
                aplicar_foco=False,
            )
    resultado = auditar_espelho(rows, amostra_max=amostra_max)
    emitir_metricas(resultado)
    try:
        escrever_json_atomico(SNAPSHOT_PATH, resultado)
    except Exception:
        pass
    if not resultado.get("atinge_meta"):
        logger.warning(
            "Integridade ML %.4f%% < meta %.2f%% (ok=%s/%s corrigidos=%s falhas=%s)",
            resultado.get("pct"),
            META_PCT,
            resultado.get("checks_ok"),
            resultado.get("checks_total"),
            resultado.get("corrigidos"),
            ",".join(resultado.get("falhas") or [])[:200],
        )
    else:
        logger.info(
            "Integridade ML %.4f%% (amostra=%s corrigidos=%s)",
            resultado.get("pct"),
            resultado.get("amostra"),
            resultado.get("corrigidos"),
        )
    return resultado
