"""
integracoes/bling/bling_client.py
Cliente da API Bling v3. Nunca lança exceção.
"""
import logging
from core.config import BLING_ACCESS_TOKEN
from core.http_client import request
from core import token_manager

logger = logging.getLogger("bling")
BASE = "https://www.bling.com.br/Api/v3"

def _h(token: str | None = None):
    tok = token or token_manager.get_token_bling()
    return {"Authorization": f"Bearer {tok}"}

def _request_bling(method: str, url: str, **kwargs):
    """
    Faz a chamada autenticada e, em caso de 401 (token expirado), força a
    renovação via refresh_token e tenta UMA vez mais.
    """
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.update(_h())
    r = request(method, url, headers=headers, **kwargs)

    if getattr(r, "status_code", None) == 401:
        logger.warning("Bling retornou 401 — renovando token e tentando novamente.")
        novo = token_manager.get_token_bling(forcar=True)
        if novo:
            headers.update(_h(novo))
            r = request(method, url, headers=headers, **kwargs)
    return r

def _to_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)

def _to_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)

def _normalizar_produto(p: dict) -> dict:
    custo = _to_float(
        p.get("precoCusto", p.get("precoCompra", p.get("custo", 0)))
    )
    imagens = p.get("imagens", p.get("imagemURL", []))
    if isinstance(imagens, str):
        imagens = [imagens]
    elif not isinstance(imagens, list):
        imagens = []
    return {
        "sku": p.get("codigo"),
        "nome": p.get("nome"),
        "preco": _to_float(p.get("preco", 0)),
        "custo": custo,
        "ncm": p.get("ncm", ""),
        "estoque": _to_int(p.get("estoqueAtual", 0)),
        "descricao": p.get("descricaoCurta", ""),
        "imagens": imagens,
    }

def buscar_produto(sku: str) -> dict | None:
    try:
        r = _request_bling("GET", f"{BASE}/produtos", params={"codigo": sku}, timeout=15)
        r.raise_for_status()
        itens = r.json().get("data", [])
        if not itens:
            return None
        return _normalizar_produto(itens[0])
    except ValueError as e:
        logger.error("Bling buscar_produto JSON inválido sku=%s erro=%s", sku, e)
        return None
    except Exception as e:
        logger.error("Bling buscar_produto erro sku=%s: %s", sku, e)
        return None

def listar_produtos() -> list[dict]:
    try:
        r = _request_bling("GET", f"{BASE}/produtos", params={"situacao": "A"}, timeout=15)
        r.raise_for_status()
        return [_normalizar_produto(p) for p in r.json().get("data", [])]
    except ValueError as e:
        logger.error("Bling listar_produtos JSON inválido: %s", e)
        return []
    except Exception as e:
        logger.error("Bling listar_produtos erro: %s", e)
        return []

def estoques_criticos(limite: int = 20) -> list[dict]:
    return [p for p in listar_produtos() if p["estoque"] <= limite]


def criar_nfe(payload_nfe: dict) -> dict:
    """
    Cria NF-e no Bling. Retorna payload de resposta ou erro padronizado.
    """
    if not BLING_ACCESS_TOKEN:
        return {"ok": False, "erro": "BLING_ACCESS_TOKEN não configurado"}
    try:
        r = _request_bling("POST", f"{BASE}/nfe", json=payload_nfe, timeout=30)
        r.raise_for_status()
        body = r.json()
        data = body.get("data", body)
        return {"ok": True, "data": data}
    except Exception as exc:
        logger.error("Bling criar_nfe erro: %s", exc)
        return {"ok": False, "erro": str(exc)}
