"""
integracoes/masterprint/ramo.py
Identidade do ramo Masterprint (CNPJ / conta ML / Telegram) — separado dos esmaltes.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

from core.atomic_io import ler_json
from core.config import (
    MASTERPRINT_CNPJ,
    MASTERPRINT_ML_NICKNAME,
    MASTERPRINT_ML_SELLER_ID,
    MASTERPRINT_NOME_FANTASIA,
    MASTERPRINT_RAMO_CATALOGO,
    MASTERPRINT_RAZAO_SOCIAL,
    MASTERPRINT_TELEGRAM_GESTOR_CHAT_ID,
    ROOT,
    TELEGRAM_GESTOR_CHAT_ID,
)

logger = logging.getLogger("masterprint_ramo")

_RE_CNPJ = re.compile(r"\D+")


def _so_digitos(valor: str) -> str:
    return _RE_CNPJ.sub("", str(valor or ""))


def formatar_cnpj(cnpj: str) -> str:
    d = _so_digitos(cnpj)
    if len(d) != 14:
        return d or ""
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


@lru_cache(maxsize=1)
def carregar_ramo(caminho: str | None = None) -> dict[str, Any]:
    path = ROOT / (caminho or MASTERPRINT_RAMO_CATALOGO)
    data = ler_json(path, default={})
    if not isinstance(data, dict) or not data:
        try:
            import json

            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            logger.warning("Falha ao ler ramo Masterprint: %s", exc)
            data = {}
    if not isinstance(data, dict):
        data = {}

    cnpj = (MASTERPRINT_CNPJ or data.get("cnpj") or "").strip()
    seller = (MASTERPRINT_ML_SELLER_ID or data.get("ml_seller_id") or "").strip()
    nick = (MASTERPRINT_ML_NICKNAME or data.get("ml_nickname") or "").strip()
    razao = (MASTERPRINT_RAZAO_SOCIAL or data.get("razao_social") or "").strip()
    fantasia = (
        MASTERPRINT_NOME_FANTASIA
        or data.get("nome_fantasia")
        or "Masterprint"
    ).strip()
    chat = (
        MASTERPRINT_TELEGRAM_GESTOR_CHAT_ID
        or data.get("telegram_gestor_chat_id")
        or ""
    ).strip()
    chat_esmaltes = (TELEGRAM_GESTOR_CHAT_ID or "").strip()
    chat_efetivo = chat or chat_esmaltes
    conta_separada = bool(seller or cnpj or (chat and chat != chat_esmaltes))

    return {
        "ramo_id": str(data.get("ramo_id") or "masterprint"),
        "nome_fantasia": fantasia,
        "razao_social": razao,
        "cnpj": _so_digitos(cnpj),
        "cnpj_formatado": formatar_cnpj(cnpj),
        "ml_seller_id": seller,
        "ml_nickname": nick,
        "telegram_gestor_chat_id": chat_efetivo,
        "telegram_chat_proprio": bool(chat and chat != chat_esmaltes),
        "diferente_do_ramo_esmaltes": bool(
            data.get("diferente_do_ramo_esmaltes", True)
        )
        or conta_separada,
        "conta_separada": conta_separada,
        "notas": data.get("notas") or "",
        "fonte": str(path),
    }


def limpar_cache_ramo() -> None:
    carregar_ramo.cache_clear()


def linha_identidade_telegram(ramo: dict[str, Any] | None = None) -> str:
    """Linha curta para o cabeçalho Telegram diferenciando o ramo."""
    r = ramo or carregar_ramo()
    partes = [f"Ramo: *{r.get('nome_fantasia') or 'Masterprint'}*"]
    if r.get("cnpj_formatado"):
        partes.append(f"CNPJ `{r['cnpj_formatado']}`")
    elif r.get("cnpj"):
        partes.append(f"CNPJ `{r['cnpj']}`")
    if r.get("ml_nickname"):
        partes.append(f"ML @{r['ml_nickname']}")
    elif r.get("ml_seller_id"):
        partes.append(f"seller `{r['ml_seller_id']}`")
    if r.get("conta_separada"):
        partes.append("_conta/CNPJ ≠ esmaltes_")
    else:
        partes.append("_preencha CNPJ/seller para separar do ramo esmaltes_")
    return " · ".join(partes)


def chat_gestor_masterprint(ramo: dict[str, Any] | None = None) -> str | None:
    r = ramo or carregar_ramo()
    chat = str(r.get("telegram_gestor_chat_id") or "").strip()
    return chat or None
