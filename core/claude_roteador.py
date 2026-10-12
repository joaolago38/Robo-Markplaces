"""
core/claude_roteador.py
Ponto de mudança Haiku → modelo de vendas (Sonnet) para eficiência no ML.

Regra: Haiku no volume; Sonnet quando a decisão cruza o algoritmo do ML
(ranking, Ads, preço, listing) ou conversão quente — e ainda há orçamento.
O gestor autoriza o FAZER; o modelo não publica.
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

# Decisões que cruzam ranking/reputação/Ads/preço do ML → Sonnet (gestor decide).
_RE_SONNET_ALGORITMO_ML = re.compile(
    r"("
    r"ruptura|guerra|"
    r"panorama|analise_ml|sintese_ml|"
    r"pricing|precos|repricing|"
    r"ads_gatilho|midia_paga|"
    r"auditor_anuncio|otimizar_listing|"
    r"monitor_concorrentes|analise_loja|"
    r"descoberta|inteligencia_precos|"
    r"playbook|demanda_alta|"
    r"acetona"
    r")",
    re.IGNORECASE,
)


def proposito_exige_sonnet(proposito: str | None) -> bool:
    return bool(_RE_SONNET_ALGORITMO_ML.search(proposito or ""))


def resolver_modelo_chamada(
    *,
    proposito: str | None = None,
    modelo: str | None = None,
    forcar_modelo: bool = False,
) -> tuple[str | None, bool]:
    """
    Haiku no volume; Sonnet se o propósito cruzar o algoritmo do ML.
    Quem já passou forcar_modelo+modelo não é sobrescrito.
    """
    if forcar_modelo and str(modelo or "").strip():
        return modelo, True
    if not str(proposito or "").strip():
        return modelo, forcar_modelo
    rota = resolver_modelo_vendas(proposito=str(proposito))
    if rota.get("escalou"):
        return rota.get("modelo") or modelo, True
    escolhido = modelo or rota.get("modelo")
    return escolhido, False


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
    estoque: int | None = None,
    analise: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Decide Haiku vs CLAUDE_MODELO_VENDAS.

    Preferência: se `analise` (ou análise gerada) estiver em nível **alto**,
    sobe para o modelo de vendas — desde que orçamento permita.
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
        "analise": None,
    }

    if not bool(getattr(c, "CLAUDE_ESCALONAR_ML", True)):
        base["motivo"] = "escalonamento_desligado"
        return base

    piso = float(getattr(c, "CLAUDE_ESCALONAR_RESTANTE_MIN_USD", 4.0) or 4.0)
    resta = restante_orcamento_usd()
    if resta is not None and resta < piso:
        base["motivo"] = f"orcamento_baixo:{resta:.2f}<{piso:.2f}"
        return base

    if proposito_exige_sonnet(proposito):
        return {
            "modelo": vendas,
            "escalou": True,
            "motivo": "complexidade_algoritmo_ml",
            "proposito": proposito,
            "forcar_modelo": True,
            "restante_usd": resta,
            "analise": analise,
        }

    if analise is None:
        try:
            from core.claude_analise_vendas import analisar_oportunidade_ml

            analise = analisar_oportunidade_ml(
                texto=texto,
                canal=canal,
                preco_produto=preco_produto,
                estoque=estoque,
                proposito=proposito,
                intencao=intencao,
                converter=converter,
                sinal_ads=sinal_ads,
            )
        except Exception as exc:
            logger.warning("analise_oportunidade_ml falhou: %s", exc)
            analise = None
    base["analise"] = analise

    motivos: list[str] = []
    if isinstance(analise, dict) and analise.get("deve_aumentar_ia"):
        motivos.append(f"analise_alta:{analise.get('score', 0)}")

    prop = (proposito or "").strip().lower()

    # Regras legado (ainda somam motivos se análise não marcou alto)
    if prop in ("oferta_conversao", "oferta", "escolher_oferta"):
        so_calor = bool(getattr(c, "CLAUDE_ESCALONAR_OFERTA_SO_CALOR", True))
        status = ""
        if isinstance(sinal_ads, dict):
            sust = sinal_ads.get("sustentabilidade") or sinal_ads
            if isinstance(sust, dict):
                status = str(sust.get("status") or "").lower()
            else:
                status = str(sinal_ads.get("status") or sinal_ads.get("status_sustentavel") or "").lower()
        if status in ("alerta", "critico"):
            motivos.append(f"ads_{status}")
        elif bool(getattr(c, "CLAUDE_ESCALONAR_OFERTA", True)) and not so_calor:
            # Modo antigo: sempre Sonnet na oferta
            motivos.append("oferta_conversao_ml")
        elif (
            bool(getattr(c, "CLAUDE_ESCALONAR_OFERTA", True))
            and so_calor
            and isinstance(analise, dict)
            and analise.get("deve_aumentar_ia")
        ):
            motivos.append("oferta_conversao_calor")
        # se so_calor e análise não alta e ads ok → fica Haiku (sem motivo extra)

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
        intents_quentes = {"preco", "atacado"}  # interesse sozinho não escala (economiza)
        if converter and (intencao or "").lower() in intents_quentes:
            motivos.append(f"lead_{intencao}")
        elif converter and texto_indica_venda(texto):
            motivos.append("lead_texto_compra")

    # Dedup preservando ordem
    vistos: set[str] = set()
    motivos_u: list[str] = []
    for m in motivos:
        if m not in vistos:
            vistos.add(m)
            motivos_u.append(m)
    motivos = motivos_u

    if not motivos:
        if isinstance(analise, dict):
            base["motivo"] = f"haiku:{analise.get('resumo') or analise.get('nivel')}"
        return base

    out = {
        "modelo": vendas,
        "escalou": True,
        "motivo": "+".join(motivos),
        "proposito": proposito,
        "forcar_modelo": True,
        "restante_usd": resta,
        "analise": analise,
    }
    logger.info(
        "Claude escalou %s → %s (%s)",
        rapido,
        vendas,
        out["motivo"],
    )
    return out
