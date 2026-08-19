"""
integracoes/ml/alerta_pendencias_loja.py
P0 da loja no Telegram: envio, pergunta que o chat não fechou, cor ruim.
Cooldown 30 min no mesmo estado; estado novo fura na hora.
"""
from __future__ import annotations

import logging
from typing import Any

from core.config import ML_LOJA_P0_ALERTA, ML_LOJA_P0_COOLDOWN_SEG
from core.datadog_metrics import incrementar
from core.notificador import alertar_gestor

logger = logging.getLogger("alerta_pendencias_loja")

_CORES_RUINS = frozenset({"laranja", "vermelho", "2_orange", "1_red", "orange", "red"})


def _i(val: Any) -> int:
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


def _cor_ruim(valor: Any) -> str:
    txt = str(valor or "").strip().lower()
    if not txt:
        return ""
    if any(tok in txt for tok in _CORES_RUINS) or txt in _CORES_RUINS:
        return str(valor).strip()
    return ""


def classificar_pendencias_p0(
    *,
    perguntas_pendentes: int = 0,
    chat_falhas: int = 0,
    envios_pendentes: int = 0,
    claims_abertos: int = 0,
    cor: str = "",
    level_id: str = "",
    atraso_rate: float = 0.0,
    cancelamentos_rate: float = 0.0,
    claims_rate: float = 0.0,
) -> dict[str, Any]:
    """Itens que o gestor tem de atuar no ciclo — vazio se a loja está limpa."""
    itens: list[str] = []
    if _i(envios_pendentes) > 0:
        itens.append(f"Envio pendente: *{_i(envios_pendentes)}* — despachar agora (não esperar o resumo das 09:00).")
    if _i(perguntas_pendentes) > 0:
        itens.append(f"Pergunta em aberto: *{_i(perguntas_pendentes)}* — teto 24 h no ML.")
    if _i(chat_falhas) > 0:
        itens.append(f"Chat ML falhou em *{_i(chat_falhas)}* resposta(s) — responder no painel.")
    if _i(claims_abertos) > 0:
        itens.append(f"Claim aberto: *{_i(claims_abertos)}* — tratar no painel agora.")
    cor_hit = _cor_ruim(cor) or _cor_ruim(level_id)
    if cor_hit:
        itens.append(f"Reputação *{cor_hit}* — congelar Anita/ads/SKU novo.")
    if float(atraso_rate or 0) >= 0.05:
        itens.append(f"Atraso {float(atraso_rate):.0%} ≥ 5% — congela a fila.")
    if float(cancelamentos_rate or 0) >= 0.05:
        itens.append(f"Cancelamento {float(cancelamentos_rate):.0%} ≥ 5% — congela a fila.")
    if float(claims_rate or 0) >= 0.05:
        itens.append(f"Claims {float(claims_rate):.0%} ≥ 5% — congela a fila.")
    assinatura = (
        f"e{_i(envios_pendentes)}:q{_i(perguntas_pendentes)}:f{_i(chat_falhas)}"
        f":c{_i(claims_abertos)}:cor{cor_hit or 'ok'}"
    )
    return {
        "tem_p0": bool(itens),
        "itens": itens,
        "assinatura": assinatura,
        "envios_pendentes": _i(envios_pendentes),
        "perguntas_pendentes": _i(perguntas_pendentes),
        "chat_falhas": _i(chat_falhas),
    }


def montar_mensagem_p0(pendencias: dict[str, Any]) -> str:
    linhas = [
        "🚨 *Loja ML — atuar agora*",
        "_P0: não espera o briefing da manhã._",
        "",
    ]
    for item in pendencias.get("itens") or []:
        linhas.append(f"• {item}")
    return "\n".join(linhas)


def emitir_alerta_p0(pendencias: dict[str, Any], *, enviar: bool = True) -> bool:
    """Envia se tem P0. Mesmo estado: 30 min. Estado novo: na hora."""
    if not enviar or not ML_LOJA_P0_ALERTA:
        return False
    if not pendencias.get("tem_p0"):
        return False
    msg = montar_mensagem_p0(pendencias)
    chave = f"ml:loja:p0:{pendencias.get('assinatura') or 'x'}"
    ok = bool(
        alertar_gestor(
            msg,
            chave=chave,
            cooldown_segundos=ML_LOJA_P0_COOLDOWN_SEG,
            agente_id="alerta_pendencias_loja",
        )
    )
    incrementar("ml.loja.p0.telegram_ok" if ok else "ml.loja.p0.telegram_skip")
    return ok


def emitir_alerta_p0_do_ciclo(
    *,
    chat_falhas: int = 0,
    perguntas_pendentes: int | None = None,
    reputacao: dict[str, Any] | None = None,
    enviar: bool = True,
) -> dict[str, Any]:
    """Varredura leve no ciclo 30 min (chat_ml): envios + perguntas + cor."""
    from integracoes.ml import ml_client

    envios_n = 0
    perg_n = int(perguntas_pendentes) if perguntas_pendentes is not None else 0
    claims_n = 0
    try:
        envios = ml_client.contar_envios_pendentes() or {}
        if envios.get("ok"):
            envios_n = _i(envios.get("total"))
    except Exception as exc:
        logger.warning("P0 envios: %s", exc)
    if perguntas_pendentes is None:
        try:
            perg_n = len(ml_client.listar_perguntas_nao_respondidas() or [])
        except Exception as exc:
            logger.warning("P0 perguntas: %s", exc)
            perg_n = 0
    try:
        claims = ml_client.contar_claims_abertos() or {}
        if claims.get("ok"):
            claims_n = _i(claims.get("total"))
    except Exception as exc:
        logger.info("P0 claims: %s", exc)

    rep = reputacao if isinstance(reputacao, dict) else {}
    metrics = rep.get("metrics") if isinstance(rep.get("metrics"), dict) else {}
    delayed = metrics.get("delayed_handling_time") if isinstance(metrics.get("delayed_handling_time"), dict) else {}
    cancel = metrics.get("cancellations") if isinstance(metrics.get("cancellations"), dict) else {}
    claims_m = metrics.get("claims") if isinstance(metrics.get("claims"), dict) else {}
    pend = classificar_pendencias_p0(
        perguntas_pendentes=perg_n,
        chat_falhas=chat_falhas,
        envios_pendentes=envios_n,
        claims_abertos=claims_n,
        cor=str(rep.get("cor") or ""),
        level_id=str(rep.get("level_id") or ""),
        atraso_rate=float(delayed.get("rate") or rep.get("atraso_rate") or 0),
        cancelamentos_rate=float(cancel.get("rate") or rep.get("cancelamentos_rate") or 0),
        claims_rate=float(claims_m.get("rate") or rep.get("claims_rate") or 0),
    )
    enviado = emitir_alerta_p0(pend, enviar=enviar)
    return {**pend, "enviado": enviado}


def emitir_alerta_p0_do_resumo(resumo: dict[str, Any], *, enviar: bool = True) -> bool:
    """Usa o snapshot do resumo da conta (09:00 ou forçar)."""
    if not resumo.get("ok"):
        return False
    rep = resumo.get("reputacao") if isinstance(resumo.get("reputacao"), dict) else {}
    pend = classificar_pendencias_p0(
        perguntas_pendentes=_i(resumo.get("perguntas_pendentes")),
        envios_pendentes=_i(resumo.get("envios_pendentes")),
        claims_abertos=_i(resumo.get("pos_venda_claims")) if resumo.get("pos_venda_ok") else 0,
        cor=str(rep.get("cor") or ""),
        level_id=str(rep.get("level_id") or ""),
        atraso_rate=float(rep.get("atraso_rate") or 0),
        cancelamentos_rate=float(rep.get("cancelamentos_rate") or 0),
        claims_rate=float(rep.get("claims_rate") or 0),
    )
    return emitir_alerta_p0(pend, enviar=enviar)
