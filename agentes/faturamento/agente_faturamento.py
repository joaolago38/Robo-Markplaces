"""
agentes/faturamento/agente_faturamento.py
Emite NF-e no Bling com validação de NCM por item.
"""
from __future__ import annotations

import logging
from datetime import datetime

from core.fiscal_mapper import resolver_ncm_item
from core.config import (
    NFE_NATUREZA_OPERACAO,
    NFE_CFOP_PADRAO,
    NFE_CST_PADRAO,
    NFE_CSOSN_PADRAO,
    NFE_ORIGEM_PADRAO,
    NFE_SERIE_PADRAO,
)
from core.notificador import alertar_critico
from integracoes.bling.bling_client import buscar_produto, criar_nfe

logger = logging.getLogger("agente_faturamento")


def _to_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _to_int(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return int(default)


def _montar_itens_nfe(itens: list[dict]) -> tuple[list[dict], list[str]]:
    itens_nfe = []
    erros = []
    for i, item in enumerate(itens, start=1):
        sku = str(item.get("sku", "")).strip()
        if not sku:
            erros.append(f"item {i} sem sku")
            continue

        produto_bling = buscar_produto(sku) or {}
        ncm = resolver_ncm_item(item, produto_bling)
        if not ncm:
            erros.append(f"item {i} sku={sku} sem NCM válido")
            continue

        qtd = _to_int(item.get("quantidade", 1), 1)
        preco = _to_float(item.get("valor_unitario", produto_bling.get("preco", 0)))
        descricao = item.get("descricao") or produto_bling.get("nome") or sku

        itens_nfe.append(
            {
                "codigo": sku,
                "descricao": descricao,
                "ncm": ncm,
                "cfop": item.get("cfop", NFE_CFOP_PADRAO),
                "origem": str(item.get("origem", NFE_ORIGEM_PADRAO)),
                "cst": str(item.get("cst", NFE_CST_PADRAO)),
                "csosn": str(item.get("csosn", NFE_CSOSN_PADRAO)),
                "quantidade": max(1, qtd),
                "valor": round(max(0.0, preco), 2),
            }
        )
    return itens_nfe, erros


def _montar_contato(cliente: dict) -> dict:
    endereco = cliente.get("endereco") or {}
    return {
        "nome": cliente.get("nome", "Consumidor Final"),
        "numeroDocumento": cliente.get("documento", ""),
        "email": cliente.get("email", ""),
        "telefone": cliente.get("telefone", ""),
        "endereco": {
            "logradouro": endereco.get("logradouro", ""),
            "numero": endereco.get("numero", ""),
            "complemento": endereco.get("complemento", ""),
            "bairro": endereco.get("bairro", ""),
            "municipio": endereco.get("municipio", ""),
            "uf": endereco.get("uf", ""),
            "cep": endereco.get("cep", ""),
        },
    }


def emitir_nfe_pedido(pedido: dict, dry_run: bool = False) -> dict:
    """
    Pedido esperado:
    {
      "pedido_id": "123",
      "cliente": {"nome": "...", "documento": "...", "email": "..."},
      "itens": [{"sku": "ESM-001", "quantidade": 2, "valor_unitario": 9.9}]
    }
    """
    pedido_id = str(pedido.get("pedido_id", "")).strip()
    itens = pedido.get("itens") or []
    cliente = pedido.get("cliente") or {}

    if not pedido_id:
        return {"ok": False, "erro": "pedido_id obrigatório"}
    if not itens:
        return {"ok": False, "erro": "itens obrigatórios"}

    itens_nfe, erros = _montar_itens_nfe(itens)
    if erros:
        msg = f"NF-e bloqueada para pedido {pedido_id}: " + "; ".join(erros)
        alertar_critico(msg)
        return {"ok": False, "erro": msg, "erros": erros}

    payload_nfe = {
        "numeroPedidoLoja": pedido_id,
        "dataEmissao": datetime.now().strftime("%Y-%m-%d"),
        "serie": str(pedido.get("serie", NFE_SERIE_PADRAO)),
        "naturezaOperacao": pedido.get("natureza_operacao", NFE_NATUREZA_OPERACAO),
        "contato": _montar_contato(cliente),
        "itens": itens_nfe,
        "observacoes": pedido.get("observacoes", ""),
    }

    if dry_run:
        return {"ok": True, "dry_run": True, "payload_nfe": payload_nfe, "itens_total": len(itens_nfe)}

    resposta = criar_nfe(payload_nfe)
    if not resposta.get("ok"):
        alertar_critico(f"Erro ao emitir NF-e no Bling pedido {pedido_id}: {resposta.get('erro')}")
        return {"ok": False, "erro": resposta.get("erro"), "payload_nfe": payload_nfe}

    return {
        "ok": True,
        "pedido_id": pedido_id,
        "itens_total": len(itens_nfe),
        "nfe": resposta.get("data"),
    }
