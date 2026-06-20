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
    Faz a chamada autenticada e, em caso de 401/403 (token expirado ou
    inválido), força a renovação via refresh_token e tenta UMA vez mais.
    """
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.update(_h())
    r = request(method, url, headers=headers, **kwargs)

    status = getattr(r, "status_code", None)
    if status in (401, 403):
        logger.warning(
            "Bling retornou %s — renovando token e tentando novamente.", status
        )
        novo = token_manager.get_token_bling(forcar=True)
        if novo:
            headers.update(_h(novo))
            r = request(method, url, headers=headers, **kwargs)
    return r


def probe_produtos() -> dict:
    """
    Verifica GET /produtos sem mascarar erros HTTP como lista vazia.
    Retorna ok, status HTTP e mensagem curta para scripts de diagnóstico.
    """
    try:
        r = _request_bling(
            "GET",
            f"{BASE}/produtos",
            params={"situacao": "A", "limite": 1},
            timeout=15,
        )
        status = getattr(r, "status_code", 0)
        if status == 200:
            qtd = len(r.json().get("data", []))
            return {"ok": True, "status": 200, "msg": "autenticado", "amostra": qtd}
        if status == 401:
            return {
                "ok": False,
                "status": 401,
                "msg": "token expirado ou invalido — rode pegar_token_bling.py",
            }
        if status == 403:
            return {
                "ok": False,
                "status": 403,
                "msg": (
                    "sem permissao — no App Bling marque escopo Produtos e "
                    "reautorize com pegar_token_bling.py"
                ),
            }
        try:
            corpo = r.json()
            detalhe = corpo.get("error", corpo) if isinstance(corpo, dict) else corpo
        except ValueError:
            detalhe = (getattr(r, "text", "") or "")[:200]
        return {"ok": False, "status": status, "msg": str(detalhe)[:200]}
    except Exception as exc:
        logger.error("Bling probe_produtos erro: %s", exc)
        return {"ok": False, "status": 0, "msg": str(exc)}

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
        status = getattr(r, "status_code", 0)
        if status != 200:
            logger.error(
                "Bling listar_produtos HTTP %s: %s",
                status,
                (getattr(r, "text", "") or "")[:300],
            )
            return []
        return [_normalizar_produto(p) for p in r.json().get("data", [])]
    except ValueError as e:
        logger.error("Bling listar_produtos JSON inválido: %s", e)
        return []
    except Exception as e:
        logger.error("Bling listar_produtos erro: %s", e)
        return []

def estoques_criticos(limite: int = 20) -> list[dict]:
    return [p for p in listar_produtos() if p["estoque"] <= limite]


def _buscar_produto_raw(sku: str) -> dict | None:
    """Retorna o objeto BRUTO do produto (com o id do Bling), ou None."""
    r = _request_bling("GET", f"{BASE}/produtos", params={"codigo": sku}, timeout=15)
    r.raise_for_status()
    itens = r.json().get("data", [])
    return itens[0] if itens else None


def obter_produto_completo(produto_id: str | int) -> dict:
    """GET de um produto específico (objeto completo, necessário para o PUT)."""
    r = _request_bling("GET", f"{BASE}/produtos/{produto_id}", timeout=15)
    r.raise_for_status()
    return r.json().get("data") or {}


def atualizar_ncm_produto(produto_id: str | int, ncm: str) -> dict:
    """
    Define o NCM de um produto no Bling com segurança: lê o produto COMPLETO,
    altera apenas o campo ncm e grava de volta (PUT é substituição no Bling v3,
    então read-modify-write evita apagar outros campos). Nunca lança exceção.
    """
    ncm_limpo = "".join(ch for ch in str(ncm) if ch.isdigit())
    if len(ncm_limpo) != 8:
        return {"ok": False, "erro": f"NCM inválido (esperado 8 dígitos): {ncm!r}", "produto_id": produto_id}
    try:
        produto = obter_produto_completo(produto_id)
        if not produto:
            return {"ok": False, "erro": f"produto {produto_id} não encontrado", "produto_id": produto_id}
        produto["ncm"] = ncm_limpo
        r = _request_bling("PUT", f"{BASE}/produtos/{produto_id}", json=produto, timeout=30)
        r.raise_for_status()
        return {"ok": True, "produto_id": produto_id, "ncm": ncm_limpo}
    except Exception as e:
        logger.error("Bling atualizar_ncm_produto erro id=%s: %s", produto_id, e)
        return {"ok": False, "erro": str(e), "produto_id": produto_id}


def definir_ncm_por_sku(sku: str, ncm: str) -> dict:
    """Resolve o id do produto pelo SKU e define o NCM. Nunca lança exceção."""
    try:
        raw = _buscar_produto_raw(sku)
    except Exception as e:
        logger.error("Bling definir_ncm_por_sku busca erro sku=%s: %s", sku, e)
        return {"ok": False, "erro": str(e), "sku": sku}
    if not raw:
        return {"ok": False, "erro": f"SKU {sku} não encontrado no Bling", "sku": sku}
    resultado = atualizar_ncm_produto(raw.get("id"), ncm)
    resultado["sku"] = sku
    return resultado


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
