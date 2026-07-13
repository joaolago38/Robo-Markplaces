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
    COPART_LEILOES_CATALOGO,
    DDG_DISABLED,
    LEILAO_ANO_MAX,
    LEILAO_ANO_MIN,
    LEILAO_COLETORES_EXIGIR_DOCUMENTO,
    LEILAO_COLETORES_LANCE_MIN_BRL,
    LEILAO_DETRAN_DDG_AMPLA,
    LEILAO_DETRAN_POR_RODADA,
    LEILAO_DETRAN_VIA_DDG,
    LEILAO_INCLUIR_COPART_DIRETO,
    LEILAO_INCLUIR_SODRE_DIRETO,
    LEILAO_INCLUIR_SUMARE_DIRETO,
    LEILAO_INCLUIR_SUPERBID_DIRETO,
    LEILAO_LEILOEIROS_POR_RODADA,
    LEILAO_PULAR_DDG_SE_BREAKER,
    LEILAO_SUMARE_MAX_LEILOES,
    LEILAO_VARREDURA_TODAS_FONTES,
    ROOT,
    SODRE_LEILOES_CATALOGO,
    SUPERBID_LEILOES_CATALOGO,
)
from core.ddg_lite import (
    buscar as ddg_buscar,
    circuit_breaker_ativo,
    mensagem_circuit_breaker,
)
from core.atomic_io import ler_json, escrever_json_atomico
from integracoes.leilao.coletores_base import lote_para_achado
from integracoes.leilao.fontes import DETRAN_POR_ESTADO, LEILOEIROS_PRINCIPAIS, URLS_CADASTRO_POR_DOMINIO

logger = logging.getLogger("leilao_busca")

_SUMARE_LOTES_CACHE: tuple[list[dict[str, Any]], dict[str, Any]] | None = None
_COLETORES_CACHE: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]] = {}

_META_COLETORES = {
    "copart": {
        "enabled": lambda: LEILAO_INCLUIR_COPART_DIRETO,
        "catalogo": COPART_LEILOES_CATALOGO,
        "fonte_tipo": "copart",
        "fonte_id": "copart",
        "fonte_nome": "Copart Brasil",
        "dominio": "copart.com.br",
        "url_cadastro": "https://www.copart.com.br/",
        "snapshot": "logs/copart_leiloes_ultima.json",
        "varredura": "integracoes.leilao.copart_leiloes:varredura_copart",
    },
    "superbid": {
        "enabled": lambda: LEILAO_INCLUIR_SUPERBID_DIRETO,
        "catalogo": SUPERBID_LEILOES_CATALOGO,
        "fonte_tipo": "superbid",
        "fonte_id": "superbid",
        "fonte_nome": "Superbid",
        "dominio": "superbid.net",
        "url_cadastro": "https://www.superbid.net/",
        "snapshot": "logs/superbid_leiloes_ultima.json",
        "varredura": "integracoes.leilao.superbid_leiloes:varredura_superbid",
    },
    "sodre": {
        "enabled": lambda: LEILAO_INCLUIR_SODRE_DIRETO,
        "catalogo": SODRE_LEILOES_CATALOGO,
        "fonte_tipo": "sodre",
        "fonte_id": "sodre",
        "fonte_nome": "Sodré Santoro",
        "dominio": "sodresantoro.com.br",
        "url_cadastro": "https://www.sodresantoro.com.br/cadastro-de-cliente",
        "snapshot": "logs/sodre_leiloes_ultima.json",
        "varredura": "integracoes.leilao.sodre_leiloes:varredura_sodre",
    },
}
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


def _limites_ano(veiculo: dict[str, Any]) -> tuple[int, int] | None:
    """
    Ano mín/máx do veículo no catálogo, com fallback em LEILAO_ANO_MIN/MAX.
    Retorna None quando não há filtro de ano (busca_todos / sem_filtro_ano / 0–0).
    """
    if veiculo.get("busca_todos") or veiculo.get("sem_filtro_ano"):
        return None
    raw_min = veiculo.get("ano_min")
    raw_max = veiculo.get("ano_max")
    if raw_min in (0, "0") and raw_max in (0, "0"):
        return None
    ano_min = int(raw_min) if raw_min not in (None, "") else LEILAO_ANO_MIN
    ano_max = int(raw_max) if raw_max not in (None, "") else LEILAO_ANO_MAX
    if ano_min <= 0 and ano_max <= 0:
        return None
    return ano_min, ano_max


def montar_termo_busca(veiculo: dict[str, Any]) -> str:
    if veiculo.get("busca_todos"):
        partes = ["veículo", "automotor"]
        limites = _limites_ano(veiculo)
        if limites:
            ano_min, ano_max = limites
            if ano_min == ano_max:
                partes.append(str(ano_min))
            else:
                partes.append(f"{ano_min}-{ano_max}")
        if veiculo.get("perfil") in _PERFIS_RECUPERADO_MONTA:
            partes.extend(_TERMOS_PERFIL_BUSCA)
        return " ".join(partes)

    partes = [
        str(veiculo.get("marca") or "").strip(),
        str(veiculo.get("modelo") or "").strip(),
    ]
    limites = _limites_ano(veiculo)
    if limites:
        ano_min, ano_max = limites
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
    if veiculo.get("busca_todos"):
        return "veículo automotor"

    partes = [
        str(veiculo.get("marca") or "").strip(),
        str(veiculo.get("modelo") or "").strip(),
    ]
    ano_min, ano_max = _limites_ano(veiculo) or (None, None)
    if ano_min is not None and ano_max is not None and ano_min == ano_max:
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
    limites = _limites_ano(veiculo)
    if limites is None:
        return True
    ano_min, ano_max = limites
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
    if veiculo.get("busca_todos"):
        if resultado.get("fonte_tipo") == "sumare":
            if not _ano_no_intervalo(blob, veiculo):
                return False
            return True
        if not _ano_no_intervalo(blob, veiculo):
            return False
        if not (_parece_leilao(blob) or _parece_leilao(resultado.get("url", ""))):
            return False
        if veiculo.get("perfil") in _PERFIS_RECUPERADO_MONTA:
            return _bate_perfil_recuperado_minimo(blob)
        return True

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
        limites = _limites_ano(veiculo)
        if limites is not None:
            ano_min, ano_max = limites
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
    if veiculo.get("busca_todos") and not out["marca"] and not out["modelo"]:
        out["descricao_veiculo"] = str(item.get("titulo") or "").strip()[:100]
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
    if LEILAO_VARREDURA_TODAS_FONTES:
        leiloeiros = list(LEILOEIROS_PRINCIPAIS)
        detrans = list(DETRAN_POR_ESTADO)
    else:
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


def reset_cache_coletores() -> None:
    """Limpa caches de coletores diretos (testes)."""
    global _SUMARE_LOTES_CACHE, _COLETORES_CACHE
    _SUMARE_LOTES_CACHE = None
    _COLETORES_CACHE = {}


def _carregar_cfg_coletor(caminho_rel: str) -> dict[str, Any]:
    cfg = ler_json(ROOT / caminho_rel, default={})
    if not isinstance(cfg, dict):
        cfg = {}
    if "lance_minimo_brl" not in cfg:
        cfg["lance_minimo_brl"] = LEILAO_COLETORES_LANCE_MIN_BRL
    if "exigir_documento" not in cfg:
        cfg["exigir_documento"] = LEILAO_COLETORES_EXIGIR_DOCUMENTO
    if "ativo" not in cfg:
        cfg["ativo"] = True
    return cfg


def _import_varredura(ref: str):
    modulo, nome = ref.split(":")
    import importlib

    mod = importlib.import_module(modulo)
    return getattr(mod, nome)


def obter_lotes_coletor(fonte: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Coleta lotes de um coletor direto (Copart/Superbid/Sodré). Cache por processo."""
    global _COLETORES_CACHE
    meta = _META_COLETORES.get(fonte)
    if not meta:
        return [], {"ativo": False, "erro": f"fonte desconhecida: {fonte}"}
    if fonte in _COLETORES_CACHE:
        return _COLETORES_CACHE[fonte]

    diag: dict[str, Any] = {
        "ativo": bool(meta["enabled"]()),
        "fonte": fonte,
        "leiloes_ok": 0,
        "leiloes_falha": 0,
        "lotes_veiculo": 0,
        "modo_coleta": None,
        "erro": None,
    }
    if not meta["enabled"]():
        _COLETORES_CACHE[fonte] = ([], diag)
        return _COLETORES_CACHE[fonte]

    try:
        cfg = _carregar_cfg_coletor(str(meta["catalogo"]))
        varredura = _import_varredura(str(meta["varredura"]))
        resultado = varredura(cfg)
        lotes = list(resultado.get("lotes") or [])
        diag.update(
            {
                "leiloes_ok": int(resultado.get("leiloes_coletados_ok") or 0),
                "leiloes_falha": int(resultado.get("leiloes_coleta_falha") or 0),
                "lotes_veiculo": len(lotes),
                "lotes_com_documento": resultado.get("lotes_com_documento"),
                "lotes_sem_documento": resultado.get("lotes_sem_documento"),
                "modo_coleta": resultado.get("modo_coleta"),
                "lance_minimo_brl": resultado.get("lance_minimo_brl"),
            }
        )
        try:
            escrever_json_atomico(
                ROOT / str(meta["snapshot"]),
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "diagnostico": diag,
                    "lotes": lotes[:80],
                    "resultado": {
                        k: resultado.get(k)
                        for k in (
                            "leiloes_encontrados",
                            "leiloes_coletados_ok",
                            "modo_coleta",
                            "lotes_veiculo_documento",
                        )
                    },
                },
            )
        except Exception as exc:
            logger.warning("snapshot %s: %s", fonte, exc)
        logger.info(
            "%s direto: %s lotes (modo=%s, ok=%s falha=%s)",
            meta["fonte_nome"],
            diag["lotes_veiculo"],
            diag.get("modo_coleta"),
            diag["leiloes_ok"],
            diag["leiloes_falha"],
        )
        _COLETORES_CACHE[fonte] = (lotes, diag)
        return _COLETORES_CACHE[fonte]
    except Exception as exc:
        logger.warning("%s direto indisponível: %s", fonte, exc)
        diag["erro"] = str(exc)
        _COLETORES_CACHE[fonte] = ([], diag)
        return _COLETORES_CACHE[fonte]


def obter_lotes_copart() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return obter_lotes_coletor("copart")


def obter_lotes_superbid() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return obter_lotes_coletor("superbid")


def obter_lotes_sodre() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return obter_lotes_coletor("sodre")


def obter_lotes_diretos() -> dict[str, tuple[list[dict[str, Any]], dict[str, Any]]]:
    """Todos os coletores diretos habilitados (exceto Sumaré, que tem cache próprio)."""
    return {nome: obter_lotes_coletor(nome) for nome in _META_COLETORES}


def _lote_direto_para_item(
    lote: dict[str, Any],
    veiculo: dict[str, Any],
    *,
    fonte: str,
) -> dict[str, Any] | None:
    meta = _META_COLETORES.get(fonte)
    if not meta:
        return None
    titulo = str(lote.get("titulo") or "")
    if not veiculo.get("busca_todos") and not _modelo_no_texto(titulo, veiculo):
        return None
    return lote_para_achado(
        lote,
        fonte_tipo=str(meta["fonte_tipo"]),
        fonte_id=str(meta["fonte_id"]),
        fonte_nome=str(meta["fonte_nome"]),
        dominio=str(meta["dominio"]),
        url_cadastro=str(meta["url_cadastro"]),
    )


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
    if not veiculo.get("busca_todos") and not _modelo_no_texto(titulo, veiculo):
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
    """Busca DDG em um domínio; DETRAN tenta query ampla se a específica vier vazia."""
    queries = [f"site:{dominio} {sufixo_query} {termo}".strip()]
    if tipo_fonte == "detran" and LEILAO_DETRAN_DDG_AMPLA:
        queries.append(f"site:{dominio} (leilão OR leilao) (veículo OR veiculo OR automóvel)")

    achados: list[dict[str, Any]] = []
    vistos_url: set[str] = set()
    for qi, query in enumerate(queries):
        brutos = buscar_duckduckgo(query, max_resultados=6)
        if diagnostico is not None:
            diagnostico["ddg_queries"] = diagnostico.get("ddg_queries", 0) + 1
            diagnostico["ddg_brutos"] = diagnostico.get("ddg_brutos", 0) + len(brutos)
            if tipo_fonte == "detran":
                diagnostico["ddg_detran_queries"] = diagnostico.get("ddg_detran_queries", 0) + 1
                diagnostico["ddg_detran_brutos"] = diagnostico.get("ddg_detran_brutos", 0) + len(brutos)
        for item in brutos:
            url = item.get("url", "")
            if dominio not in url or url in vistos_url:
                continue
            vistos_url.add(url)
            achados.append(
                {
                    "url": url,
                    "titulo": item.get("titulo") or url,
                    "snippet": item.get("snippet") or "",
                    "fonte_tipo": tipo_fonte,
                    "fonte_id": fonte_id,
                    "fonte_nome": fonte_nome,
                    "dominio": dominio,
                    "hash": _hash_url(url),
                    "query_ampla": qi > 0,
                    **({"uf": fonte_id} if tipo_fonte == "detran" else {}),
                }
            )
        # Só cai na query ampla se a específica não trouxe nada do domínio
        if achados:
            break
    return achados


def _ddg_status_atual() -> dict[str, Any]:
    if DDG_DISABLED:
        return {"ddg_status": "desabilitado", "ddg_nota": "DDG_DISABLED=1 — buscas web desligadas"}
    if circuit_breaker_ativo("leilao"):
        return {
            "ddg_status": "breaker",
            "ddg_nota": mensagem_circuit_breaker("leilao") or "circuit breaker ativo",
            "circuit_breaker_ativo": True,
            "circuit_breaker_msg": mensagem_circuit_breaker("leilao"),
        }
    return {"ddg_status": "ok", "ddg_nota": None}


def buscar_veiculo_em_fontes(
    veiculo: dict[str, Any],
    *,
    incluir_leiloeiros: bool = True,
    incluir_detran: bool = True,
    pausa_entre_fontes_seg: float = 0.8,
    lotes_sumare: list[dict[str, Any]] | None = None,
    diag_sumare: dict[str, Any] | None = None,
    lotes_diretos: dict[str, list[dict[str, Any]]] | None = None,
    diag_diretos: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Varre leiloeiros/DETRAN (rotacionados) + coletores diretos (Sumaré/Copart/…) + fallback DDG.
    Retorna {"achados": [...], "diagnostico": {...}}. Nunca lança exceção.
    """
    termo = montar_termo_busca(veiculo)
    termo_site = _termo_query_site(veiculo)
    if not termo.strip():
        return {"achados": [], "diagnostico": {"motivo": "termo vazio"}}

    vistos: set[str] = set()
    todos: list[dict[str, Any]] = []
    contadores: dict[str, Any] = {
        "ddg_queries": 0,
        "ddg_brutos": 0,
        "ddg_descartados_filtro": 0,
        "ddg_detran_queries": 0,
        "ddg_detran_brutos": 0,
        "ddg_fontes_puladas": 0,
        "sumare_candidatos": 0,
        "sumare_achados": 0,
        "sumare_detran_candidatos": 0,
        "sumare_detran_achados": 0,
        "copart_candidatos": 0,
        "copart_achados": 0,
        "superbid_candidatos": 0,
        "superbid_achados": 0,
        "sodre_candidatos": 0,
        "sodre_achados": 0,
        "diretos_candidatos": 0,
        "diretos_achados": 0,
    }
    fontes, meta_fontes = _fontes_da_rodada()
    if not incluir_leiloeiros:
        fontes = [f for f in fontes if f[1] != "leiloeiro"]
    if not incluir_detran:
        fontes = [f for f in fontes if f[1] != "detran"]

    ddg_info = _ddg_status_atual()
    pular_ddg = bool(
        DDG_DISABLED
        or (LEILAO_PULAR_DDG_SE_BREAKER and circuit_breaker_ativo("leilao"))
    )

    if lotes_sumare is None and LEILAO_INCLUIR_SUMARE_DIRETO:
        lotes_sumare, diag_sumare = obter_lotes_sumare()

    if lotes_diretos is None:
        lotes_diretos = {}
        diag_diretos = diag_diretos or {}
        for nome in _META_COLETORES:
            if _META_COLETORES[nome]["enabled"]():
                lots, diag = obter_lotes_coletor(nome)
                lotes_diretos[nome] = lots
                diag_diretos[nome] = diag
    diag_diretos = diag_diretos or {}

    for lote in lotes_sumare or []:
        contadores["sumare_candidatos"] += 1
        comitente = _normalizar(str(lote.get("comitente") or lote.get("tipo_comitente") or ""))
        eh_detran_sumare = "detran" in comitente
        if eh_detran_sumare:
            contadores["sumare_detran_candidatos"] += 1
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
        if eh_detran_sumare:
            contadores["sumare_detran_achados"] += 1
            item["fonte_nome"] = "Sumaré — DETRAN"
        todos.append(enriquecer_achado_leilao(item, veiculo))

    for fonte, lotes in (lotes_diretos or {}).items():
        chave_c = f"{fonte}_candidatos"
        chave_a = f"{fonte}_achados"
        for lote in lotes or []:
            contadores[chave_c] = contadores.get(chave_c, 0) + 1
            contadores["diretos_candidatos"] += 1
            item = _lote_direto_para_item(lote, veiculo, fonte=fonte)
            if not item:
                continue
            if not _relevante_para_veiculo(item, veiculo):
                continue
            h = item["hash"]
            if h in vistos:
                continue
            vistos.add(h)
            contadores[chave_a] = contadores.get(chave_a, 0) + 1
            contadores["diretos_achados"] += 1
            todos.append(enriquecer_achado_leilao(item, veiculo))

    achados_por_dominio: dict[str, int] = {}
    for fonte, tipo, fid in fontes:
        dominio = fonte.get("dominio", "")
        nome = fonte.get("nome", dominio)
        if not dominio:
            continue
        if tipo == "leiloeiro" and fid in _META_COLETORES and _META_COLETORES[fid]["enabled"]():
            continue
        if tipo == "leiloeiro" and fid == "sumare" and LEILAO_INCLUIR_SUMARE_DIRETO:
            continue
        if tipo == "detran" and not LEILAO_DETRAN_VIA_DDG:
            contadores["ddg_fontes_puladas"] = contadores.get("ddg_fontes_puladas", 0) + 1
            continue
        if pular_ddg:
            contadores["ddg_fontes_puladas"] = contadores.get("ddg_fontes_puladas", 0) + 1
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
                # Query ampla DETRAN: aceita página de leilão mesmo sem o modelo no título
                ampla = bool(item.pop("query_ampla", False))
                relevante = _relevante_para_veiculo(item, veiculo)
                if not relevante and not (
                    ampla
                    and tipo == "detran"
                    and any(
                        w in _normalizar(f"{item.get('titulo')} {item.get('snippet')}")
                        for w in ("leilao", "hasta", "lote", "edital")
                    )
                ):
                    contadores["ddg_descartados_filtro"] += 1
                    continue
                h = item["hash"]
                if h in vistos:
                    continue
                vistos.add(h)
                achados_por_dominio[dominio] = achados_por_dominio.get(dominio, 0) + 1
                todos.append(enriquecer_achado_leilao(item, veiculo))
        except Exception as exc:
            logger.warning("Fonte %s (%s) falhou: %s", nome, dominio, exc)
        if pausa_entre_fontes_seg > 0:
            time.sleep(pausa_entre_fontes_seg)

    if not pular_ddg:
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

    # Status final do DDG após as queries
    if ddg_info.get("ddg_status") == "ok":
        if contadores["ddg_queries"] and contadores["ddg_brutos"] == 0:
            ddg_info = {
                "ddg_status": "vazio",
                "ddg_nota": (
                    "DDG respondeu vazio em todas as queries "
                    "(rate limit, indexação fraca ou termo muito específico)"
                ),
            }
        elif contadores.get("ddg_fontes_puladas") and contadores["ddg_queries"] == 0:
            ddg_info = {
                "ddg_status": "pulado",
                "ddg_nota": "DDG pulado (breaker/desabilitado) — DETRAN via site: não consultado",
            }

    diagnostico: dict[str, Any] = {
        **contadores,
        **meta_fontes,
        **ddg_info,
        "fontes_consultadas": len(fontes),
        "achados_total": len(todos),
        "achados_ddg_por_dominio": achados_por_dominio,
        "circuit_breaker_ativo": circuit_breaker_ativo("leilao") or bool(ddg_info.get("circuit_breaker_ativo")),
        "circuit_breaker_msg": mensagem_circuit_breaker("leilao") or ddg_info.get("circuit_breaker_msg"),
        "sumare_coleta": diag_sumare or {},
        "coletores_diretos": diag_diretos,
        "detran_via_ddg": LEILAO_DETRAN_VIA_DDG,
        "detran_ddg_ampla": LEILAO_DETRAN_DDG_AMPLA,
    }
    return {"achados": todos, "diagnostico": diagnostico}
