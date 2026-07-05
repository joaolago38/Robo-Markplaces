"""
integracoes/leilao/sumare_leiloes.py
Coleta leilões PREFEITURA/DETRAN no site oficial Sumaré Leilões (sumareleiloes.com.br).
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
import unicodedata
from typing import Any
from urllib.parse import urljoin

import requests

from core.ddg_lite import buscar as ddg_buscar

logger = logging.getLogger("sumare_leiloes")

BASE_URL = "https://www.sumareleiloes.com.br"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RoboMarkplaces/1.0)"}

_RE_AUCTION_BLOCK = re.compile(
    r'<div class="auction-item">(.*?)<a href="https://www\.sumareleiloes\.com\.br/leiloes/(\d+)" class="goToAuction"',
    re.DOTALL | re.IGNORECASE,
)
_RE_COMITENTE = re.compile(
    r'card-img-overlay-top">\s*<div class="card-title">\s*(.*?)\s*</div>',
    re.DOTALL | re.IGNORECASE,
)
_RE_LOT_CARD = re.compile(r'<div class="lot-item">(.*?)</div>\s*</div>\s*</div>', re.DOTALL | re.IGNORECASE)
_RE_LOT_TITLE = re.compile(r'card-title[^"]*">\s*(.*?)\s*</div>', re.DOTALL | re.IGNORECASE)
_RE_LOT_LOC = re.compile(
    r'fa-map-marker"></i>\s*([^<]+)</span>(?:\s*<span>\s*(R\$\s*[\d\.\,]+)\s*</span>)?',
    re.IGNORECASE,
)
_RE_LOT_NUM = re.compile(r"LOTE\s+(\d+)", re.IGNORECASE)
_RE_LOT_URL = re.compile(r'href="(https://www\.sumareleiloes\.com\.br/lotes/[a-f0-9-]+)"', re.IGNORECASE)
_RE_LOT_UUID = re.compile(r'data-id="([a-f0-9-]{36})"', re.IGNORECASE)
_RE_VARS = re.compile(r"var\s+listaLotsTotal\s*=\s*(\d+)", re.IGNORECASE)
_RE_LEILAO_NUM = re.compile(r"var\s+listaLotsLeilao\s*=\s*(\d+)", re.IGNORECASE)
_RE_PRECO = re.compile(r"R\$\s*([\d]{1,3}(?:\.\d{3})*,\d{2}|\d+)")
_RE_ANO_VEIC = re.compile(r"\b(\d{2}/\d{2}|\d{4})\s*$")
_RE_LANCE_LINHA = re.compile(
    r"Lance\s+(Inicial|Atual)\s*:?\s*</td>\s*<td>\s*R\$\s*([\d\.\,]+)",
    re.IGNORECASE,
)

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
)
_MARCAS_VEICULO = (
    "fiat",
    "ford",
    "chevrolet",
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
)


def _normalizar(texto: str) -> str:
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


def _hash_lote(lote_id: str) -> str:
    return hashlib.sha256(lote_id.encode()).hexdigest()[:16]


def _limpar_html(texto: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", texto or "")).strip()


def _classificar_comitente(nome: str) -> str | None:
    norm = _normalizar(nome)
    if "detran" in norm:
        return "detran"
    if "prefeitura" in norm:
        return "prefeitura"
    return None


def listar_leiloes_home(session: requests.Session | None = None) -> list[dict[str, Any]]:
    """Lista leilões visíveis na home do site."""
    sess = session or requests.Session()
    sess.headers.update(_HEADERS)
    try:
        r = sess.get(f"{BASE_URL}/", timeout=30)
        if r.status_code != 200:
            logger.warning("Sumaré home HTTP %s", r.status_code)
            return []
        html = r.text
    except Exception as exc:
        logger.error("Sumaré home erro: %s", exc)
        return []

    leiloes: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for bloco, leilao_id in _RE_AUCTION_BLOCK.findall(html):
        if leilao_id in vistos:
            continue
        vistos.add(leilao_id)
        m_com = _RE_COMITENTE.search(bloco)
        comitente = _limpar_html(m_com.group(1)) if m_com else ""
        tipo = _classificar_comitente(comitente)
        leiloes.append(
            {
                "leilao_id": leilao_id,
                "comitente": comitente,
                "tipo_comitente": tipo,
                "url": f"{BASE_URL}/leiloes/{leilao_id}",
                "fonte": "home",
            }
        )
    return leiloes


def buscar_leiloes_detran_ddg(*, max_resultados: int = 12) -> list[dict[str, Any]]:
    """Fallback: leilões DETRAN indexados no site via busca."""
    leiloes: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for query in (
        "site:sumareleiloes.com.br/leiloes DETRAN veículo",
        "site:sumareleiloes.com.br/leiloes DETRAN",
    ):
        try:
            for item in ddg_buscar(query, max_resultados=max_resultados, contexto="sumare_leiloes"):
                url = item.get("url") or ""
                m = re.search(r"/leiloes/(\d+)", url)
                if not m:
                    continue
                lid = m.group(1)
                if lid in vistos:
                    continue
                vistos.add(lid)
                blob = f"{item.get('titulo', '')} {item.get('snippet', '')}"
                leiloes.append(
                    {
                        "leilao_id": lid,
                        "comitente": blob[:120] if "detran" in _normalizar(blob) else "DETRAN",
                        "tipo_comitente": "detran",
                        "url": f"{BASE_URL}/leiloes/{lid}",
                        "fonte": "ddg",
                    }
                )
        except Exception as exc:
            logger.warning("Sumaré DDG DETRAN falhou: %s", exc)
    return leiloes


def filtrar_leiloes_por_comitente(
    leiloes: list[dict[str, Any]],
    tipos: list[str],
) -> list[dict[str, Any]]:
    alvo = {_normalizar(t) for t in tipos}
    saida: list[dict[str, Any]] = []
    for leilao in leiloes:
        tipo = leilao.get("tipo_comitente") or _classificar_comitente(str(leilao.get("comitente") or ""))
        if tipo and tipo in alvo:
            leilao = {**leilao, "tipo_comitente": tipo}
            saida.append(leilao)
    return saida


def _parse_lote_card(fragmento: str, *, leilao: dict[str, Any]) -> dict[str, Any] | None:
    titulo_m = _RE_LOT_TITLE.search(fragmento)
    if not titulo_m:
        return None
    titulo = _limpar_html(titulo_m.group(1))
    if not titulo:
        return None

    tem_documento = "DOCUMENTO" in fragmento.upper() or "documento-icone" in fragmento.lower()
    loc_m = _RE_LOT_LOC.search(fragmento)
    local_data = _limpar_html(loc_m.group(1)) if loc_m else ""
    preco_lista = parse_preco_brl(loc_m.group(2)) if loc_m and loc_m.group(2) else None

    url_m = _RE_LOT_URL.search(fragmento)
    uuid_m = _RE_LOT_UUID.search(fragmento)
    lote_uuid = uuid_m.group(1) if uuid_m else ""
    url = url_m.group(1) if url_m else (f"{BASE_URL}/lotes/{lote_uuid}" if lote_uuid else "")

    num_m = _RE_LOT_NUM.search(fragmento)
    numero_lote = num_m.group(1) if num_m else ""

    cidade, uf, data_fech = _parse_local_data(local_data)

    return {
        "hash": _hash_lote(lote_uuid or url or titulo),
        "lote_uuid": lote_uuid,
        "numero_lote": numero_lote,
        "titulo": titulo,
        "tem_documento": tem_documento,
        "local_data": local_data,
        "cidade": cidade,
        "uf": uf,
        "data_fechamento": data_fech,
        "lance_lista_brl": preco_lista,
        "lance_brl": preco_lista,
        "url": url,
        "leilao_id": leilao.get("leilao_id"),
        "comitente": leilao.get("comitente"),
        "tipo_comitente": leilao.get("tipo_comitente"),
        "url_leilao": leilao.get("url"),
    }


def _parse_local_data(texto: str) -> tuple[str | None, str | None, str | None]:
    if not texto:
        return None, None, None
    m = re.search(
        r"([A-ZÀÁÂÃÉÊÍÓÔÕÚÇ][A-ZÀÁÂÃÉÊÍÓÔÕÚÇa-zàáâãéêíóôõúç\s]+?)\s*/\s*([A-Z]{2})\s*-\s*(\d{1,2}/\d{1,2}/\d{4})",
        texto,
    )
    if m:
        return m.group(1).strip(), m.group(2).upper(), m.group(3)
    return None, None, None


def eh_veiculo_com_documento(lote: dict[str, Any]) -> bool:
    titulo = str(lote.get("titulo") or "")
    norm = _normalizar(titulo)

    if not lote.get("tem_documento"):
        return False
    if any(p in norm for p in _PALAVRAS_SUCATA):
        return False
    if "blindad" in norm:
        return False
    if any(p in norm for p in _PALAVRAS_NAO_VEICULO):
        return False

    if any(m in norm for m in _MARCAS_VEICULO):
        return True
    if "/" in titulo and _RE_ANO_VEIC.search(titulo.strip()):
        return True
    if re.search(r"\b(moto|motocicleta|nxr|cg\s*\d|biz)\b", norm):
        return False
    return bool(_RE_ANO_VEIC.search(titulo.strip()))


def _extrair_lotes_html(html: str, leilao: dict[str, Any]) -> list[dict[str, Any]]:
    lotes: list[dict[str, Any]] = []
    for fragmento in _RE_LOT_CARD.findall(html):
        lote = _parse_lote_card(fragmento, leilao=leilao)
        if lote:
            lotes.append(lote)
    return lotes


def _buscar_pagina_lotes_ajax(
    sess: requests.Session,
    *,
    leilao_id: str,
    total: int,
    pagina: int,
) -> str:
    data = {
        "totalLotes": total,
        "leilaoNum": int(leilao_id),
        "loteInitial": 1,
        "orderLots": "",
        "typeLots": "",
        "searchLotsLotCondition": "",
        "searchLotsPhpId": "",
        "searchLotsAuctionVendor": "",
        "searchLotsYearMin": "",
        "searchLotsYearMax": "",
        "searchLotsRetirado": "",
        "searchLotsString": "",
        "searchValueMin": "",
        "searchValueMax": "",
        "searchWithBids": "",
        "searchCity": "",
        "searchProcesso": "",
        "searchExecutado": "",
        "listaTipo": "cards",
        "pagina": pagina,
    }
    r = sess.post(
        f"{BASE_URL}/ajaxListaLotes",
        data=data,
        timeout=30,
        headers={**_HEADERS, "X-Requested-With": "XMLHttpRequest"},
    )
    return r.text if r.status_code == 200 else ""


def coletar_lotes_leilao(
    leilao: dict[str, Any],
    session: requests.Session | None = None,
    *,
    pausa_paginas_seg: float = 0.5,
) -> list[dict[str, Any]]:
    """Coleta todos os lotes de um leilão (HTML + paginação ajax)."""
    sess = session or requests.Session()
    sess.headers.update(_HEADERS)
    leilao_id = str(leilao.get("leilao_id") or "")
    url = str(leilao.get("url") or f"{BASE_URL}/leiloes/{leilao_id}")
    if not leilao_id:
        return []

    try:
        r = sess.get(url, timeout=35)
        if r.status_code != 200:
            logger.warning("Sumaré leilão %s HTTP %s", leilao_id, r.status_code)
            return []
        html = r.text
    except Exception as exc:
        logger.error("Sumaré leilão %s erro: %s", leilao_id, exc)
        return []

    total_m = _RE_VARS.search(html)
    total = int(total_m.group(1)) if total_m else 0

    lotes = _extrair_lotes_html(html, leilao)
    por_pagina = max(1, len(lotes))
    if total > len(lotes) and por_pagina > 0:
        paginas = (total + por_pagina - 1) // por_pagina
        for pagina in range(2, paginas + 1):
            if pausa_paginas_seg > 0:
                time.sleep(pausa_paginas_seg)
            frag = _buscar_pagina_lotes_ajax(sess, leilao_id=leilao_id, total=total, pagina=pagina)
            if frag and "lot-item" in frag:
                lotes.extend(_extrair_lotes_html(frag, leilao))

    # dedupe
    unicos: dict[str, dict[str, Any]] = {}
    for lote in lotes:
        chave = str(lote.get("lote_uuid") or lote.get("hash") or "")
        if chave:
            unicos[chave] = lote
    return list(unicos.values())


def enriquecer_lance_lote(lote: dict[str, Any], session: requests.Session | None = None) -> dict[str, Any]:
    """Busca Lance Inicial/Atual na página do lote."""
    if lote.get("lance_brl"):
        return lote
    url = str(lote.get("url") or "")
    if not url:
        return lote

    sess = session or requests.Session()
    sess.headers.update(_HEADERS)
    try:
        r = sess.get(url, timeout=25)
        if r.status_code != 200:
            return lote
        html = r.text
    except Exception as exc:
        logger.debug("Sumaré lote %s erro: %s", url, exc)
        return lote

    lances: dict[str, float] = {}
    for tipo, valor_txt in _RE_LANCE_LINHA.findall(html):
        val = parse_preco_brl(f"R$ {valor_txt}")
        if val:
            lances[tipo.lower()] = val

    atual = lances.get("atual") or lances.get("inicial")
    if atual:
        lote = {**lote, "lance_brl": atual, "lance_inicial_brl": lances.get("inicial"), "lance_atual_brl": lances.get("atual")}

    if "COM DIREITO A DOCUMENTO" in html.upper():
        lote = {**lote, "tem_documento": True}

    return lote


def varredura_sumare(
    config: dict[str, Any],
    *,
    pausa_entre_leiloes_seg: float = 1.0,
    pausa_paginas_seg: float = 0.5,
    enriquecer_lances: bool = True,
) -> dict[str, Any]:
    """
    Varre leilões PREFEITURA/DETRAN no Sumaré e retorna lotes filtrados.
    """
    tipos = config.get("comitentes") or ["prefeitura", "detran"]
    lance_min = float(config.get("lance_minimo_brl") or 2000)

    sess = requests.Session()
    sess.headers.update(_HEADERS)

    leiloes = listar_leiloes_home(sess)
    leiloes.extend(buscar_leiloes_detran_ddg())
    leiloes_filtrados = filtrar_leiloes_por_comitente(leiloes, tipos)

    # dedupe leilões
    por_id: dict[str, dict[str, Any]] = {}
    for leilao in leiloes_filtrados:
        por_id[str(leilao["leilao_id"])] = leilao
    leiloes_filtrados = list(por_id.values())

    todos_lotes: list[dict[str, Any]] = []
    for i, leilao in enumerate(leiloes_filtrados):
        if i > 0 and pausa_entre_leiloes_seg > 0:
            time.sleep(pausa_entre_leiloes_seg)
        brutos = coletar_lotes_leilao(leilao, sess, pausa_paginas_seg=pausa_paginas_seg)
        for lote in brutos:
            if not eh_veiculo_com_documento(lote):
                continue
            if enriquecer_lances and not lote.get("lance_brl"):
                lote = enriquecer_lance_lote(lote, sess)
                time.sleep(0.3)
            lance = float(lote.get("lance_brl") or lote.get("lance_lista_brl") or 0)
            lote["lance_brl"] = lance or None
            if lance and lance < lance_min:
                lote["abaixo_lance_minimo"] = True
                continue
            lote["abaixo_lance_minimo"] = False
            todos_lotes.append(lote)

    todos_lotes.sort(key=lambda x: float(x.get("lance_brl") or 0), reverse=True)
    return {
        "leiloes_encontrados": len(leiloes_filtrados),
        "lotes_veiculo_documento": len(todos_lotes),
        "lotes": todos_lotes,
        "leiloes": leiloes_filtrados,
    }
