"""
integracoes/lojahub/lojahub_client.py
Cliente da API Lojahub. A preencher com endpoints reais.
"""
import logging
from core.config import LOJAHUB_TOKEN
from core.http_client import request

logger = logging.getLogger("lojahub")
BASE = "https://api.lojahub.com.br/v1"

def _h():
    return {"Authorization": f"Bearer {LOJAHUB_TOKEN}"}

def _enabled() -> bool:
    return bool(LOJAHUB_TOKEN)

def listar_pedidos_pendentes() -> list[dict]:
    if not _enabled():
        logger.warning("Lojahub não configurado.")
        return []
    try:
        r = request("GET", f"{BASE}/pedidos", headers=_h(), params={"status": "pending", "limit": 50}, timeout=20)
        r.raise_for_status()
        body = r.json()
        return body.get("data", body.get("pedidos", []))
    except Exception as exc:
        logger.error("Lojahub listar_pedidos_pendentes erro: %s", exc)
        return []


def listar_pedidos_prontos_faturar(limit: int = 50) -> list[dict]:
    """
    Retorna pedidos pagos/aprovados aguardando emissão de NF.
    """
    if not _enabled():
        logger.warning("Lojahub não configurado para faturamento.")
        return []
    try:
        r = request(
            "GET",
            f"{BASE}/pedidos",
            headers=_h(),
            params={"status": "approved", "faturado": "false", "limit": limit},
            timeout=20,
        )
        r.raise_for_status()
        body = r.json()
        return body.get("data", body.get("pedidos", []))
    except Exception as exc:
        logger.error("Lojahub listar_pedidos_prontos_faturar erro: %s", exc)
        return []


def listar_resumo_vendas_24h() -> dict:
    """
    Tenta coletar resumo das últimas 24h.
    """
    if not _enabled():
        return {"ok": False, "erro": "LOJAHUB_TOKEN não configurado"}
    try:
        r = request("GET", f"{BASE}/analytics/vendas", headers=_h(), params={"periodo": "24h"}, timeout=20)
        r.raise_for_status()
        body = r.json()
        data = body.get("data", body)
        return {"ok": True, "data": data}
    except Exception as exc:
        logger.error("Lojahub listar_resumo_vendas_24h erro: %s", exc)
        return {"ok": False, "erro": str(exc)}
