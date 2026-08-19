"""
Momento em que campanhas Instagram/Facebook entram no ciclo operacional.

Não é o pulso do agente meta_metricas (isso já roda a cada 30 min).
É o AND da doutrina de Ads Impala (fase 3+) com a saúde da conta ML
(sem laranja/vermelho, taxas < 5%). Campanhas podem ficar em 0 até
existirem na Meta; o gauge pronto=1 é o sinal de ligar IG/FB.
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import ler_json
from core.config import ROOT
from core.datadog_metrics import gauge
from integracoes.empresa.ponto_ruptura_segundo_cnpj import _f, _saude_conta_ok

logger = logging.getLogger("ciclo_campanhas_meta")

PLATAFORMAS = ("facebook", "instagram")
SNAPSHOT_RESUMO = ROOT / "logs" / "resumo_conta_ml_ultima.json"


def _resumo_para_saude(resumo_conta: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(resumo_conta, dict):
        snap = resumo_conta
    else:
        snap = ler_json(SNAPSHOT_RESUMO, default={})
        snap = snap if isinstance(snap, dict) else {}
    out = dict(snap)
    if isinstance(snap.get("reputacao"), dict):
        out.update(snap["reputacao"])
    return out


def saude_conta_ml_ok(resumo_conta: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Reputação da loja: laranja/vermelho ou taxa ≥5% bloqueia Ads Meta."""
    conta = _resumo_para_saude(resumo_conta)
    if conta.get("ok") is False:
        return False, "resumo_indisponivel"
    return _saude_conta_ok(
        cor=str(conta.get("cor") or conta.get("level_id") or ""),
        atraso_rate=_f(conta.get("atraso_rate")),
        cancelamentos_rate=_f(conta.get("cancelamentos_rate")),
        claims_rate=_f(conta.get("claims_rate")),
    )


def avaliar_momento_ciclo_meta(
    *,
    condicoes: dict[str, Any] | None = None,
    resumo_conta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    pronto=1 só com saúde da conta ML ok E Impala na fase de Ads (3+).

    Fase 3 da doutrina: frente MIMO/PERL/JUPAES no ar, 20 reviews, nota 4.8.
    Antes disso tráfego pago IG/FB queima em listing/reputação fracos.
    """
    if not (isinstance(condicoes, dict) and condicoes.get("fase") is not None):
        from integracoes.esmaltes.doutrina_guerra_impala import avaliar_condicoes_guerra

        condicoes = avaliar_condicoes_guerra()
    lib = condicoes.get("liberar") if isinstance(condicoes.get("liberar"), dict) else {}
    try:
        fase = int(condicoes.get("fase") or 0)
    except (TypeError, ValueError):
        fase = 0
    impala_ok = bool(lib.get("ads"))
    saude_ok, saude_atual = saude_conta_ml_ok(resumo_conta)
    pronto = saude_ok and impala_ok
    if not saude_ok:
        motivo = f"saude_conta:{saude_atual}"
    elif not impala_ok:
        motivo = str(condicoes.get("proximo") or f"aguardar_fase_3_atual_{fase}")
    else:
        motivo = "ligar_ig_fb"
    return {
        "ok": True,
        "pronto": pronto,
        "saude_conta_ok": saude_ok,
        "impala_ok": impala_ok,
        "fase": fase,
        "motivo": motivo,
    }


def clicks_de_campanha(campanha: dict[str, Any]) -> float:
    """Cliques: gasto/CPC; senão impressões × CTR%."""
    cpc = _f(campanha.get("cpc"))
    gasto = _f(campanha.get("gasto"))
    if cpc > 0 and gasto > 0:
        return gasto / cpc
    impressoes = _f(campanha.get("impressoes"))
    ctr = _f(campanha.get("ctr"))
    if impressoes > 0 and ctr > 0:
        return impressoes * (ctr / 100.0)
    return 0.0


def agregar_meta_campanhas(campanhas: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = [c for c in (campanhas or []) if isinstance(c, dict)]
    metricas = [
        (c.get("metricas") if isinstance(c.get("metricas"), dict) else c) for c in rows
    ]
    gasto = sum(_f(m.get("gasto")) for m in metricas)
    impressoes = sum(_f(m.get("impressoes")) for m in metricas)
    clicks = sum(clicks_de_campanha(m) for m in metricas)
    compras = sum(_f(m.get("compras")) for m in metricas)
    receita_pixel = sum(_f(m.get("receita")) for m in metricas)
    return {
        "campanhas": len(metricas),
        "gasto_meta": round(gasto, 2),
        "impressoes": int(impressoes),
        "clicks": round(clicks, 2),
        "compras_pixel": round(compras, 2),
        "receita_meta_pixel": round(receita_pixel, 2),
    }


def avaliar_eficiencia_ciclo(
    *,
    meta: dict[str, Any] | None = None,
    ml: dict[str, Any] | None = None,
    periodo_dias: int = 1,
) -> dict[str, Any]:
    """
    Eficiência ponta a ponta: gasto/impressões/cliques Meta × pedidos/receita ML.

    Não atribui pedido a IG vs FB (sem UTM). ROAS real = receita ML / gasto Meta.
    Conversões ficam 0 até haver campanha e/ou venda.
    """
    from integracoes.social.sustentabilidade_ads_ml import avaliar_sustentabilidade

    meta = meta if isinstance(meta, dict) else {}
    ml = ml if isinstance(ml, dict) else {}
    gasto = _f(meta.get("gasto_meta"))
    impressoes = _f(meta.get("impressoes"))
    clicks = _f(meta.get("clicks"))
    compras_pixel = _f(meta.get("compras_pixel"))
    rec_pixel = _f(meta.get("receita_meta_pixel"))
    rec_ml = _f(ml.get("receita_ml"))
    pedidos = int(_f(ml.get("pedidos_ml")))
    sust = avaliar_sustentabilidade(
        gasto_meta=gasto,
        receita_meta_pixel=rec_pixel,
        receita_ml=rec_ml,
        pedidos_ml=pedidos,
        periodo_dias=periodo_dias,
    )
    conv_imp = round(pedidos / impressoes * 100.0, 4) if impressoes > 0 else 0.0
    conv_click = round(pedidos / clicks * 100.0, 4) if clicks > 0 else 0.0
    conv_pixel = round(pedidos / compras_pixel * 100.0, 2) if compras_pixel > 0 else 0.0
    cpa = round(gasto / pedidos, 2) if pedidos > 0 else (round(gasto, 2) if gasto > 0 else 0.0)
    ticket = round(rec_ml / pedidos, 2) if pedidos > 0 else 0.0
    roas_min = _f(sust.get("roas_min_meta"), 2.2)
    if gasto <= 0 and rec_ml <= 0:
        efic = 0.0
    elif gasto <= 0 and rec_ml > 0:
        efic = 100.0
    else:
        efic = min(100.0, round(_f(sust.get("roas_real")) / max(roas_min, 0.01) * 100.0, 1))
    status = str(sust.get("status") or "insuficiente_dados")
    status_num = {
        "insuficiente_dados": 0.0,
        "sustentavel": 1.0,
        "alerta": 2.0,
        "critico": 3.0,
    }.get(status, 0.0)
    return {
        **sust,
        "impressoes": int(impressoes),
        "clicks": round(clicks, 2),
        "compras_pixel": round(compras_pixel, 2),
        "conversao_imp_pct": conv_imp,
        "conversao_click_pct": conv_click,
        "conversao_pixel_vs_ml_pct": conv_pixel,
        "cpa_ml": cpa,
        "ticket_ml": ticket,
        "eficiencia_pct": efic,
        "status_num": status_num,
        "ml_ok": bool(ml.get("ok")),
    }


def emitir_metricas_ciclo_meta(
    momento: dict[str, Any] | None = None,
    *,
    plataformas: dict[str, Any] | None = None,
    eficiencia: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Gauges do gate + campanhas IG/FB + eficiência Ads×ML (0 até haver dado)."""
    try:
        mom = (
            momento
            if isinstance(momento, dict) and "pronto" in momento
            else avaliar_momento_ciclo_meta()
        )
        gauge("meta.ciclo.pronto", 1.0 if mom.get("pronto") else 0.0)
        gauge("meta.ciclo.saude_conta_ok", 1.0 if mom.get("saude_conta_ok") else 0.0)
        gauge("meta.ciclo.impala_ok", 1.0 if mom.get("impala_ok") else 0.0)
        # Mesmo sinal no ciclo 30 min: resumo_conta (diário) sozinho deixa o widget N/A.
        gauge("ml.saude.conta_ok", 1.0 if mom.get("saude_conta_ok") else 0.0)
        if plataformas is not None:
            plat = plataformas if isinstance(plataformas, dict) else {}
            for nome in PLATAFORMAS:
                bucket = plat.get(nome) if isinstance(plat.get(nome), dict) else {}
                tags = [f"plataforma:{nome}"]
                gauge("meta.campanhas_plataforma", float(bucket.get("campanhas") or 0), tags=tags)
                gauge("meta.gasto_plataforma", float(bucket.get("gasto") or 0), tags=tags)
        if isinstance(eficiencia, dict) and "roas_real" in eficiencia:
            gauge("meta.ciclo.roas_real", _f(eficiencia.get("roas_real")))
            gauge("meta.ciclo.roas_pixel", _f(eficiencia.get("roas_pixel")))
            gauge("meta.ciclo.receita_ml", _f(eficiencia.get("receita_ml")))
            gauge("meta.ciclo.pedidos_ml", _f(eficiencia.get("pedidos_ml")))
            gauge("meta.ciclo.cpa_ml", _f(eficiencia.get("cpa_ml")))
            gauge("meta.ciclo.ticket_ml", _f(eficiencia.get("ticket_ml")))
            gauge("meta.ciclo.conversao_imp_pct", _f(eficiencia.get("conversao_imp_pct")))
            gauge("meta.ciclo.conversao_click_pct", _f(eficiencia.get("conversao_click_pct")))
            gauge("meta.ciclo.cobertura_reais", _f(eficiencia.get("cobertura_reais")))
            gauge("meta.ciclo.eficiencia_pct", _f(eficiencia.get("eficiencia_pct")))
            gauge("meta.ciclo.status_num", _f(eficiencia.get("status_num")))
            gauge("meta.ciclo.impressoes", _f(eficiencia.get("impressoes")))
            mom["eficiencia"] = {
                "roas_real": eficiencia.get("roas_real"),
                "roas_pixel": eficiencia.get("roas_pixel"),
                "receita_ml": eficiencia.get("receita_ml"),
                "pedidos_ml": eficiencia.get("pedidos_ml"),
                "cpa_ml": eficiencia.get("cpa_ml"),
                "conversao_imp_pct": eficiencia.get("conversao_imp_pct"),
                "conversao_click_pct": eficiencia.get("conversao_click_pct"),
                "eficiencia_pct": eficiencia.get("eficiencia_pct"),
                "status": eficiencia.get("status"),
            }
        return mom
    except Exception as exc:
        logger.warning("emitir_metricas_ciclo_meta: %s", exc)
        return {"ok": False, "erro": str(exc)}
