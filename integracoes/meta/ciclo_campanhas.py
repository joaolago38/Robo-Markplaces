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


def emitir_metricas_ciclo_meta(
    momento: dict[str, Any] | None = None,
    *,
    plataformas: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Gauges do gate + campanhas IG/FB (0 até existir campanha na Meta)."""
    try:
        mom = (
            momento
            if isinstance(momento, dict) and "pronto" in momento
            else avaliar_momento_ciclo_meta()
        )
        gauge("meta.ciclo.pronto", 1.0 if mom.get("pronto") else 0.0)
        gauge("meta.ciclo.saude_conta_ok", 1.0 if mom.get("saude_conta_ok") else 0.0)
        gauge("meta.ciclo.impala_ok", 1.0 if mom.get("impala_ok") else 0.0)
        if plataformas is not None:
            plat = plataformas if isinstance(plataformas, dict) else {}
            for nome in PLATAFORMAS:
                bucket = plat.get(nome) if isinstance(plat.get(nome), dict) else {}
                tags = [f"plataforma:{nome}"]
                gauge("meta.campanhas_plataforma", float(bucket.get("campanhas") or 0), tags=tags)
                gauge("meta.gasto_plataforma", float(bucket.get("gasto") or 0), tags=tags)
        return mom
    except Exception as exc:
        logger.warning("emitir_metricas_ciclo_meta: %s", exc)
        return {"ok": False, "erro": str(exc)}
