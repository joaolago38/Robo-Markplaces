"""
integracoes/licitacao/pncp_client.py
Cliente da API pública de consulta do PNCP (todos os estados).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from core.http_client import request

logger = logging.getLogger("licitacao_pncp")

BASE_URL = "https://pncp.gov.br/api/consulta/v1"


def _formatar_data(d: date) -> str:
    return d.strftime("%Y%m%d")


def _get_json(path: str, *, params: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    try:
        r = request("GET", f"{BASE_URL}{path}", params=params, timeout=timeout)
        if r.status_code != 200:
            logger.warning("PNCP %s status=%s body=%s", path, r.status_code, (r.text or "")[:200])
            return {}
        body = r.json()
        return body if isinstance(body, dict) else {}
    except Exception as exc:
        logger.error("PNCP %s erro: %s", path, exc)
        return {}


def buscar_propostas_abertas(
    *,
    codigo_modalidade: int,
    uf: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 50,
    dias_frente: int = 45,
) -> dict[str, Any]:
    """Contratações com recebimento de propostas em aberto."""
    hoje = date.today()
    params: dict[str, Any] = {
        "dataFinal": _formatar_data(hoje + timedelta(days=dias_frente)),
        "codigoModalidadeContratacao": codigo_modalidade,
        "pagina": max(1, pagina),
        "tamanhoPagina": max(10, min(50, tamanho_pagina)),
    }
    if uf:
        params["uf"] = uf.strip().upper()[:2]
    return _get_json("/contratacoes/proposta", params=params)


def buscar_publicacoes_recentes(
    *,
    codigo_modalidade: int,
    uf: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 50,
    dias_atras: int = 7,
) -> dict[str, Any]:
    """Contratações publicadas recentemente."""
    hoje = date.today()
    params: dict[str, Any] = {
        "dataInicial": _formatar_data(hoje - timedelta(days=dias_atras)),
        "dataFinal": _formatar_data(hoje),
        "codigoModalidadeContratacao": codigo_modalidade,
        "pagina": max(1, pagina),
        "tamanhoPagina": max(10, min(50, tamanho_pagina)),
    }
    if uf:
        params["uf"] = uf.strip().upper()[:2]
    return _get_json("/contratacoes/publicacao", params=params)


def buscar_detalhe_compra(cnpj_orgao: str, ano: int, sequencial: int) -> dict[str, Any]:
    cnpj = "".join(c for c in str(cnpj_orgao) if c.isdigit())
    if not cnpj or not ano or not sequencial:
        return {}
    return _get_json(f"/orgaos/{cnpj}/compras/{int(ano)}/{int(sequencial)}", params={})
