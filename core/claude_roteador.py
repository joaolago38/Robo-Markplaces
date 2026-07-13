"""
core/claude_roteador.py
Ponto de mudança Haiku → modelo de vendas (Sonnet) para eficiência no ML.

Regra: Haiku no volume; Sonnet só quando a decisão impacta conversão/venda
e ainda há orçamento local suficiente.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("claude_roteador")

# Sinais de comprador / dúvida que exigem resposta melhor no ML
_RE_INTENCAO_VENDA = re.compile(
    r"("
    r"pre[cç]o|quanto\s+cust|valor\s+do|desconto|promo|"
    r"atacado|revenda|lote|quantidade|quantas?\s+unidade|"
    r"frete|cep|prazo|entrega|full|"
    r"comprar|fechamos|fecha\s|fechamento|pedido|"
    r"kit\s*\d+|montar\s+kit|escolh(o|er)\s+cor|"
    r"reclam|cancel|troca|devolver|garantia|"
    r"melhor\s+kit|qual\s+kit|indica|"
    r"nota\s+fiscal|cnpj|mei"
    r")",
    re.IGNORECASE,
)

_CANAIS_ML = frozenset(
    {
        "ml",
        "mercadolivre",
        "mercado_livre",
        "mercadolibre",
        "chat_ml",
        "manicures_ml",
    }
)


def _cfg():
    from core import config as cfg

    return cfg


def restante_orcamento_usd() -> float | None:
    """None se orçamento indisponível (não bloqueia escalonamento por piso)."""
    try:
        from core.claude_orcamento import resumo

        return float(resumo().get("restante_usd") or 0)
    except Exception:
        return None


def texto_indica_venda(texto: str | None) -> bool:
    return bool(_RE_INTENCAO_VENDA.search(texto or ""))


def canal_e_ml(canal: str | None) -> bool:
    c = (canal or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not c:
        return False
    if c in _CANAIS_ML:
        return True
    return "mercado" in c or c.endswith("_ml") or c.startswith("ml_")


def resolver_modelo_vendas(
    *,
    proposito: str,
    canal: str | None = None,
    texto: str | None = None,
    preco_produto: float | None = None,
    sinal_ads: dict[str, Any] | None = None,
    intencao: str | None = None,
    converter: bool | None = None,
) -> dict[str, Any]:
    """
    Decide Haiku vs CLAUDE_MODELO_VENDAS.

    Pontos de mudança (escala para Sonnet):
      1. oferta_conversao — escolha de kit/copy que dispara o funil (se flag)
      2. chat_ml — intenção de compra / ticket alto / canal ML
      3. resposta_lead — lead com converter + intenção de preço/atacado/interesse quente
      4. ads_status critico/alerta na oferta — copy mais cuidadosa

    Sempre fica em Haiku se:
      - CLAUDE_ESCALONAR_ML=0
      - restante orçamento < CLAUDE_ESCALONAR_RESTANTE_MIN_USD
    """
    c = _cfg()
    rapido = str(getattr(c, "CLAUDE_MODELO_RAPIDO", "claude-haiku-4-5") or "claude-haiku-4-5")
    vendas = str(getattr(c, "CLAUDE_MODELO_VENDAS", "claude-sonnet-4-5") or "claude-sonnet-4-5")
    base = {
        "modelo": rapido,
        "escalou": False,
        "motivo": "haiku_padrao",
        "proposito": proposito,
        "forcar_modelo": False,
    }

    if not bool(getattr(c, "CLAUDE_ESCALONAR_ML", True)):
        base["motivo"] = "escalonamento_desligado"
        return base

    piso = float(getattr(c, "CLAUDE_ESCALONAR_RESTANTE_MIN_USD", 1.5) or 1.5)
    resta = restante_orcamento_usd()
    if resta is not None and resta < piso:
        base["motivo"] = f"orcamento_baixo:{resta:.2f}<{piso:.2f}"
        return base

    prop = (proposito or "").strip().lower()
    motivos: list[str] = []

    if prop in ("oferta_conversao", "oferta", "escolher_oferta"):
        if bool(getattr(c, "CLAUDE_ESCALONAR_OFERTA", True)):
            motivos.append("oferta_conversao_ml")
        status = ""
        if isinstance(sinal_ads, dict):
            sust = sinal_ads.get("sustentabilidade") or sinal_ads
            if isinstance(sust, dict):
                status = str(sust.get("status") or "").lower()
            else:
                status = str(sinal_ads.get("status") or "").lower()
        if status in ("alerta", "critico"):
            motivos.append(f"ads_{status}")

    if prop in ("chat_ml", "chat", "responder_chat", "resposta_chat_ml"):
        if bool(getattr(c, "CLAUDE_ESCALONAR_CHAT", True)):
            if canal_e_ml(canal) or prop.startswith("chat_ml") or prop == "resposta_chat_ml":
                if texto_indica_venda(texto):
                    motivos.append("intencao_compra_ml")
                preco_min = float(getattr(c, "CLAUDE_ESCALONAR_PRECO_MIN", 55.0) or 55.0)
                try:
                    preco = float(preco_produto) if preco_produto is not None else 0.0
                except (TypeError, ValueError):
                    preco = 0.0
                if preco >= preco_min:
                    motivos.append(f"ticket_alto:{preco:.2f}")

    if prop in ("resposta_lead", "lead_conversao"):
        intents_quentes = {"preco", "atacado", "interesse"}
        if converter and (intencao or "").lower() in intents_quentes:
            motivos.append(f"lead_{intencao}")
        elif texto_indica_venda(texto):
            motivos.append("lead_texto_compra")

    if not motivos:
        return base

    out = {
        "modelo": vendas,
        "escalou": True,
        "motivo": "+".join(motivos),
        "proposito": proposito,
        "forcar_modelo": True,  # vale mesmo com CLAUDE_ECONOMICO=1
        "restante_usd": resta,
    }
    logger.info(
        "Claude escalou %s → %s (%s)",
        rapido,
        vendas,
        out["motivo"],
    )
    return out
