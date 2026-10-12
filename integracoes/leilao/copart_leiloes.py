"""
integracoes/leilao/copart_leiloes.py
Coleta direta Copart Brasil (padrão Sumaré) + fallback DDG.
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

logger = logging.getLogger("copart_leiloes")

BASE_URL = "https://www.copart.com.br"
DOMINIO = "copart.com.br"

_RE_LOT_LINK = re.compile(
    r'href="((?:https://www\.copart\.com\.br)?/lot/\d+-[^"]+)"',
    re.IGNORECASE,
)
_RE_CARD = re.compile(
    r'<div[^>]*class="[^"]*lot[^"]*"[^>]*>(.*?)</div>\s*</div>',
    re.DOTALL | re.IGNORECASE,
)
_RE_TITLE = re.compile(r"<h[1-4][^>]*>(.*?)</h[1-4]>", re.DOTALL | re.IGNORECASE)
_RE_LOT_NUM = re.compile(r"/lot/(\d+)", re.IGNORECASE)


def parse_lotes_html(html: str) -> list[dict[str, Any]]:
    """Extrai lotes de HTML estático / fixture."""
    lotes: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for m in _RE_LOT_LINK.finditer(html or ""):
        path = m.group(1)
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        if url in vistos:
            continue
        vistos.add(url)
        num_m = _RE_LOT_NUM.search(url)
        numero = num_m.group(1) if num_m else ""
        # contexto próximo para título/preço
        start = max(0, m.start() - 400)
        frag = html[start : m.end() + 400]
        titulo_m = _RE_TITLE.search(frag)
        titulo = re.sub(r"<[^>]+>", " ", titulo_m.group(1)).strip() if titulo_m else f"Lote Copart {numero}"
        titulo = re.sub(r"\s+", " ", titulo)
        lance = parse_preco_brl(frag)
        blob = normalizar(frag)
        lotes.append(
            {
                "hash": hash_lote(url),
                "lote_uuid": numero,
                "numero_lote": numero,
                "titulo": titulo,
                "url": url,
                "lance_brl": lance,
                "lance_lista_brl": lance,
                "tem_documento": "documento" in blob or "regular" in blob,
                "comitente": "Copart",
                "tipo_comitente": "leiloeiro",
                "fonte": "html",
            }
        )
    # Cards sem link absoluto (fixture)
    if not lotes:
        for frag in _RE_CARD.findall(html or ""):
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
                    "comitente": "Copart",
                    "tipo_comitente": "leiloeiro",
                    "fonte": "html",
                }
            )
    return lotes


def listar_leiloes_home(session=None) -> list[dict[str, Any]]:
    sess = session or criar_sessao()
    r = request_com_retry(
        sess, "GET", f"{BASE_URL}/", contexto="home", logger_nome="copart_leiloes"
    )
    if r is None or r.status_code != 200:
        return []
    # Copart costuma ser SPA/Incapsula — se houver lotes no HTML, trata como 1 leilão virtual
    lotes = parse_lotes_html(r.text)
    if not lotes:
        return [{"leilao_id": "home", "url": f"{BASE_URL}/", "comitente": "Copart", "fonte": "home"}]
    return [
        {
            "leilao_id": "inventario",
            "url": f"{BASE_URL}/lotSearchResults",
            "comitente": "Copart",
            "fonte": "home",
            "_lotes_prefetch": lotes,
        }
    ]


def varredura_copart(
    config: dict[str, Any] | None = None,
    *,
    usar_ddg_fallback: bool = True,
) -> dict[str, Any]:
    """Varre inventário Copart (HTML direto ou DDG)."""
    config = config or {}
    if not config.get("ativo", True):
        return montar_resultado_varredura(
            fonte="copart",
            leiloes=[],
            lotes=[],
            modo_coleta="desativado",
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
        url = str(leilao.get("url") or BASE_URL)
        r = request_com_retry(sess, "GET", url, contexto="listagem", logger_nome="copart_leiloes")
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
                f"site:{DOMINIO}/lot veículo leilão",
                f"site:{DOMINIO} lot car auction",
            ],
            contexto="copart_leiloes",
        )
        for lote in lotes:
            lote.setdefault("comitente", "Copart")
            lote.setdefault("tipo_comitente", "leiloeiro")
        ok = 1 if lotes else 0

    logger.info("Copart: %s lotes brutos modo=%s", len(lotes), modo)
    return montar_resultado_varredura(
        fonte="copart",
        leiloes=leiloes or [{"leilao_id": "ddg", "fonte": "ddg"}],
        lotes=lotes,
        leiloes_ok=ok,
        leiloes_falha=falha,
        modo_coleta=modo,
        lance_min=lance_min,
        exigir_documento=exigir_doc,
    )
