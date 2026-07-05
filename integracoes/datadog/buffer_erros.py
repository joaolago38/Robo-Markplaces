"""
integracoes/datadog/buffer_erros.py
Espelho local dos erros enviados ao Datadog — permite vigia sem DD_APPLICATION_KEY.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT

logger = logging.getLogger("buffer_erros_datadog")

BUFFER_PATH = ROOT / "logs" / "datadog_erros_recentes.json"
_MAX_ERROS = 150


def _fingerprint(*, nome_logger: str, mensagem: str, error_kind: str | None) -> str:
    base = f"{nome_logger}|{(error_kind or '')}|{mensagem[:200]}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:20]


def registrar_erro_local(
    *,
    nome_logger: str,
    mensagem: str,
    status: str = "error",
    error_kind: str | None = None,
    error_message: str | None = None,
) -> None:
    """Registra erro espelhado do Datadog. Nunca lança exceção."""
    try:
        agora = datetime.now(timezone.utc).isoformat()
        fp = _fingerprint(nome_logger=nome_logger, mensagem=mensagem, error_kind=error_kind)
        data = ler_json(BUFFER_PATH, default={"erros": []})
        erros: list[dict[str, Any]] = list(data.get("erros") or [])

        existente = next((e for e in erros if e.get("fingerprint") == fp), None)
        if existente:
            existente["ultima_vez"] = agora
            existente["ocorrencias"] = int(existente.get("ocorrencias") or 1) + 1
            existente["mensagem"] = mensagem[:500]
        else:
            erros.append(
                {
                    "fingerprint": fp,
                    "primeira_vez": agora,
                    "ultima_vez": agora,
                    "logger": nome_logger,
                    "mensagem": mensagem[:500],
                    "status": status,
                    "error_kind": error_kind,
                    "error_message": (error_message or "")[:300] or None,
                    "ocorrencias": 1,
                }
            )

        erros.sort(key=lambda x: str(x.get("ultima_vez") or ""), reverse=True)
        escrever_json_atomico(BUFFER_PATH, {"erros": erros[:_MAX_ERROS], "atualizado_em": agora})
    except Exception as exc:
        logger.debug("buffer_erros registrar falhou: %s", exc)


def listar_erros_recentes(*, limite: int = 100) -> list[dict[str, Any]]:
    data = ler_json(BUFFER_PATH, default={"erros": []})
    erros = list(data.get("erros") or [])
    return erros[: max(1, limite)]
