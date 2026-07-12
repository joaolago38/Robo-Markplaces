"""
integracoes/leilao/superbid_leiloes.py
Coleta direta Superbid (padrão Sumaré) + fallback DDG.
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

logger = logging.getLogger("superbid_leiloes")

BASE_URL = "https://www.superbid.net"
EXCHANGE_URL = "https://exchange.superbid.net"
DOMINIO = "superbid.net"

_RE_EVENTO = re.compile(
    r'href="((?:https://(?:www|exchange)\.superbid\.net)?/(?:evento|event|oferta|lote)[^"]+)"',
    re.IGNORECASE,
)
_RE_TITLE = re.compile(r"<h[1-4][^>]*>(.*?)</h[1-4]>", re.DOTALL | re.IGNORECASE)
_RE_CARD = re.compile(
    r'data-testid="[^"]*lot[^"]*"[^>]*>(.*?)</div>',
    re.DOTALL | re.IGNORECASE,
)


def parse_lotes_html(html: str) -> list[dict[str, Any]]:
    lotes: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for m in _RE_EVENTO.finditer(html or ""):
        path = m.group(1)
        url = path if path.startswith("http") else f"{EXCHANGE_URL}{path}"
        if url in vistos:
            continue
        vistos.add(url)
        start = max(0, m.start() - 350)
        frag = html[start : m.end() + 350]
        titulo_m = _RE_TITLE.search(frag)
        titulo = re.sub(r"<[^>]+>", " ", titulo_m.group(1)).strip() if titulo_m else url.rstrip("/").split("/")[-1]
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
                "comitente": "Superbid",
                "tipo_comitente": "leiloeiro",
                "fonte": "html",
            }
        )
    if not lotes:
        for frag in _RE_CARD.findall(html or ""):
            titulo_m = _RE_TITLE.search(frag) or re.search(r'title="([^"]+)"', frag)
            if not titulo_m:
                continue
            titulo = re.sub(r"<[^>]+>", " ", titulo_m.group(1)).strip()
            url_m = re.search(r'href="([^"]+)"', frag)
            url = url_m.group(1) if url_m else ""
            if url and not url.startswith("http"):
                url = f"{EXCHANGE_URL}{url}"
            lance = parse_preco_brl(frag)
            lotes.append(
                {
                    "hash": hash_lote(url or titulo),
                    "titulo": titulo,
                    "url": url,
                    "lance_brl": lance,
                    "lance_lista_brl": lance,
                    "tem_documento": "documento" in normalizar(frag),
                    "comitente": "Superbid",
                    "tipo_comitente": "leiloeiro",
                    "fonte": "html",
                }
            )
    return lotes


def listar_leiloes_home(session=None) -> list[dict[str, Any]]:
    sess = session or criar_sessao()
    urls = [
        f"{BASE_URL}/categorias/veiculos",
        f"{EXCHANGE_URL}/explorar",
        BASE_URL,
    ]
    for url in urls:
        r = request_com_retry(sess, "GET", url, contexto="home", logger_nome="superbid_leiloes")
        if r is None or r.status_code != 200:
            continue
        lotes = parse_lotes_html(r.text)
        if lotes:
            return [
                {
                    "leilao_id": "veiculos",
                    "url": url,
                    "comitente": "Superbid",
                    "fonte": "home",
                    "_lotes_prefetch": lotes,
                }
            ]
    return [{"leilao_id": "veiculos", "url": f"{BASE_URL}/categorias/veiculos", "comitente": "Superbid", "fonte": "home"}]


def varredura_superbid(
    config: dict[str, Any] | None = None,
    *,
    usar_ddg_fallback: bool = True,
) -> dict[str, Any]:
    config = config or {}
    if not config.get("ativo", True):
        return montar_resultado_varredura(
            fonte="superbid", leiloes=[], lotes=[], modo_coleta="desativado"
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
            logger_nome="superbid_leiloes",
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
                "site:exchange.superbid.net veículo lote",
            ],
            contexto="superbid_leiloes",
        )
        for lote in lotes:
            lote.setdefault("comitente", "Superbid")
            lote.setdefault("tipo_comitente", "leiloeiro")
        ok = 1 if lotes else 0

    logger.info("Superbid: %s lotes brutos modo=%s", len(lotes), modo)
    return montar_resultado_varredura(
        fonte="superbid",
        leiloes=leiloes or [{"leilao_id": "ddg", "fonte": "ddg"}],
        lotes=lotes,
        leiloes_ok=ok,
        leiloes_falha=falha,
        modo_coleta=modo,
        lance_min=lance_min,
        exigir_documento=exigir_doc,
    )
