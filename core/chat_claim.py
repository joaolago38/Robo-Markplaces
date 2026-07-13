"""
core/chat_claim.py
Exclusão mútua de perguntas entre chat_ml / conversão / auto_respostas.
Evita duas respostas Claude na mesma pergunta.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from core.atomic_io import ler_e_atualizar_json
from core.config import ROOT

logger = logging.getLogger("chat_claim")

CLAIM_PATH = ROOT / "logs" / "chat_perguntas_claimed.json"
TTL_PADRAO_SEG = 7200  # 2h


def tentar_claim(
    canal: str,
    pergunta_id: str,
    *,
    agente: str,
    ttl_seg: int = TTL_PADRAO_SEG,
) -> bool:
    """
    True se este agente ficou com a pergunta (pode responder).
    False se outro agente já reservou e o claim ainda é válido.
    """
    pid = str(pergunta_id or "").strip()
    if not pid:
        return False
    chave = f"{(canal or '').strip().lower()}:{pid}"
    agora = time.time()
    resultado = {"ok": False}

    def _upd(estado: Any) -> dict:
        if not isinstance(estado, dict):
            estado = {"claims": {}}
        claims = estado.get("claims")
        if not isinstance(claims, dict):
            claims = {}
        # limpa expirados
        vivos = {
            k: v
            for k, v in claims.items()
            if isinstance(v, dict) and float(v.get("until") or 0) > agora
        }
        atual = vivos.get(chave)
        if atual and str(atual.get("agente") or "") != agente:
            resultado["ok"] = False
            estado["claims"] = vivos
            return estado
        vivos[chave] = {"agente": agente, "until": agora + max(60, int(ttl_seg))}
        resultado["ok"] = True
        estado["claims"] = vivos
        return estado

    try:
        ler_e_atualizar_json(CLAIM_PATH, _upd, default={"claims": {}})
    except Exception as exc:
        logger.warning("chat_claim falhou (%s) — permite resposta (fail-open leitura)", exc)
        return True
    return bool(resultado["ok"])
