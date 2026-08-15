"""
core/chat_seguro_ml.py
Travas rígidas para respostas Claude no chat ML (sem inventar frete/prazo/preço/desconto).
"""
from __future__ import annotations

import re
from typing import Any

MSG_CONFIRMAR = "Vou confirmar os detalhes e já te respondo. Frete e prazo aparecem no anúncio com o seu CEP."
MSG_INDISPONIVEL = "Produto indisponível no momento. Acompanhe o anúncio para nova disponibilidade."
MSG_ESTOQUE_INCERTO = (
    "Vou confirmar o estoque e já te retorno. "
    "Enquanto isso, confira frete e prazo no anúncio com o seu CEP."
)
MSG_CONSULTAR_ANUNCIO = (
    "Para frete, prazo e valor final, confira direto no anúncio com o seu CEP — "
    "assim você vê a informação oficial do Mercado Livre."
)
MSG_SEM_DESCONTO = (
    "Não consigo garantir desconto por aqui. "
    "O preço oficial é o que aparece no anúncio; posso tirar dúvida sobre o produto."
)

# Promessas absolutas de frete/prazo/Full
_RE_FRETE_ABSOLUTO = re.compile(
    r"("
    r"frete\s*gr[aá]tis|"
    r"chegar[aá]\s+gr[aá]tis|"
    r"full\s+ativo|"
    r"amanh[aã]|"
    r"hoje\s+(ainda\s+)?(chega|entrega)|"
    r"\d+\s*dias?\s*[úu]teis|"
    r"entrega\s+em\s+\d+"
    r")",
    re.IGNORECASE,
)

# Promessas de desconto / preço especial
_RE_DESCONTO = re.compile(
    r"("
    r"desconto|"
    r"promo(ção|cao)?|"
    r"pre[cç]o\s+especial|"
    r"mais\s+barato|"
    r"%\s*off|"
    r"lev[eo]\s+\d+|compre\s+\d+"
    r")",
    re.IGNORECASE,
)

# Valores monetários no texto
_RE_PRECO = re.compile(r"R\$\s*[\d.,]+|\b\d{1,3}(?:[.,]\d{3})*[.,]\d{2}\b", re.IGNORECASE)


def _precos_permitidos(produto: dict[str, Any] | None) -> set[str]:
    """Normaliza preços do produto que podem aparecer na resposta."""
    out: set[str] = set()
    if not isinstance(produto, dict):
        return out
    for chave in ("preco", "preco_brl", "preco_ml"):
        try:
            v = float(produto.get(chave) or 0)
        except (TypeError, ValueError):
            continue
        if v <= 0:
            continue
        out.add(f"{v:.2f}")
        out.add(f"{v:.2f}".replace(".", ","))
        # formas sem casas quando inteiro
        if abs(v - round(v)) < 1e-9:
            out.add(str(int(round(v))))
    return out


def _preco_texto_permitido(trecho: str, permitidos: set[str]) -> bool:
    if not permitidos:
        return False
    limpo = re.sub(r"[^\d.,]", "", trecho)
    limpo = limpo.replace(",", ".")
    try:
        val = float(limpo)
    except ValueError:
        return False
    candidatos = {f"{val:.2f}", f"{val:.2f}".replace(".", ",")}
    if abs(val - round(val)) < 1e-9:
        candidatos.add(str(int(round(val))))
    return bool(candidatos & permitidos)


def sanitizar_resposta_chat_ml(texto: str, produto: dict[str, Any] | None = None) -> str:
    """
    Remove/substitui trechos perigosos antes de publicar no ML.
    Não inventa frete/prazo; não promete desconto; só permite preço do catálogo.
    """
    raw = str(texto or "").strip()
    if not raw:
        return MSG_CONFIRMAR

    if _RE_FRETE_ABSOLUTO.search(raw):
        return MSG_CONSULTAR_ANUNCIO

    if _RE_DESCONTO.search(raw):
        return MSG_SEM_DESCONTO

    permitidos = _precos_permitidos(produto)
    for m in _RE_PRECO.finditer(raw):
        if not _preco_texto_permitido(m.group(0), permitidos):
            return MSG_CONSULTAR_ANUNCIO

    return raw


def prompt_sistema_chat(canal: str = "mercadolivre") -> str:
    """Prompt de chat por canal. ML é referente; Impala nos outros só depois da saúde ML."""
    c = str(canal or "mercadolivre").strip().lower() or "mercadolivre"
    nomes = {
        "mercadolivre": "Mercado Livre",
        "shopee": "Shopee",
        "magalu": "Magalu",
        "amazon": "Amazon",
    }
    nome = nomes.get(c, c)
    base = (
        f"Você responde perguntas de compradores no {nome}. "
        "Tom neutro, factual e curto. "
        "NUNCA invente frete, prazo, Full, desconto, promoção, preço, tolueno ou formaldeído. "
        "Não invente anúncio, item_id ou estoque em canal onde o kit não está no ar. "
        "Título Impala MIMO: Kit 3 Esmaltes Impala Mimo + Carmed Manicure. "
        "Não ofereça francesinha, sortidas, tratamento incolor nem kit SORT. "
        "Mercado Livre é o referente de preço e saúde da conta; "
        "Shopee/Magalu/Amazon só depois de 20 reviews / nota 4.8 no ML. "
        "Não peça dados sensíveis. "
    )
    if c == "mercadolivre":
        return (
            base
            + "Para frete/prazo/CEP, oriente a consultar o anúncio. "
            "Não prometa disponibilidade além do estoque informado."
        )
    return (
        base
        + "Impala ainda não está publicado neste canal. "
        "Não invente listing nem cole link do Mercado Livre se não houver MLB real. "
        "Se perguntarem de kit Impala, diga que o kit está em preparação neste canal."
    )


def prompt_sistema_chat_ml() -> str:
    return prompt_sistema_chat("mercadolivre")
