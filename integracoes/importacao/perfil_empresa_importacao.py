"""
integracoes/importacao/perfil_empresa_importacao.py
Busca dados do importador (CNPJ) via BrasilAPI com fallback ReceitaWS.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from core.atomic_io import ler_json
from core.config import IMPORTACAO_OPERACAO_FIXA_CATALOGO, ROOT
from core.http_client import request

logger = logging.getLogger("perfil_empresa_importacao")


def _limpar_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj or "")


def _carregar_operacao_fixa() -> dict[str, Any]:
    return ler_json(ROOT / IMPORTACAO_OPERACAO_FIXA_CATALOGO, default={})


def _normalizar_brasilapi(data: dict[str, Any]) -> dict[str, Any]:
    endereco = ", ".join(
        p
        for p in (
            data.get("logradouro"),
            data.get("numero"),
            data.get("bairro"),
            f"{data.get('municipio', '')}/{data.get('uf', '')}".strip("/"),
            data.get("cep"),
        )
        if p
    )
    regime = "simples" if data.get("opcao_pelo_simples") else "lucro_presumido"
    return {
        "cnpj": _limpar_cnpj(str(data.get("cnpj") or "")),
        "razao_social": str(data.get("razao_social") or data.get("nome_fantasia") or "").strip(),
        "endereco": endereco,
        "regime_tributario": regime,
        "fonte": "brasilapi",
        "ok": True,
    }


def _normalizar_receitaws(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("status") == "ERROR":
        return {"ok": False, "motivo": data.get("message", "ReceitaWS erro")}
    endereco = ", ".join(
        p
        for p in (
            data.get("logradouro"),
            data.get("numero"),
            data.get("bairro"),
            f"{data.get('municipio', '')}/{data.get('uf', '')}".strip("/"),
            data.get("cep"),
        )
        if p
    )
    regime = "simples" if str(data.get("simples", "")).lower() in ("sim", "true", "1") else "lucro_presumido"
    return {
        "cnpj": _limpar_cnpj(str(data.get("cnpj") or "")),
        "razao_social": str(data.get("nome") or data.get("fantasia") or "").strip(),
        "endereco": endereco,
        "regime_tributario": regime,
        "fonte": "receitaws",
        "ok": True,
    }


def buscar_empresa_por_cnpj(cnpj: str) -> dict[str, Any]:
    """Consulta BrasilAPI; fallback ReceitaWS. Nunca lança exceção."""
    cnpj_limpo = _limpar_cnpj(cnpj)
    if len(cnpj_limpo) != 14:
        return {"ok": False, "motivo": "CNPJ inválido", "cnpj": cnpj_limpo}

    try:
        r = request("GET", f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}", timeout=15)
        if r.status_code == 200:
            out = _normalizar_brasilapi(r.json())
            if out.get("ok"):
                return out
    except Exception as exc:
        logger.warning("BrasilAPI CNPJ %s falhou: %s", cnpj_limpo, exc)

    try:
        r = request("GET", f"https://www.receitaws.com.br/v1/cnpj/{cnpj_limpo}", timeout=20)
        if r.status_code == 200:
            out = _normalizar_receitaws(r.json())
            if out.get("ok"):
                return out
    except Exception as exc:
        logger.warning("ReceitaWS CNPJ %s falhou: %s", cnpj_limpo, exc)

    fixa = _carregar_operacao_fixa()
    return {
        "ok": False,
        "cnpj": cnpj_limpo,
        "razao_social": fixa.get("razao_social") or "",
        "endereco": fixa.get("endereco") or "",
        "regime_tributario": fixa.get("regime_tributario") or "lucro_presumido",
        "fonte": "manual",
        "motivo": "APIs indisponíveis — preencha manualmente",
    }


def obter_perfil_importador(*, atualizar_cnpj: bool = True) -> dict[str, Any]:
    """
    Perfil fixo da operação + dados do CNPJ quando disponível.
    """
    fixa = _carregar_operacao_fixa()
    cnpj = _limpar_cnpj(str(fixa.get("cnpj") or ""))
    perfil: dict[str, Any] = {
        "ok": True,
        "cnpj": cnpj,
        "razao_social": fixa.get("razao_social") or "",
        "endereco": fixa.get("endereco") or "",
        "regime_tributario": fixa.get("regime_tributario") or "lucro_presumido",
        "modal_transporte": fixa.get("modal_transporte") or "aereo",
        "aeroporto_desembaraco": fixa.get("aeroporto_desembaraco") or {},
        "destino_entrega": fixa.get("destino_entrega") or {},
        "responsavel": fixa.get("responsavel") or {},
        "aviso_legal": fixa.get("aviso_legal") or "",
        "fonte_empresa": "catalogo",
    }

    if atualizar_cnpj and cnpj:
        api = buscar_empresa_por_cnpj(cnpj)
        if api.get("ok"):
            perfil.update(
                {
                    "razao_social": api.get("razao_social") or perfil["razao_social"],
                    "endereco": api.get("endereco") or perfil["endereco"],
                    "regime_tributario": api.get("regime_tributario") or perfil["regime_tributario"],
                    "fonte_empresa": api.get("fonte") or "api",
                }
            )
        elif api.get("motivo"):
            perfil["aviso_cnpj"] = api["motivo"]

    return perfil
