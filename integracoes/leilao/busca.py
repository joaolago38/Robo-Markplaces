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
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from core.config import (
    LEILAO_ANO_MAX,
    LEILAO_ANO_MIN,
    LEILAO_DETRAN_POR_RODADA,
    LEILAO_INCLUIR_SUMARE_DIRETO,
    LEILAO_LEILOEIROS_POR_RODADA,
    LEILAO_SUMARE_MAX_LEILOES,
)
from core.ddg_lite import buscar as ddg_buscar, circuit_breaker_ativo, mensagem_circuit_breaker
from integracoes.leilao.fontes import DETRAN_POR_ESTADO, LEILOEIROS_PRINCIPAIS, URLS_CADASTRO_POR_DOMINIO

logger = logging.getLogger("leilao_busca")

_SUMARE_LOTES_CACHE: tuple[list[dict[str, Any]], dict[str, Any]] | None = None

_DDG_HTML = "https://html.duckduckgo.com/html/"  # compat testes legados
_PALAVRAS_LEILAO = ("leilao", "leilão", "lote", "arremate", "edital", "veiculo", "veículo", "automotor")
_PERFIL_RECUPERADO_FURTO = "recuperado_furto_pequena_monta"
_PERFIS_RECUPERADO_MONTA = frozenset({
    "recuperado_furto_pequena_monta",
    "recuperado_furto_media_monta",  # legado — mesmo comportamento
})
_TERMOS_PERFIL_BUSCA = ("recuperado", "furto", "pequena monta", "média monta", "media monta")
_PALAVRAS_RECUPERADO = ("recuperado", "furto", "furtado", "roubado", "judicial", "detran")
_PALAVRAS_MONTA_LEVE = (
    "pequena monta",
    "media monta",
    "média monta",
    "avaria media",
    "avaria média",
    "avaria leve",
    "leve",
    "pequeno reparo",
)
_PALAVRAS_MEDIA_MONTA = _PALAVRAS_MONTA_LEVE
_PALAVRAS_EXCLUIR_MONTA = ("grande monta", "perda total", "irrecuperavel", "irrecuperável", "sucata")
_MODELOS_MARCA_OPCIONAL = frozenset({"gol", "civic", "city", "fit", "fiorino", "furgao", "furgão"})
_MESES_PT = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def _limites_ano(veiculo: dict[str, Any]) -> tuple[int, int]:
    """Ano mín/máx do veículo no catálogo, com fallback em LEILAO_ANO_MIN/MAX."""
    raw_min = veiculo.get("ano_min")
    raw_max = veiculo.get("ano_max")
    ano_min = int(raw_min) if raw_min not in (None, "") else LEILAO_ANO_MIN
    ano_max = int(raw_max) if raw_max not in (None, "") else LEILAO_ANO_MAX
    return ano_min, ano_max


def montar_termo_busca(veiculo: dict[str, Any]) -> str:
    partes = [
        str(veiculo.get("marca") or "").strip(),
        str(veiculo.get("modelo") or "").strip(),
    ]
    ano_min, ano_max = _limites_ano(veiculo)
    if ano_min == ano_max:
        partes.append(str(ano_min))
    else:
        partes.append(f"{ano_min}-{ano_max}")
    for extra in veiculo.get("termos_extra") or []:
        if extra:
            partes.append(str(extra).strip())
    if veiculo.get("perfil") in _PERFIS_RECUPERADO_MONTA:
        partes.extend(_TERMOS_PERFIL_BUSCA)
    return " ".join(p for p in partes if p)


def _termo_query_site(veiculo: dict[str, Any]) -> str:
    """
    Termo enxuto para `site:dominio` — evita query gigante (perfil já vai no sufixo).
    Reduz 403 por rate limit no DuckDuckGo.
    """
    partes = [
        str(veiculo.get("marca") or "").strip(),
        str(veiculo.get("modelo") or "").strip(),
    ]
    ano_min, ano_max = _limites_ano(veiculo)
    if ano_min == ano_max:
        partes.append(str(ano_min))
    for extra in veiculo.get("termos_extra") or []:
        if extra:
            partes.append(str(extra).strip())
    return " ".join(p for p in partes if p)


def _headers_ddg() -> dict[str, str]:
    from core.ddg_lite import _headers

    return _headers()


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def _sufixo_query_leilao(veiculo: dict[str, Any], *, tipo_fonte: str) -> str:
    if veiculo.get("perfil") in _PERFIS_RECUPERADO_MONTA:
        base = "leilão veículo recuperado furto pequena monta"
    else:
        base = "leilão veículo"
    if tipo_fonte == "detran":
        return f"{base} DETRAN"
    return base


def _bate_perfil_recuperado_minimo(texto: str) -> bool:
    """
    Aceita furto/recuperado/DETRAN **ou** pequena/média monta.
    Exclui grande monta, perda total e sucata.
    """
    norm = _normalizar(texto)
    if any(x in norm for x in _PALAVRAS_EXCLUIR_MONTA):
        return False
    tem_recuperado = any(x in norm for x in _PALAVRAS_RECUPERADO)
    tem_monta_leve = any(x in norm for x in _PALAVRAS_MONTA_LEVE)
    return tem_recuperado or tem_monta_leve


def _tem_media_monta(texto: str) -> bool:
    norm = _normalizar(texto)
    return any(x in norm for x in _PALAVRAS_MEDIA_MONTA)


def _bate_perfil_recuperado_furto(texto: str) -> bool:
    """Perfil estrito — recuperado + monta leve (pequena ou média)."""
    if not _bate_perfil_recuperado_minimo(texto):
        return False
    norm = _normalizar(texto)
    return any(x in norm for x in _PALAVRAS_RECUPERADO) and any(x in norm for x in _PALAVRAS_MONTA_LEVE)


def _extrair_resultados_ddg(html: str) -> list[dict[str, str]]:
    from core.ddg_lite import extrair_resultados

    return extrair_resultados(html)


def buscar_duckduckgo(query: str, *, max_resultados: int = 8) -> list[dict[str, str]]:
    """Busca no DuckDuckGo HTML (rate limit global + retry). Nunca lança exceção."""
    return ddg_buscar(query, max_resultados=max_resultados, contexto="leilao")


def _ano_no_intervalo(texto: str, veiculo: dict[str, Any]) -> bool:
    ano_min, ano_max = _limites_ano(veiculo)
    anos = [int(a) for a in re.findall(r"\b(?:19|20)\d{2}\b", texto)]
    if not anos:
        return True
    for ano in anos:
        if ano < ano_min:
            continue
        if ano > ano_max:
            continue
        return True
    return False


def _parece_leilao(texto: str) -> bool:
    norm = _normalizar(texto)
    return any(p in norm for p in _PALAVRAS_LEILAO)


def _modelo_no_texto(texto: str, veiculo: dict[str, Any]) -> bool:
    norm = _normalizar(texto)
    modelo = _normalizar(str(veiculo.get("modelo") or ""))
    if not modelo:
        return True
    if modelo in norm:
        return True
    for extra in veiculo.get("termos_extra") or []:
        if extra and _normalizar(str(extra)) in norm:
            return True
    return False


def _relevante_para_veiculo(resultado: dict[str, str], veiculo: dict[str, Any]) -> bool:
    blob = f"{resultado.get('titulo', '')} {resultado.get('snippet', '')} {resultado.get('url', '')}"
    norm = _normalizar(blob)
    marca = _normalizar(str(veiculo.get("marca") or ""))
    modelo = _normalizar(str(veiculo.get("modelo") or ""))
    if resultado.get("fonte_tipo") == "sumare":
        return _modelo_no_texto(blob, veiculo)
    if modelo and modelo not in norm:
        if not _modelo_no_texto(blob, veiculo):
            return False
    if marca and marca not in norm:
        if modelo not in _MODELOS_MARCA_OPCIONAL:
            return False
    if not _ano_no_intervalo(blob, veiculo):
        return False
    if not (_parece_leilao(blob) or _parece_leilao(resultado.get("url", ""))):
        return False
    if veiculo.get("perfil") in _PERFIS_RECUPERADO_MONTA:
        return _bate_perfil_recuperado_minimo(blob)
    return True


def _hash_url(url: str) -> str:
    return hashlib.sha256((url or "").strip().encode()).hexdigest()[:16]


def _extrair_ano(texto: str, veiculo: dict[str, Any] | None = None) -> int | None:
    anos = [int(a) for a in re.findall(r"\b(?:19|20)\d{2}\b", texto or "")]
    if not anos:
        return None
    if veiculo:
        ano_min, ano_max = _limites_ano(veiculo)
        for ano in sorted(anos, reverse=True):
            if ano < ano_min:
                continue
            if ano > ano_max:
                continue
            return ano
    return max(anos)


def _extrair_valor(texto: str) -> str | None:
    norm = texto or ""
    for padrao in (
        r"R\$\s*([\d]{1,3}(?:\.\d{3})*,\d{2})",
        r"R\$\s*([\d]+)",
        r"valor[:\s]+R\$\s*([\d.,]+)",
        r"lance[:\s]+R\$\s*([\d.,]+)",
        r"arremate[:\s]+R\$\s*([\d.,]+)",
    ):
        m = re.search(padrao, norm, re.IGNORECASE)
        if not m:
            continue
        bruto = m.group(1).strip()
        if "," in bruto:
            return f"R$ {bruto}"
        try:
            return f"R$ {int(bruto):,}".replace(",", ".")
        except ValueError:
            return f"R$ {bruto}"
    return None


def _extrair_cidade_uf(texto: str) -> tuple[str | None, str | None]:
    blob = texto or ""
    m = re.search(
        r"([A-ZÀÁÂÃÉÊÍÓÔÕÚÇ][a-zàáâãéêíóôõúç]+"
        r"(?:\s+(?:do|da|de|dos|das)\s+[A-ZÀÁÂÃÉÊÍÓÔÕÚÇ][a-zàáâãéêíóôõúç]+)?)"
        r"\s*/\s*([A-Z]{2})\b",
        blob,
    )
    if m:
        return m.group(1).strip(), m.group(2).upper()
    m = re.search(
        r"\bem\s+([A-ZÀÁÂÃÉÊÍÓÔÕÚÇ][a-zàáâãéêíóôõúç]+"
        r"(?:\s+[A-ZÀÁÂÃÉÊÍÓÔÕÚÇ][a-zàáâãéêíóôõúç]+)?)"
        r"(?:\s*[-–]\s*|\s+)([A-Z]{2})\b",
        blob,
    )
    if m:
        return m.group(1).strip(), m.group(2).upper()
    return None, None


def _formatar_data(dia: int, mes: int, ano: int) -> str:
    if ano < 100:
        ano += 2000
    return f"{dia:02d}/{mes:02d}/{ano}"


def _extrair_data_leilao(texto: str) -> str | None:
    blob = texto or ""
    candidatas: list[str] = []

    for m in re.finditer(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", blob):
        try:
            candidatas.append(_formatar_data(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            continue

    for m in re.finditer(
        r"\b(\d{1,2})\s+de\s+([A-Za-zÀ-ÿ]+)\s+de\s+(\d{4})\b",
        blob,
        re.IGNORECASE,
    ):
        mes_nome = _normalizar(m.group(2))
        mes = _MESES_PT.get(mes_nome)
        if mes:
            try:
                candidatas.append(_formatar_data(int(m.group(1)), mes, int(m.group(3))))
            except ValueError:
                continue

    if not candidatas:
        return None

    palavras_data = ("leilao", "leilão", "arremate", "pregao", "pregão", "edital", "dia")
    for data in candidatas:
        pos = blob.find(data)
        trecho = _normalizar(blob[max(0, pos - 40) : pos + len(data) + 40])
        if any(p in trecho for p in palavras_data):
            return data
    return candidatas[0]


def _extrair_url_cadastro(texto: str, *, url: str = "", dominio: str = "") -> str | None:
    blob = texto or ""
    for link in re.findall(r"https?://[^\s<>\"']+", blob, re.IGNORECASE):
        norm = link.lower()
        if any(x in norm for x in ("cadastro", "inscricao", "inscrição", "registro", "credenciamento")):
            return link.rstrip(".,;)")
    dom = (dominio or urlparse(url).netloc or "").lower().replace("www.", "")
    if dom in URLS_CADASTRO_POR_DOMINIO:
        return URLS_CADASTRO_POR_DOMINIO[dom]
    if dom.startswith("detran.") and dom.endswith(".gov.br"):
        return f"https://www.{dom}/leilao"
    return None


def enriquecer_achado_leilao(item: dict[str, Any], veiculo: dict[str, Any]) -> dict[str, Any]:
    """Extrai cidade, DETRAN, ano, valor, data e URL de cadastro para o alerta."""
    blob = f"{item.get('titulo', '')} {item.get('snippet', '')}"
    cidade, uf_texto = _extrair_cidade_uf(blob)
    ano = _extrair_ano(blob, veiculo)
    valor = _extrair_valor(blob)
    data_leilao = _extrair_data_leilao(blob)
    dominio = str(item.get("dominio") or urlparse(str(item.get("url") or "")).netloc)
    url_cadastro = _extrair_url_cadastro(blob, url=str(item.get("url") or ""), dominio=dominio)

    out = {
        **item,
        "marca": str(veiculo.get("marca") or "").strip(),
        "modelo": str(veiculo.get("modelo") or "").strip(),
        "url_anuncio": str(item.get("url") or "").strip(),
    }
    if ano:
        out["ano"] = ano
    if valor:
        out["valor"] = valor
    if data_leilao:
        out["data_leilao"] = data_leilao
    if url_cadastro:
        out["url_cadastro"] = url_cadastro

    blob = f"{item.get('titulo', '')} {item.get('snippet', '')}"
    if veiculo.get("perfil") in _PERFIS_RECUPERADO_MONTA:
        out["perfil_monta_leve"] = _tem_media_monta(blob)
        out["perfil_recuperado"] = any(
            x in _normalizar(blob) for x in _PALAVRAS_RECUPERADO
        )

    if item.get("fonte_tipo") == "detran":
        out["detran_nome"] = item.get("fonte_nome") or f"DETRAN {item.get('fonte_id', '')}"
        out["uf"] = item.get("uf") or item.get("fonte_id") or uf_texto
        if cidade:
            out["cidade"] = cidade
    else:
        if cidade:
            out["cidade"] = cidade
        if uf_texto:
            out["uf"] = uf_texto

    return out


def _rotacionar_fontes(
    fontes: list[dict[str, str]],
    *,
    limite: int,
    bucket: int,
) -> list[dict[str, str]]:
    """Seleciona subconjunto rotativo por hora — reduz carga DDG no CI."""
    if limite <= 0 or limite >= len(fontes):
        return list(fontes)
    inicio = bucket % len(fontes)
    selecionadas: list[dict[str, str]] = []
    for i in range(limite):
        selecionadas.append(fontes[(inicio + i) % len(fontes)])
    return selecionadas


def _fontes_da_rodada() -> tuple[list[tuple[dict[str, str], str, str]], dict[str, Any]]:
    hora_utc = datetime.now(timezone.utc).hour
    leiloeiros = _rotacionar_fontes(
        LEILOEIROS_PRINCIPAIS,
        limite=LEILAO_LEILOEIROS_POR_RODADA,
        bucket=hora_utc,
    )
    detrans = _rotacionar_fontes(
        DETRAN_POR_ESTADO,
        limite=LEILAO_DETRAN_POR_RODADA,
        bucket=hora_utc + 7,
    )
    fontes: list[tuple[dict[str, str], str, str]] = []
    for f in leiloeiros:
        fontes.append((f, "leiloeiro", f.get("id", f["dominio"])))
    for f in detrans:
        fontes.append((f, "detran", f.get("uf", f["dominio"])))
    meta = {
        "hora_utc": hora_utc,
        "leiloeiros_na_rodada": len(leiloeiros),
        "detrans_na_rodada": len(detrans),
        "leiloeiros_ids": [f.get("id", f.get("dominio", "")) for f in leiloeiros],
        "detrans_ufs": [f.get("uf", "") for f in detrans],
    }
    return fontes, meta


def reset_cache_sumare() -> None:
    """Limpa cache Sumaré (testes)."""
    global _SUMARE_LOTES_CACHE
    _SUMARE_LOTES_CACHE = None


def obter_lotes_sumare() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Coleta lotes Sumaré uma vez por processo (DETRAN/prefeitura, com documento).
    Não lança exceção.
    """
    global _SUMARE_LOTES_CACHE
    if _SUMARE_LOTES_CACHE is not None:
        return _SUMARE_LOTES_CACHE

    diag: dict[str, Any] = {
        "ativo": LEILAO_INCLUIR_SUMARE_DIRETO,
        "leiloes_ok": 0,
        "leiloes_falha": 0,
        "lotes_veiculo": 0,
        "erro": None,
    }
    if not LEILAO_INCLUIR_SUMARE_DIRETO:
        _SUMARE_LOTES_CACHE = ([], diag)
        return _SUMARE_LOTES_CACHE

    try:
        from integracoes.leilao.sumare_leiloes import (
            buscar_leiloes_detran_ddg,
            coletar_lotes_leilao,
            eh_veiculo_com_documento,
            filtrar_leiloes_por_comitente,
            listar_leiloes_home,
            _criar_sessao,
        )

        sess = _criar_sessao()
        leiloes = listar_leiloes_home(sess)
        leiloes.extend(buscar_leiloes_detran_ddg())
        leiloes = filtrar_leiloes_por_comitente(leiloes, ["prefeitura", "detran"])
        por_id: dict[str, dict[str, Any]] = {}
        for leilao in leiloes:
            por_id[str(leilao["leilao_id"])] = leilao
        leiloes = list(por_id.values())[:LEILAO_SUMARE_MAX_LEILOES]

        lotes: list[dict[str, Any]] = []
        falhas = 0
        for leilao in leiloes:
            brutos = coletar_lotes_leilao(leilao, sess, pausa_paginas_seg=0)
            if brutos is None:
                diag["leiloes_falha"] = int(diag["leiloes_falha"]) + 1
                falhas += 1
                if falhas >= 5:
                    logger.warning("Sumaré leilão veículos: abortando após 5 falhas consecutivas")
                    break
                continue
            diag["leiloes_ok"] = int(diag["leiloes_ok"]) + 1
            falhas = 0
            for lote in brutos:
                if eh_veiculo_com_documento(lote):
                    lotes.append(lote)

        diag["lotes_veiculo"] = len(lotes)
        logger.info(
            "Sumaré direto: %s leilões OK, %s falhas, %s lotes veículo/doc",
            diag["leiloes_ok"],
            diag["leiloes_falha"],
            diag["lotes_veiculo"],
        )
        _SUMARE_LOTES_CACHE = (lotes, diag)
        return _SUMARE_LOTES_CACHE
    except Exception as exc:
        logger.warning("Sumaré direto indisponível: %s", exc)
        diag["erro"] = str(exc)
        _SUMARE_LOTES_CACHE = ([], diag)
        return _SUMARE_LOTES_CACHE


def _lote_sumare_para_item(lote: dict[str, Any], veiculo: dict[str, Any]) -> dict[str, Any] | None:
    titulo = str(lote.get("titulo") or "")
    if not _modelo_no_texto(titulo, veiculo):
        return None
    lance = float(lote.get("lance_brl") or lote.get("lance_lista_brl") or 0)
    valor_txt = f"R$ {lance:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if lance else None
    url = str(lote.get("url") or "")
    snippet = " ".join(
        p
        for p in (
            str(lote.get("comitente") or ""),
            str(lote.get("local_data") or ""),
            "DOCUMENTO",
            "DETRAN" if "detran" in _normalizar(str(lote.get("comitente") or "")) else "",
        )
        if p
    )
    return {
        "url": url,
        "titulo": titulo,
        "snippet": snippet,
        "fonte_tipo": "sumare",
        "fonte_id": "sumare",
        "fonte_nome": "Sumaré Leilões",
        "dominio": "sumareleiloes.com.br",
        "hash": str(lote.get("hash") or _hash_url(url)),
        "cidade": lote.get("cidade"),
        "uf": lote.get("uf"),
        "valor": valor_txt,
        "lance_brl": lance or None,
        "data_leilao": lote.get("data_fechamento"),
        "url_cadastro": "https://www.sumareleiloes.com.br/",
    }


def _buscar_em_dominio(
    dominio: str,
    termo: str,
    *,
    tipo_fonte: str,
    fonte_id: str,
    fonte_nome: str,
    sufixo_query: str = "leilão veículo",
    diagnostico: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    query = f'site:{dominio} {sufixo_query} {termo}'
    achados: list[dict[str, Any]] = []
    brutos = buscar_duckduckgo(query, max_resultados=6)
    if diagnostico is not None:
        diagnostico["ddg_queries"] = diagnostico.get("ddg_queries", 0) + 1
        diagnostico["ddg_brutos"] = diagnostico.get("ddg_brutos", 0) + len(brutos)
    for item in brutos:
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
                **({"uf": fonte_id} if tipo_fonte == "detran" else {}),
            }
        )
    return achados


def buscar_veiculo_em_fontes(
    veiculo: dict[str, Any],
    *,
    incluir_leiloeiros: bool = True,
    incluir_detran: bool = True,
    pausa_entre_fontes_seg: float = 0.8,
    lotes_sumare: list[dict[str, Any]] | None = None,
    diag_sumare: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Varre leiloeiros/DETRAN (rotacionados) + Sumaré direto + fallback DDG.
    Retorna {"achados": [...], "diagnostico": {...}}. Nunca lança exceção.
    """
    termo = montar_termo_busca(veiculo)
    termo_site = _termo_query_site(veiculo)
    if not termo.strip():
        return {"achados": [], "diagnostico": {"motivo": "termo vazio"}}

    vistos: set[str] = set()
    todos: list[dict[str, Any]] = []
    contadores: dict[str, int] = {
        "ddg_queries": 0,
        "ddg_brutos": 0,
        "ddg_descartados_filtro": 0,
        "sumare_candidatos": 0,
        "sumare_achados": 0,
    }

    fontes, meta_fontes = _fontes_da_rodada()
    if not incluir_leiloeiros:
        fontes = [f for f in fontes if f[1] != "leiloeiro"]
    if not incluir_detran:
        fontes = [f for f in fontes if f[1] != "detran"]

    if lotes_sumare is None and LEILAO_INCLUIR_SUMARE_DIRETO:
        lotes_sumare, diag_sumare = obter_lotes_sumare()

    for lote in lotes_sumare or []:
        contadores["sumare_candidatos"] += 1
        item = _lote_sumare_para_item(lote, veiculo)
        if not item:
            continue
        if not _relevante_para_veiculo(item, veiculo):
            continue
        h = item["hash"]
        if h in vistos:
            continue
        vistos.add(h)
        contadores["sumare_achados"] += 1
        todos.append(enriquecer_achado_leilao(item, veiculo))

    for fonte, tipo, fid in fontes:
        dominio = fonte.get("dominio", "")
        nome = fonte.get("nome", dominio)
        if not dominio:
            continue
        sufixo = _sufixo_query_leilao(veiculo, tipo_fonte=tipo)
        try:
            lote = _buscar_em_dominio(
                dominio,
                termo_site,
                tipo_fonte=tipo,
                fonte_id=fid,
                fonte_nome=nome,
                sufixo_query=sufixo,
                diagnostico=contadores,
            )
            for item in lote:
                if not _relevante_para_veiculo(item, veiculo):
                    contadores["ddg_descartados_filtro"] += 1
                    continue
                h = item["hash"]
                if h in vistos:
                    continue
                vistos.add(h)
                todos.append(enriquecer_achado_leilao(item, veiculo))
        except Exception as exc:
            logger.warning("Fonte %s (%s) falhou: %s", nome, dominio, exc)
        if pausa_entre_fontes_seg > 0:
            time.sleep(pausa_entre_fontes_seg)

    try:
        query_geral = f'{_sufixo_query_leilao(veiculo, tipo_fonte="web")} {termo} Brasil'
        contadores["ddg_queries"] += 1
        for item in buscar_duckduckgo(query_geral, max_resultados=10):
            contadores["ddg_brutos"] += 1
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
                contadores["ddg_descartados_filtro"] += 1
                continue
            if enriquecido["hash"] in vistos:
                continue
            vistos.add(enriquecido["hash"])
            todos.append(enriquecer_achado_leilao(enriquecido, veiculo))
    except Exception as exc:
        logger.warning("Busca geral falhou: %s", exc)

    diagnostico: dict[str, Any] = {
        **contadores,
        **meta_fontes,
        "fontes_consultadas": len(fontes),
        "achados_total": len(todos),
        "circuit_breaker_ativo": circuit_breaker_ativo("leilao"),
        "circuit_breaker_msg": mensagem_circuit_breaker("leilao"),
        "sumare_coleta": diag_sumare or {},
    }
    return {"achados": todos, "diagnostico": diagnostico}
