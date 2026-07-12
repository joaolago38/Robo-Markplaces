"""
integracoes/cambio/cotacao_usd.py
Cotação USD/BRL em tempo real (AwesomeAPI) com histórico e fallback.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    CAMBIO_API_URL,
    CAMBIO_BLOQUEAR_FALLBACK_MARGEM,
    CAMBIO_FALLBACK_USD_BRL,
    CAMBIO_HISTORICO_MAX,
    CAMBIO_MAX_IDADE_SEG,
    ROOT,
)
from core.datadog_metrics import gauge
from core.http_client import request

logger = logging.getLogger("cotacao_usd")

HISTORY_PATH = ROOT / "logs" / "cambio_history.json"


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _idade_segundos(consultado_em: str | None) -> int | None:
    if not consultado_em:
        return None
    try:
        ts = datetime.fromisoformat(str(consultado_em).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - ts).total_seconds()))
    except (TypeError, ValueError):
        return None


def cotacao_confiavel_para_margem(cotacao: dict[str, Any] | None) -> bool:
    """True se a cotação pode alimentar cálculo/alerta de margem de importação."""
    if not cotacao or not cotacao.get("ok"):
        return False
    try:
        if float(cotacao.get("usd_brl") or 0) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    if cotacao.get("confiavel") is False:
        return False
    if CAMBIO_BLOQUEAR_FALLBACK_MARGEM and str(cotacao.get("fonte") or "") == "fallback":
        return False
    idade = cotacao.get("idade_seg")
    if idade is None:
        idade = _idade_segundos(cotacao.get("consultado_em"))
    if CAMBIO_MAX_IDADE_SEG > 0 and idade is not None and int(idade) > CAMBIO_MAX_IDADE_SEG:
        return False
    return True


def obter_cotacao_usd(*, usar_cache: bool = True) -> dict[str, Any]:
    """
    Retorna cotação USD/BRL. Nunca lança exceção.
    Campos: ok, usd_brl, fonte, variacao_pct, consultado_em, confiavel, idade_seg
    """
    historico = ler_json(HISTORY_PATH, default={"registros": []}) if usar_cache else {"registros": []}
    registros: list[dict[str, Any]] = list(historico.get("registros") or [])

    cotacao: dict[str, Any] | None = None
    try:
        r = request("GET", CAMBIO_API_URL, timeout=12)
        r.raise_for_status()
        body = r.json() or {}
        par = body.get("USDBRL") if isinstance(body, dict) else None
        if isinstance(par, dict):
            bid = float(par.get("bid") or par.get("ask") or 0)
            if bid > 0:
                variacao = None
                try:
                    variacao = float(par.get("pctChange") or 0)
                except (TypeError, ValueError):
                    variacao = None
                agora = _agora_iso()
                cotacao = {
                    "ok": True,
                    "usd_brl": round(bid, 4),
                    "fonte": "awesomeapi",
                    "variacao_pct": variacao,
                    "consultado_em": agora,
                    "idade_seg": 0,
                    "confiavel": True,
                    "alta": par.get("high"),
                    "baixa": par.get("low"),
                }
    except Exception as exc:
        logger.warning("Cotação USD indisponível via API: %s", exc)

    if not cotacao:
        ultimo = registros[-1] if registros else None
        if ultimo and ultimo.get("usd_brl"):
            fallback = float(ultimo["usd_brl"])
            consultado_em = str(ultimo.get("consultado_em") or _agora_iso())
        else:
            fallback = CAMBIO_FALLBACK_USD_BRL
            consultado_em = _agora_iso()
        idade = _idade_segundos(consultado_em) or 0
        cotacao = {
            "ok": True,
            "usd_brl": round(fallback, 4),
            "fonte": "fallback",
            "variacao_pct": None,
            "consultado_em": consultado_em,
            "idade_seg": idade,
            "confiavel": False,
            "aviso": "API de câmbio indisponível — usando último valor ou padrão",
        }

    if "confiavel" not in cotacao:
        cotacao["confiavel"] = cotacao_confiavel_para_margem(cotacao)
    if cotacao.get("idade_seg") is None:
        cotacao["idade_seg"] = _idade_segundos(cotacao.get("consultado_em"))

    if usar_cache:
        registros.append(
            {
                "usd_brl": cotacao["usd_brl"],
                "fonte": cotacao.get("fonte"),
                "consultado_em": cotacao.get("consultado_em") or _agora_iso(),
            }
        )
        historico["registros"] = registros[-CAMBIO_HISTORICO_MAX:]
        historico["ultima"] = cotacao
        escrever_json_atomico(HISTORY_PATH, historico)

    gauge("cambio.usd_brl", float(cotacao["usd_brl"]), tags=[f"fonte:{cotacao.get('fonte', '?')}"])
    return cotacao


def variacao_desde_ultima_rodada(*, limite_registros: int = 2) -> dict[str, Any]:
    """Compara última cotação com a anterior no histórico."""
    historico = ler_json(HISTORY_PATH, default={"registros": []})
    registros = list(historico.get("registros") or [])
    if len(registros) < 2:
        return {"ok": False, "motivo": "histórico insuficiente"}
    atual = float(registros[-1].get("usd_brl") or 0)
    anterior = float(registros[-2].get("usd_brl") or 0)
    if atual <= 0 or anterior <= 0:
        return {"ok": False, "motivo": "valores inválidos"}
    diff_pct = round((atual - anterior) / anterior * 100, 2)
    return {
        "ok": True,
        "usd_brl_atual": atual,
        "usd_brl_anterior": anterior,
        "variacao_pct": diff_pct,
        "subiu": diff_pct > 0,
    }
