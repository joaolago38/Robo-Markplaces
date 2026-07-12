"""
integracoes/leilao/sodre_leiloes.py
Coleta direta Sodré Santoro (padrão Sumaré) + fallback DDG.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from integracoes.leilao.coletores_base import (
    coletar_via_ddg_site,
    criar_sessao,
    hash_lote,
    montar_resultado_varredura,
    normalizar,
    parse_preco_brl,
    request_com_retry,
)

logger = logging.getLogger("sodre_leiloes")

BASE_URL = "https://www.sodresantoro.com.br"
DOMINIO = "sodresantoro.com.br"

_RE_LOTE_LINK = re.compile(
    r'href="((?:https://www\.sodresantoro\.com\.br)?/(?:lote|lotes|veiculo|veiculos)/[^"]+)"',
    re.IGNORECASE,
)
_RE_TITLE = re.compile(r"<h[1-4][^>]*>(.*?)</h[1-4]>", re.DOTALL | re.IGNORECASE)
_RE_CARD = re.compile(
    r'<article[^>]*>(.*?)</article>|<div[^>]*class="[^"]*lote[^"]*"[^>]*>(.*?)</div>\s*</div>',
    re.DOTALL | re.IGNORECASE,
)


def parse_lotes_html(html: str) -> list[dict[str, Any]]:
    lotes: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for m in _RE_LOTE_LINK.finditer(html or ""):
        path = m.group(1)
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        if url in vistos:
            continue
        vistos.add(url)
        start = max(0, m.start() - 400)
        frag = html[start : m.end() + 400]
        titulo_m = _RE_TITLE.search(frag)
        titulo = (
            re.sub(r"<[^>]+>", " ", titulo_m.group(1)).strip()
            if titulo_m
            else url.rstrip("/").split("/")[-1].replace("-", " ")
        )
        titulo = re.sub(r"\s+", " ", titulo)
        lance = parse_preco_brl(frag)
        lotes.append(
            {
                "hash": hash_lote(url),
                "titulo": titulo,
                "url": url,
                "lance_brl": lance,
                "lance_lista_brl": lance,
                "tem_documento": "documento" in normalizar(frag),
                "comitente": "Sodré Santoro",
                "tipo_comitente": "leiloeiro",
                "fonte": "html",
            }
        )
    if not lotes:
        for match in _RE_CARD.finditer(html or ""):
            frag = match.group(1) or match.group(2) or ""
            titulo_m = _RE_TITLE.search(frag)
            if not titulo_m:
                continue
            titulo = re.sub(r"<[^>]+>", " ", titulo_m.group(1)).strip()
            url_m = re.search(r'href="([^"]+)"', frag)
            url = url_m.group(1) if url_m else ""
            if url and not url.startswith("http"):
                url = f"{BASE_URL}{url}"
            lance = parse_preco_brl(frag)
            lotes.append(
                {
                    "hash": hash_lote(url or titulo),
                    "titulo": titulo,
                    "url": url,
                    "lance_brl": lance,
                    "lance_lista_brl": lance,
                    "tem_documento": "documento" in normalizar(frag),
                    "comitente": "Sodré Santoro",
                    "tipo_comitente": "leiloeiro",
                    "fonte": "html",
                }
            )
    return lotes


def listar_leiloes_home(session=None) -> list[dict[str, Any]]:
    sess = session or criar_sessao()
    urls = [
        f"{BASE_URL}/veiculos",
        f"{BASE_URL}/leiloes",
        BASE_URL,
    ]
    for url in urls:
        r = request_com_retry(sess, "GET", url, contexto="home", logger_nome="sodre_leiloes")
        if r is None or r.status_code != 200:
            continue
        lotes = parse_lotes_html(r.text)
        if lotes:
            return [
                {
                    "leilao_id": "veiculos",
                    "url": url,
                    "comitente": "Sodré Santoro",
                    "fonte": "home",
                    "_lotes_prefetch": lotes,
                }
            ]
    return [
        {
            "leilao_id": "veiculos",
            "url": f"{BASE_URL}/veiculos",
            "comitente": "Sodré Santoro",
            "fonte": "home",
        }
    ]


def varredura_sodre(
    config: dict[str, Any] | None = None,
    *,
    usar_ddg_fallback: bool = True,
) -> dict[str, Any]:
    config = config or {}
    if not config.get("ativo", True):
        return montar_resultado_varredura(
            fonte="sodre", leiloes=[], lotes=[], modo_coleta="desativado"
        )
    lance_min = float(config.get("lance_minimo_brl") or 500)
    exigir_doc = bool(config.get("exigir_documento", False))
    sess = criar_sessao()
    leiloes = listar_leiloes_home(sess)
    lotes: list[dict[str, Any]] = []
    modo = "direto"
    ok = 0
    falha = 0

    for leilao in leiloes:
        pref = leilao.pop("_lotes_prefetch", None)
        if pref:
            lotes.extend(pref)
            ok += 1
            continue
        r = request_com_retry(
            sess,
            "GET",
            str(leilao.get("url") or BASE_URL),
            contexto="listagem",
            logger_nome="sodre_leiloes",
        )
        if r is None or r.status_code != 200:
            falha += 1
            continue
        extraidos = parse_lotes_html(r.text)
        if extraidos:
            lotes.extend(extraidos)
            ok += 1
        else:
            falha += 1

    if not lotes and usar_ddg_fallback:
        modo = "ddg"
        lotes = coletar_via_ddg_site(
            DOMINIO,
            queries=[
                f"site:{DOMINIO} leilão veículo",
                f"site:{DOMINIO}/lote carro",
            ],
            contexto="sodre_leiloes",
        )
        for lote in lotes:
            lote.setdefault("comitente", "Sodré Santoro")
            lote.setdefault("tipo_comitente", "leiloeiro")
        ok = 1 if lotes else 0

    logger.info("Sodré: %s lotes brutos modo=%s", len(lotes), modo)
    return montar_resultado_varredura(
        fonte="sodre",
        leiloes=leiloes or [{"leilao_id": "ddg", "fonte": "ddg"}],
        lotes=lotes,
        leiloes_ok=ok,
        leiloes_falha=falha,
        modo_coleta=modo,
        lance_min=lance_min,
        exigir_documento=exigir_doc,
    )
