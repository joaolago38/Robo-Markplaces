"""
integracoes/bling/bling_client.py
Cliente da API Bling v3. Nunca lança exceção.
"""
import logging
from core.config import BLING_ACCESS_TOKEN
from core.http_client import request

logger = logging.getLogger("bling")
BASE = "https://www.bling.com.br/Api/v3"

def _h():
    return {"Authorization": f"Bearer {BLING_ACCESS_TOKEN}"}

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
    return {
        "sku": p.get("codigo"),
        "nome": p.get("nome"),
        "preco": _to_float(p.get("preco", 0)),
        "custo": custo,
        "ncm": p.get("ncm", ""),
        "estoque": _to_int(p.get("estoqueAtual", 0)),
        "descricao": p.get("descricaoCurta", ""),
    }

def buscar_produto(sku: str) -> dict | None:
    try:
        r = request("GET", f"{BASE}/produtos", headers=_h(), params={"codigo": sku}, timeout=15)
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
        r = request("GET", f"{BASE}/produtos", headers=_h(), params={"situacao": "A"}, timeout=15)
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
        r = request("POST", f"{BASE}/nfe", headers=_h(), json=payload_nfe, timeout=30)
        r.raise_for_status()
        body = r.json()
        data = body.get("data", body)
        return {"ok": True, "data": data}
    except Exception as exc:
        logger.error("Bling criar_nfe erro: %s", exc)
        return {"ok": False, "erro": str(exc)}
