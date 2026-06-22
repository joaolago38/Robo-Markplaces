import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
from pathlib import Path

import core.config as cfg
from core.github_secrets import sync_secrets_github
from core.http_client import request

logger = logging.getLogger("token_manager")

_token_cache_ml = {"access_token": None, "expires_at": 0}
_ml_refresh_efetivo = {"valor": None}

_token_cache_shopee = {"access_token": None, "expires_at": 0}
_shopee_refresh_efetivo = {"valor": None}

_token_cache_magalu = {"access_token": None, "expires_at": 0}
_magalu_refresh_efetivo = {"valor": None}

_token_cache_bling = {"access_token": None, "expires_at": 0}
_bling_refresh_efetivo = {"valor": None}

_token_cache_meta = {"access_token": None, "expires_at": 0}
_meta_token_efetivo = {"valor": None}


def _ml_refresh_disponivel() -> str | None:
    """Prioriza o refresh_token rotacionado (em memória) sobre o do .env/secret."""
    if _ml_refresh_efetivo["valor"] is None:
        _ml_refresh_efetivo["valor"] = (cfg.ML_REFRESH_TOKEN or "").strip() or None
    return _ml_refresh_efetivo["valor"]


def _renovar_token_ml():
    url = "https://api.mercadolibre.com/oauth/token"

    refresh = _ml_refresh_disponivel()

    if not all([cfg.ML_CLIENT_ID, cfg.ML_CLIENT_SECRET, refresh]):
        logger.error("Credenciais ML ausentes para renovação de token.")
        return None

    data = {
        "grant_type": "refresh_token",
        "client_id": cfg.ML_CLIENT_ID,
        "client_secret": cfg.ML_CLIENT_SECRET,
        "refresh_token": refresh,
    }

    try:
        r = request("POST", url, data=data, timeout=15)
        r.raise_for_status()

        tokens = r.json()

        access_token = tokens.get("access_token")
        expires_in = tokens.get("expires_in", 21600)
        novo_refresh = tokens.get("refresh_token")

        _token_cache_ml["access_token"] = access_token
        _token_cache_ml["expires_at"] = time.time() + expires_in - 60

        # ML rotaciona o refresh_token (uso único): guarda o novo, senão a
        # próxima renovação falha com 400 invalid_grant.
        if novo_refresh:
            _ml_refresh_efetivo["valor"] = novo_refresh
            cfg.ML_REFRESH_TOKEN = novo_refresh

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


def tokens_ml_atuais() -> dict:
    """
    Tokens ML mais recentes em memória (após a última renovação), para o
    write-back nos Secrets. NÃO dispara nova renovação (evita consumir o
    refresh_token rotacionado duas vezes).
    """
    return {
        "access_token": _token_cache_ml["access_token"] or cfg.ML_ACCESS_TOKEN,
        "refresh_token": _ml_refresh_efetivo["valor"] or cfg.ML_REFRESH_TOKEN,
    }


def tokens_shopee_atuais() -> dict:
    """Tokens Shopee mais recentes em memória — sem disparar nova renovação."""
    return {
        "access_token": _token_cache_shopee["access_token"] or cfg.SHOPEE_ACCESS_TOKEN,
        "refresh_token": _shopee_refresh_efetivo["valor"] or cfg.SHOPEE_REFRESH_TOKEN,
    }


def tokens_magalu_atuais() -> dict:
    """Tokens Magalu mais recentes em memória — sem disparar nova renovação."""
    return {
        "access_token": _token_cache_magalu["access_token"] or cfg.MAGALU_ACCESS_TOKEN,
        "refresh_token": _magalu_refresh_efetivo["valor"] or cfg.MAGALU_REFRESH_TOKEN,
    }


def _meta_store_path() -> Path | None:
    """
    Cofre do token longo do Meta em disco. Ativo só quando META_TOKEN_STORE
    está definido (assim Actions e testes mantêm o comportamento sem tocar disco).
        META_TOKEN_STORE=dados/meta_token.json
    """
    p = (os.getenv("META_TOKEN_STORE") or "").strip()
    return Path(p) if p else None


def _carregar_store_meta() -> dict:
    p = _meta_store_path()
    if not p or not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.error("Falha ao ler store Meta (%s): %s", p, e)
        return {}


def _salvar_store_meta(access_token: str, expires_at: float) -> None:
    p = _meta_store_path()
    if not p:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "access_token": access_token,
                    "expires_at": expires_at,
                    "atualizado_em": time.time(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        logger.info("Token Meta persistido em %s", p)
    except Exception as e:
        logger.error("Falha ao gravar store Meta (%s): %s", p, e)


def _meta_token_disponivel() -> str | None:
    """Prioridade: token rotacionado em memória > disco > .env/secret."""
    if _meta_token_efetivo["valor"] is None:
        store = _carregar_store_meta()
        _meta_token_efetivo["valor"] = (
            (store.get("access_token") or cfg.META_ACCESS_TOKEN or "").strip() or None
        )
    return _meta_token_efetivo["valor"]


def _renovar_token_meta():
    """
    Estende o token longo do Meta (fb_exchange_token). O token longo dura ~60 dias;
    reexchange antes do vencimento renova por mais ~60 dias. Requer META_APP_ID,
    META_APP_SECRET e um token longo atual válido.
    """
    token_atual = _meta_token_disponivel()

    if not all([cfg.META_APP_ID, cfg.META_APP_SECRET, token_atual]):
        logger.error("Credenciais Meta ausentes para renovação (app_id/secret/token).")
        return None

    version = getattr(cfg, "META_API_VERSION", "v19.0")
    url = f"https://graph.facebook.com/{version}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": cfg.META_APP_ID,
        "client_secret": cfg.META_APP_SECRET,
        "fb_exchange_token": token_atual,
    }

    try:
        r = request("GET", url, params=params, timeout=15)
        r.raise_for_status()
        tokens = r.json()

        access_token = tokens.get("access_token")
        if not access_token:
            logger.error("Meta refresh sem access_token na resposta.")
            return None

        expires_in = int(tokens.get("expires_in") or 5184000)  # ~60 dias
        _token_cache_meta["access_token"] = access_token
        _token_cache_meta["expires_at"] = time.time() + max(120, expires_in) - 300
        _meta_token_efetivo["valor"] = access_token
        cfg.META_ACCESS_TOKEN = access_token
        _salvar_store_meta(access_token, _token_cache_meta["expires_at"])

        logger.info("Token Meta renovado com sucesso")
        return access_token

    except ValueError as e:
        logger.error("Erro de parse da resposta do token Meta: %s", e)
        return None
    except Exception as e:
        logger.error("Erro ao renovar token Meta: %s", e)
        return None


def get_token_meta(forcar: bool = False):
    """Retorna um token Meta válido (renova via fb_exchange_token quando forçado/expirado)."""
    now = time.time()

    if _token_cache_meta["access_token"] is None:
        store = _carregar_store_meta()
        if store.get("access_token"):
            _token_cache_meta["access_token"] = store["access_token"]
            _token_cache_meta["expires_at"] = store.get("expires_at", 0)

    if not forcar:
        if _token_cache_meta["access_token"] and now < _token_cache_meta["expires_at"]:
            return _token_cache_meta["access_token"]
        if not _token_cache_meta["access_token"]:
            return cfg.META_ACCESS_TOKEN or None

    novo = _renovar_token_meta()
    return novo or cfg.META_ACCESS_TOKEN or None


def renovar_token_meta_detalhado() -> dict:
    """Força a renovação do token longo e devolve o novo valor (para write-back nos Secrets)."""
    if not all([cfg.META_APP_ID, cfg.META_APP_SECRET, _meta_token_disponivel()]):
        return {"ok": False, "motivo": "credenciais Meta ausentes"}

    access = _renovar_token_meta()
    if not access:
        return {"ok": False, "motivo": "falha ao renovar (token longo expirado/inválido?)"}

    return {"ok": True, "access_token": access}


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
        if r.status_code >= 400:
            logger.error(
                "Erro ao renovar token Magazine Luiza: HTTP %s — %s",
                r.status_code,
                (r.text or "")[:500],
            )
            return None
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
        logger.error("Erro ao renovar token Magazine Luiza (rede/parse): %s", e)
        return None


def get_token_magalu():
    if not _magalu_refresh_disponivel():
        return cfg.MAGALU_ACCESS_TOKEN or None

    now = time.time()

    if _token_cache_magalu["access_token"] and now < _token_cache_magalu["expires_at"]:
        return _token_cache_magalu["access_token"]

    novo = _renovar_token_magalu()
    return novo or cfg.MAGALU_ACCESS_TOKEN or None


def _bling_store_path() -> Path | None:
    """
    Caminho do cofre de tokens do Bling em disco. Só fica ATIVO quando a env
    BLING_TOKEN_STORE está definida — assim o GitHub Actions e os testes (que
    não a definem) mantêm exatamente o comportamento antigo, sem tocar em disco.
    Em máquina persistente (servidor/PC com tarefa agendada), defina:
        BLING_TOKEN_STORE=dados/bling_token.json
    """
    p = (os.getenv("BLING_TOKEN_STORE") or "").strip()
    return Path(p) if p else None


def _carregar_store_bling() -> dict:
    p = _bling_store_path()
    if not p or not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.error("Falha ao ler store Bling (%s): %s", p, e)
        return {}


def _salvar_store_bling(access_token: str, refresh_token: str | None, expires_at: float) -> None:
    p = _bling_store_path()
    if not p:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": expires_at,
                    "atualizado_em": time.time(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        try:
            os.chmod(p, 0o600)  # apenas dono lê/grava (best-effort; ignora no Windows)
        except OSError:
            pass
        logger.info("Tokens Bling persistidos em %s", p)
    except Exception as e:
        logger.error("Falha ao gravar store Bling (%s): %s", p, e)


def _hidratar_cache_bling_do_store() -> None:
    """Na partida de um processo novo, usa o token do disco em vez do .env estático."""
    if _token_cache_bling["access_token"] is None:
        store = _carregar_store_bling()
        if store.get("access_token"):
            _token_cache_bling["access_token"] = store["access_token"]
            _token_cache_bling["expires_at"] = store.get("expires_at", 0)


def _bling_refresh_disponivel() -> str | None:
    if _bling_refresh_efetivo["valor"] is None:
        # Prioridade: refresh_token do disco (mais recente) > .env/secret (bootstrap).
        store = _carregar_store_bling()
        _bling_refresh_efetivo["valor"] = (
            (store.get("refresh_token") or cfg.BLING_REFRESH_TOKEN or "").strip() or None
        )
    return _bling_refresh_efetivo["valor"]


def _dica_erro_refresh_bling(status: int, detalhe: str) -> None:
    d = (detalhe or "").lower()
    if "invalid_grant" in d or "expired" in d or "revoked" in d:
        logger.error("→ refresh_token invalido/expirado/ja usado. Re-bootstrap com pegar_token_bling.py e atualize BLING_ACCESS_TOKEN e BLING_REFRESH_TOKEN.")
    elif "invalid_client" in d or "client" in d or status in (401, 403):
        logger.error("→ client_id/client_secret incorretos. Confira BLING_CLIENT_ID e BLING_CLIENT_SECRET (sem ponto, sem aspas, sem espaco).")
    elif status == 400:
        logger.error("→ HTTP 400 no /oauth/token: quase sempre refresh_token consumido/expirado OU BLING_CLIENT_SECRET ausente/errado.")


def _renovar_token_bling():
    """
    Renova o access_token do Bling v3 via grant_type=refresh_token.

    IMPORTANTE: o Bling ROTACIONA o refresh_token a cada renovação — o token
    antigo é invalidado e a resposta traz um refresh_token novo. Ele é guardado
    em memória (cfg.BLING_REFRESH_TOKEN) e no cofre em disco (se ativo).
    """
    refresh = _bling_refresh_disponivel()

    if not all([cfg.BLING_CLIENT_ID, cfg.BLING_CLIENT_SECRET, refresh]):
        logger.error(
            "Credenciais Bling ausentes para renovação "
            "(client_id/secret ou refresh_token)."
        )
        return None

    credenciais = base64.b64encode(
        f"{cfg.BLING_CLIENT_ID}:{cfg.BLING_CLIENT_SECRET}".encode()
    ).decode()

    try:
        r = request(
            "POST",
            "https://www.bling.com.br/Api/v3/oauth/token",
            headers={
                "Authorization": f"Basic {credenciais}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
            timeout=25,
        )

        if r.status_code != 200:
            detalhe = ""
            try:
                corpo = r.json()
                detalhe = corpo.get("error_description") or corpo.get("error") or ""
                if isinstance(detalhe, dict):
                    detalhe = detalhe.get("description") or detalhe.get("message") or str(detalhe)
            except Exception:
                detalhe = (getattr(r, "text", "") or "")[:300]
            logger.error("Bling refresh falhou (HTTP %s): %s", r.status_code, detalhe)
            _dica_erro_refresh_bling(r.status_code, str(detalhe))
            return None

        tokens = r.json()

        access_token = tokens.get("access_token")
        expires_in = int(tokens.get("expires_in") or 21600)
        novo_refresh = tokens.get("refresh_token")

        if not access_token:
            logger.error("Bling refresh sem access_token na resposta.")
            return None

        _token_cache_bling["access_token"] = access_token
        # margem de 5 min antes do vencimento real
        _token_cache_bling["expires_at"] = time.time() + max(120, expires_in) - 300

        if novo_refresh:
            _bling_refresh_efetivo["valor"] = novo_refresh
            cfg.BLING_REFRESH_TOKEN = novo_refresh

        cfg.BLING_ACCESS_TOKEN = access_token

        # Persiste em disco (se o cofre estiver ativo) — resolve a rotação fora do Actions.
        _salvar_store_bling(
            access_token,
            novo_refresh or refresh,
            _token_cache_bling["expires_at"],
        )

        if os.getenv("GITHUB_ACTIONS") == "true":
            if sync_secrets_github(access_token, novo_refresh or refresh, prefix="BLING"):
                logger.info("Secrets BLING_* sincronizados no GitHub (rotação automática).")
            else:
                logger.warning(
                    "Falha ao sincronizar BLING_* no GitHub após rotação — "
                    "o próximo refresh pode falhar até o sync funcionar."
                )

        logger.info("Token Bling renovado com sucesso")
        return access_token

    except ValueError as e:
        logger.error("Erro de parse da resposta do token Bling: %s", e)
        return None
    except Exception as e:
        logger.error("Erro ao renovar token Bling: %s", e)
        return None


def get_token_bling(forcar: bool = False):
    """
    Retorna um access_token válido do Bling.

    - forcar=True   → tenta renovar imediatamente (usado após um 401).
    - cache válido  → devolve o token em cache.
    - sem cache     → devolve o BLING_ACCESS_TOKEN estático (sem chamada de rede).
    """
    now = time.time()

    _hidratar_cache_bling_do_store()

    if not forcar:
        if _token_cache_bling["access_token"] and now < _token_cache_bling["expires_at"]:
            return _token_cache_bling["access_token"]
        if not _token_cache_bling["access_token"]:
            return cfg.BLING_ACCESS_TOKEN or None

    novo = _renovar_token_bling()
    return novo or cfg.BLING_ACCESS_TOKEN or None


def renovar_token_bling_detalhado() -> dict:
    """
    Força a renovação e devolve os novos tokens (para o CLI/script local
    persistir o refresh_token rotacionado).
    """
    if not all([cfg.BLING_CLIENT_ID, cfg.BLING_CLIENT_SECRET, _bling_refresh_disponivel()]):
        return {"ok": False, "motivo": "credenciais Bling ausentes"}

    access = _renovar_token_bling()
    if not access:
        return {"ok": False, "motivo": "falha ao renovar (refresh expirado/inválido?)"}

    return {
        "ok": True,
        "access_token": access,
        "refresh_token": _bling_refresh_efetivo["valor"],
    }


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

    bl = get_token_bling()
    out["bling"] = bool(bl)

    return out


def renovar_todos_tokens() -> dict[str, dict]:
    """
    Força uma tentativa de renovação para cada marketplace suportado.
    Usado pelo script CLI / Actions para validar credenciais.
    """
    ml = _renovar_token_ml()
    sp = _renovar_token_shopee()
    mg = _renovar_token_magalu()
    # Bling NÃO entra aqui: é renovado separadamente (renovar_token_bling_detalhado),
    # pois o refresh_token rotaciona e seria consumido duas vezes.

    return {
        "mercadolivre": {"ok": bool(ml)},
        "shopee": {"ok": bool(sp)},
        "magalu": {"ok": bool(mg)},
    }
