"""
integracoes/veiculos/scrapers.py
Coleta anúncios das lojas Lucinei e Leopardo.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse

from core.http_client import request
from integracoes.veiculos.fontes import FONTES_PADRAO

logger = logging.getLogger("veiculos_scrapers")

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RoboMarkplaces/1.0)"}
_RE_PRECO = re.compile(r"R\$\s*([\d\.\,]+)")
_RE_LUCINEIA_CARD_BODY = re.compile(
    r'<div class="card-body p-2 mr-1">(.*?)</div>',
    re.DOTALL | re.IGNORECASE,
)
_RE_LEOPARDO_BLOCO = re.compile(
    r"<div class=\"col-list-3 divlinkclicable[^\"]*\" id='divveiculo(\d+)'.*?</div>\s*</div>\s*</div>",
    re.DOTALL | re.IGNORECASE,
)
_RE_MOTORJAN_ITEM = re.compile(
    r'<div class=offer_item[^>]*>.*?'
    r'<a href="?([^">\s]+)"?[^>]*title="([^"]*)"[^>]*>.*?'
    r'<h2><a href=[^>]+>([^<]+)</a></h2>.*?<p>Modelo\s+([^<]+)</p>.*?'
    r'C[ÓO]DIGO:\s*(\d+).*?'
    r'class=offer_price>R\$\s*([\d\.\,]+)',
    re.DOTALL | re.IGNORECASE,
)
_RE_VELOZES_PRODUTO = re.compile(
    r'href="(https://velozesbatidos\.com\.br/product/[^"]+)"',
    re.IGNORECASE,
)
_RE_ANO_TITULO = re.compile(r"\b(?:19|20)\d{2}\b")


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
    for match in _RE_LUCINEIA_CARD_BODY.finditer(html):
        bloco = match.group(1)
        m_id = re.search(r"Veiculo\.aspx\?id=(\d+)", bloco, re.I)
        m_titulo = re.search(r'<h5 class="card-text alert-link">([^<]+)</h5>', bloco, re.I)
        m_marca = re.search(r"Marca:\s*([^<\n]+)", bloco, re.I)
        m_ano = re.search(r"Ano:\s*([^<\n]+)", bloco, re.I)
        m_preco = re.search(r'text-right">(R\$\s*[\d\.\,]+)</h5>', bloco, re.I)
        if not m_id or not m_titulo or not m_preco:
            continue
        vid = m_id.group(1)
        preco = parse_preco_brl(m_preco.group(1))
        if preco is None:
            continue
        condicao = None
        m_cond = re.search(r"disabled[^>]*>([^<]+)</p>", bloco, re.I)
        if m_cond:
            condicao = m_cond.group(1).strip()
        anuncios.append(
            _anuncio_base(
                loja_id=str(fonte.get("id") or "lucineia"),
                loja_nome=str(fonte.get("nome") or "Lucinei"),
                id_externo=vid,
                titulo=m_titulo.group(1),
                marca=(m_marca.group(1).strip() if m_marca else ""),
                ano=(m_ano.group(1).strip() if m_ano else ""),
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


def _extrair_ano_titulo(titulo: str) -> str:
    anos = _RE_ANO_TITULO.findall(titulo or "")
    return anos[-1] if anos else ""


def coletar_motorjan(fonte: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    fonte = fonte or {"id": "motorjan", "nome": "Motorjan Veículos"}
    url = str(fonte.get("url_listagem") or "https://www.motorjanveiculos.com.br/veiculos")
    base = "https://www.motorjanveiculos.com.br"
    try:
        r = request("GET", url, timeout=25, headers=_HEADERS)
        if r.status_code != 200:
            logger.warning("Motorjan: HTTP %s em %s", r.status_code, url)
            return []
        html = r.text
    except Exception as exc:
        logger.error("Motorjan: erro ao buscar listagem: %s", exc)
        return []

    anuncios: list[dict[str, Any]] = []
    for match in _RE_MOTORJAN_ITEM.finditer(html):
        href, _title_attr, titulo, ano, codigo, preco_txt = match.groups()
        preco = parse_preco_brl(f"R$ {preco_txt}")
        if preco is None:
            continue
        url_anuncio = href if href.startswith("http") else urljoin(base, href)
        titulo = re.sub(r"\s+", " ", titulo).strip()
        marca = titulo.split()[0] if titulo else ""
        anuncios.append(
            _anuncio_base(
                loja_id=str(fonte.get("id") or "motorjan"),
                loja_nome=str(fonte.get("nome") or "Motorjan"),
                id_externo=str(codigo),
                titulo=titulo,
                marca=marca,
                ano=str(ano).strip(),
                preco=preco,
                url=url_anuncio,
                condicao="sinistrado/batido",
            )
        )
    logger.info("Motorjan: %s anúncio(s) coletado(s)", len(anuncios))
    return anuncios


def coletar_velozes(fonte: dict[str, Any] | None = None, *, max_produtos: int = 24) -> list[dict[str, Any]]:
    fonte = fonte or {"id": "velozes", "nome": "Velozes Batidos"}
    url = str(fonte.get("url_listagem") or "https://velozesbatidos.com.br/")
    try:
        r = request("GET", url, timeout=25, headers=_HEADERS)
        if r.status_code != 200:
            logger.warning("Velozes: HTTP %s em %s", r.status_code, url)
            return []
        html = r.text
    except Exception as exc:
        logger.error("Velozes: erro ao buscar listagem: %s", exc)
        return []

    urls: list[str] = []
    vistos_url: set[str] = set()
    for m in _RE_VELOZES_PRODUTO.finditer(html):
        link = m.group(1).strip()
        if link in vistos_url:
            continue
        vistos_url.add(link)
        urls.append(link)
        if len(urls) >= max_produtos:
            break

    anuncios: list[dict[str, Any]] = []
    for link in urls:
        try:
            rp = request("GET", link, timeout=20, headers=_HEADERS)
            if rp.status_code != 200:
                continue
            pagina = rp.text
        except Exception as exc:
            logger.debug("Velozes produto %s: %s", link, exc)
            continue

        tm = re.search(r'<h1[^>]*class="[^"]*product_title[^"]*"[^>]*>([^<]+)</h1>', pagina, re.I)
        if not tm:
            tm = re.search(r"<title>([^<|]+)", pagina, re.I)
        titulo = re.sub(r"\s+", " ", (tm.group(1) if tm else "")).strip()
        if not titulo:
            continue
        pm = re.search(r'class="woocommerce-Price-amount[^"]*"[^>]*>.*?R\$\s*([\d\.\,]+)', pagina, re.S | re.I)
        preco = parse_preco_brl(f"R$ {pm.group(1)}") if pm else None
        if preco is None:
            continue
        slug = link.rstrip("/").split("/")[-1]
        ano = _extrair_ano_titulo(titulo)
        marca = titulo.split()[0] if titulo else ""
        anuncios.append(
            _anuncio_base(
                loja_id=str(fonte.get("id") or "velozes"),
                loja_nome=str(fonte.get("nome") or "Velozes Batidos"),
                id_externo=slug,
                titulo=titulo,
                marca=marca,
                ano=ano,
                preco=preco,
                url=link,
                condicao="batido/sinistrado",
            )
        )

    logger.info("Velozes: %s anúncio(s) coletado(s)", len(anuncios))
    return anuncios


# Estados/regiões para a busca web nacional (mais populosos primeiro)
_UFS_BUSCA_WEB: tuple[str, ...] = (
    "São Paulo",
    "Rio de Janeiro",
    "Minas Gerais",
    "Paraná",
    "Rio Grande do Sul",
    "Bahia",
    "Santa Catarina",
    "Goiás",
    "Pernambuco",
    "Ceará",
    "Espírito Santo",
    "Distrito Federal",
    "Pará",
    "Mato Grosso",
    "Maranhão",
)
_TERMOS_BUSCA_WEB = "carros batidos sinistrados salvados seguradora à venda"
_DOMINIOS_IGNORAR_BUSCA_WEB = (
    "olx.com.br",
    "mercadolivre",
    "webmotors",
    "icarros",
    "youtube.com",
    "facebook.com",
    "instagram.com",
    "wikipedia.org",
    "reclameaqui",
)


def coletar_busca_web_brasil(
    *,
    max_ufs: int = 9,
    max_resultados: int = 8,
    pausa_seg: float = 3.0,
) -> list[dict[str, Any]]:
    """
    Busca web nacional (DuckDuckGo) por lojas/anúncios de carros batidos em todo o Brasil.
    Rotaciona as UFs por hora para cobrir o país ao longo do dia. Nunca lança exceção.
    """
    from datetime import datetime, timezone

    from core.ddg_lite import buscar as ddg_buscar

    hora = datetime.now(timezone.utc).hour
    total = len(_UFS_BUSCA_WEB)
    inicio = (hora * max(1, max_ufs)) % total
    ufs = [_UFS_BUSCA_WEB[(inicio + i) % total] for i in range(min(max_ufs, total))]

    anuncios: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for uf in ufs:
        query = f"{_TERMOS_BUSCA_WEB} {uf}"
        try:
            resultados = ddg_buscar(query, max_resultados=max_resultados, contexto="carros_batidos")
        except Exception as exc:
            logger.warning("Busca web batidos [%s] falhou: %s", uf, exc)
            resultados = []
        for res in resultados:
            url = str(res.get("url") or "").strip()
            if not url:
                continue
            low = url.lower()
            if any(d in low for d in _DOMINIOS_IGNORAR_BUSCA_WEB):
                continue
            dominio = urlparse(url).netloc.replace("www.", "")
            if not dominio or dominio in vistos:
                continue
            vistos.add(dominio)
            titulo = re.sub(r"\s+", " ", str(res.get("titulo") or dominio)).strip()
            snippet = str(res.get("snippet") or "")
            preco = parse_preco_brl(f"{titulo} {snippet}")
            ano = _extrair_ano_titulo(f"{titulo} {snippet}")
            anuncios.append(
                {
                    "hash": _hash_anuncio("busca_web", dominio),
                    "loja_id": "busca_web",
                    "loja_nome": f"Busca web — {dominio}",
                    "id_externo": dominio,
                    "titulo": titulo[:120],
                    "marca": "",
                    "ano": ano,
                    "preco": preco or 0.0,
                    "url": url,
                    "condicao": "batido/sinistrado",
                    "uf_busca": uf,
                    "snippet": snippet[:200],
                }
            )
        if pausa_seg > 0:
            time.sleep(pausa_seg)

    logger.info("Busca web batidos: %s domínio(s) em %s UF(s)", len(anuncios), len(ufs))
    return anuncios


def coletar_fonte(fonte: dict[str, Any]) -> list[dict[str, Any]]:
    tipo = str(fonte.get("tipo") or fonte.get("id") or "html").lower()
    if fonte.get("id") == "lucineia" or tipo == "lucineia":
        return coletar_lucineia(fonte)
    if fonte.get("id") == "leopardo" or tipo == "leopardo" or tipo == "ajax":
        return coletar_leopardo(fonte)
    if fonte.get("id") == "motorjan" or tipo == "motorjan":
        return coletar_motorjan(fonte)
    if fonte.get("id") == "velozes" or tipo == "velozes":
        return coletar_velozes(fonte)
    if tipo == "html":
        return coletar_lucineia(fonte)
    logger.warning("Fonte desconhecida: %s", fonte.get("id"))
    return []
