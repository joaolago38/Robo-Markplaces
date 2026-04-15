import time
import logging

from core.config import ML_CLIENT_ID, ML_CLIENT_SECRET, ML_REFRESH_TOKEN
from core.http_client import request

logger = logging.getLogger("token_manager")

_token_cache = {
    "access_token": None,
    "expires_at": 0
}


def _renovar_token():
    url = "https://api.mercadolibre.com/oauth/token"

    data = {
        "grant_type": "refresh_token",
        "client_id": ML_CLIENT_ID,
        "client_secret": ML_CLIENT_SECRET,
        "refresh_token": ML_REFRESH_TOKEN
    }

    if not all([ML_CLIENT_ID, ML_CLIENT_SECRET, ML_REFRESH_TOKEN]):
        logger.error("Credenciais ML ausentes para renovação de token.")
        return None

    try:
        r = request("POST", url, data=data, timeout=15)
        r.raise_for_status()

        tokens = r.json()

        access_token = tokens.get("access_token")
        expires_in = tokens.get("expires_in", 21600)

        _token_cache["access_token"] = access_token
        _token_cache["expires_at"] = time.time() + expires_in - 60

        logger.info("Token ML renovado com sucesso")

        return access_token

    except ValueError as e:
        logger.error("Erro de parse da resposta do token ML: %s", e)
        return None
    except Exception as e:
        logger.error("Erro ao renovar token ML: %s", e)
        return None


def get_token_ml():
    now = time.time()

    if _token_cache["access_token"] and now < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    return _renovar_token()