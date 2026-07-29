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
from urllib.parse import parse_qs, quote_plus, unquote, urlparse, urlunparse

from core.config import ALIBABA_EXIGIR_MOQ_PARA_OPORTUNIDADE
from core.http_client import request

logger = logging.getLogger("alibaba_busca")

_ALIBABA_SEARCH = "https://www.alibaba.com/trade/search"
_DDG_HTML = "https://html.duckduckgo.com/html/"
# UA de browser real — o bot string antigo dispara captcha/punish com frequência
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_DOMINIOS_ALIBABA = ("alibaba.com", "alibaba.cn")


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def montar_termo_busca(produto: dict[str, Any]) -> str:
    from core.config import ALIBABA_PREFERIR_TERMO_PT

    chaves = ("termo_busca", "termo_busca_pt", "nome", "descricao")
    if ALIBABA_PREFERIR_TERMO_PT:
        chaves = ("termo_busca_pt", "termo_busca", "nome", "descricao")
    for chave in chaves:
        valor = str(produto.get(chave) or "").strip()
        if valor:
            return valor
    partes = [str(produto.get(k) or "").strip() for k in ("categoria", "material")]
    return " ".join(p for p in partes if p)


def termos_busca_produto(produto: dict[str, Any]) -> list[str]:
    """Termo principal + secundário (EN/PT) para ampliar cobertura."""
    from core.config import ALIBABA_BUSCAR_TERMO_SECUNDARIO, ALIBABA_PREFERIR_TERMO_PT

    principal = montar_termo_busca(produto)
    termos: list[str] = []
    if principal:
        termos.append(principal)
    if not ALIBABA_BUSCAR_TERMO_SECUNDARIO:
        return termos
    secundario_chave = "termo_busca" if ALIBABA_PREFERIR_TERMO_PT else "termo_busca_pt"
    secundario = str(produto.get(secundario_chave) or "").strip()
    if secundario and _normalizar(secundario) != _normalizar(principal):
        termos.append(secundario)
    return termos


def _hash_url(url: str) -> str:
    return hashlib.sha256(normalizar_url_alibaba(url).encode()).hexdigest()[:16]


def normalizar_url_alibaba(url: str) -> str:
    """
    Corrige URLs do Alibaba extraídas com slug/ID colados (ex.: ...1kg1601242225300.html → ...1kg_1601242225300.html).
    """
    bruto = unescape((url or "").strip())
    if not bruto:
        return ""
    if bruto.startswith("//"):
        bruto = "https:" + bruto
    elif not bruto.startswith("http"):
        bruto = "https://" + bruto.lstrip("/")

    parsed = urlparse(bruto)
    host = (parsed.netloc or "").lower()
    if host == "alibaba.com":
        parsed = parsed._replace(netloc="www.alibaba.com")
        host = "www.alibaba.com"

    path = parsed.path or ""
    m = re.search(r"(/product-detail/)(.+?)(\.html?)$", path, re.IGNORECASE)
    if m:
        prefix, slug, ext = m.groups()
        slug_corrigido = re.sub(r"([a-zA-Z0-9])(\d{10,})$", r"\1_\2", slug)
        if slug_corrigido != slug:
            path = f"{prefix}{slug_corrigido}{ext}"
            parsed = parsed._replace(path=path)

    # Remove query/fragment de tracking — evita links quebrados no Telegram
    parsed = parsed._replace(query="", fragment="")
    return urlunparse(parsed)


def montar_url_busca_alibaba(termo: str) -> str:
    termo_limpo = (termo or "").strip()
    if not termo_limpo:
        return _ALIBABA_SEARCH
    return f"{_ALIBABA_SEARCH}?fsb=y&IndexArea=product_en&SearchText={quote_plus(termo_limpo)}"


def _aplicar_url_item(item: dict[str, Any]) -> dict[str, Any]:
    url = normalizar_url_alibaba(str(item.get("url") or ""))
    if url:
        item["url"] = url
        item["url_busca"] = montar_url_busca_alibaba(
            str(item.get("termo_busca") or item.get("titulo") or "")
        )
    return item


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
            bruto = m.group(1).strip()
            # US: 1,234.56 | EU/BR decimal: 0,28 | plain: 0.28
            if "," in bruto and "." in bruto:
                bruto = bruto.replace(",", "")
            elif "," in bruto:
                bruto = bruto.replace(",", ".")
            try:
                valor = float(bruto)
            except ValueError:
                continue
            if valor > 0:
                return valor
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


def _limpar_nome_distribuidor(nome: str) -> str:
    nome = re.sub(r"\s+", " ", unescape(nome or "")).strip(" -|,")
    return nome[:80]


def _distribuidor_da_url(url: str) -> str | None:
    host = (urlparse(url).netloc or "").lower()
    m = re.match(r"^([a-z0-9-]+)\.(?:en\.)?alibaba\.com$", host)
    if not m:
        return None
    slug = m.group(1)
    if slug in {"www", "m", "us", "sale", "www2"}:
        return None
    return _limpar_nome_distribuidor(slug.replace("-", " ").title())


def _extrair_distribuidor(texto: str, *, url: str = "") -> str | None:
    da_url = _distribuidor_da_url(url)
    if da_url:
        return da_url
    blob = unescape(texto or "")
    for padrao in (
        r'(?:company|supplier|store|seller|manufacturer)\s*name["\s:=]+([^"<\n|]{3,80})',
        r"(?:company|supplier|store|seller|manufacturer)[:\s]+([^<\n|]{3,80})",
        r"\bby\s+([A-Z][A-Za-z0-9 &.'\-]{2,60}(?:Co\.|Ltd\.|Limited|Inc\.|Company|Factory|Trading))",
        r"\b([A-Z][A-Za-z0-9 &.'\-]{2,60}(?:Co\.|Ltd\.|Limited|Inc\.|Company|Factory|Trading))\b",
    ):
        m = re.search(padrao, blob, re.IGNORECASE)
        if m:
            nome = _limpar_nome_distribuidor(m.group(1))
            if len(nome) >= 3:
                return nome
    return None


def _enriquecer_distribuidor(item: dict[str, Any]) -> dict[str, Any]:
    existente = str(item.get("distribuidor") or item.get("fornecedor") or "").strip()
    if existente:
        item["distribuidor"] = _limpar_nome_distribuidor(existente)
        return item
    blob = f"{item.get('titulo', '')} {item.get('snippet', '')}"
    nome = _extrair_distribuidor(blob, url=str(item.get("url") or ""))
    if nome:
        item["distribuidor"] = nome
    return item


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
            resultados.append(
                _aplicar_url_item({"titulo": titulo, "url": url, "snippet": snippet})
            )
    return resultados


def buscar_duckduckgo(query: str, *, max_resultados: int = 10) -> list[dict[str, str]]:
    from core.ddg_lite import buscar as ddg_buscar

    return ddg_buscar(query, max_resultados=max_resultados, contexto="alibaba")


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
        achados.append(_aplicar_url_item({"url": url, "titulo": "", "snippet": ""}))
    for m in re.finditer(
        r'data-title="([^"]+)"[^>]*data-href="([^"]+)"',
        html,
        re.IGNORECASE,
    ):
        achados.append(
            _aplicar_url_item({"titulo": unescape(m.group(1)), "url": unescape(m.group(2)), "snippet": ""})
        )
    return achados


def _itens_da_pagina_html(html: str, termo: str, vistos: set[str]) -> list[dict[str, Any]]:
    """Extrai anúncios de uma página de busca; atualiza `vistos` com URLs já vistas."""
    itens: list[dict[str, Any]] = []
    for raw in _extrair_links_html(html):
        link = raw.get("url", "")
        if not link or link in vistos:
            continue
        vistos.add(link)
        pos = html.find(link)
        blob = f"{raw.get('titulo', '')} {html[max(0, pos - 200) : pos + 400] if pos >= 0 else ''}"
        item = _aplicar_url_item(
            {
                "url": link,
                "titulo": raw.get("titulo") or termo,
                "snippet": raw.get("snippet") or "",
                "preco_usd": _extrair_preco_usd(blob),
                "moq": _extrair_moq(blob),
                "fonte": "alibaba_search",
                "termo_busca": termo,
            }
        )
        itens.append(_enriquecer_distribuidor(item))

    trecho_termo = termo[:20] if termo else ""
    if trecho_termo:
        for m in re.finditer(re.escape(trecho_termo), html, re.IGNORECASE):
            trecho = html[m.start() : m.start() + 800]
            for link_m in re.finditer(r'href="(https?://[^"]*alibaba\.com[^"]+)"', trecho):
                link = unescape(link_m.group(1))
                if link in vistos or not _url_e_produto_alibaba(link):
                    continue
                vistos.add(link)
                item = _aplicar_url_item(
                    {
                        "url": link,
                        "titulo": termo,
                        "snippet": re.sub(r"<[^>]+>", " ", trecho)[:300],
                        "preco_usd": _extrair_preco_usd(trecho),
                        "moq": _extrair_moq(trecho),
                        "fonte": "alibaba_search",
                        "termo_busca": termo,
                    }
                )
                itens.append(_enriquecer_distribuidor(item))
    return itens


def detectar_bloqueio_html_alibaba(html: str) -> str | None:
    """
    Detecta página anti-bot (captcha/punish) disfarçada de HTTP 200.
    Retorna motivo curto ou None se o HTML parecer listagem normal.
    """
    if not html:
        return "html_vazio"
    low = html.lower()
    tem_produto = ("product-detail" in low) or ("/offer/" in low) or ("p-detail" in low)
    if tem_produto:
        return None
    if len(html) < 800:
        return "html_muito_curto"
    sinais: list[str] = []
    for chave in ("captcha", "punish", "slideverify", "nc_wrapper", "baxia-dialog", "deny"):
        if chave in low:
            sinais.append(chave)
    # Página de challenge Alibaba costuma ser SPA curta sem ofertas
    if sinais:
        return "anti_bot:" + "+".join(sinais[:4])
    if "trade/search" in low and "searchtext" not in low.replace(" ", ""):
        # shell sem resultados embutidos
        if "flexible.js" in low or "aplus-xplug" in low:
            return "anti_bot:shell_sem_ofertas"
    return None


def _headers_busca() -> dict[str, str]:
    return {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
        "Cache-Control": "no-cache",
    }


def buscar_alibaba_direto_detalhado(
    termo: str,
    *,
    max_resultados: int | None = None,
    paginas: int | None = None,
) -> dict[str, Any]:
    """
    GET na busca pública do Alibaba com metadados de coleta.
    Nunca lança: retorna itens + flags de bloqueio anti-bot.
    """
    from core.config import ALIBABA_BUSCA_MAX_RESULTADOS, ALIBABA_BUSCA_PAGINAS

    vazio: dict[str, Any] = {
        "itens": [],
        "bloqueado": False,
        "motivo": None,
        "paginas_ok": 0,
        "status_http": None,
    }
    if not termo.strip():
        return {**vazio, "motivo": "termo_vazio"}
    if max_resultados is None:
        max_resultados = ALIBABA_BUSCA_MAX_RESULTADOS
    if paginas is None:
        paginas = max(1, ALIBABA_BUSCA_PAGINAS)

    vistos: set[str] = set()
    itens: list[dict[str, Any]] = []
    headers = _headers_busca()
    status_http: int | None = None
    paginas_ok = 0
    motivo_bloqueio: str | None = None

    try:
        for pagina in range(1, paginas + 1):
            if len(itens) >= max_resultados:
                break
            url = (
                f"{_ALIBABA_SEARCH}?fsb=y&IndexArea=product_en"
                f"&SearchText={quote_plus(termo)}&page={pagina}"
            )
            r = request("GET", url, headers=headers, timeout=25)
            status_http = int(r.status_code)
            if r.status_code >= 400:
                logger.warning(
                    "Alibaba search HTTP %s termo=%r page=%s",
                    r.status_code,
                    termo[:60],
                    pagina,
                )
                if not itens:
                    motivo_bloqueio = f"http_{r.status_code}"
                break
            html = r.text or ""
            bloqueio = detectar_bloqueio_html_alibaba(html)
            if bloqueio and not itens:
                motivo_bloqueio = bloqueio
                logger.warning(
                    "Alibaba coleta bloqueada motivo=%s termo=%r page=%s",
                    bloqueio,
                    termo[:60],
                    pagina,
                )
                break
            novos = _itens_da_pagina_html(html, termo, vistos)
            if not novos:
                if not itens and not motivo_bloqueio:
                    # HTTP 200 sem produtos e sem sinal clássico — ainda pode ser shell anti-bot
                    if detectar_bloqueio_html_alibaba(html) or len(html) < 5000:
                        motivo_bloqueio = detectar_bloqueio_html_alibaba(html) or "sem_ofertas_na_pagina"
                break
            paginas_ok += 1
            itens.extend(novos)
            if pagina < paginas and len(itens) < max_resultados:
                time.sleep(0.4)

        bloqueado = bool(motivo_bloqueio) and not itens
        return {
            "itens": itens[:max_resultados],
            "bloqueado": bloqueado,
            "motivo": motivo_bloqueio if bloqueado else None,
            "paginas_ok": paginas_ok,
            "status_http": status_http,
        }
    except Exception as exc:
        logger.error("Alibaba direto falhou: %s", exc)
        return {
            "itens": itens[:max_resultados],
            "bloqueado": not itens,
            "motivo": f"excecao:{type(exc).__name__}" if not itens else None,
            "paginas_ok": paginas_ok,
            "status_http": status_http,
        }


def buscar_alibaba_direto(
    termo: str,
    *,
    max_resultados: int | None = None,
    paginas: int | None = None,
) -> list[dict[str, Any]]:
    """GET na página de busca pública do Alibaba (com paginação). Nunca lança exceção."""
    return buscar_alibaba_direto_detalhado(
        termo, max_resultados=max_resultados, paginas=paginas
    )["itens"]


def _termo_relevante(termo: str, blob: str) -> bool:
    termo_n = _normalizar(termo)
    if not termo_n:
        return True
    palavras = [p for p in termo_n.split() if len(p) >= 3]
    if not palavras:
        palavras = termo_n.split()
    return sum(1 for p in palavras if p in blob) >= max(1, len(palavras) // 2)


def _relevante(produto_cfg: dict[str, Any], item: dict[str, Any]) -> bool:
    blob = _normalizar(
        f"{item.get('titulo', '')} {item.get('snippet', '')} {item.get('url', '')}"
    )
    termos = termos_busca_produto(produto_cfg)
    if not termos:
        return True
    return any(_termo_relevante(t, blob) for t in termos)


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

    # moq_max só filtra quando MOQ foi parseado; ausente não elimina (salvo flag)
    if ALIBABA_EXIGIR_MOQ_PARA_OPORTUNIDADE and moq is None:
        return False

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


def buscar_oportunidades_detalhado(
    produto: dict[str, Any],
    *,
    pausa_seg: float = 1.0,
) -> dict[str, Any]:
    """
    Busca no Alibaba (direto + site:alibaba.com via DDG) com meta de coleta.
    `bloqueado=True` quando a busca direta foi barrada por anti-bot e não há ofertas.
    """
    from core.config import (
        ALIBABA_BUSCA_MAX_RESULTADOS,
        ALIBABA_BUSCA_PAGINAS,
        DDG_ALIBABA_MIN_DIRETO_PARA_PULAR,
        DDG_ALIBABA_SKIP_SE_DIRETO,
    )

    coleta: dict[str, Any] = {
        "bloqueado": False,
        "motivo": None,
        "direto": 0,
        "ddg": 0,
        "candidatos": 0,
        "status_http": None,
    }
    termos = termos_busca_produto(produto)
    if not termos:
        return {"oportunidades": [], "coleta": {**coleta, "motivo": "termo_vazio"}}
    termo_principal = termos[0]

    vistos: set[str] = set()
    candidatos: list[dict[str, Any]] = []
    motivos_bloqueio: list[str] = []
    direto_total = 0

    for i, termo in enumerate(termos):
        det = buscar_alibaba_direto_detalhado(
            termo,
            max_resultados=ALIBABA_BUSCA_MAX_RESULTADOS,
            paginas=ALIBABA_BUSCA_PAGINAS,
        )
        if det.get("status_http") is not None:
            coleta["status_http"] = det["status_http"]
        if det.get("bloqueado") and det.get("motivo"):
            motivos_bloqueio.append(str(det["motivo"]))
        for item in det.get("itens") or []:
            direto_total += 1
            h = _hash_url(item.get("url", ""))
            if h in vistos:
                continue
            vistos.add(h)
            item["hash"] = h
            candidatos.append(item)
        if i < len(termos) - 1 and pausa_seg > 0:
            time.sleep(pausa_seg)

    coleta["direto"] = direto_total

    if pausa_seg > 0:
        time.sleep(pausa_seg)

    pular_ddg = (
        DDG_ALIBABA_SKIP_SE_DIRETO
        and len(candidatos) >= DDG_ALIBABA_MIN_DIRETO_PARA_PULAR
    )
    ddg_total = 0
    if pular_ddg:
        logger.debug(
            "Alibaba: pulando DDG — %s itens da busca direta (mín=%s) termo=%r",
            len(candidatos),
            DDG_ALIBABA_MIN_DIRETO_PARA_PULAR,
            termo_principal[:60],
        )
    else:
        for termo in termos[:2]:
            query = f"site:alibaba.com wholesale {termo}"
            for raw in buscar_duckduckgo(query, max_resultados=12):
                if not _url_e_produto_alibaba(raw.get("url", "")):
                    continue
                h = _hash_url(raw["url"])
                if h in vistos:
                    continue
                vistos.add(h)
                ddg_total += 1
                blob = f"{raw.get('titulo', '')} {raw.get('snippet', '')}"
                item = _aplicar_url_item(
                    {
                        "url": raw["url"],
                        "titulo": raw.get("titulo") or termo,
                        "snippet": raw.get("snippet") or "",
                        "preco_usd": _extrair_preco_usd(blob),
                        "moq": _extrair_moq(blob),
                        "fonte": "duckduckgo",
                        "hash": h,
                        "termo_busca": termo,
                    }
                )
                candidatos.append(_enriquecer_distribuidor(item))
            if len(termos) > 1 and pausa_seg > 0:
                time.sleep(min(pausa_seg, 0.5))

    coleta["ddg"] = ddg_total
    coleta["candidatos"] = len(candidatos)

    oportunidades: list[dict[str, Any]] = []
    for item in candidatos:
        if not _relevante(produto, item):
            continue
        if not _e_oportunidade(produto, item):
            continue
        item["termo_busca"] = item.get("termo_busca") or termo_principal
        oportunidades.append(item)

    # Bloqueio só conta se não sobrou nenhuma oferta (direto nem DDG)
    if not oportunidades and not candidatos and motivos_bloqueio:
        coleta["bloqueado"] = True
        coleta["motivo"] = motivos_bloqueio[0]
        try:
            from core.datadog_metrics import incrementar

            incrementar("alibaba.coleta_bloqueada")
        except Exception:
            pass

    return {"oportunidades": oportunidades, "coleta": coleta}


def buscar_oportunidades(
    produto: dict[str, Any],
    *,
    pausa_seg: float = 1.0,
) -> list[dict[str, Any]]:
    """
    Busca no Alibaba (direto + site:alibaba.com via DDG).
    Retorna itens marcados como oportunidade. Nunca lança exceção.
    """
    return buscar_oportunidades_detalhado(produto, pausa_seg=pausa_seg)["oportunidades"]
