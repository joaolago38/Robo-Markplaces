"""
integracoes/masterprint/ramo.py
Identidade do ramo Masterprint (CNPJ / conta ML / Telegram) — separado dos esmaltes.

Complementa (não substitui) catalogo/masterprint_ramo.json e env MASTERPRINT_*.
Quando vazios, tenta preencher via catalogo/empresas_cnae_cnpj.json (empresa masterprint).
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


def _empresa_masterprint() -> dict[str, Any]:
    try:
        from core.empresa_contexto import empresa_por_id, empresa_por_ramo

        return empresa_por_id("masterprint") or empresa_por_ramo("masterprint") or {}
    except Exception as exc:
        logger.debug("empresa_contexto indisponível para Masterprint: %s", exc)
        return {}


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

    emp = _empresa_masterprint()
    ml_emp = emp.get("ml") if isinstance(emp.get("ml"), dict) else {}

    # Prioridade: env MASTERPRINT_* → masterprint_ramo.json → empresas_cnae_cnpj.json
    cnpj = (MASTERPRINT_CNPJ or data.get("cnpj") or emp.get("cnpj") or "").strip()
    seller = (
        MASTERPRINT_ML_SELLER_ID or data.get("ml_seller_id") or ml_emp.get("seller_id") or ""
    ).strip()
    nick = (
        MASTERPRINT_ML_NICKNAME or data.get("ml_nickname") or ml_emp.get("nickname") or ""
    ).strip()
    razao = (
        MASTERPRINT_RAZAO_SOCIAL or data.get("razao_social") or emp.get("razao_social") or ""
    ).strip()
    fantasia = (
        MASTERPRINT_NOME_FANTASIA
        or data.get("nome_fantasia")
        or emp.get("nome_fantasia")
        or "Masterprint"
    ).strip()
    chat = (
        MASTERPRINT_TELEGRAM_GESTOR_CHAT_ID
        or data.get("telegram_gestor_chat_id")
        or emp.get("telegram_gestor_chat_id")
        or ""
    ).strip()
    chat_esmaltes = (TELEGRAM_GESTOR_CHAT_ID or "").strip()
    chat_efetivo = chat or chat_esmaltes
    conta_separada = bool(seller or cnpj or (chat and chat != chat_esmaltes))
    cnaes = list(emp.get("cnaes") or [])
    cnae_principal = emp.get("cnae_principal")
    foco_ml = bool(emp.get("prioriza_mercadolivre", True))

    return {
        "ramo_id": str(data.get("ramo_id") or emp.get("id") or "masterprint"),
        "empresa_id": emp.get("id") or "masterprint",
        "nome_fantasia": fantasia,
        "razao_social": razao,
        "cnpj": _so_digitos(cnpj),
        "cnpj_formatado": formatar_cnpj(cnpj),
        "cnaes": cnaes,
        "cnae_principal": cnae_principal,
        "ml_seller_id": seller,
        "ml_nickname": nick,
        "telegram_gestor_chat_id": chat_efetivo,
        "telegram_chat_proprio": bool(chat and chat != chat_esmaltes),
        "diferente_do_ramo_esmaltes": bool(
            data.get("diferente_do_ramo_esmaltes", True)
        )
        or conta_separada,
        "conta_separada": conta_separada,
        "foco_marketplace": "mercadolivre" if foco_ml else str(
            (emp.get("marketplaces") or {}).get("foco_principal") or "mercadolivre"
        ),
        "notas": data.get("notas") or emp.get("notas") or "",
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
    cnae = r.get("cnae_principal") or {}
    if cnae.get("codigo"):
        partes.append(f"CNAE `{cnae['codigo']}`")
    if r.get("ml_nickname"):
        partes.append(f"ML @{r['ml_nickname']}")
    elif r.get("ml_seller_id"):
        partes.append(f"seller `{r['ml_seller_id']}`")
    if r.get("foco_marketplace") == "mercadolivre":
        partes.append("foco *ML*")
    if r.get("conta_separada"):
        partes.append("_CNPJ demais produtos ≠ esmaltes_")
    else:
        partes.append("_preencha CNPJ/seller para separar do ramo esmaltes_")
    return " · ".join(partes)


def chat_gestor_masterprint(ramo: dict[str, Any] | None = None) -> str | None:
    r = ramo or carregar_ramo()
    chat = str(r.get("telegram_gestor_chat_id") or "").strip()
    return chat or None
