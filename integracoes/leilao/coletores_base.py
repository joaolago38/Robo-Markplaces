"""
integracoes/leilao/coletores_base.py
Contrato compartilhado para coletores diretos de leilão (padrão Sumaré).
"""
from __future__ import annotations

import hashlib
import logging
import random
import re
import time
import unicodedata
from typing import Any, Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("leilao_coletores_base")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
}

_RE_PRECO = re.compile(r"R\$\s*([\d]{1,3}(?:\.\d{3})*,\d{2}|\d+(?:,\d{2})?)")
_RE_ANO_VEIC = re.compile(r"\b(\d{2}/\d{2}|\d{4})\b")

_PALAVRAS_SUCATA = (
    "sucata",
    "ferrosa",
    "reciclagem",
    "eletrodomestic",
    "informatica",
    "informática",
    "equipamentos de inform",
)
_PALAVRAS_NAO_VEICULO = (
    "poste",
    "tanque",
    "compressor",
    "rolo",
    "retro escav",
    "trator",
    "distribuidor",
    "resfriador",
    "bebedouro",
    "geladeira",
    "mesa escolar",
    "arado",
    "bomba agr",
    "pipa reboc",
    "imóvel",
    "imovel",
    "apartamento",
    "terreno",
)
_MARCAS_VEICULO = (
    "fiat",
    "ford",
    "chevrolet",
    "gm/",
    "vw",
    "volkswagen",
    "honda",
    "toyota",
    "renault",
    "peugeot",
    "citroen",
    "citroën",
    "hyundai",
    "nissan",
    "jeep",
    "mitsubishi",
    "bmw",
    "mercedes",
    "audi",
    "volvo",
    "kia",
    "ram",
    "iveco",
    "mbenz",
    "m.benz",
    "i/fiat",
    "i/ford",
    "i/vw",
    "i/mb",
    "marcopolo",
    "mpolo",
    "scania",
    "yamaha",
    "suzuki",
)


def normalizar(texto: str) -> str:
    txt = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in txt if not unicodedata.combining(c))


def parse_preco_brl(texto: str) -> float | None:
    if not texto:
        return None
    m = _RE_PRECO.search(str(texto).replace("\n", " "))
    if not m:
        return None
    bruto = m.group(1).replace(".", "").replace(",", ".")
    try:
        valor = float(bruto)
    except ValueError:
        return None
    return valor if valor > 0 else None


def hash_lote(*partes: str) -> str:
    bruto = "|".join(str(p or "") for p in partes)
    return hashlib.sha256(bruto.encode()).hexdigest()[:16]


def criar_sessao(
    *,
    retry_max: int = 3,
    headers: dict[str, str] | None = None,
) -> requests.Session:
    retry = Retry(
        total=retry_max,
        connect=retry_max,
        read=retry_max,
        status=2,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=4)
    sess = requests.Session()
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    sess.headers.update(headers or DEFAULT_HEADERS)
    return sess


def request_com_retry(
    sess: requests.Session,
    method: str,
    url: str,
    *,
    contexto: str,
    logger_nome: str = "leilao",
    timeout: float = 45.0,
    retry_max: int = 3,
    **kwargs: Any,
) -> requests.Response | None:
    """Request com backoff; falhas transitórias → warning."""
    log = logging.getLogger(logger_nome)
    ultimo_erro: Exception | None = None
    for tentativa in range(1, retry_max + 1):
        try:
            resp = sess.request(method.upper(), url, timeout=timeout, **kwargs)
            if resp.status_code == 429 and tentativa < retry_max:
                espera = min(30.0, 2.0 ** tentativa)
                log.warning(
                    "%s %s HTTP 429 — aguardando %.0fs (tentativa %s/%s)",
                    logger_nome,
                    contexto,
                    espera,
                    tentativa,
                    retry_max,
                )
                time.sleep(espera)
                continue
            return resp
        except requests.RequestException as exc:
            ultimo_erro = exc
            if tentativa < retry_max:
                espera = min(20.0, 1.5 * tentativa + random.uniform(0, 0.5))
                log.warning(
                    "%s %s rede (tentativa %s/%s): %s — retry em %.1fs",
                    logger_nome,
                    contexto,
                    tentativa,
                    retry_max,
                    exc,
                    espera,
                )
                time.sleep(espera)
            else:
                log.warning(
                    "%s %s indisponível após %s tentativas: %s",
                    logger_nome,
                    contexto,
                    retry_max,
                    exc,
                )
    if ultimo_erro:
        log.debug("%s %s falha final: %s", logger_nome, contexto, ultimo_erro)
    return None


def eh_veiculo(titulo: str, *, tem_documento: bool | None = None, exigir_documento: bool = False) -> bool:
    """Heurística de veículo (marca/ano), opcionalmente exigindo documento."""
    if exigir_documento and not tem_documento:
        return False
    norm = normalizar(titulo)
    if any(p in norm for p in _PALAVRAS_SUCATA):
        return False
    if "blindad" in norm:
        return False
    if any(p in norm for p in _PALAVRAS_NAO_VEICULO):
        return False
    if any(m in norm for m in _MARCAS_VEICULO):
        return True
    if "/" in (titulo or "") and _RE_ANO_VEIC.search(titulo.strip()):
        return True
    if re.search(r"\b(moto|motocicleta|nxr|cg\s*\d|biz)\b", norm):
        return True
    return bool(_RE_ANO_VEIC.search((titulo or "").strip()))


def diagnostico_vazio(*, ativo: bool, fonte: str) -> dict[str, Any]:
    return {
        "ativo": ativo,
        "fonte": fonte,
        "leiloes_ok": 0,
        "leiloes_falha": 0,
        "lotes_veiculo": 0,
        "lotes_com_documento": 0,
        "lotes_sem_documento": 0,
        "lotes_abaixo_lance_min": 0,
        "modo_coleta": None,
        "erro": None,
    }


def filtrar_lotes_padrao(
    lotes: list[dict[str, Any]],
    *,
    lance_min: float = 500.0,
    exigir_documento: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Aplica filtros Sumaré-like e devolve lotes + contadores."""
    stats = {
        "lotes_veiculo_brutos": 0,
        "lotes_com_documento": 0,
        "lotes_sem_documento": 0,
        "lotes_abaixo_lance_min": 0,
    }
    saida: list[dict[str, Any]] = []
    for lote in lotes:
        titulo = str(lote.get("titulo") or "")
        tem_doc = bool(lote.get("tem_documento"))
        if not eh_veiculo(titulo, tem_documento=tem_doc, exigir_documento=exigir_documento):
            continue
        stats["lotes_veiculo_brutos"] += 1
        if tem_doc:
            stats["lotes_com_documento"] += 1
        else:
            stats["lotes_sem_documento"] += 1
        lance = float(lote.get("lance_brl") or lote.get("lance_lista_brl") or 0)
        lote = {**lote, "lance_brl": lance or None}
        if lance and lance < lance_min:
            lote["abaixo_lance_minimo"] = True
            stats["lotes_abaixo_lance_min"] += 1
            continue
        lote["abaixo_lance_minimo"] = False
        saida.append(lote)
    saida.sort(key=lambda x: float(x.get("lance_brl") or 0), reverse=True)
    return saida, stats


def lote_para_achado(
    lote: dict[str, Any],
    *,
    fonte_tipo: str,
    fonte_id: str,
    fonte_nome: str,
    dominio: str,
    url_cadastro: str = "",
) -> dict[str, Any]:
    """Normaliza lote de coletor direto para o formato de achado do agente."""
    lance = float(lote.get("lance_brl") or lote.get("lance_lista_brl") or 0)
    valor_txt = (
        f"R$ {lance:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if lance else None
    )
    url = str(lote.get("url") or "")
    snippet = " ".join(
        p
        for p in (
            str(lote.get("comitente") or ""),
            str(lote.get("local_data") or ""),
            "DOCUMENTO" if lote.get("tem_documento") else "",
            str(lote.get("snippet") or ""),
        )
        if p
    )
    return {
        "url": url,
        "titulo": str(lote.get("titulo") or ""),
        "snippet": snippet,
        "fonte_tipo": fonte_tipo,
        "fonte_id": fonte_id,
        "fonte_nome": fonte_nome,
        "dominio": dominio,
        "hash": str(lote.get("hash") or hash_lote(url or str(lote.get("titulo") or ""))),
        "cidade": lote.get("cidade"),
        "uf": lote.get("uf"),
        "valor": valor_txt,
        "lance_brl": lance or None,
        "data_leilao": lote.get("data_fechamento") or lote.get("data_leilao"),
        "url_cadastro": url_cadastro or f"https://www.{dominio}/",
        "tem_documento": bool(lote.get("tem_documento")),
    }


def coletar_via_ddg_site(
    dominio: str,
    *,
    queries: list[str],
    max_por_query: int = 8,
    contexto: str = "leilao_direto",
    mapear: Callable[[dict[str, str]], dict[str, Any] | None] | None = None,
) -> list[dict[str, Any]]:
    """Fallback: descobrir URLs via DuckDuckGo site:dominio."""
    from core.ddg_lite import buscar as ddg_buscar

    lotes: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for query in queries:
        try:
            for item in ddg_buscar(query, max_resultados=max_por_query, contexto=contexto):
                url = item.get("url") or ""
                if dominio not in url:
                    continue
                if url in vistos:
                    continue
                vistos.add(url)
                if mapear:
                    lote = mapear(item)
                    if lote:
                        lotes.append(lote)
                else:
                    titulo = item.get("titulo") or url
                    snippet = item.get("snippet") or ""
                    lance = parse_preco_brl(f"{titulo} {snippet}")
                    lotes.append(
                        {
                            "hash": hash_lote(url),
                            "titulo": titulo,
                            "url": url,
                            "snippet": snippet,
                            "lance_brl": lance,
                            "lance_lista_brl": lance,
                            "tem_documento": "documento" in normalizar(f"{titulo} {snippet}"),
                            "fonte": "ddg",
                        }
                    )
        except Exception as exc:
            logger.warning("DDG site:%s falhou (%s): %s", dominio, query[:40], exc)
    return lotes


def montar_resultado_varredura(
    *,
    fonte: str,
    leiloes: list[dict[str, Any]],
    lotes: list[dict[str, Any]],
    leiloes_ok: int = 0,
    leiloes_falha: int = 0,
    modo_coleta: str = "direto",
    lance_min: float = 500.0,
    exigir_documento: bool = False,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    filtrados, stats = filtrar_lotes_padrao(
        lotes, lance_min=lance_min, exigir_documento=exigir_documento
    )
    out: dict[str, Any] = {
        "fonte": fonte,
        "leiloes_encontrados": len(leiloes),
        "leiloes_coletados_ok": leiloes_ok,
        "leiloes_coleta_falha": leiloes_falha,
        "lotes_veiculo_documento": len(filtrados),
        "lotes_veiculo_brutos": stats["lotes_veiculo_brutos"],
        "lotes_com_documento": stats["lotes_com_documento"],
        "lotes_sem_documento": stats["lotes_sem_documento"],
        "lotes_abaixo_lance_min": stats["lotes_abaixo_lance_min"],
        "exigir_documento": exigir_documento,
        "lance_minimo_brl": lance_min,
        "modo_coleta": modo_coleta,
        "lotes": filtrados,
        "leiloes": leiloes,
    }
    if extras:
        out.update(extras)
    return out
