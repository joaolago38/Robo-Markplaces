"""
integracoes/licitacao/requisitos.py
Requisitos típicos para participar de licitações públicas no Brasil.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from integracoes.licitacao.fontes import URLS_PARTICIPACAO


def _link_participacao(item: dict[str, Any]) -> str | None:
    usuario = str(item.get("sistema_origem") or "").lower()
    if "compras.gov" in usuario:
        return URLS_PARTICIPACAO["compras.gov.br"]

    for chave in ("url_participacao", "link_sistema", "url"):
        url = str(item.get(chave) or "").strip()
        if not url:
            continue
        dominio = urlparse(url).netloc.lower().replace("www.", "")
        for dom, cadastro in URLS_PARTICIPACAO.items():
            if dom in dominio:
                return cadastro
        if "comprasnet" in dominio or "compras.gov" in dominio:
            return URLS_PARTICIPACAO["compras.gov.br"]
    return URLS_PARTICIPACAO.get("pncp.gov.br")


def montar_requisitos_participacao(item: dict[str, Any]) -> dict[str, Any]:
    """
    Lista o que o fornecedor normalmente precisa para participar.
    Detalhes finais sempre estão no edital (link do processo).
    """
    modalidade = str(item.get("modalidade") or "").strip()
    encerramento = str(item.get("data_encerramento") or "ver edital").strip()
    link_proc = str(item.get("url") or item.get("link_sistema") or "").strip()
    usuario = str(item.get("sistema_origem") or "").strip()

    checklist: list[str] = [
        "CNPJ ativo e regular (Receita Federal)",
        "Certidão negativa de débitos federais (PGFN)",
        "Certidão FGTS (CRF) válida",
        "Certidão negativa de débitos trabalhistas (CNDT)",
        f"Enviar proposta até {encerramento}",
        "Ler edital e anexos no link do processo",
    ]

    if "compras.gov" in usuario.lower() or "comprasnet" in link_proc.lower():
        checklist.insert(0, "Cadastro ativo no SICAF/Compras.gov.br (fornecedor)")
    else:
        checklist.insert(0, "Cadastro no portal de compras do órgão/estado")

    if "pregão" in modalidade.lower():
        checklist.append("Proposta com preços unitários conforme planilha do edital")
        checklist.append("Documentos de habilitação (jurídica, fiscal, trabalhista, econômico-financeira)")
    elif "dispensa" in modalidade.lower():
        checklist.append("Manifestação de interesse no prazo do aviso")
    elif "concorrência" in modalidade.lower():
        checklist.append("Proposta técnica e de preços se exigido no edital")

    if item.get("srp"):
        checklist.append("SRP: registro de preços — contratos futuros conforme demanda do órgão")

    if item.get("orcamento_sigiloso"):
        checklist.append("Orçamento sigiloso — valor estimado não divulgado no PNCP")

    return {
        "checklist": checklist,
        "url_cadastro_fornecedor": _link_participacao(item),
        "url_processo": link_proc or None,
        "observacao": "Requisitos base Lei 14.133/2021 — confira o edital oficial.",
    }
