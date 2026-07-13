"""
integracoes/social/promocoes_manicures.py
Monta mensagens pré-definidas de promoção ML para manicures.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from core.atomic_io import ler_json
from core.catalogo_produtos import carregar_produtos_catalogo
from core.config import ML_LOJA_URL, PROMOCOES_MANICURES_CATALOGO, PROMOCOES_MANICURES_RODAPE, ROOT

logger = logging.getLogger("promocoes_manicures")

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
_ITEM_ID_INVALIDO = frozenset({"", "MLB_PREENCHER", "MLB-PREENCHER"})


def carregar_campanhas() -> list[dict[str, Any]]:
    caminho = ROOT / PROMOCOES_MANICURES_CATALOGO
    data = ler_json(caminho, default=[])
    if not isinstance(data, list):
        return []
    return [c for c in data if isinstance(c, dict) and c.get("ativo")]


def _fmt_brl(valor: Any) -> str:
    try:
        return f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "0,00"


def _produto_por_sku(sku: str) -> dict[str, Any] | None:
    sku = (sku or "").strip().upper()
    if not sku:
        return None
    for p in carregar_produtos_catalogo():
        if str(p.get("sku") or "").strip().upper() == sku:
            return p
    return None


def _link_ml(produto: dict[str, Any]) -> str:
    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    item_id = str(ml.get("item_id") or "").strip().upper().replace("-", "")
    if item_id and item_id not in _ITEM_ID_INVALIDO:
        return f"https://produto.mercadolivre.com.br/{item_id}"

    permalink = str(ml.get("permalink") or "").strip()
    if permalink.startswith("http"):
        return permalink

    termo = str(ml.get("titulo_anuncio") or produto.get("nome") or "").strip()
    loja = (ML_LOJA_URL or "").strip().rstrip("/")
    if loja and termo:
        from urllib.parse import quote_plus

        return f"{loja}/lista/{quote_plus(termo)}/"
    if loja:
        return loja

    if termo:
        from urllib.parse import quote_plus

        return f"https://lista.mercadolivre.com.br/{quote_plus(termo)}"

    return "https://www.mercadolivre.com.br"


def link_ml_valido(link: str) -> bool:
    link = (link or "").strip()
    if not link.startswith("http"):
        return False
    u = link.upper()
    if "MLB_PREENCHER" in u or "MLB-PREENCHER" in u:
        return False
    # Lista genérica = anúncio ainda não cadastrado no catálogo
    if "lista.mercadolivre" in link.lower() and "/lista/" in link.lower():
        return False
    return True


def _item_id_produto(produto: dict[str, Any]) -> str:
    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    return str(ml.get("item_id") or "").strip().upper().replace("-", "")


def montar_mensagem_campanha(campanha: dict[str, Any]) -> dict[str, Any]:
    """Preenche template da campanha com dados do produto no catálogo."""
    sku = str(campanha.get("sku") or "").strip()
    produto = _produto_por_sku(sku)
    if not produto:
        return {"ok": False, "motivo": f"sku não encontrado: {sku}", "campanha_id": campanha.get("id")}

    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    if not ml.get("ativo", True):
        return {"ok": False, "motivo": "produto inativo no ML", "campanha_id": campanha.get("id")}

    preco = float(ml.get("preco") or produto.get("preco") or 0)
    if preco <= 0:
        return {"ok": False, "motivo": "preço inválido", "campanha_id": campanha.get("id")}

    preco_de = campanha.get("preco_de")
    if preco_de is None:
        preco_de = round(preco * 1.15, 2)

    link = _link_ml(produto)
    item_id = _item_id_produto(produto)
    item_ok = bool(item_id) and item_id not in _ITEM_ID_INVALIDO
    valido = link_ml_valido(link) and item_ok

    ctx = {
        "produto": str(produto.get("nome") or campanha.get("nome") or sku),
        "preco": _fmt_brl(preco),
        "preco_de": _fmt_brl(preco_de),
        "sku": sku,
        "link": link,
        "loja_url": (ML_LOJA_URL or "https://www.mercadolivre.com.br").strip(),
        "rodape": str(campanha.get("rodape") or PROMOCOES_MANICURES_RODAPE),
        "marketplace": "Mercado Livre",
    }

    template = str(campanha.get("template") or "").strip()
    if not template:
        return {"ok": False, "motivo": "template vazio", "campanha_id": campanha.get("id")}

    def _sub(match: re.Match[str]) -> str:
        chave = match.group(1)
        return str(ctx.get(chave, match.group(0)))

    texto = _PLACEHOLDER_RE.sub(_sub, template)

    out = {
        "ok": True,
        "campanha_id": campanha.get("id"),
        "campanha_nome": campanha.get("nome"),
        "sku": sku,
        "preco_brl": preco,
        "link_ml": ctx["link"],
        "link_valido": valido,
        "item_id": item_id or None,
        "texto": texto,
        "texto_telegram": texto,
        "texto_whatsapp": _para_whatsapp(texto),
    }
    if not valido:
        out["aviso_link"] = (
            "item_id ainda é MLB_PREENCHER ou link genérico — "
            "não efetive divulgação até preencher o MLB real no catálogo"
        )
    return out


def _para_whatsapp(texto: str) -> str:
    """Remove markdown Telegram (*_) para WhatsApp."""
    out = texto.replace("*", "").replace("_", "")
    return out.strip()


def escolher_campanha(
    campanhas: list[dict[str, Any]],
    *,
    ultimo_id: str | None = None,
) -> dict[str, Any] | None:
    """Rotação por prioridade — evita repetir a mesma campanha em sequência."""
    if not campanhas:
        return None
    ordenadas = sorted(campanhas, key=lambda c: int(c.get("prioridade") or 99))
    if len(ordenadas) == 1:
        return ordenadas[0]
    ids = [str(c.get("id") or "") for c in ordenadas]
    if ultimo_id and ultimo_id in ids:
        idx = ids.index(ultimo_id)
        return ordenadas[(idx + 1) % len(ordenadas)]
    return ordenadas[0]
