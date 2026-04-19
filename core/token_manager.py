import hashlib
import hmac
import logging
import time
import urllib.parse

import core.config as cfg
from core.http_client import request

logger = logging.getLogger("token_manager")

_token_cache_ml = {"access_token": None, "expires_at": 0}

_token_cache_shopee = {"access_token": None, "expires_at": 0}
_shopee_refresh_efetivo = {"valor": None}

_token_cache_magalu = {"access_token": None, "expires_at": 0}
_magalu_refresh_efetivo = {"valor": None}


def _renovar_token_ml():
    url = "https://api.mercadolibre.com/oauth/token"

    data = {
        "grant_type": "refresh_token",
        "client_id": cfg.ML_CLIENT_ID,
        "client_secret": cfg.ML_CLIENT_SECRET,
        "refresh_token": cfg.ML_REFRESH_TOKEN,
    }

    if not all([cfg.ML_CLIENT_ID, cfg.ML_CLIENT_SECRET, cfg.ML_REFRESH_TOKEN]):
        logger.error("Credenciais ML ausentes para renovação de token.")
        return None

    try:
        r = request("POST", url, data=data, timeout=15)
        r.raise_for_status()

        tokens = r.json()

        access_token = tokens.get("access_token")
        expires_in = tokens.get("expires_in", 21600)

        _token_cache_ml["access_token"] = access_token
        _token_cache_ml["expires_at"] = time.time() + expires_in - 60

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

    if _token_cache_ml["access_token"] and now < _token_cache_ml["expires_at"]:
        return _token_cache_ml["access_token"]

    return _renovar_token_ml()


def _shopee_refresh_disponivel() -> str | None:
    if _shopee_refresh_efetivo["valor"] is None:
        _shopee_refresh_efetivo["valor"] = (cfg.SHOPEE_REFRESH_TOKEN or "").strip() or None
    return _shopee_refresh_efetivo["valor"]


def _assinar_shopee_auth_sem_acesso(path: str, timestamp: int) -> str:
    """Endpoints /api/v2/auth/* sem access_token no base string."""
    base = f"{cfg.SHOPEE_PARTNER_ID}{path}{timestamp}"
    return hmac.new(
        cfg.SHOPEE_PARTNER_KEY.encode("utf-8"),
        base.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _renovar_token_shopee():
    refresh = _shopee_refresh_disponivel()
    host = "https://partner.shopeemobile.com"
    path = "/api/v2/auth/access_token/get"

    if not all([cfg.SHOPEE_PARTNER_ID, cfg.SHOPEE_PARTNER_KEY, cfg.SHOPEE_SHOP_ID, refresh]):
        logger.error("Credenciais Shopee ausentes para renovação de token.")
        return None

    ts = int(time.time())
    sign = _assinar_shopee_auth_sem_acesso(path, ts)
    qs = urllib.parse.urlencode({"partner_id": int(cfg.SHOPEE_PARTNER_ID), "timestamp": ts, "sign": sign})

    body_json = {
        "refresh_token": refresh,
        "partner_id": int(cfg.SHOPEE_PARTNER_ID),
        "shop_id": int(cfg.SHOPEE_SHOP_ID),
    }

    try:
        r = request(
            "POST",
            f"{host}{path}?{qs}",
            json=body_json,
            headers={"Content-Type": "application/json"},
            timeout=25,
        )
        r.raise_for_status()
        body = r.json()

        err = body.get("error")
        if err not in (None, "", 0):
            logger.error("Shopee refresh falhou (error=%s message=%s)", err, body.get("message"))
            return None

        tok_payload = body.get("response") if isinstance(body.get("response"), dict) else body
        if not isinstance(tok_payload, dict):
            logger.error("Shopee refresh resposta inesperada.")
            return None

        access_token = tok_payload.get("access_token")
        expires_in = int(
            tok_payload.get("expire_in")
            or tok_payload.get("expires_in")
            or body.get("expire_in")
            or 14400
        )
        novo_refresh = tok_payload.get("refresh_token") or body.get("refresh_token")

        if not access_token:
            logger.error("Shopee refresh sem access_token na resposta.")
            return None

        _token_cache_shopee["access_token"] = access_token
        _token_cache_shopee["expires_at"] = time.time() + max(120, expires_in) - 120

        if novo_refresh:
            _shopee_refresh_efetivo["valor"] = novo_refresh

        cfg.SHOPEE_ACCESS_TOKEN = access_token
        if novo_refresh:
            cfg.SHOPEE_REFRESH_TOKEN = novo_refresh

        logger.info("Token Shopee renovado com sucesso")
        return access_token

    except Exception as e:
        logger.error("Erro ao renovar token Shopee: %s", e)
        return None


def get_token_shopee():
    if not _shopee_refresh_disponivel():
        return cfg.SHOPEE_ACCESS_TOKEN or None

    now = time.time()

    if _token_cache_shopee["access_token"] and now < _token_cache_shopee["expires_at"]:
        return _token_cache_shopee["access_token"]

    novo = _renovar_token_shopee()
    return novo or cfg.SHOPEE_ACCESS_TOKEN or None


def _magalu_refresh_disponivel() -> str | None:
    if _magalu_refresh_efetivo["valor"] is None:
        _magalu_refresh_efetivo["valor"] = (cfg.MAGALU_REFRESH_TOKEN or "").strip() or None
    return _magalu_refresh_efetivo["valor"]


def _renovar_token_magalu():
    rt = _magalu_refresh_disponivel()
    if not all([cfg.MAGALU_CLIENT_ID, cfg.MAGALU_CLIENT_SECRET, rt]):
        logger.error("Credenciais Magalu ausentes para renovação (client_id/secret ou refresh_token).")
        return None

    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": cfg.MAGALU_CLIENT_ID,
            "client_secret": cfg.MAGALU_CLIENT_SECRET,
            "refresh_token": rt,
        }
    )

    try:
        r = request(
            "POST",
            "https://id.magalu.com/oauth/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=25,
        )
        r.raise_for_status()
        tokens = r.json()

        access_token = tokens.get("access_token")
        expires_in = int(tokens.get("expires_in") or 3600)
        novo_refresh = tokens.get("refresh_token")

        if not access_token:
            logger.error("Magalu refresh sem access_token na resposta.")
            return None

        _token_cache_magalu["access_token"] = access_token
        _token_cache_magalu["expires_at"] = time.time() + max(60, expires_in) - 45

        if novo_refresh:
            _magalu_refresh_efetivo["valor"] = novo_refresh

        cfg.MAGALU_ACCESS_TOKEN = access_token
        if novo_refresh:
            cfg.MAGALU_REFRESH_TOKEN = novo_refresh

        logger.info("Token Magazine Luiza renovado com sucesso")
        return access_token

    except Exception as e:
        logger.error("Erro ao renovar token Magazine Luiza: %s", e)
        return None


def get_token_magalu():
    if not _magalu_refresh_disponivel():
        return cfg.MAGALU_ACCESS_TOKEN or None

    now = time.time()

    if _token_cache_magalu["access_token"] and now < _token_cache_magalu["expires_at"]:
        return _token_cache_magalu["access_token"]

    novo = _renovar_token_magalu()
    return novo or cfg.MAGALU_ACCESS_TOKEN or None


def garantir_tokens_marketplaces() -> dict[str, bool]:
    """
    Renova caches em sequência (útil na entrada de agentes longos).
    Retorna mapa marketplace -> conseguiu token válido ou renovou.
    """
    out: dict[str, bool] = {}

    ml = get_token_ml()
    out["mercadolivre"] = bool(ml)

    sp = get_token_shopee()
    out["shopee"] = bool(sp)

    mg = get_token_magalu()
    out["magalu"] = bool(mg)

    return out


def renovar_todos_tokens() -> dict[str, dict]:
    """
    Força uma tentativa de renovação para cada marketplace suportado.
    Usado pelo script CLI / Actions para validar credenciais.
    """
    ml = _renovar_token_ml()
    sp = _renovar_token_shopee()
    mg = _renovar_token_magalu()

    return {
        "mercadolivre": {"ok": bool(ml)},
        "shopee": {"ok": bool(sp)},
        "magalu": {"ok": bool(mg)},
    }
