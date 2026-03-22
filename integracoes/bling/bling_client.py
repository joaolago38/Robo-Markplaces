"""
integracoes/bling/bling_client.py
Cliente da API Bling v3. Nunca lança exceção.
"""
import logging
import requests
from core.config import BLING_ACCESS_TOKEN, BLING_REFRESH_TOKEN, BLING_CLIENT_ID, BLING_CLIENT_SECRET

logger = logging.getLogger("bling")
BASE = "https://www.bling.com.br/Api/v3"

def _h():
    return {"Authorization": f"Bearer {BLING_ACCESS_TOKEN}"}

def buscar_produto(sku: str) -> dict | None:
    try:
        r = requests.get(f"{BASE}/produtos", headers=_h(), params={"codigo": sku}, timeout=15)
        r.raise_for_status()
        itens = r.json().get("data", [])
        if not itens:
            return None
        p = itens[0]
        return {
            "sku":      p.get("codigo"),
            "nome":     p.get("nome"),
            "preco":    float(p.get("preco", 0)),
            "estoque":  int(p.get("estoqueAtual", 0)),
            "descricao": p.get("descricaoCurta", ""),
        }
    except Exception as e:
        logger.error(f"Bling buscar_produto erro: {e}")
        return None

def listar_produtos() -> list[dict]:
    try:
        r = requests.get(f"{BASE}/produtos", headers=_h(), params={"situacao": "A"}, timeout=15)
        r.raise_for_status()
        return [
            {"sku": p.get("codigo"), "nome": p.get("nome"),
             "preco": float(p.get("preco", 0)), "estoque": int(p.get("estoqueAtual", 0))}
            for p in r.json().get("data", [])
        ]
    except Exception as e:
        logger.error(f"Bling listar_produtos erro: {e}")
        return []

def estoques_criticos(limite: int = 20) -> list[dict]:
    return [p for p in listar_produtos() if p["estoque"] <= limite]
