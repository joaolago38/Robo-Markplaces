"""
integracoes/meta/meta_client.py
Cliente da Meta Graph API (Facebook + Instagram) para publicação.
"""
import logging

from core.config import (
    META_ACCESS_TOKEN,
    META_API_VERSION,
    META_INSTAGRAM_ID,
    META_PAGE_ID,
)
from core.http_client import request

logger = logging.getLogger("meta")
BASE = f"https://graph.facebook.com/{META_API_VERSION}"


def publicar_instagram(texto: str, imagem_url: str = "") -> bool:
    """
    Publica uma imagem com legenda no Instagram (fluxo de 2 passos da Graph API):
      1. cria um container de mídia (/{ig_id}/media)
      2. publica o container (/{ig_id}/media_publish)
    Requer META_INSTAGRAM_ID, META_ACCESS_TOKEN e uma imagem hospedada (imagem_url).
    """
    if not META_ACCESS_TOKEN or not META_INSTAGRAM_ID:
        logger.warning("Meta não configurado para Instagram (token/instagram_id).")
        return False
    if not imagem_url:
        logger.warning("Instagram exige uma imagem hospedada (imagem_url).")
        return False

    try:
        r1 = request(
            "POST",
            f"{BASE}/{META_INSTAGRAM_ID}/media",
            params={
                "access_token": META_ACCESS_TOKEN,
                "image_url": imagem_url,
                "caption": texto,
            },
            timeout=30,
        )
        r1.raise_for_status()
        creation_id = r1.json().get("id")
        if not creation_id:
            logger.error("Instagram: container sem id de criação.")
            return False

        r2 = request(
            "POST",
            f"{BASE}/{META_INSTAGRAM_ID}/media_publish",
            params={
                "access_token": META_ACCESS_TOKEN,
                "creation_id": creation_id,
            },
            timeout=30,
        )
        r2.raise_for_status()
        return True
    except Exception as e:
        logger.error("Meta publicar_instagram erro: %s", e)
        return False


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
