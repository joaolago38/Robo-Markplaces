"""
integracoes/importacao/comparar_portos_alibaba.py
Compara condições de importação aéreo/marítimo em qualquer porto/aeroporto
do Brasil, sempre com estrutura Alibaba (FOB USD) como referência.

Qualquer produto ofertado no território brasileiro (ou via catálogo Alibaba)
pode ser avaliado: calcula landed por gateway e ranqueia condições atrativas.
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar
from core.horario import agora_brasil
from integracoes.importacao.custo_landed import calcular_custo_landed
from integracoes.importacao.portos_brasil import (
    distancia_km_para_cep,
    gateway_por_codigo,
    icms_gateway,
    listar_gateways,
    resumo_estrutura_gateway,
)

logger = logging.getLogger("comparar_portos_alibaba")

SNAPSHOT_PATH = ROOT / "logs" / "comparar_portos_alibaba_ultima.json"


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v: Any, default: int = 1) -> int:
    try:
        return max(1, int(v))
    except (TypeError, ValueError):
        return default


def _cfg():
    from core import config as cfg

    return cfg


def normalizar_produto_alibaba(produto: dict[str, Any] | None) -> dict[str, Any]:
    """
    Aceita produto do catálogo Alibaba, oportunidade de busca ou
    oferta genérica em território BR (preço FOB/USD + peso).
    """
    p = dict(produto or {})
    preco = p.get("preco_fob_usd")
    if preco is None:
        preco = p.get("preco_usd") or p.get("price_usd") or p.get("fob_usd")
    unidade = max(1, _i(p.get("unidade_por_preco"), 1))
    fob = _f(preco)
    if fob > 0 and unidade > 1:
        fob = fob / unidade

    return {
        "id": p.get("id") or p.get("sku") or p.get("product_id") or "produto",
        "nome": p.get("nome") or p.get("titulo") or p.get("title") or "Produto Alibaba",
        "preco_fob_usd": fob,
        "peso_kg": max(0.01, _f(p.get("peso_kg") or p.get("weight_kg"), 1.0)),
        "quantidade": _i(p.get("moq") or p.get("moq_referencia") or p.get("quantidade"), 1),
        "ncm": str(p.get("ncm") or ""),
        "ii_pct": _f(p.get("ii_pct"), 16.0),
        "ipi_pct": _f(p.get("ipi_pct"), 0.0),
        "icms_pct": p.get("icms_pct"),
        "origem": "alibaba" if (
            p.get("termo_busca") or p.get("alibaba") or "alibaba" in str(p.get("fonte") or "").lower()
        ) else str(p.get("fonte") or "territorio_br_ou_alibaba"),
        "territorio": "BR",
        "raw_keys": sorted(p.keys())[:20],
    }


def calcular_landed_no_gateway(
    produto_norm: dict[str, Any],
    gateway: dict[str, Any],
    *,
    cambio_usd_brl: float,
    cep_destino: str | None = None,
    uf_destino: str | None = None,
) -> dict[str, Any]:
    """Landed cost no gateway (aéreo ou marítimo) com estrutura Alibaba."""
    modal = str(gateway.get("tipo") or "maritimo")
    if modal not in ("aereo", "maritimo"):
        modal = "maritimo"

    km = distancia_km_para_cep(str(gateway.get("codigo") or ""), cep_destino)
    custos = gateway.get("custos_locais_brl") or {}
    locais = sum(
        _f(custos.get(k))
        for k in ("armazenagem", "desembaraco", "thc_manuseio", "siscomex", "outros")
    )
    frete_interno_unit = (km * _f(gateway.get("frete_interno_brl_por_km"), 5.0)) / max(
        1, _i(produto_norm.get("quantidade"))
    )
    # Rateia custos locais fixos na quantidade
    qty = _i(produto_norm.get("quantidade"))
    desembaraco_eq = locais  # passa como desembaraco+siscomex agregados no landed

    icms = _f(produto_norm.get("icms_pct"))
    if icms <= 0:
        icms = icms_gateway(gateway, uf_destino)

    frete_usd_kg = _f(gateway.get("frete_internacional_usd_kg"), 0.85 if modal == "maritimo" else 5.5)

    landed = calcular_custo_landed(
        produto_norm["preco_fob_usd"],
        cambio_usd_brl=cambio_usd_brl,
        peso_kg_unit=produto_norm["peso_kg"],
        quantidade=qty,
        modo_frete=modal,  # type: ignore[arg-type]
        ii_pct=_f(produto_norm.get("ii_pct"), 16.0),
        ipi_pct=_f(produto_norm.get("ipi_pct"), 0.0),
        icms_pct=icms,
        frete_maritimo_usd_kg=frete_usd_kg if modal == "maritimo" else 0.85,
        frete_aereo_usd_kg=frete_usd_kg if modal == "aereo" else 5.5,
        siscomex_brl=0.0,  # já no agregados locais
        desembaraco_brl=desembaraco_eq,
        frete_nacional_brl_unit=frete_interno_unit,
    )
    if not landed.get("ok"):
        return {**landed, "gateway": resumo_estrutura_gateway(gateway)}

    score_atrativo = _score_atratividade(
        landed_unit=_f(landed.get("custo_unitario_brl")),
        fob_usd=_f(produto_norm.get("preco_fob_usd")),
        cambio=cambio_usd_brl,
        atratividade_cat=_f(gateway.get("atratividade"), 50),
        modal=modal,
    )

    return {
        "ok": True,
        "referencia": "alibaba",
        "modal": modal,
        "gateway": resumo_estrutura_gateway(gateway),
        "cep_destino": cep_destino,
        "distancia_km": round(km, 1),
        "frete_interno_brl_unit": round(frete_interno_unit, 2),
        "custos_locais_brl": round(locais, 2),
        "custo_unitario_brl": landed.get("custo_unitario_brl"),
        "custo_total_brl": landed.get("custo_total_brl"),
        "cif_brl": landed.get("cif_brl"),
        "impostos_total_brl": landed.get("impostos_total_brl"),
        "frete_internacional_brl": landed.get("frete_internacional_brl"),
        "score_atratividade": score_atrativo,
        "landed": landed,
    }


def _score_atratividade(
    *,
    landed_unit: float,
    fob_usd: float,
    cambio: float,
    atratividade_cat: float,
    modal: str,
) -> float:
    """
    Score 0–100: menor landed vs FOB convertido + atratividade do hub.
    Preferência leve ao marítimo em volume (custo) e aéreo em agilidade (catálogo).
    """
    fob_brl = max(0.01, fob_usd * cambio)
    markup = landed_unit / fob_brl if fob_brl else 99.0
    # markup 1.3 → bom; 2.5+ → ruim
    score_custo = max(0.0, min(100.0, 100.0 - (markup - 1.2) * 80.0))
    peso_cat = 0.35
    peso_custo = 0.65
    base = peso_custo * score_custo + peso_cat * atratividade_cat
    if modal == "maritimo" and markup < 1.8:
        base += 3.0
    if modal == "aereo" and markup < 1.6:
        base += 2.0
    return round(min(100.0, max(0.0, base)), 1)


def eh_condicao_atrativa(cenario: dict[str, Any]) -> bool:
    cfg = _cfg()
    min_score = float(getattr(cfg, "IMPORTACAO_PORTOS_SCORE_MIN_ATRATIVA", 55.0))
    max_markup = float(getattr(cfg, "IMPORTACAO_PORTOS_MARKUP_MAX_ATRATIVA", 2.2))
    if not cenario.get("ok"):
        return False
    if _f(cenario.get("score_atratividade")) < min_score:
        return False
    landed = cenario.get("landed") or {}
    fob = _f((cenario.get("landed") or {}).get("fob_usd_unit"))
    cambio = _f(landed.get("cambio_usd_brl"), 1.0)
    unit = _f(cenario.get("custo_unitario_brl"))
    if fob > 0 and cambio > 0 and unit / (fob * cambio) > max_markup:
        return False
    return True


def comparar_portos_para_produto_alibaba(
    produto: dict[str, Any],
    *,
    cambio_usd_brl: float | None = None,
    cep_destino: str | None = None,
    uf_destino: str | None = None,
    modal: str = "todos",
    codigos: list[str] | None = None,
    top_n: int = 8,
) -> dict[str, Any]:
    """
    Ranqueia todos (ou filtrados) portos/aeroportos do BR para o produto Alibaba.
    Retorna melhores condições aéreo e marítimo + lista atrativas.
    """
    from integracoes.cambio.cotacao_usd import (
        cotacao_confiavel_para_margem,
        obter_cotacao_usd,
    )
    from integracoes.importacao.operacao_destino import normalizar_cep, resumo_destino

    prod = normalizar_produto_alibaba(produto)
    if prod["preco_fob_usd"] <= 0:
        return {"ok": False, "motivo": "produto_sem_fob_usd_alibaba", "produto": prod}

    dest = resumo_destino()
    cep = normalizar_cep(cep_destino or dest.get("destino_cep") or "13467-694")
    uf = (uf_destino or dest.get("destino_uf") or "SP").upper()

    if cambio_usd_brl is None:
        cot = obter_cotacao_usd(usar_cache=True)
        if not cotacao_confiavel_para_margem(cot):
            return {
                "ok": False,
                "motivo": "cambio_nao_confiavel",
                "produto": prod,
                "cambio": cot,
            }
        cambio = _f(cot.get("usd_brl"))
        cambio_meta = cot
    else:
        cambio = float(cambio_usd_brl)
        cambio_meta = {"ok": True, "usd_brl": cambio, "fonte": "parametro"}

    if codigos:
        gateways = []
        for c in codigos:
            g = gateway_por_codigo(c)
            if g and g.get("ativo", True):
                gateways.append(g)
    else:
        modal_f = modal if modal in ("aereo", "maritimo", "todos") else "todos"
        gateways = listar_gateways(modal=modal_f)  # type: ignore[arg-type]

    cenarios: list[dict[str, Any]] = []
    for g in gateways:
        try:
            cenarios.append(
                calcular_landed_no_gateway(
                    prod, g, cambio_usd_brl=cambio, cep_destino=cep, uf_destino=uf
                )
            )
        except Exception as exc:
            logger.debug("gateway %s: %s", g.get("codigo"), exc)

    ok_list = [c for c in cenarios if c.get("ok")]
    ok_list.sort(key=lambda c: (-_f(c.get("score_atratividade")), _f(c.get("custo_unitario_brl"), 1e9)))

    atrativas = [c for c in ok_list if eh_condicao_atrativa(c)]
    melhor_aereo = next((c for c in ok_list if c.get("modal") == "aereo"), None)
    melhor_maritimo = next((c for c in ok_list if c.get("modal") == "maritimo"), None)
    melhor_geral = ok_list[0] if ok_list else None

    out = {
        "ok": bool(ok_list),
        "gerado_em": agora_brasil().isoformat(),
        "referencia": "alibaba",
        "territorio": "BR",
        "produto": prod,
        "cambio": {"usd_brl": cambio, **{k: cambio_meta.get(k) for k in ("fonte", "confiavel", "ok")}},
        "destino": {"cep": cep, "uf": uf},
        "total_gateways_avaliados": len(cenarios),
        "total_atrativos": len(atrativas),
        "melhor_geral": _resumo_cenario(melhor_geral),
        "melhor_aereo": _resumo_cenario(melhor_aereo),
        "melhor_maritimo": _resumo_cenario(melhor_maritimo),
        "top_atrativos": [_resumo_cenario(c) for c in atrativas[:top_n]],
        "ranking": [_resumo_cenario(c) for c in ok_list[: max(top_n, 12)]],
        "aviso": (
            "Custos estimados por porto/aeroporto BR · referência FOB Alibaba. "
            "Confirme frete real e NCM com despachante/agente de carga."
        ),
    }

    _emitir_metricas(out)
    escrever_json_atomico(SNAPSHOT_PATH, out)
    return out


def _resumo_cenario(c: dict[str, Any] | None) -> dict[str, Any] | None:
    if not c or not c.get("ok"):
        return None
    g = c.get("gateway") or {}
    return {
        "codigo": g.get("codigo"),
        "nome": g.get("nome"),
        "cidade": g.get("cidade"),
        "uf": g.get("uf"),
        "modal": c.get("modal"),
        "custo_unitario_brl": c.get("custo_unitario_brl"),
        "custo_total_brl": c.get("custo_total_brl"),
        "score_atratividade": c.get("score_atratividade"),
        "atrativa": eh_condicao_atrativa(c),
        "distancia_km": c.get("distancia_km"),
        "frete_internacional_brl": c.get("frete_internacional_brl"),
        "custos_locais_brl": c.get("custos_locais_brl"),
    }


def _emitir_metricas(out: dict[str, Any]) -> None:
    tags = ["referencia:alibaba", "territorio:BR"]
    melhor = out.get("melhor_geral") or {}
    if melhor.get("modal"):
        tags.append(f"modal:{melhor['modal']}")
    if melhor.get("codigo"):
        tags.append(f"gateway:{str(melhor['codigo'])[:12]}")
    gauge("portos_alibaba.gateways_avaliados", float(out.get("total_gateways_avaliados") or 0), tags)
    gauge("portos_alibaba.atrativos", float(out.get("total_atrativos") or 0), tags)
    if melhor.get("custo_unitario_brl") is not None:
        gauge("portos_alibaba.melhor_custo_unit", float(melhor["custo_unitario_brl"]), tags)
    if melhor.get("score_atratividade") is not None:
        gauge("portos_alibaba.melhor_score", float(melhor["score_atratividade"]), tags)
    incrementar("portos_alibaba.comparacao_ok" if out.get("ok") else "portos_alibaba.comparacao_erro", tags=tags)


def formatar_comparacao_telegram(resultado: dict[str, Any], *, max_linhas: int = 6) -> str:
    """Card curto para Telegram."""
    if not resultado.get("ok"):
        return f"_Comparação portos Alibaba falhou: `{resultado.get('motivo')}`_"

    prod = resultado.get("produto") or {}
    linhas = [
        "🚢✈️ *Portos BR × Alibaba*",
        f"Produto: *{prod.get('nome')}* · FOB US$ {prod.get('preco_fob_usd')}",
        f"USD R$ {(resultado.get('cambio') or {}).get('usd_brl')} · "
        f"CEP `{(resultado.get('destino') or {}).get('cep')}`",
        f"Avaliados: *{resultado.get('total_gateways_avaliados')}* · "
        f"Atrativos: *{resultado.get('total_atrativos')}*",
    ]
    melhor = resultado.get("melhor_geral")
    if melhor:
        linhas.append(
            f"✅ Melhor: *{melhor.get('codigo')}* {melhor.get('nome')} "
            f"({melhor.get('modal')}) · R$ {melhor.get('custo_unitario_brl')}/un · "
            f"score {melhor.get('score_atratividade')}"
        )
    ma = resultado.get("melhor_aereo")
    mm = resultado.get("melhor_maritimo")
    if ma:
        linhas.append(
            f"✈️ Aéreo: `{ma.get('codigo')}` R$ {ma.get('custo_unitario_brl')}/un"
        )
    if mm:
        linhas.append(
            f"🚢 Marítimo: `{mm.get('codigo')}` R$ {mm.get('custo_unitario_brl')}/un"
        )
    linhas.append("*Top atrativos*")
    for c in (resultado.get("top_atrativos") or [])[:max_linhas]:
        linhas.append(
            f"• `{c.get('codigo')}` {c.get('modal')} · "
            f"R$ {c.get('custo_unitario_brl')} · score {c.get('score_atratividade')}"
        )
    linhas.append(f"_{resultado.get('aviso')}_")
    return "\n".join(linhas)
