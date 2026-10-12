"""
integracoes/leilao/fontes.py
Cadastro dos principais leiloeiros e portais DETRAN (todos os estados BR).
"""
from __future__ import annotations

# Principais sites de leilão de veículos no Brasil
LEILOEIROS_PRINCIPAIS: list[dict[str, str]] = [
    {"id": "copart", "nome": "Copart Brasil", "dominio": "copart.com.br"},
    {"id": "superbid", "nome": "Superbid", "dominio": "superbid.net"},
    {"id": "sodre", "nome": "Sodré Santoro", "dominio": "sodresantoro.com.br"},
    {"id": "portalzuk", "nome": "Portal Zuk", "dominio": "portalzuk.com.br"},
    {"id": "freitas", "nome": "Freitas Leiloeiro", "dominio": "freitasleiloeiro.com.br"},
    {"id": "megaleiloes", "nome": "Mega Leilões", "dominio": "megaleiloes.com.br"},
    {"id": "leilaovip", "nome": "Leilão VIP", "dominio": "leilaovip.com.br"},
    {"id": "sold", "nome": "SOLD Leilões", "dominio": "sold.com.br"},
    {"id": "zucchetti", "nome": "Zucchetti Leilões", "dominio": "zucchetti.lel.br"},
    {"id": "balbino", "nome": "Balbino Leilões", "dominio": "balbinoleiloes.com.br"},
    {"id": "pestana", "nome": "Pestana Leilões", "dominio": "pestanaleiloes.com.br"},
    {"id": "santander", "nome": "Santander Leilões", "dominio": "santander.com.br"},
    {"id": "bradesco", "nome": "Bradesco Leilões", "dominio": "bradescoleiloes.com.br"},
    {"id": "sumare", "nome": "Sumaré Leilões", "dominio": "sumareleiloes.com.br"},
]

# DETRAN — um portal por UF (busca via site:dominio)
DETRAN_POR_ESTADO: list[dict[str, str]] = [
    {"uf": "AC", "nome": "DETRAN Acre", "dominio": "detran.ac.gov.br"},
    {"uf": "AL", "nome": "DETRAN Alagoas", "dominio": "detran.al.gov.br"},
    {"uf": "AP", "nome": "DETRAN Amapá", "dominio": "detran.ap.gov.br"},
    {"uf": "AM", "nome": "DETRAN Amazonas", "dominio": "detran.am.gov.br"},
    {"uf": "BA", "nome": "DETRAN Bahia", "dominio": "detran.ba.gov.br"},
    {"uf": "CE", "nome": "DETRAN Ceará", "dominio": "detran.ce.gov.br"},
    {"uf": "DF", "nome": "DETRAN Distrito Federal", "dominio": "detran.df.gov.br"},
    {"uf": "ES", "nome": "DETRAN Espírito Santo", "dominio": "detran.es.gov.br"},
    {"uf": "GO", "nome": "DETRAN Goiás", "dominio": "detran.go.gov.br"},
    {"uf": "MA", "nome": "DETRAN Maranhão", "dominio": "detran.ma.gov.br"},
    {"uf": "MT", "nome": "DETRAN Mato Grosso", "dominio": "detran.mt.gov.br"},
    {"uf": "MS", "nome": "DETRAN Mato Grosso do Sul", "dominio": "detran.ms.gov.br"},
    {"uf": "MG", "nome": "DETRAN Minas Gerais", "dominio": "detran.mg.gov.br"},
    {"uf": "PA", "nome": "DETRAN Pará", "dominio": "detran.pa.gov.br"},
    {"uf": "PB", "nome": "DETRAN Paraíba", "dominio": "detran.pb.gov.br"},
    {"uf": "PR", "nome": "DETRAN Paraná", "dominio": "detran.pr.gov.br"},
    {"uf": "PE", "nome": "DETRAN Pernambuco", "dominio": "detran.pe.gov.br"},
    {"uf": "PI", "nome": "DETRAN Piauí", "dominio": "detran.pi.gov.br"},
    {"uf": "RJ", "nome": "DETRAN Rio de Janeiro", "dominio": "detran.rj.gov.br"},
    {"uf": "RN", "nome": "DETRAN Rio Grande do Norte", "dominio": "detran.rn.gov.br"},
    {"uf": "RS", "nome": "DETRAN Rio Grande do Sul", "dominio": "detran.rs.gov.br"},
    {"uf": "RO", "nome": "DETRAN Rondônia", "dominio": "detran.ro.gov.br"},
    {"uf": "RR", "nome": "DETRAN Roraima", "dominio": "detran.rr.gov.br"},
    {"uf": "SC", "nome": "DETRAN Santa Catarina", "dominio": "detran.sc.gov.br"},
    {"uf": "SP", "nome": "DETRAN São Paulo", "dominio": "detran.sp.gov.br"},
    {"uf": "SE", "nome": "DETRAN Sergipe", "dominio": "detran.se.gov.br"},
    {"uf": "TO", "nome": "DETRAN Tocantins", "dominio": "detran.to.gov.br"},
]

TODAS_AS_FONTES: list[dict[str, str]] = [
    *[{**f, "tipo": "leiloeiro"} for f in LEILOEIROS_PRINCIPAIS],
    *[{**f, "tipo": "detran"} for f in DETRAN_POR_ESTADO],
]

# URLs de cadastro/inscrição conhecidas por portal (fallback quando não vier no snippet)
URLS_CADASTRO_POR_DOMINIO: dict[str, str] = {
    "copart.com.br": "https://www.copart.com.br/br/Account/Register",
    "superbid.net": "https://www.superbid.net/cadastro",
    "sodresantoro.com.br": "https://www.sodresantoro.com.br/cadastro-de-cliente",
    "portalzuk.com.br": "https://www.portalzuk.com.br/cadastro",
    "freitasleiloeiro.com.br": "https://www.freitasleiloeiro.com.br/cadastro",
    "megaleiloes.com.br": "https://www.megaleiloes.com.br/cadastro",
    "leilaovip.com.br": "https://www.leilaovip.com.br/cadastro",
    "sold.com.br": "https://www.sold.com.br/cadastro",
    "balbinoleiloes.com.br": "https://www.balbinoleiloes.com.br/cadastro",
    "pestanaleiloes.com.br": "https://www.pestanaleiloes.com.br/cadastro",
    "detran.sp.gov.br": "https://www.detran.sp.gov.br/wps/portal/portaldetran/cidadao/leiloes",
    "detran.pr.gov.br": "https://www.detran.pr.gov.br/leilao-de-veiculos",
    "detran.rj.gov.br": "https://www.detran.rj.gov.br/leilao",
    "detran.mg.gov.br": "https://www.detran.mg.gov.br/leilao",
    "detran.rs.gov.br": "https://www.detran.rs.gov.br/leilao",
}
