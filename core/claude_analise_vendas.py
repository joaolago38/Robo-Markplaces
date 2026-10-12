"""
core/claude_analise_vendas.py
Termômetros de conversão manicures:

  • captacao (Instagram/Facebook/Ads) — traz lead / tráfego pago
  • fechamento (Mercado Livre) — onde a venda acontece = termômetro principal

A dosagem de IA (Haiku → Sonnet) é mais exigida no fechamento ML.
A captação Meta aumenta a pressão sobre o ML (mais precisão no chat/oferta)
quando há gasto e leads, mas sozinha não substitui o termômetro de vendas.
"""
from __future__ import annotations

import re
from typing import Any

from core.claude_roteador import canal_e_ml, texto_indica_venda

_RE_FORTE = re.compile(
    r"("
    r"comprar|fechamos|fecha\s|fechamento|quero\s+levar|vou\s+levar|"
    r"atacado|revenda|lote\s*\d+|quantas?\s+unidade|kit\s*\d+\s*un|"
    r"desconto|melhor\s+pre[cç]o|negocia|"
    r"reclam|cancel|troca|devolver|"
    r"cnpj|nota\s+fiscal|mei"
    r")",
    re.IGNORECASE,
)

_RE_MEDIO = re.compile(
    r"("
    r"pre[cç]o|quanto\s+cust|valor|"
    r"frete|cep|prazo|entrega|full|"
    r"escolh(o|er)\s+cor|montar\s+kit|qual\s+kit|indica|"
    r"parcela|pix|boleto"
    r")",
    re.IGNORECASE,
)

_CANAIS_CAPTACAO = frozenset({"facebook", "instagram", "meta", "fb", "ig", "whatsapp", "telegram"})


def _cfg():
    from core import config as cfg

    return cfg


def _preco(valor: Any) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


def _papel(
    *,
    canal: str | None,
    proposito: str | None,
) -> str:
    """fechamento_ml | captacao_meta | misto"""
    prop = (proposito or "").strip().lower()
    c = (canal or "").strip().lower()
    if prop in ("chat_ml", "resposta_chat_ml", "responder_chat") or canal_e_ml(canal):
        return "fechamento_ml"
    if prop in ("oferta_conversao", "oferta", "escolher_oferta"):
        return "misto"  # decide o que vai para o ML
    if prop in ("resposta_lead", "lead_conversao") or c in _CANAIS_CAPTACAO:
        return "captacao_meta"
    return "misto"


def analisar_oportunidade_ml(
    *,
    texto: str | None = None,
    canal: str | None = None,
    preco_produto: float | None = None,
    estoque: int | None = None,
    proposito: str | None = None,
    intencao: str | None = None,
    converter: bool | None = None,
    sinal_ads: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Score 0–100 + níveis.

    deve_aumentar_ia (Sonnet) é verdadeiro sobretudo quando o papel é
    fechamento_ml (ou misto/oferta) e o calor está alto — inclusive se a
    captacao Meta estiver 'pressionando' (gasto alto / ROAS real fraco).
    """
    c = _cfg()
    limiar_alto = int(getattr(c, "CLAUDE_ANALISE_SCORE_ALTO", 70) or 70)
    limiar_medio = int(getattr(c, "CLAUDE_ANALISE_SCORE_MEDIO", 40) or 40)
    limiar_alto_captacao = int(getattr(c, "CLAUDE_ANALISE_SCORE_ALTO_CAPTACAO", 85) or 85)
    preco_min = float(getattr(c, "CLAUDE_ESCALONAR_PRECO_MIN", 55.0) or 55.0)
    gasto_pressao = float(getattr(c, "CLAUDE_ANALISE_GASTO_META_PRESSAO", 30.0) or 30.0)

    papel = _papel(canal=canal, proposito=proposito)
    score = 0
    fatores: list[str] = []
    txt = (texto or "").strip()
    prop = (proposito or "").strip().lower()

    # ——— Termômetro principal: FECHAMENTO ML ———
    if papel == "fechamento_ml":
        score += 25
        fatores.append("termometro_fechamento_ml:+25")
    elif papel == "misto":
        score += 15
        fatores.append("termometro_misto_oferta:+15")
    else:
        score += 5
        fatores.append("termometro_captacao:+5")

    if prop in ("oferta_conversao", "oferta", "escolher_oferta"):
        score += 30
        fatores.append("escolha_oferta_para_ml:+30")

    if _RE_FORTE.search(txt):
        score += 30 if papel == "fechamento_ml" else 18
        fatores.append("sinal_compra_forte")
    elif _RE_MEDIO.search(txt) or texto_indica_venda(txt):
        score += 20 if papel == "fechamento_ml" else 12
        fatores.append("sinal_compra_medio")

    if len(txt) >= 80:
        score += 8
        fatores.append("mensagem_detalhada:+8")
    elif len(txt) >= 40:
        score += 4
        fatores.append("mensagem_media:+4")

    preco = _preco(preco_produto)
    if preco >= preco_min:
        score += 15
        fatores.append(f"ticket_alto:{preco:.0f}:+15")
    elif preco >= preco_min * 0.7:
        score += 8
        fatores.append(f"ticket_medio:{preco:.0f}:+8")

    est = int(estoque if estoque is not None else -1)
    if 0 < est <= 5:
        score += 10
        fatores.append("estoque_baixo:+10")
    elif est > 5:
        score += 3
        fatores.append("estoque_ok:+3")

    inten = (intencao or "").strip().lower()
    if converter and inten in {"preco", "atacado"}:
        # Lead Meta quente → copy precisa empurrar para o ML
        score += 20 if papel == "captacao_meta" else 25
        fatores.append(f"lead_{inten}")
    elif converter and inten == "interesse":
        score += 8
        fatores.append("lead_interesse:+8")
    elif converter:
        score += 6
        fatores.append("lead_converter:+6")

    # ——— Pressão da CAPTAÇÃO Meta sobre o fechamento ML ———
    gasto = 0.0
    roas_real = None
    status_ads = ""
    compras_pixel = 0.0
    if isinstance(sinal_ads, dict):
        try:
            gasto = float(sinal_ads.get("gasto") or 0)
        except (TypeError, ValueError):
            gasto = 0.0
        try:
            compras_pixel = float(sinal_ads.get("compras") or 0)
        except (TypeError, ValueError):
            compras_pixel = 0.0
        if sinal_ads.get("roas_real") is not None:
            try:
                roas_real = float(sinal_ads.get("roas_real"))
            except (TypeError, ValueError):
                roas_real = None
        sust = sinal_ads.get("sustentabilidade") or {}
        if isinstance(sust, dict):
            status_ads = str(sust.get("status") or sinal_ads.get("status_sustentavel") or "").lower()
            if roas_real is None and sust.get("roas_real") is not None:
                try:
                    roas_real = float(sust.get("roas_real"))
                except (TypeError, ValueError):
                    pass
        else:
            status_ads = str(sinal_ads.get("status_sustentavel") or "").lower()

    if gasto >= gasto_pressao:
        # Tráfego pago ativo → fechamento ML deve ser mais preciso
        bonus = 18 if papel == "fechamento_ml" else 10
        score += bonus
        fatores.append(f"captacao_meta_gasto:{gasto:.0f}:+{bonus}")
    if status_ads == "critico":
        # Ads gasta mal vs ML → ML chat/oferta precisa recuperar conversão
        bonus = 22 if papel in ("fechamento_ml", "misto") else 8
        score += bonus
        fatores.append(f"pressao_ads_critico:+{bonus}")
    elif status_ads == "alerta":
        bonus = 14 if papel in ("fechamento_ml", "misto") else 6
        score += bonus
        fatores.append(f"pressao_ads_alerta:+{bonus}")
    if roas_real is not None and roas_real > 0 and roas_real < 1.5 and gasto >= gasto_pressao:
        bonus = 12 if papel == "fechamento_ml" else 5
        score += bonus
        fatores.append(f"roas_real_baixo:{roas_real:.2f}:+{bonus}")
    if compras_pixel >= 1 and papel == "fechamento_ml":
        score += 6
        fatores.append("pixel_comprou_reforca_ml:+6")

    score = max(0, min(100, score))

    # Limiar: captacao pura exige score MAIS alto para Sonnet (economiza);
    # fechamento ML usa limiar padrão (mais exigente / sobe antes).
    limiar_uso = limiar_alto if papel != "captacao_meta" else limiar_alto_captacao
    if score >= limiar_uso:
        nivel = "alto"
    elif score >= limiar_medio:
        nivel = "medio"
    else:
        nivel = "baixo"

    deve = nivel == "alto"
    return {
        "ok": True,
        "score": score,
        "nivel": nivel,
        "papel": papel,
        "termometro_principal": "mercado_livre",
        "deve_aumentar_ia": deve,
        "limiar_usado": limiar_uso,
        "limiar_alto": limiar_alto,
        "limiar_medio": limiar_medio,
        "fatores": fatores,
        "captacao_meta": {
            "gasto": round(gasto, 2),
            "status": status_ads or None,
            "roas_real": roas_real,
            "compras_pixel": compras_pixel,
        },
        "resumo": (
            f"[{papel}] score {score}/100 → {nivel}"
            + (" → aumentar IA (Sonnet) no fechamento ML" if deve and papel == "fechamento_ml"
               else " → aumentar IA (Sonnet)" if deve
               else " → Haiku/template")
        ),
    }
