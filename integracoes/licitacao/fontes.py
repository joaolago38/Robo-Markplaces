"""
integracoes/licitacao/fontes.py
Fontes nacionais (PNCP) e portais estaduais para licitações públicas.
"""
from __future__ import annotations

# Códigos PNCP — Manual API Consultas v1
MODALIDADES_PNCP: dict[int, str] = {
    1: "Leilão - Eletrônico",
    2: "Diálogo Competitivo",
    3: "Concurso",
    4: "Concorrência - Eletrônica",
    5: "Concorrência - Presencial",
    6: "Pregão - Eletrônico",
    7: "Pregão - Presencial",
    8: "Dispensa de Licitação",
    9: "Inexigibilidade",
    12: "Credenciamento",
}

MODALIDADES_PADRAO_BUSCA: list[int] = [6, 8, 4]

TODAS_UFS: list[str] = [
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
]

# Portais estaduais / compras públicas (busca complementar via DDG)
PORTAIS_POR_ESTADO: list[dict[str, str]] = [
    {"uf": "AC", "nome": "Compras Acre", "dominio": "compras.ac.gov.br"},
    {"uf": "AL", "nome": "Compras Alagoas", "dominio": "compras.al.gov.br"},
    {"uf": "AP", "nome": "Portal de Compras AP", "dominio": "portaldecompras.ap.gov.br"},
    {"uf": "AM", "nome": "Compras Amazonas", "dominio": "compras.am.gov.br"},
    {"uf": "BA", "nome": "Compras Bahia", "dominio": "compras.ba.gov.br"},
    {"uf": "CE", "nome": "Compras Ceará", "dominio": "compras.ce.gov.br"},
    {"uf": "DF", "nome": "Compras DF", "dominio": "compras.df.gov.br"},
    {"uf": "ES", "nome": "Compras ES", "dominio": "compras.es.gov.br"},
    {"uf": "GO", "nome": "Compras Goiás", "dominio": "compras.go.gov.br"},
    {"uf": "MA", "nome": "Compras Maranhão", "dominio": "compras.ma.gov.br"},
    {"uf": "MT", "nome": "Compras MT", "dominio": "compras.mt.gov.br"},
    {"uf": "MS", "nome": "Compras MS", "dominio": "compras.ms.gov.br"},
    {"uf": "MG", "nome": "Compras MG", "dominio": "compras.mg.gov.br"},
    {"uf": "PA", "nome": "Compras Pará", "dominio": "compras.pa.gov.br"},
    {"uf": "PB", "nome": "Compras Paraíba", "dominio": "compras.pb.gov.br"},
    {"uf": "PR", "nome": "Compras Paraná", "dominio": "compras.pr.gov.br"},
    {"uf": "PE", "nome": "Compras Pernambuco", "dominio": "compras.pe.gov.br"},
    {"uf": "PI", "nome": "Compras Piauí", "dominio": "compras.pi.gov.br"},
    {"uf": "RJ", "nome": "Compras RJ", "dominio": "compras.rj.gov.br"},
    {"uf": "RN", "nome": "Compras RN", "dominio": "compras.rn.gov.br"},
    {"uf": "RS", "nome": "Compras RS", "dominio": "compras.rs.gov.br"},
    {"uf": "RO", "nome": "Compras Rondônia", "dominio": "compras.ro.gov.br"},
    {"uf": "RR", "nome": "Compras Roraima", "dominio": "compras.rr.gov.br"},
    {"uf": "SC", "nome": "Compras SC", "dominio": "compras.sc.gov.br"},
    {"uf": "SP", "nome": "Compras SP", "dominio": "compras.sp.gov.br"},
    {"uf": "SE", "nome": "Compras Sergipe", "dominio": "compras.se.gov.br"},
    {"uf": "TO", "nome": "Compras Tocantins", "dominio": "compras.to.gov.br"},
]

PORTAIS_NACIONAIS: list[dict[str, str]] = [
    {"id": "pncp", "nome": "PNCP", "dominio": "pncp.gov.br"},
    {"id": "comprasgov", "nome": "Compras.gov.br", "dominio": "compras.gov.br"},
]

URLS_PARTICIPACAO: dict[str, str] = {
    "compras.gov.br": "https://www.gov.br/compras/pt-br/fornecedor/sicaf",
    "pncp.gov.br": "https://www.gov.br/pncp/pt-br",
    "compras.sp.gov.br": "https://www.compras.sp.gov.br/",
    "compras.pr.gov.br": "https://www.compras.pr.gov.br/",
}
