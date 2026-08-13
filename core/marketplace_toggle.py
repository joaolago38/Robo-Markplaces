"""
core/marketplace_toggle.py
Liga/desliga operação por canal sem editar spec.yaml.

Prioridade (primeiro que decide vence):
  1. spec.yaml ativo: true → operando
  2. Env MARKETPLACE_<CANAL>_OPERANDO=1|0
  3. logs/marketplaces_operacao.json

ML já nasce no spec. Shopee/Magalu/Amazon ficam off até o toggle
(quando a conta estiver homologada e o CNPJ puder ser identificado).

Uso:
  python scripts/toggle_marketplaces.py status
  python scripts/toggle_marketplaces.py shopee on
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT, marketplace_spec_ativo

logger = logging.getLogger("marketplace_toggle")

TOGGLE_PATH = ROOT / "logs" / "marketplaces_operacao.json"
CANAIS = ("mercadolivre", "shopee", "magalu", "amazon")

_ENV_KEY = {
    "mercadolivre": "MARKETPLACE_MERCADOLIVRE_OPERANDO",
    "shopee": "MARKETPLACE_SHOPEE_OPERANDO",
    "magalu": "MARKETPLACE_MAGALU_OPERANDO",
    "amazon": "MARKETPLACE_AMAZON_OPERANDO",
}


def _norm(canal: str) -> str:
    n = (canal or "").strip().lower()
    if n in ("ml", "mlb"):
        return "mercadolivre"
    return n


def _env_operando(canal: str) -> bool | None:
    key = _ENV_KEY.get(canal, "")
    if not key:
        return None
    raw = os.getenv(key, "").strip().lower()
    if raw in ("1", "true", "on", "yes"):
        return True
    if raw in ("0", "false", "off", "no"):
        return False
    return None


def _arquivo() -> dict[str, Any]:
    data = ler_json(TOGGLE_PATH, default={})
    return data if isinstance(data, dict) else {}


def canal_em_operacao(canal: str) -> bool:
    """True se o canal deve rodar algoritmo/chat/identidade de CNPJ."""
    nome = _norm(canal)
    if nome not in CANAIS:
        return False
    if marketplace_spec_ativo(nome):
        return True
    env = _env_operando(nome)
    if env is not None:
        return env
    data = _arquivo()
    canais = data.get("canais") if isinstance(data.get("canais"), dict) else {}
    item = canais.get(nome) if isinstance(canais.get(nome), dict) else {}
    return bool(item.get("operando"))


def estado_canais() -> dict[str, Any]:
    data = _arquivo()
    canais_arq = data.get("canais") if isinstance(data.get("canais"), dict) else {}
    out: dict[str, Any] = {}
    for nome in CANAIS:
        env = _env_operando(nome)
        spec = marketplace_spec_ativo(nome)
        arq = canais_arq.get(nome) if isinstance(canais_arq.get(nome), dict) else {}
        operando = canal_em_operacao(nome)
        fonte = "spec" if spec else ("env" if env is not None else ("arquivo" if arq else "off"))
        out[nome] = {
            "operando": operando,
            "fonte": fonte if operando else "off",
            "spec_ativo": spec,
            "env": env,
            "arquivo_operando": bool(arq.get("operando")) if arq else None,
            "motivo": arq.get("motivo") or "",
        }
    return {
        "canais": out,
        "atualizado_em": data.get("atualizado_em"),
        "atualizado_por": data.get("atualizado_por") or "",
        "path": str(TOGGLE_PATH),
    }


def definir_canal(
    canal: str,
    operando: bool,
    *,
    motivo: str = "",
    atualizado_por: str = "manual",
) -> dict[str, Any]:
    nome = _norm(canal)
    if nome not in CANAIS:
        raise ValueError(f"canal inválido: {canal!r} (use {', '.join(CANAIS)})")
    data = _arquivo()
    canais = dict(data.get("canais") or {}) if isinstance(data.get("canais"), dict) else {}
    canais[nome] = {
        "operando": bool(operando),
        "motivo": (motivo or ("operacao" if operando else "pausa_manual")).strip()[:200],
    }
    payload = {
        "canais": canais,
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
        "atualizado_por": (atualizado_por or "manual").strip()[:80],
    }
    escrever_json_atomico(TOGGLE_PATH, payload)
    logger.info("Marketplace toggle %s → operando=%s", nome, operando)
    return estado_canais()
