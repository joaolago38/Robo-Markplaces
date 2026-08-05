"""
core/brave_search.py
Cliente único Brave Search API com controle de cota mensal.

- Conta consultas em logs/brave_uso_mensal.json (mês calendário UTC)
- Soft alert em BRAVE_QUOTA_ALERTA_PCT (padrão 80%)
- Hard-stop em BRAVE_QUOTA_MES (padrão 1800, margem sob o free ~2000)
- Emite métricas brave.* e alerta Telegram ao aproximar/esgotar

Docs: https://brave.com/search/api/
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT
from core.http_client import request

logger = logging.getLogger("brave_search")

_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_USO_PATH = ROOT / "logs" / "brave_uso_mensal.json"
_LOCK = threading.Lock()


def _cfg() -> tuple[str, int, float, bool]:
    from core.config import (
        BRAVE_QUOTA_ALERTA_PCT,
        BRAVE_QUOTA_HARD_STOP,
        BRAVE_QUOTA_MES,
        BRAVE_SEARCH_API_KEY,
    )

    key = (BRAVE_SEARCH_API_KEY or "").strip()
    quota = max(1, int(BRAVE_QUOTA_MES or 1800))
    alerta_pct = float(BRAVE_QUOTA_ALERTA_PCT or 80)
    alerta_pct = max(1.0, min(99.0, alerta_pct))
    return key, quota, alerta_pct, bool(BRAVE_QUOTA_HARD_STOP)

def _mes_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _carregar_uso() -> dict[str, Any]:
    data = ler_json(_USO_PATH, default={}) or {}
    if not isinstance(data, dict):
        data = {}
    mes = _mes_utc()
    if data.get("mes") != mes:
        return {"mes": mes, "consultas": 0, "alerta_enviado": False, "esgotado_enviado": False}
    return {
        "mes": mes,
        "consultas": int(data.get("consultas") or 0),
        "alerta_enviado": bool(data.get("alerta_enviado")),
        "esgotado_enviado": bool(data.get("esgotado_enviado")),
    }


def _salvar_uso(uso: dict[str, Any]) -> None:
    escrever_json_atomico(_USO_PATH, uso)


def status_cota() -> dict[str, Any]:
    """Resumo da cota atual (sem consumir)."""
    _key, quota, alerta_pct, hard = _cfg()
    with _LOCK:
        uso = _carregar_uso()
    usadas = int(uso.get("consultas") or 0)
    restante = max(0, quota - usadas)
    pct = round(100.0 * usadas / quota, 1) if quota else 100.0
    return {
        "mes": uso.get("mes"),
        "consultas": usadas,
        "quota": quota,
        "restante": restante,
        "pct_usado": pct,
        "hard_stop": hard,
        "esgotada": usadas >= quota,
        "alerta_pct": alerta_pct,
    }


def _metricas(status: str, *, tags: list[str] | None = None) -> None:
    try:
        from core.datadog_metrics import gauge, incrementar

        st = status_cota()
        t = list(tags or [])
        incrementar("brave.consulta", tags=[*t, f"status:{status}"])
        gauge("brave.quota_usada", float(st["consultas"]))
        gauge("brave.quota_restante", float(st["restante"]))
        gauge("brave.quota_pct", float(st["pct_usado"]))
        if status == "esgotada":
            incrementar("brave.quota_esgotada", tags=t)
        if status == "429":
            incrementar("brave.http_429", tags=t)
    except Exception:
        pass


def _alertar_cota(uso: dict[str, Any], *, esgotada: bool) -> None:
    try:
        from core.notificador import alertar_gestor

        st = status_cota()
        if esgotada:
            if uso.get("esgotado_enviado"):
                return
            alertar_gestor(
                "🛑 *Brave Search — cota esgotada*\n"
                f"Uso: {st['consultas']}/{st['quota']} ({st['pct_usado']}%) no mês {st['mes']}.\n"
                "Fallback Brave parado (hard-stop). DDG/APIs nativas seguem.\n"
                "Opções: subir plano Brave, aumentar `BRAVE_QUOTA_MES`, ou `BRAVE_QUOTA_HARD_STOP=0`.",
                chave="brave:quota_esgotada",
                cooldown_segundos=86400,
            )
            uso["esgotado_enviado"] = True
        else:
            if uso.get("alerta_enviado"):
                return
            alertar_gestor(
                "⚠️ *Brave Search — cota alta*\n"
                f"Uso: {st['consultas']}/{st['quota']} ({st['pct_usado']}%) no mês {st['mes']}.\n"
                f"Restam ~{st['restante']} consultas. Hard-stop ao atingir a cota.",
                chave="brave:quota_alerta",
                cooldown_segundos=86400,
            )
            uso["alerta_enviado"] = True
    except Exception as exc:
        logger.debug("Brave alerta cota: %s", exc)


def _reservar_consulta() -> tuple[bool, str]:
    """Reserva 1 consulta na cota. Retorna (ok, motivo)."""
    key, quota, alerta_pct, hard = _cfg()
    if not key:
        return False, "sem_chave"
    with _LOCK:
        uso = _carregar_uso()
        usadas = int(uso.get("consultas") or 0)
        if hard and usadas >= quota:
            _metricas("esgotada")
            _alertar_cota(uso, esgotada=True)
            _salvar_uso(uso)
            return False, "cota_esgotada"
        uso["consultas"] = usadas + 1
        novas = uso["consultas"]
        limiar = int(quota * (alerta_pct / 100.0))
        if novas >= quota:
            _alertar_cota(uso, esgotada=True)
        elif novas >= limiar:
            _alertar_cota(uso, esgotada=False)
        _salvar_uso(uso)
    return True, "ok"


def buscar_web(
    query: str,
    *,
    limite: int = 15,
    contexto: str = "geral",
) -> list[dict[str, str]]:
    """
    GET Brave web search. Conta 1 consulta na cota mensal.
    Retorna [{url, titulo, snippet}]. Nunca lança.
    """
    query = (query or "").strip()
    if not query:
        return []

    key, _quota, _alerta, _hard = _cfg()
    if not key:
        return []

    ok, motivo = _reservar_consulta()
    if not ok:
        if motivo == "cota_esgotada":
            logger.warning(
                "Brave cota esgotada — busca ignorada contexto=%s query=%r",
                contexto,
                query[:60],
            )
        return []

    tags = [f"contexto:{contexto}"]
    try:
        r = request(
            "GET",
            _BRAVE_URL,
            params={"q": query, "count": max(1, min(20, int(limite)))},
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": key,
            },
            timeout=20,
        )
        if r.status_code == 401:
            logger.warning("Brave Search API: chave inválida (401) contexto=%s", contexto)
            _metricas("401", tags=tags)
            return []
        if r.status_code == 429:
            logger.warning("Brave Search API: rate limit (429) contexto=%s", contexto)
            _metricas("429", tags=tags)
            try:
                from core.notificador import alertar_gestor

                alertar_gestor(
                    "⚠️ Brave Search HTTP 429 (rate limit/cota).\n"
                    "Verifique painel Brave e `BRAVE_QUOTA_MES`.",
                    chave="brave:http_429",
                    cooldown_segundos=3600,
                )
            except Exception:
                pass
            return []
        if r.status_code >= 400:
            logger.warning(
                "Brave Search HTTP %s contexto=%s query=%r",
                r.status_code,
                contexto,
                query[:60],
            )
            _metricas(f"http_{r.status_code}", tags=tags)
            return []

        body = r.json() or {}
        brutos = (body.get("web") or {}).get("results") or []
        out: list[dict[str, str]] = []
        for row in brutos:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            titulo = str(row.get("title") or "").strip()
            if not url:
                continue
            out.append(
                {
                    "url": url,
                    "titulo": titulo,
                    "snippet": str(row.get("description") or ""),
                }
            )
            if len(out) >= max(1, int(limite)):
                break
        _metricas("ok" if out else "vazio", tags=tags)
        if out:
            logger.info(
                "Brave OK contexto=%s resultados=%d query=%r",
                contexto,
                len(out),
                query[:60],
            )
        return out
    except Exception as exc:
        logger.warning("Brave erro contexto=%s query=%r: %s", contexto, query[:60], exc)
        _metricas("erro", tags=tags)
        return []
