"""
integracoes/meta/meta_client.py
Cliente da Meta Graph API (Facebook + Instagram).
"""
import logging
from core.config import META_ACCESS_TOKEN, META_PAGE_ID, META_INSTAGRAM_ID
from core.http_client import request

logger = logging.getLogger("meta")
BASE = "https://graph.facebook.com/v19.0"

def publicar_instagram(texto: str, imagem_url: str = "") -> bool:
    # TODO: implementar upload de imagem e publicação
    logger.info(f"[META] Publicaria: {texto[:80]}...")
    return True

def publicar_facebook(texto: str) -> bool:
    if not META_ACCESS_TOKEN or not META_PAGE_ID:
        logger.warning("Meta não configurado para Facebook.")
        return False
    try:
        r = request(
            "POST",
            f"{BASE}/{META_PAGE_ID}/feed",
            params={"access_token": META_ACCESS_TOKEN},
            json={"message": texto},
            timeout=15,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error("Meta publicar_facebook erro: %s", e)
        return False
