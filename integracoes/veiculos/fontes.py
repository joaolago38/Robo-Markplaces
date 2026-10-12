"""
integracoes/veiculos/fontes.py
Lojas monitoradas (salvados/batidos).
"""
from __future__ import annotations

from typing import Any

FONTES_PADRAO: tuple[dict[str, Any], ...] = (
    {
        "id": "lucineia",
        "nome": "Lucinei Automóveis",
        "url_listagem": "https://lucineiautomoveis.com.br/BuscadorVeiculo.aspx",
        "tipo": "html",
    },
    {
        "id": "leopardo",
        "nome": "Leopardo Veículos",
        "url_listagem": "https://www.leopardoveiculos.com.br/veiculos",
        "tipo": "ajax",
        "ajax_url": "https://www.leopardoveiculos.com.br/loadveiculos",
        "categoria_carros": "49874",
    },
)
