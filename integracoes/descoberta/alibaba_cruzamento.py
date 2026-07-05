"""
integracoes/descoberta/alibaba_cruzamento.py
Cruza oportunidades de marketplace com fornecedores no Alibaba.com.
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("descoberta_alibaba")


def _formatar_preco_usd(preco: Any) -> str:
    if preco is None:
        return "preço n/d"
    try:
        return f"US$ {float(preco):.2f}"
    except (TypeError, ValueError):
        return "preço n/d"


def _formatar_moq(moq: Any) -> str:
    if moq is None:
        return "MOQ n/d"
    try:
        return f"MOQ {int(moq)}"
    except (TypeError, ValueError):
        return "MOQ n/d"


def _termo_para_oportunidade(oportunidade: dict[str, Any], nicho: dict[str, Any]) -> str:
    for chave in ("termo_alibaba", "termo_alibaba_en", "termo_busca_en"):
        t = str(oportunidade.get(chave) or nicho.get(chave) or "").strip()
        if t:
            return t
    produto = str(oportunidade.get("produto") or "").strip()
    if produto:
        return produto
    return str(nicho.get("termo_busca") or nicho.get("nome") or "").strip()


def buscar_fornecedores_alibaba(
    termo: str,
    *,
    preco_max_usd: float | None = None,
    moq_max: int | None = None,
    max_resultados: int = 5,
    pausa_seg: float = 0,
) -> list[dict[str, Any]]:
    """Busca amostra de fornecedores no Alibaba. Nunca lança exceção."""
    from integracoes.alibaba.busca import buscar_alibaba_direto

    termo = (termo or "").strip()
    if not termo:
        return []
    if pausa_seg > 0:
        time.sleep(pausa_seg)

    try:
        brutos = buscar_alibaba_direto(termo, max_resultados=max(8, max_resultados * 2))
    except Exception as exc:
        logger.warning("Alibaba cruzamento falhou termo=%r: %s", termo[:60], exc)
        return []

    filtrados: list[dict[str, Any]] = []
    for item in brutos:
        preco = item.get("preco_usd")
        moq = item.get("moq")
        if preco_max_usd is not None and preco is not None:
            try:
                if float(preco) > float(preco_max_usd):
                    continue
            except (TypeError, ValueError):
                pass
        if moq_max is not None and moq is not None:
            try:
                if int(moq) > int(moq_max):
                    continue
            except (TypeError, ValueError):
                pass
        filtrados.append(item)

    filtrados.sort(key=lambda x: (x.get("preco_usd") is None, float(x.get("preco_usd") or 9999)))
    return filtrados[:max_resultados]


def cruzar_oportunidades_com_alibaba(
    nicho: dict[str, Any],
    analise: dict[str, Any],
    *,
    max_por_oportunidade: int = 3,
    pausa_seg: float = 0.5,
) -> dict[str, Any]:
    """
    Para cada oportunidade da análise, busca fornecedores no Alibaba.
    Retorna estrutura pronta para logs, snapshot e Telegram.
    """
    from core.config import DESCOBERTA_ALIBABA_MOQ_MAX, DESCOBERTA_ALIBABA_PRECO_MAX_USD

    preco_max = nicho.get("alibaba_preco_max_usd", DESCOBERTA_ALIBABA_PRECO_MAX_USD)
    moq_max = nicho.get("alibaba_moq_max", DESCOBERTA_ALIBABA_MOQ_MAX)
    try:
        preco_max_f = float(preco_max) if preco_max is not None else None
    except (TypeError, ValueError):
        preco_max_f = None
    try:
        moq_max_i = int(moq_max) if moq_max is not None else None
    except (TypeError, ValueError):
        moq_max_i = None

    oportunidades = analise.get("oportunidades") or []
    cruzadas: list[dict[str, Any]] = []
    total_fornecedores = 0

    for i, op in enumerate(oportunidades[:5]):
        if not isinstance(op, dict):
            continue
        termo = _termo_para_oportunidade(op, nicho)
        if not termo:
            continue
        if i > 0 and pausa_seg > 0:
            time.sleep(pausa_seg)
        fornecedores = buscar_fornecedores_alibaba(
            termo,
            preco_max_usd=preco_max_f,
            moq_max=moq_max_i,
            max_resultados=max_por_oportunidade,
        )
        total_fornecedores += len(fornecedores)
        cruzadas.append(
            {
                "produto": op.get("produto"),
                "confianca": op.get("confianca"),
                "sinal_marketplace": op.get("sinal"),
                "faixa_preco_sugerida": op.get("faixa_preco_sugerida"),
                "termo_alibaba": termo,
                "fornecedores": [
                    {
                        "titulo": f.get("titulo"),
                        "preco_usd": f.get("preco_usd"),
                        "moq": f.get("moq"),
                        "distribuidor": f.get("distribuidor"),
                        "url": f.get("url"),
                    }
                    for f in fornecedores
                ],
            }
        )

    return {
        "total_oportunidades": len(cruzadas),
        "total_fornecedores": total_fornecedores,
        "oportunidades": cruzadas,
    }


def estimar_margem_importacao(
    preco_venda_brl: float,
    preco_alibaba_usd: float,
    *,
    cambio_usd_brl: float | None = None,
    taxa_marketplace_pct: float | None = None,
) -> dict[str, Any]:
    """Estimativa simples de margem para painel de decisão."""
    from core.config import DESCOBERTA_CAMBIO_USD_BRL, REGRAS

    cambio = cambio_usd_brl if cambio_usd_brl is not None else DESCOBERTA_CAMBIO_USD_BRL
    taxa = taxa_marketplace_pct if taxa_marketplace_pct is not None else float(
        REGRAS.get("taxa_marketplace_pct", 14)
    )
    try:
        venda = float(preco_venda_brl)
        custo_usd = float(preco_alibaba_usd)
    except (TypeError, ValueError):
        return {"ok": False}
    if venda <= 0 or custo_usd <= 0:
        return {"ok": False}
    custo_brl = custo_usd * cambio
    liquido = venda * (1 - taxa / 100)
    margem_brl = round(liquido - custo_brl, 2)
    margem_pct = round(margem_brl / venda * 100, 1)
    return {
        "ok": True,
        "preco_venda_brl": round(venda, 2),
        "custo_import_brl": round(custo_brl, 2),
        "liquido_apos_taxa_brl": round(liquido, 2),
        "margem_brl": margem_brl,
        "margem_pct": margem_pct,
        "cambio_usd_brl": cambio,
        "taxa_marketplace_pct": taxa,
    }


def formatar_fornecedor_log(item: dict[str, Any]) -> str:
    return (
        f"{_formatar_preco_usd(item.get('preco_usd'))} | "
        f"{_formatar_moq(item.get('moq'))} | "
        f"{item.get('distribuidor') or 'distribuidor n/d'} | "
        f"{item.get('url') or ''}"
    )
