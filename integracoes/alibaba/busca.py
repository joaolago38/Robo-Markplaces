"""
integracoes/alibaba/busca.py
Busca de produtos no Alibaba.com para oportunidades de importação.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import unicodedata
from html import unescape
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from core.http_client import request

logger = logging.getLogger("alibaba_busca")

_ALIBABA_SEARCH = "https://www.alibaba.com/trade/search"
_DDG_HTML = "https://html.duckduckgo.com/html/"
_USER_AGENT = (
    "Mozilla/5.0 (compatible; RoboMarkplaces-ImportBot/1.0; +https://github.com/joaolago38/Robo-Markplaces)"
)
_DOMINIOS_ALIBABA = ("alibaba.com", "alibaba.cn")


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def montar_termo_busca(produto: dict[str, Any]) -> str:
    for chave in ("termo_busca", "termo_busca_pt", "nome", "descricao"):
        valor = str(produto.get(chave) or "").strip()
        if valor:
            return valor
    partes = [str(produto.get(k) or "").strip() for k in ("categoria", "material")]
    return " ".join(p for p in partes if p)


def _hash_url(url: str) -> str:
    return hashlib.sha256((url or "").strip().encode()).hexdigest()[:16]


def _extrair_preco_usd(texto: str) -> float | None:
    if not texto:
        return None
    for padrao in (
        r"US\s*\$\s*([\d.,]+)",
        r"\$\s*([\d.,]+)",
        r"USD\s*([\d.,]+)",
    ):
        m = re.search(padrao, texto, re.IGNORECASE)
        if m:
            bruto = m.group(1).replace(",", "")
            try:
                return float(bruto)
            except ValueError:
                continue
    return None


def _extrair_moq(texto: str) -> int | None:
    if not texto:
        return None
    m = re.search(r"MOQ[:\s]*([\d.,]+)", texto, re.IGNORECASE)
    if not m:
        m = re.search(r"min(?:imum)?\s*order[:\s]*([\d.,]+)", texto, re.IGNORECASE)
    if not m:
        return None
    try:
        return int(float(m.group(1).replace(",", "")))
    except ValueError:
        return None


def _url_e_produto_alibaba(url: str) -> bool:
    u = (url or "").lower()
    if not any(d in u for d in _DOMINIOS_ALIBABA):
        return False
    return any(
        frag in u
        for frag in (
            "/product-detail/",
            "/offer/",
            "/p-detail/",
            "productgrouplist",
            "/trade/search",
        )
    )


def _extrair_resultados_ddg(html: str) -> list[dict[str, str]]:
    resultados: list[dict[str, str]] = []
    if not html:
        return resultados
    blocos = re.split(r'class="result\s', html)
    for bloco in blocos[1:]:
        titulo_m = re.search(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            bloco,
            re.DOTALL | re.IGNORECASE,
        )
        if not titulo_m:
            continue
        href_bruto = unescape(titulo_m.group(1))
        titulo = unescape(re.sub(r"<[^>]+>", "", titulo_m.group(2))).strip()
        url = href_bruto
        if "uddg=" in href_bruto:
            parsed = urlparse(href_bruto)
            qs = parse_qs(parsed.query)
            url = unquote((qs.get("uddg") or [href_bruto])[0])
        snippet_m = re.search(
            r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)>',
            bloco,
            re.DOTALL | re.IGNORECASE,
        )
        snippet = ""
        if snippet_m:
            snippet = unescape(re.sub(r"<[^>]+>", "", snippet_m.group(1))).strip()
        if url.startswith("http"):
            resultados.append({"titulo": titulo, "url": url, "snippet": snippet})
    return resultados


def buscar_duckduckgo(query: str, *, max_resultados: int = 10) -> list[dict[str, str]]:
    try:
        r = request(
            "POST",
            _DDG_HTML,
            data={"q": query, "kl": "br-pt"},
            headers={"User-Agent": _USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
        if r.status_code >= 400:
            return []
        return _extrair_resultados_ddg(r.text)[:max_resultados]
    except Exception as exc:
        logger.error("DDG Alibaba falhou: %s", exc)
        return []


def _parsear_json_embutido(html: str) -> list[dict[str, Any]]:
    """Tenta extrair listagens de scripts JSON embutidos na página de busca."""
    achados: list[dict[str, Any]] = []
    for bloco in re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE):
        if "product" not in bloco.lower() and "offer" not in bloco.lower():
            continue
        for candidato in re.findall(r"(\{[^{}]*\"title\"[^{}]*\})", bloco):
            try:
                obj = json.loads(candidato)
                if isinstance(obj, dict) and obj.get("title"):
                    achados.append(obj)
            except json.JSONDecodeError:
                continue
    return achados


def _extrair_links_html(html: str) -> list[dict[str, str]]:
    achados: list[dict[str, str]] = []
    for m in re.finditer(
        r'href="(https?://[^"]*alibaba\.com[^"]*(?:product-detail|offer|p-detail)[^"]*)"',
        html,
        re.IGNORECASE,
    ):
        url = unescape(m.group(1)).split("&")[0]
        achados.append({"url": url, "titulo": "", "snippet": ""})
    for m in re.finditer(
        r'data-title="([^"]+)"[^>]*data-href="([^"]+)"',
        html,
        re.IGNORECASE,
    ):
        achados.append({"titulo": unescape(m.group(1)), "url": unescape(m.group(2)), "snippet": ""})
    return achados


def buscar_alibaba_direto(termo: str, *, max_resultados: int = 15) -> list[dict[str, Any]]:
    """GET na página de busca pública do Alibaba. Nunca lança exceção."""
    if not termo.strip():
        return []
    url = f"{_ALIBABA_SEARCH}?fsb=y&IndexArea=product_en&SearchText={quote_plus(termo)}"
    try:
        r = request(
            "GET",
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
            },
            timeout=25,
        )
        if r.status_code >= 400:
            logger.warning("Alibaba search HTTP %s termo=%r", r.status_code, termo[:60])
            return []
        html = r.text or ""
        vistos: set[str] = set()
        itens: list[dict[str, Any]] = []

        for raw in _extrair_links_html(html):
            link = raw.get("url", "")
            if not link or link in vistos:
                continue
            vistos.add(link)
            blob = f"{raw.get('titulo', '')} {html[max(0, html.find(link) - 200):html.find(link) + 400]}"
            itens.append(
                {
                    "url": link,
                    "titulo": raw.get("titulo") or termo,
                    "snippet": raw.get("snippet") or "",
                    "preco_usd": _extrair_preco_usd(blob),
                    "moq": _extrair_moq(blob),
                    "fonte": "alibaba_search",
                }
            )

        # Contexto ao redor do termo no HTML (preços em listagens)
        for m in re.finditer(re.escape(termo[:20]), html, re.IGNORECASE):
            trecho = html[m.start() : m.start() + 800]
            for link_m in re.finditer(r'href="(https?://[^"]*alibaba\.com[^"]+)"', trecho):
                link = unescape(link_m.group(1))
                if link in vistos or not _url_e_produto_alibaba(link):
                    continue
                vistos.add(link)
                itens.append(
                    {
                        "url": link,
                        "titulo": termo,
                        "snippet": re.sub(r"<[^>]+>", " ", trecho)[:300],
                        "preco_usd": _extrair_preco_usd(trecho),
                        "moq": _extrair_moq(trecho),
                        "fonte": "alibaba_search",
                    }
                )

        return itens[:max_resultados]
    except Exception as exc:
        logger.error("Alibaba direto falhou: %s", exc)
        return []


def _relevante(produto_cfg: dict[str, Any], item: dict[str, Any]) -> bool:
    termo = _normalizar(montar_termo_busca(produto_cfg))
    blob = _normalizar(
        f"{item.get('titulo', '')} {item.get('snippet', '')} {item.get('url', '')}"
    )
    if not termo:
        return True
    palavras = [p for p in termo.split() if len(p) >= 3]
    if not palavras:
        palavras = termo.split()
    return sum(1 for p in palavras if p in blob) >= max(1, len(palavras) // 2)


def _e_oportunidade(produto_cfg: dict[str, Any], item: dict[str, Any]) -> bool:
    preco_max = produto_cfg.get("preco_max_usd")
    moq_max = produto_cfg.get("moq_max")
    preco = item.get("preco_usd")
    moq = item.get("moq")

    if preco_max is not None and preco is not None:
        try:
            if float(preco) > float(preco_max):
                return False
        except (TypeError, ValueError):
            pass

    if moq_max is not None and moq is not None:
        try:
            if int(moq) > int(moq_max):
                return False
        except (TypeError, ValueError):
            pass

    texto = f"{item.get('titulo', '')} {item.get('snippet', '')}".lower()
    sinais = ("trade assurance", "wholesale", "factory", "oem", "odm", "moq", "sample")
    if any(s in texto for s in sinais):
        return True
    # Sem preço/MOQ parseados mas link novo e relevante ainda pode ser oportunidade
    return preco is not None or moq is not None or "product-detail" in (item.get("url") or "")


def buscar_oportunidades(
    produto: dict[str, Any],
    *,
    pausa_seg: float = 1.0,
) -> list[dict[str, Any]]:
    """
    Busca no Alibaba (direto + site:alibaba.com via DDG).
    Retorna itens marcados como oportunidade. Nunca lança exceção.
    """
    termo = montar_termo_busca(produto)
    if not termo:
        return []

    vistos: set[str] = set()
    candidatos: list[dict[str, Any]] = []

    for item in buscar_alibaba_direto(termo):
        h = _hash_url(item.get("url", ""))
        if h in vistos:
            continue
        vistos.add(h)
        item["hash"] = h
        candidatos.append(item)

    if pausa_seg > 0:
        time.sleep(pausa_seg)

    query = f'site:alibaba.com wholesale {termo}'
    for raw in buscar_duckduckgo(query, max_resultados=12):
        if not _url_e_produto_alibaba(raw.get("url", "")):
            continue
        h = _hash_url(raw["url"])
        if h in vistos:
            continue
        vistos.add(h)
        blob = f"{raw.get('titulo', '')} {raw.get('snippet', '')}"
        candidatos.append(
            {
                "url": raw["url"],
                "titulo": raw.get("titulo") or termo,
                "snippet": raw.get("snippet") or "",
                "preco_usd": _extrair_preco_usd(blob),
                "moq": _extrair_moq(blob),
                "fonte": "duckduckgo",
                "hash": h,
            }
        )

    oportunidades: list[dict[str, Any]] = []
    for item in candidatos:
        if not _relevante(produto, item):
            continue
        if not _e_oportunidade(produto, item):
            continue
        item["termo_busca"] = termo
        oportunidades.append(item)

    return oportunidades
