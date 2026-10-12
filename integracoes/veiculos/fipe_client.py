"""
integracoes/veiculos/fipe_client.py
Consulta Tabela FIPE (API Parallelum) com cache em memória.
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from typing import Any

from core.config import FIPE_API_BASE, FIPE_PAUSA_ENTRE_CHAMADAS_SEG
from core.http_client import request

logger = logging.getLogger("fipe_client")

_CACHE: dict[str, tuple[float, Any]] = {}
_ALIASES_MARCA: dict[str, str] = {
    "vw": "Volkswagen",
    "gm": "Chevrolet",
    "chevrolet": "Chevrolet",
    "citroen": "Citroën",
    "mercedes": "Mercedes-Benz",
    "m.benz": "Mercedes-Benz",
    "mbenz": "Mercedes-Benz",
    "land rover": "Land Rover",
    "mini": "Mini",
}


def _normalizar(texto: str) -> str:
    txt = unicodedata.normalize("NFKD", (texto or "").strip().lower())
    return "".join(c for c in txt if not unicodedata.combining(c))


def _cache_get(chave: str) -> Any | None:
    item = _CACHE.get(chave)
    if not item:
        return None
    expira, valor = item
    if time.monotonic() > expira:
        _CACHE.pop(chave, None)
        return None
    return valor


def _cache_set(chave: str, valor: Any, ttl_seg: float = 86400) -> None:
    _CACHE[chave] = (time.monotonic() + ttl_seg, valor)


def _get_json(path: str) -> Any:
    url = f"{FIPE_API_BASE.rstrip('/')}/{path.lstrip('/')}"
    chave = f"GET:{url}"
    cached = _cache_get(chave)
    if cached is not None:
        return cached
    r = request("GET", url, timeout=20)
    if r.status_code != 200:
        logger.warning("FIPE %s retornou %s", path, r.status_code)
        return None
    data = r.json()
    _cache_set(chave, data)
    if FIPE_PAUSA_ENTRE_CHAMADAS_SEG > 0:
        time.sleep(FIPE_PAUSA_ENTRE_CHAMADAS_SEG)
    return data


def listar_marcas() -> list[dict[str, Any]]:
    data = _get_json("carros/marcas")
    return data if isinstance(data, list) else []


def _resolver_marca(marca: str) -> dict[str, Any] | None:
    alvo = _normalizar(marca)
    if not alvo:
        return None
    alvo = _ALIASES_MARCA.get(alvo, marca).strip()
    alvo_norm = _normalizar(alvo)
    marcas = listar_marcas()
    for item in marcas:
        nome = str(item.get("nome") or "")
        if _normalizar(nome) == alvo_norm or alvo_norm in _normalizar(nome):
            return item
    for item in marcas:
        nome = str(item.get("nome") or "")
        if alvo_norm.split()[0] in _normalizar(nome):
            return item
    return None


def _tokens_modelo(texto: str) -> set[str]:
    stop = {"de", "do", "da", "com", "flex", "aut", "mec", "ano", "total", "fire", "evo", "way"}
    partes = re.findall(r"[a-z0-9]+", _normalizar(texto))
    return {p for p in partes if len(p) > 1 and p not in stop}


def _encontrar_modelo(marca_id: str, titulo: str, modelo_hint: str = "") -> dict[str, Any] | None:
    chave = f"modelos:{marca_id}"
    modelos_data = _cache_get(chave)
    if modelos_data is None:
        modelos_data = _get_json(f"carros/marcas/{marca_id}/modelos")
        if modelos_data is None:
            return None
        _cache_set(chave, modelos_data)
    modelos = modelos_data.get("modelos") if isinstance(modelos_data, dict) else modelos_data
    if not isinstance(modelos, list):
        return None

    texto = f"{titulo} {modelo_hint}".strip()
    tokens = _tokens_modelo(texto)
    melhor: dict[str, Any] | None = None
    melhor_score = 0
    for modelo in modelos:
        nome = str(modelo.get("nome") or "")
        nome_tokens = _tokens_modelo(nome)
        if not nome_tokens:
            continue
        comum = len(tokens & nome_tokens)
        score = comum / max(len(nome_tokens), 1)
        if nome_tokens.issubset(tokens):
            score += 0.5
        if score > melhor_score:
            melhor_score = score
            melhor = modelo
    if melhor and melhor_score >= 0.35:
        return melhor
    return None


def _extrair_ano(ano_texto: str) -> int | None:
    nums = [int(x) for x in re.findall(r"\b(?:19|20)\d{2}\b", ano_texto or "")]
    return nums[0] if nums else None


def _escolher_ano_id(anos: list[dict[str, Any]], ano_alvo: int) -> str | None:
    candidatos: list[tuple[int, str]] = []
    for item in anos:
        codigo = str(item.get("codigo") or "")
        nome = str(item.get("nome") or "")
        ano = _extrair_ano(nome) or _extrair_ano(codigo)
        if ano is not None:
            candidatos.append((ano, codigo))
    if not candidatos:
        return None
    candidatos.sort(key=lambda x: abs(x[0] - ano_alvo))
    return candidatos[0][1]


def parse_valor_fipe(valor: str) -> float:
    limpo = re.sub(r"[^\d,]", "", (valor or "").replace(".", ""))
    if not limpo:
        return 0.0
    return float(limpo.replace(",", "."))


def consultar_preco_fipe(
    *,
    marca: str,
    titulo: str,
    ano_texto: str,
    modelo_hint: str = "",
) -> dict[str, Any] | None:
    """
    Retorna preço FIPE estimado para carro (marca + título + ano).
    """
    marca_item = _resolver_marca(marca)
    if not marca_item:
        return None
    marca_id = str(marca_item.get("codigo") or "")
    modelo_item = _encontrar_modelo(marca_id, titulo, modelo_hint)
    if not modelo_item:
        return None
    modelo_id = str(modelo_item.get("codigo") or "")
    ano_alvo = _extrair_ano(ano_texto)
    if ano_alvo is None:
        return None

    anos = _get_json(f"carros/marcas/{marca_id}/modelos/{modelo_id}/anos")
    if not isinstance(anos, list) or not anos:
        return None
    ano_id = _escolher_ano_id(anos, ano_alvo)
    if not ano_id:
        return None

    info = _get_json(f"carros/marcas/{marca_id}/modelos/{modelo_id}/anos/{ano_id}")
    if not isinstance(info, dict):
        return None
    valor = parse_valor_fipe(str(info.get("Valor") or info.get("valor") or ""))
    if valor <= 0:
        return None
    return {
        "valor_fipe": valor,
        "marca_fipe": marca_item.get("nome"),
        "modelo_fipe": modelo_item.get("nome"),
        "ano_fipe": info.get("AnoModelo") or ano_alvo,
        "combustivel": info.get("Combustivel"),
        "codigo_fipe": info.get("CodigoFipe"),
    }
