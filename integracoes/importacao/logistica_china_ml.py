"""
integracoes/importacao/logistica_china_ml.py
Custo logístico 40HC China → porto BR → hub Full do Mercado Livre.

Compara oceano + AFRMM + custos locais + rodoviário. Sem mercadoria nem
II/IPI/PIS/COFINS (quase iguais entre portos). Toggle no agente:
LOGISTICA_CHINA_ML_ATIVO (default 0).
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar
from core.horario import agora_brasil
from integracoes.importacao.portos_brasil import gateway_por_codigo

logger = logging.getLogger("logistica_china_ml")

SNAPSHOT_PATH = ROOT / "logs" / "logistica_china_ml_ultima.json"
CATALOGO_REL = "catalogo/logistica_china_ml.json"


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _cfg():
    from core import config as cfg

    return cfg


def carregar_catalogo(caminho: str | None = None) -> dict[str, Any]:
    rel = caminho or getattr(_cfg(), "LOGISTICA_CHINA_ML_CATALOGO", CATALOGO_REL)
    data = ler_json(ROOT / rel, default={})
    return data if isinstance(data, dict) else {}


def inland_40hc_brl(km: float, inland: dict[str, Any] | None = None) -> float:
    cfg = inland or {}
    piso = _f(cfg.get("piso_brl"), 2200.0)
    ate = _f(cfg.get("brl_por_km_ate_400"), 8.0)
    acima = _f(cfg.get("brl_por_km_acima_400"), 5.5)
    k = max(0.0, _f(km))
    return round(piso + min(k, 400.0) * ate + max(0.0, k - 400.0) * acima, 2)


def _locais_brl(codigo: str) -> float:
    g = gateway_por_codigo(codigo) or {}
    c = g.get("custos_locais_brl") or {}
    if not isinstance(c, dict):
        return 0.0
    return round(sum(_f(c.get(k)) for k in ("armazenagem", "desembaraco", "thc_manuseio", "siscomex", "outros")), 2)


def _origem(cat: dict[str, Any], origem_id: str) -> dict[str, Any]:
    itens = cat.get("origens_china") or []
    for o in itens:
        if isinstance(o, dict) and str(o.get("id") or "") == origem_id:
            return o
    return itens[0] if itens and isinstance(itens[0], dict) else {"id": origem_id, "nome": origem_id, "ocean_mult": 1.0}


def _hub(cat: dict[str, Any], hub_id: str) -> dict[str, Any]:
    itens = cat.get("hubs_ml") or []
    for h in itens:
        if isinstance(h, dict) and str(h.get("id") or "") == hub_id:
            return h
    return itens[0] if itens and isinstance(itens[0], dict) else {"id": hub_id, "nome": hub_id, "regiao": "sudeste"}


def _playbook(hub: dict[str, Any]) -> str:
    regiao = str(hub.get("regiao") or "sudeste")
    if regiao == "sul":
        return (
            "Para o Full de Santa Catarina, Navegantes/Itapoá/Itajaí ganham de Santos "
            "no rodoviário (79–120 km vs ~750 km)."
        )
    if regiao == "nordeste":
        return (
            "Suape/Pecém só vencem quando o estoque entra no Full local. "
            "Para o Sudeste, transbordo e 2.400 km destroem a margem."
        )
    return (
        "Para o hub principal do ML (Cajamar/Campinas/Araçariguama/Extrema) e para "
        "Americana, Santos é o menor custo total."
    )


def ranquear_portos_ml(
    *,
    origem_id: str = "szx",
    hub_id: str = "cajamar",
    cambio_usd_brl: float | None = None,
    gravar: bool = True,
) -> dict[str, Any]:
    """Ranqueia portos BR pelo custo logístico 40HC até o hub do ML."""
    cat = carregar_catalogo()
    if not (cat.get("portos_br") or []):
        out = {"ok": False, "motivo": "catalogo_logistica_china_ml_vazio"}
        incrementar("logistica_china_ml.erro", tags=["motivo:catalogo"])
        return out

    origem = _origem(cat, origem_id)
    hub = _hub(cat, hub_id)
    inland_cfg = cat.get("inland_40hc") if isinstance(cat.get("inland_40hc"), dict) else {}
    afrmm_pct = _f(cat.get("afrmm_pct"), 8.0) / 100.0
    mult = _f(origem.get("ocean_mult"), 1.0)

    if cambio_usd_brl is None:
        try:
            from integracoes.cambio.cotacao_usd import obter_cotacao_usd

            cot = obter_cotacao_usd(usar_cache=True) or {}
            cambio = _f(cot.get("usd_brl"), _f(cat.get("cambio_fallback_usd_brl"), 5.5))
            cambio_meta = cot if cot.get("ok") else {"ok": True, "usd_brl": cambio, "fonte": "fallback_catalogo"}
        except Exception:
            cambio = _f(cat.get("cambio_fallback_usd_brl"), 5.5)
            cambio_meta = {"ok": True, "usd_brl": cambio, "fonte": "fallback_catalogo"}
    else:
        cambio = float(cambio_usd_brl)
        cambio_meta = {"ok": True, "usd_brl": cambio, "fonte": "parametro"}

    ranking: list[dict[str, Any]] = []
    for p in cat.get("portos_br") or []:
        if not isinstance(p, dict):
            continue
        codigo = str(p.get("codigo") or "").upper()
        if not codigo:
            continue
        gw = gateway_por_codigo(codigo) or {}
        km_map = p.get("km") if isinstance(p.get("km"), dict) else {}
        km = _f(km_map.get(hub.get("id")), 9999)
        ocean_usd = round(_f(p.get("ocean_usd_40hc")) * mult, 2)
        ocean_brl = round(ocean_usd * cambio, 2)
        afrmm = round(ocean_brl * afrmm_pct, 2)
        locais = _locais_brl(codigo)
        inland = inland_40hc_brl(km, inland_cfg)
        total = round(ocean_brl + afrmm + locais + inland, 2)
        ranking.append(
            {
                "codigo": codigo,
                "nome": gw.get("nome") or codigo,
                "uf": gw.get("uf") or "",
                "rota": p.get("rota") or "direta",
                "transit_dias": p.get("transit_dias") or "",
                "ocean_usd": ocean_usd,
                "ocean_brl": ocean_brl,
                "afrmm_brl": afrmm,
                "locais_brl": locais,
                "km": km,
                "inland_brl": inland,
                "total_logistico_brl": total,
            }
        )

    ranking.sort(key=lambda r: float(r["total_logistico_brl"]))
    melhor = ranking[0] if ranking else {}
    base = float(melhor.get("total_logistico_brl") or 0)
    for r in ranking:
        r["delta_vs_melhor_brl"] = round(float(r["total_logistico_brl"]) - base, 2)

    santos = next((r for r in ranking if r["codigo"] == "BRSSZ"), None)
    suape = next((r for r in ranking if r["codigo"] == "BRSUA"), None)

    out: dict[str, Any] = {
        "ok": bool(ranking),
        "gerado_em": agora_brasil().isoformat(),
        "toggle": "LOGISTICA_CHINA_ML_ATIVO",
        "origem": {
            "id": origem.get("id"),
            "nome": origem.get("nome"),
            "regiao": origem.get("regiao"),
            "perfil": origem.get("perfil"),
            "ocean_mult": mult,
        },
        "hub_ml": {
            "id": hub.get("id"),
            "nome": hub.get("nome"),
            "papel": hub.get("papel"),
            "regiao": hub.get("regiao"),
        },
        "cambio": cambio_meta,
        "afrmm_pct": afrmm_pct * 100.0,
        "ocean_coleta": cat.get("ocean_coleta"),
        "melhor": melhor,
        "playbook": _playbook(hub),
        "veredito": (
            f"{origem.get('nome')} → {melhor.get('nome')} → {hub.get('nome')}"
            if melhor
            else ""
        ),
        "delta_suape_vs_melhor_brl": (
            round(float(suape["total_logistico_brl"]) - base, 2) if suape else None
        ),
        "delta_santos_vs_melhor_brl": (
            round(float(santos["total_logistico_brl"]) - base, 2) if santos else None
        ),
        "ranking": ranking,
        "aviso": cat.get("aviso_legal"),
    }

    tags = [f"origem:{origem.get('id')}", f"hub:{hub.get('id')}"]
    if gravar:
        escrever_json_atomico(SNAPSHOT_PATH, out)
    if out.get("ok"):
        incrementar("logistica_china_ml.ok", tags=tags)
        gauge("logistica_china_ml.melhor_total_brl", float(melhor.get("total_logistico_brl") or 0), tags)
        if suape:
            gauge("logistica_china_ml.delta_suape_brl", float(out["delta_suape_vs_melhor_brl"] or 0), tags)
    else:
        incrementar("logistica_china_ml.erro", tags=tags)
    return out


def formatar_logistica_telegram(resultado: dict[str, Any], *, max_linhas: int = 6) -> str:
    if resultado.get("motivo") == "LOGISTICA_CHINA_ML_ATIVO=0":
        return (
            "_Logística China→ML desligada_ (`LOGISTICA_CHINA_ML_ATIVO=0`). "
            "CLI: `--forcar` ou env=1."
        )
    if not resultado.get("ok"):
        return f"_Logística China→ML falhou: `{resultado.get('motivo')}`_"

    origem = resultado.get("origem") or {}
    hub = resultado.get("hub_ml") or {}
    melhor = resultado.get("melhor") or {}
    cambio = resultado.get("cambio") or {}
    linhas = [
        "🇨🇳➡️📦 *China → portos BR → ML Full*",
        f"Origem: *{origem.get('nome')}* · Hub: *{hub.get('nome')}*",
        f"USD R$ {cambio.get('usd_brl')} · 40HC (sem mercadoria/tributos)",
        f"✅ Melhor: *{melhor.get('nome')}* ({melhor.get('uf')}) "
        f"R$ {melhor.get('total_logistico_brl')} · {melhor.get('transit_dias')} d "
        f"({melhor.get('rota')})",
        f"_{resultado.get('playbook')}_",
    ]
    for r in (resultado.get("ranking") or [])[:max_linhas]:
        delta = r.get("delta_vs_melhor_brl") or 0
        marca = "→" if delta == 0 else f"+{delta}"
        linhas.append(
            f"• `{r.get('codigo')}` {r.get('nome')} · {marca} · "
            f"{r.get('km')} km · {r.get('rota')}"
        )
    extra = resultado.get("delta_suape_vs_melhor_brl")
    if extra and extra > 0:
        linhas.append(f"Suape neste hub: +R$ {extra} vs 1º")
    return "\n".join(linhas)
