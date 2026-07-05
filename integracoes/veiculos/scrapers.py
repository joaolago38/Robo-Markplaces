"""
integracoes/veiculos/scrapers.py
Coleta anúncios das lojas Lucinei e Leopardo.
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any
from urllib.parse import urljoin

from core.http_client import request
from integracoes.veiculos.fontes import FONTES_PADRAO

logger = logging.getLogger("veiculos_scrapers")

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RoboMarkplaces/1.0)"}
_RE_PRECO = re.compile(r"R\$\s*([\d\.\,]+)")
_RE_LUCINEIA_CARD = re.compile(
    r'href="Veiculo\.aspx\?id=(\d+)"[^>]*>.*?'
    r'<h5[^>]*card-text[^>]*>([^<]+)</h5>.*?'
    r"Marca:\s*([^<]+)<br\s*/>\s*"
    r"Ano:\s*([^<]+)<br.*?>"
    r'<h5[^>]*text-right[^>]*>(R\$\s*[\d\.\,]+)</h5>',
    re.DOTALL | re.IGNORECASE,
)
_RE_LEOPARDO_BLOCO = re.compile(
    r"<div class=\"col-list-3 divlinkclicable[^\"]*\" id='divveiculo(\d+)'.*?</div>\s*</div>\s*</div>",
    re.DOTALL | re.IGNORECASE,
)


def parse_preco_brl(texto: str) -> float | None:
    if not texto:
        return None
    upper = texto.upper()
    if any(x in upper for x in ("VENDIDO", "PRÉ-LIBERAÇÃO", "PRE-LIBERACAO", "RESERVA")):
        return None
    m = _RE_PRECO.search(texto.replace("\n", " "))
    if not m:
        return None
    bruto = m.group(1).replace(".", "").replace(",", ".")
    try:
        valor = float(bruto)
    except ValueError:
        return None
    return valor if valor > 0 else None


def _hash_anuncio(loja_id: str, id_externo: str) -> str:
    return hashlib.sha256(f"{loja_id}:{id_externo}".encode()).hexdigest()[:16]


def _anuncio_base(
    *,
    loja_id: str,
    loja_nome: str,
    id_externo: str,
    titulo: str,
    marca: str,
    ano: str,
    preco: float,
    url: str,
    condicao: str | None = None,
) -> dict[str, Any]:
    return {
        "hash": _hash_anuncio(loja_id, id_externo),
        "loja_id": loja_id,
        "loja_nome": loja_nome,
        "id_externo": id_externo,
        "titulo": titulo.strip(),
        "marca": marca.strip(),
        "ano": ano.strip(),
        "preco": preco,
        "url": url,
        "condicao": condicao,
    }


def coletar_lucineia(fonte: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    fonte = fonte or FONTES_PADRAO[0]
    url = str(fonte.get("url_listagem") or "")
    base = "https://lucineiautomoveis.com.br/"
    try:
        r = request("GET", url, timeout=25, headers=_HEADERS)
        if r.status_code != 200:
            logger.warning("Lucinei: HTTP %s em %s", r.status_code, url)
            return []
        html = r.text
    except Exception as exc:
        logger.error("Lucinei: erro ao buscar listagem: %s", exc)
        return []

    anuncios: list[dict[str, Any]] = []
    for match in _RE_LUCINEIA_CARD.finditer(html):
        vid, titulo, marca, ano, preco_txt = match.groups()
        preco = parse_preco_brl(preco_txt)
        if preco is None:
            continue
        condicao = None
        bloco = match.group(0)
        m_cond = re.search(r"disabled[^>]*>([^<]+)</p>", bloco, re.I)
        if m_cond:
            condicao = m_cond.group(1).strip()
        anuncios.append(
            _anuncio_base(
                loja_id=str(fonte.get("id") or "lucineia"),
                loja_nome=str(fonte.get("nome") or "Lucinei"),
                id_externo=vid,
                titulo=titulo,
                marca=marca,
                ano=ano,
                preco=preco,
                url=urljoin(base, f"Veiculo.aspx?id={vid}"),
                condicao=condicao,
            )
        )
    logger.info("Lucinei: %s anúncio(s) coletado(s)", len(anuncios))
    return anuncios


def _extrair_csrf(html: str) -> str:
    m = re.search(r'csrf-token"\s+content="([^"]+)"', html)
    return m.group(1) if m else ""


def _parse_leopardo_html(html_fragment: str, fonte: dict[str, Any]) -> list[dict[str, Any]]:
    base_url = "https://www.leopardoveiculos.com.br"
    anuncios: list[dict[str, Any]] = []
    for bloco in _RE_LEOPARDO_BLOCO.finditer(html_fragment):
        vid = bloco.group(1)
        trecho = bloco.group(0)
        m_titulo = re.search(r"titulo-veiculo-card[^>]*>.*?<a[^>]*>([^<]+)</a>", trecho, re.I | re.S)
        m_ano = re.search(r"pull-left text-bold[^>]*>\s*([^<]+)\s*</span>", trecho, re.I | re.S)
        m_preco = re.search(r'class="price"[^>]*>(.*?)</span>', trecho, re.I | re.S)
        m_url = re.search(r'href="(https://www\.leopardoveiculos\.com\.br/veiculo/[^"]+)"', trecho, re.I)
        if not m_titulo or not m_preco:
            continue
        titulo = re.sub(r"\s+", " ", m_titulo.group(1)).strip()
        preco = parse_preco_brl(m_preco.group(1))
        if preco is None:
            continue
        ano = (m_ano.group(1).strip() if m_ano else "")
        url_anuncio = m_url.group(1) if m_url else f"{base_url}/veiculo/{vid}"
        marca = titulo.split()[0] if titulo else ""
        if marca.upper() in {"VW", "GM"} and len(titulo.split()) > 1:
            marca = f"{marca} {titulo.split()[1]}"
        anuncios.append(
            _anuncio_base(
                loja_id=str(fonte.get("id") or "leopardo"),
                loja_nome=str(fonte.get("nome") or "Leopardo"),
                id_externo=vid,
                titulo=titulo,
                marca=marca,
                ano=ano,
                preco=preco,
                url=url_anuncio,
            )
        )
    return anuncios


def coletar_leopardo(
    fonte: dict[str, Any] | None = None,
    *,
    max_paginas: int = 8,
    categoria_carros: bool = True,
) -> list[dict[str, Any]]:
    fonte = fonte or FONTES_PADRAO[1]
    url_listagem = str(fonte.get("url_listagem") or "")
    ajax_url = str(fonte.get("ajax_url") or "")
    try:
        r = request("GET", url_listagem, timeout=25, headers=_HEADERS)
        if r.status_code != 200:
            logger.warning("Leopardo: HTTP %s", r.status_code)
            return []
        html = r.text
        token = _extrair_csrf(html)
    except Exception as exc:
        logger.error("Leopardo: erro ao abrir listagem: %s", exc)
        return []

    tipo_tab = str(fonte.get("categoria_carros") or "49874") if categoria_carros else "6"
    payload_base = {
        "inputvaluepagination49382": "1",
        "inputvaluepagination49761": "1",
        "inputvaluepagination49874": "1",
        "inputvaluepagination52601": "1",
        "inputvaluepagination52742": "1",
        "inputvaluepagination6": "1",
        "inputvaluepagination0": "1",
        "inputvaluepaginationtype": tipo_tab,
        "liberado": "1",
        "tipo": "0",
        "tabactiveinputform": "4",
        "view": "2",
        "_token": token,
    }
    headers = {
        **_HEADERS,
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRF-TOKEN": token,
        "Referer": url_listagem,
    }

    anuncios: list[dict[str, Any]] = []
    vistos: set[str] = set()
    pagina = 1
    while pagina <= max_paginas:
        payload = {**payload_base, "inputvaluepagination" + tipo_tab: str(pagina), "idvehicles[]": "0"}
        try:
            r_ajax = request("POST", ajax_url, timeout=30, data=payload, headers=headers)
            if r_ajax.status_code != 200:
                logger.warning("Leopardo loadveiculos HTTP %s (página %s)", r_ajax.status_code, pagina)
                break
            data = r_ajax.json()
        except Exception as exc:
            logger.error("Leopardo AJAX página %s: %s", pagina, exc)
            break

        fragmento = str(data.get("returnhtml") or "")
        novos = _parse_leopardo_html(fragmento, fonte)
        if not novos:
            break
        for item in novos:
            h = item["hash"]
            if h in vistos:
                continue
            vistos.add(h)
            anuncios.append(item)

        retorno = data.get("retornopagina")
        if retorno == -1:
            break
        pagina += 1

    logger.info("Leopardo: %s anúncio(s) coletado(s)", len(anuncios))
    return anuncios


def coletar_fonte(fonte: dict[str, Any]) -> list[dict[str, Any]]:
    tipo = str(fonte.get("tipo") or "html").lower()
    if fonte.get("id") == "lucineia" or tipo == "html":
        return coletar_lucineia(fonte)
    if fonte.get("id") == "leopardo" or tipo == "ajax":
        return coletar_leopardo(fonte)
    logger.warning("Fonte desconhecida: %s", fonte.get("id"))
    return []
