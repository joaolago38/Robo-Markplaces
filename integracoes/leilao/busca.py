"""
integracoes/leilao/busca.py
Busca de leilões por veículo em leiloeiros e portais DETRAN via web search.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
import unicodedata
from html import unescape
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from core.http_client import request
from integracoes.leilao.fontes import DETRAN_POR_ESTADO, LEILOEIROS_PRINCIPAIS

logger = logging.getLogger("leilao_busca")

_DDG_HTML = "https://html.duckduckgo.com/html/"
_USER_AGENT = (
    "Mozilla/5.0 (compatible; RoboMarkplaces-LeilaoBot/1.0; +https://github.com/joaolago38/Robo-Markplaces)"
)
_PALAVRAS_LEILAO = ("leilao", "leilão", "lote", "arremate", "edital", "veiculo", "veículo", "automotor")
_PERFIL_RECUPERADO_FURTO = "recuperado_furto_media_monta"
_TERMOS_PERFIL_BUSCA = ("recuperado", "furto", "média monta", "media monta")
_PALAVRAS_RECUPERADO = ("recuperado", "furto", "furtado", "roubado", "judicial", "detran")
_PALAVRAS_MEDIA_MONTA = ("media monta", "média monta", "medio", "médio", "avaria media", "avaria média")
_PALAVRAS_EXCLUIR_MONTA = ("grande monta", "perda total", "irrecuperavel", "irrecuperável", "sucata")
_MODELOS_MARCA_OPCIONAL = frozenset({"gol", "civic", "city", "fit", "fiorino", "furgao", "furgão"})


def montar_termo_busca(veiculo: dict[str, Any]) -> str:
    partes = [
        str(veiculo.get("marca") or "").strip(),
        str(veiculo.get("modelo") or "").strip(),
    ]
    ano_min = veiculo.get("ano_min")
    ano_max = veiculo.get("ano_max")
    if ano_min and ano_max and ano_min == ano_max:
        partes.append(str(ano_min))
    elif ano_min or ano_max:
        partes.append(f"{ano_min or ''}-{ano_max or ''}".strip("-"))
    for extra in veiculo.get("termos_extra") or []:
        if extra:
            partes.append(str(extra).strip())
    if veiculo.get("perfil") == _PERFIL_RECUPERADO_FURTO:
        partes.extend(_TERMOS_PERFIL_BUSCA)
    return " ".join(p for p in partes if p)


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def _sufixo_query_leilao(veiculo: dict[str, Any], *, tipo_fonte: str) -> str:
    if veiculo.get("perfil") == _PERFIL_RECUPERADO_FURTO:
        base = "leilão veículo recuperado furto média monta"
    else:
        base = "leilão veículo"
    if tipo_fonte == "detran":
        return f"{base} DETRAN"
    return base


def _bate_perfil_recuperado_furto(texto: str) -> bool:
    norm = _normalizar(texto)
    if any(x in norm for x in _PALAVRAS_EXCLUIR_MONTA):
        return False
    if not any(x in norm for x in _PALAVRAS_RECUPERADO):
        return False
    return any(x in norm for x in _PALAVRAS_MEDIA_MONTA)


def _extrair_resultados_ddg(html: str) -> list[dict[str, str]]:
    """Extrai título, URL e snippet do HTML do DuckDuckGo Lite."""
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
        titulo = re.sub(r"<[^>]+>", "", titulo_m.group(2))
        titulo = unescape(titulo).strip()
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
            snippet = re.sub(r"<[^>]+>", "", snippet_m.group(1))
            snippet = unescape(snippet).strip()
        if url.startswith("http"):
            resultados.append({"titulo": titulo, "url": url, "snippet": snippet})
    return resultados


def buscar_duckduckgo(query: str, *, max_resultados: int = 8) -> list[dict[str, str]]:
    """Busca no DuckDuckGo HTML (sem API key). Nunca lança exceção."""
    try:
        r = request(
            "POST",
            _DDG_HTML,
            data={"q": query, "kl": "br-pt"},
            headers={"User-Agent": _USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
        if r.status_code >= 400:
            logger.warning("DDG HTTP %s para query=%r", r.status_code, query[:80])
            return []
        return _extrair_resultados_ddg(r.text)[:max_resultados]
    except Exception as exc:
        logger.error("DDG busca falhou: %s", exc)
        return []


def _ano_no_intervalo(texto: str, veiculo: dict[str, Any]) -> bool:
    ano_min = int(veiculo.get("ano_min") or 0) or None
    ano_max = int(veiculo.get("ano_max") or 0) or None
    if not ano_min and not ano_max:
        return True
    anos = [int(a) for a in re.findall(r"\b(?:19|20)\d{2}\b", texto)]
    if not anos:
        return True
    for ano in anos:
        if ano_min and ano < ano_min:
            continue
        if ano_max and ano > ano_max:
            continue
        return True
    return False


def _parece_leilao(texto: str) -> bool:
    norm = _normalizar(texto)
    return any(p in norm for p in _PALAVRAS_LEILAO)


def _relevante_para_veiculo(resultado: dict[str, str], veiculo: dict[str, Any]) -> bool:
    blob = f"{resultado.get('titulo', '')} {resultado.get('snippet', '')} {resultado.get('url', '')}"
    norm = _normalizar(blob)
    marca = _normalizar(str(veiculo.get("marca") or ""))
    modelo = _normalizar(str(veiculo.get("modelo") or ""))
    if modelo and modelo not in norm:
        return False
    if marca and marca not in norm:
        if modelo not in _MODELOS_MARCA_OPCIONAL:
            return False
    if not _ano_no_intervalo(blob, veiculo):
        return False
    if not (_parece_leilao(blob) or _parece_leilao(resultado.get("url", ""))):
        return False
    if veiculo.get("perfil") == _PERFIL_RECUPERADO_FURTO:
        return _bate_perfil_recuperado_furto(blob)
    return True


def _hash_url(url: str) -> str:
    return hashlib.sha256((url or "").strip().encode()).hexdigest()[:16]


def _buscar_em_dominio(
    dominio: str,
    termo: str,
    *,
    tipo_fonte: str,
    fonte_id: str,
    fonte_nome: str,
    sufixo_query: str = "leilão veículo",
) -> list[dict[str, Any]]:
    query = f'site:{dominio} {sufixo_query} {termo}'
    achados: list[dict[str, Any]] = []
    for item in buscar_duckduckgo(query, max_resultados=6):
        if dominio not in item.get("url", ""):
            continue
        achados.append(
            {
                "url": item["url"],
                "titulo": item.get("titulo") or item["url"],
                "snippet": item.get("snippet") or "",
                "fonte_tipo": tipo_fonte,
                "fonte_id": fonte_id,
                "fonte_nome": fonte_nome,
                "dominio": dominio,
                "hash": _hash_url(item["url"]),
            }
        )
    return achados


def buscar_veiculo_em_fontes(
    veiculo: dict[str, Any],
    *,
    incluir_leiloeiros: bool = True,
    incluir_detran: bool = True,
    pausa_entre_fontes_seg: float = 0.8,
) -> list[dict[str, Any]]:
    """
    Varre leiloeiros principais e DETRAN de todos os estados.
    Retorna lista deduplicada por URL. Nunca lança exceção.
    """
    termo = montar_termo_busca(veiculo)
    if not termo.strip():
        return []

    vistos: set[str] = set()
    todos: list[dict[str, Any]] = []

    fontes: list[tuple[dict[str, str], str, str]] = []
    if incluir_leiloeiros:
        for f in LEILOEIROS_PRINCIPAIS:
            fontes.append((f, "leiloeiro", f.get("id", f["dominio"])))
    if incluir_detran:
        for f in DETRAN_POR_ESTADO:
            fontes.append((f, "detran", f.get("uf", f["dominio"])))

    for fonte, tipo, fid in fontes:
        dominio = fonte.get("dominio", "")
        nome = fonte.get("nome", dominio)
        if not dominio:
            continue
        sufixo = _sufixo_query_leilao(veiculo, tipo_fonte=tipo)
        try:
            lote = _buscar_em_dominio(
                dominio,
                termo,
                tipo_fonte=tipo,
                fonte_id=fid,
                fonte_nome=nome,
                sufixo_query=sufixo,
            )
            for item in lote:
                if not _relevante_para_veiculo(item, veiculo):
                    continue
                h = item["hash"]
                if h in vistos:
                    continue
                vistos.add(h)
                todos.append(item)
        except Exception as exc:
            logger.warning("Fonte %s (%s) falhou: %s", nome, dominio, exc)
        if pausa_entre_fontes_seg > 0:
            time.sleep(pausa_entre_fontes_seg)

    # Busca ampla (fallback)
    try:
        query_geral = f'{_sufixo_query_leilao(veiculo, tipo_fonte="web")} {termo} Brasil'
        for item in buscar_duckduckgo(query_geral, max_resultados=10):
            enriquecido = {
                "url": item["url"],
                "titulo": item.get("titulo") or item["url"],
                "snippet": item.get("snippet") or "",
                "fonte_tipo": "web",
                "fonte_id": "busca_geral",
                "fonte_nome": "Busca geral",
                "dominio": urlparse(item["url"]).netloc,
                "hash": _hash_url(item["url"]),
            }
            if not _relevante_para_veiculo(enriquecido, veiculo):
                continue
            if enriquecido["hash"] in vistos:
                continue
            vistos.add(enriquecido["hash"])
            todos.append(enriquecido)
    except Exception as exc:
        logger.warning("Busca geral falhou: %s", exc)

    return todos
