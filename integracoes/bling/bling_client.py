"""
integracoes/bling/bling_client.py
Cliente da API Bling v3. Nunca lança exceção.

Erros de auth/API silenciados no Datadog por padrão (empresa inativa / token).
Religar: LOG_ERROS_BLING=1
"""
import logging
from core.config import BLING_ACCESS_TOKEN
from core.http_client import request
from core.log_opcional import erro_opcional, log_erros_bling_ativos
from core import token_manager

logger = logging.getLogger("bling")
BASE = "https://www.bling.com.br/Api/v3"


def _erro_bling(msg: str, *args) -> None:
    erro_opcional(logger, log_erros_bling_ativos(), msg, *args, flag_hint="LOG_ERROS_BLING")


class NfeVerificacaoIndisponivel(Exception):
    """Levantada quando não foi possível confirmar se já existe NF-e para o pedido."""


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


def _extrair_estoque(p: dict):
    """
    Lê o saldo de estoque conforme a API v3 do Bling.
    Na v3 o estoque NÃO vem como 'estoqueAtual'; quando presente, vem em
    'saldoVirtualTotal'/'saldoFisicoTotal' (ou num objeto aninhado 'estoque').
    Retorna None quando o saldo não está presente no payload — assim não
    classificamos como "crítico" um produto cujo estoque é apenas desconhecido.
    # TODO: a listagem GET /produtos normalmente NÃO traz saldo; para estoque
    # confiável, buscar via endpoint dedicado de estoques/saldos por id.
    """
    for chave in ("saldoVirtualTotal", "saldoFisicoTotal", "estoqueAtual"):
        if p.get(chave) is not None:
            return _to_int(p.get(chave))
    est = p.get("estoque")
    if isinstance(est, dict):
        for chave in ("saldoVirtualTotal", "saldoFisicoTotal"):
            if est.get(chave) is not None:
                return _to_int(est.get(chave))
    return None


def _normalizar_produto(p: dict) -> dict:
    custo = _to_float(
        p.get("precoCusto", p.get("precoCompra", p.get("custo", 0)))
    )
    imagens = p.get("imagens", p.get("imagemURL", []))
    if isinstance(imagens, str):
        imagens = [imagens]
    elif not isinstance(imagens, list):
        imagens = []
    sku = p.get("codigo") or p.get("sku") or (str(p.get("id")) if p.get("id") else None)
    return {
        "sku": sku,
        "codigo": sku,
        "nome": p.get("nome"),
        "preco": _to_float(p.get("preco", 0)),
        "custo": custo,
        "ncm": p.get("ncm", ""),
        "estoque": _extrair_estoque(p),
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
        _erro_bling("Bling buscar_produto JSON inválido sku=%s erro=%s", sku, e)
        return None
    except Exception as e:
        _erro_bling("Bling buscar_produto erro sku=%s: %s", sku, e)
        return None

def listar_produtos() -> list[dict]:
    try:
        r = _request_bling("GET", f"{BASE}/produtos", params={"situacao": "A"}, timeout=15)
        status = getattr(r, "status_code", 0)
        if status != 200:
            _erro_bling(
                "Bling listar_produtos HTTP %s: %s",
                status,
                (getattr(r, "text", "") or "")[:300],
            )
            return []
        return [_normalizar_produto(p) for p in r.json().get("data", [])]
    except ValueError as e:
        _erro_bling("Bling listar_produtos JSON inválido: %s", e)
        return []
    except Exception as e:
        _erro_bling("Bling listar_produtos erro: %s", e)
        return []

def listar_produtos_por_sku() -> dict[str, dict]:
    """
    Mesma chamada de listar_produtos() (1 request HTTP), mas indexada
    por código/SKU para lookup O(1) em loops que hoje fariam um
    buscar_produto(sku) por item.
    """
    return {p["codigo"]: p for p in listar_produtos() if p.get("codigo")}

def estoques_criticos(limite: int = 20) -> list[dict]:
    # Só considera crítico quando o estoque é conhecido E está abaixo do limite.
    # Estoque None (não retornado pela listagem) não é tratado como zero.
    return [
        p for p in listar_produtos()
        if p.get("estoque") is not None and p["estoque"] <= limite
    ]


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
        logger.info("Bling NCM atualizado com sucesso produto_id=%s ncm=%s", produto_id, ncm_limpo)
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
    from core.guardrails import bloqueio_escrita_global

    if bloqueio := bloqueio_escrita_global():
        return bloqueio
    if not BLING_ACCESS_TOKEN:
        return {"ok": False, "erro": "BLING_ACCESS_TOKEN não configurado"}
    try:
        r = _request_bling("POST", f"{BASE}/nfe", json=payload_nfe, timeout=30)
        r.raise_for_status()
        body = r.json()
        data = body.get("data", body)
        logger.info(
            "Bling NF-e criada com sucesso numeroPedidoLoja=%s",
            payload_nfe.get("numeroPedidoLoja"),
        )
        return {"ok": True, "data": data}
    except Exception as exc:
        logger.error("Bling criar_nfe erro: %s", exc)
        return {"ok": False, "erro": str(exc)}


def buscar_nfe_por_pedido(numero_pedido_loja: str, dias: int = 30) -> dict | None:
    """
    Verifica se já existe NF-e emitida para numeroPedidoLoja no Bling.
    Retorna None se não encontrar ou em caso de erro (nunca lança exceção).
    """
    pedido_ref = str(numero_pedido_loja or "").strip()
    if not pedido_ref:
        return None
    try:
        from datetime import datetime, timedelta

        corte = datetime.now() - timedelta(days=max(1, int(dias)))
        pagina = 1
        while pagina <= 20:
            r = _request_bling(
                "GET",
                f"{BASE}/nfe",
                params={"pagina": pagina, "limite": 100},
                timeout=20,
            )
            r.raise_for_status()
            data = r.json().get("data", []) or []
            if not data:
                break
            for nfe in data:
                if not isinstance(nfe, dict):
                    continue
                ref = str(
                    nfe.get("numeroPedidoLoja")
                    or nfe.get("numero_pedido_loja")
                    or ""
                ).strip()
                if ref != pedido_ref:
                    continue
                data_em = str(nfe.get("dataEmissao") or nfe.get("data_emissao") or "")[:10]
                if data_em:
                    try:
                        if datetime.strptime(data_em, "%Y-%m-%d") < corte:
                            continue
                    except ValueError:
                        pass
                return nfe
            if len(data) < 100:
                break
            pagina += 1
        return None
    except Exception as exc:
        logger.error(
            "Bling buscar_nfe_por_pedido erro pedido=%s: %s",
            pedido_ref,
            exc,
        )
        raise NfeVerificacaoIndisponivel(
            f"não foi possível confirmar duplicidade de NF-e para pedido {pedido_ref}: {exc}"
        ) from exc
