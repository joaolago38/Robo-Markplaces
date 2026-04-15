"""
integracoes/lojahub/lojahub_client.py
Cliente da API Lojahub. A preencher com endpoints reais.
"""
import logging
from core.config import LOJAHUB_TOKEN

logger = logging.getLogger("lojahub")
BASE = "https://api.lojahub.com.br/v1"

def _h():
    return {"Authorization": f"Bearer {LOJAHUB_TOKEN}"}

def listar_pedidos_pendentes() -> list[dict]:
    # TODO: implementar quando tiver acesso à API Lojahub
    return []
