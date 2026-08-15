"""
integracoes/esmaltes/decisao_batalha_agir.py
Transforma batalha Impala (gap/rivais) em fila ranqueada de ações — sem escrever no ML.

Emite gauges robo.impala.batalha.agir_* e opcionalmente texto Claude (só resumo).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from core.datadog_metrics import gauge, incrementar

logger = logging.getLogger("decisao_batalha_agir")

_GAP_PRECO_MIN = float(os.getenv("BATALHA_AGIR_GAP_PCT_MIN", "3"))
_RIVAIS_MUITOS = int(os.getenv("BATALHA_AGIR_RIVAIS_MUITOS", "8"))
_CLAUDE = os.getenv("BATALHA_AGIR_CLAUDE", "0").strip().lower() not in ("0", "false", "no", "")


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _prio_peso(prio: str) -> float:
    p = (prio or "").lower()
    if p in ("p0", "0"):
        return 2.0
    if p in ("p1", "1"):
        return 1.5
    return 1.0


def _papel_peso(papel: str) -> float:
    p = str(papel or "").lower()
    return 1.6 if p in ("guerra", "entrada", "giro", "preco") else 1.0


def _rival_ao_vivo(comp: dict[str, Any]) -> bool:
    fonte = str(comp.get("fonte_rival") or "").strip().lower()
    if fonte == "ao_vivo":
        return True
    if fonte in ("ausente", "catalogo"):
        return False
    # snapshots antigos sem fonte: só vale se havia rivais amostrados
    return comp.get("gap_pct") is not None and int(comp.get("rivais_no_tam") or 0) > 0


def classificar_acao(comp: dict[str, Any]) -> dict[str, Any] | None:
    """
    Uma comparação de kit → ação sugerida (ou None se só observar sem score).
    """
    sku = str(comp.get("sku") or "").strip().upper()
    if not sku:
        return None
    gap = comp.get("gap_pct")
    gap_f = _f(gap) if gap is not None else 0.0
    rivais = int(comp.get("rivais_no_tam") or 0)
    mlb_ok = bool(comp.get("mlb_ok"))
    papel = str(comp.get("papel") or "catalogo")
    prio = str(comp.get("prio") or "p?")
    ao_vivo = _rival_ao_vivo(comp)

    if not mlb_ok:
        try:
            from integracoes.esmaltes.doutrina_guerra_impala import sku_pode_publicar_agora

            pode_pub, motivo_pub = sku_pode_publicar_agora(sku)
        except Exception:
            pode_pub, motivo_pub = True, "SKU sem MLB válido"
        if not pode_pub:
            acao = "observar"
            motivo = motivo_pub
            score = 2.0
        else:
            acao = "publicar_mlb"
            motivo = motivo_pub or "SKU sem MLB válido — publicar na frente de guerra antes de reagir a preço"
            score = 40.0 + max(0.0, gap_f)
    elif not ao_vivo:
        acao = "observar"
        motivo = "Sem rival ao vivo no tamanho — não reagir a preço de planilha"
        score = 1.0
    elif gap is None:
        return None
    elif gap_f >= _GAP_PRECO_MIN:
        try:
            from integracoes.esmaltes.doutrina_guerra_impala import sku_pode_mexer_preco

            pode_preco = sku_pode_mexer_preco(sku)
        except Exception:
            pode_preco = True
        if not pode_preco:
            acao = "melhorar_listing"
            motivo = (
                f"Gap {gap_f:.1f}% — doutrina: diferenciar `{sku}` "
                "(só PERL iguala preço na faixa)"
            )
            score = 10.0 + gap_f * 0.3 * _prio_peso(prio)
        else:
            acao = "revisar_preco"
            motivo = (
                f"Preço ~{gap_f:.1f}% acima do rival min "
                f"(R$ {_f(comp.get('nosso_preco')):.2f} vs R$ {_f(comp.get('rival_min')):.2f})"
            )
            score = gap_f * _prio_peso(prio) * _papel_peso(papel)
    elif gap_f <= 0 and rivais >= _RIVAIS_MUITOS:
        acao = "melhorar_listing"
        motivo = (
            f"Preço competitivo, mas {rivais} rivais no tamanho do kit — "
            "diferenciar título/fotos/Ads"
        )
        score = 10.0 + rivais * 0.5 * _prio_peso(prio)
    else:
        acao = "observar"
        motivo = f"Gap {gap_f:.1f}% / {rivais} rivais — sem urgência"
        score = max(0.0, 5.0 - abs(gap_f))

    return {
        "sku": sku,
        "kit_tag": comp.get("kit_tag") or f"kit:{sku.lower()}",
        "acao": acao,
        "motivo": motivo,
        "score": round(score, 2),
        "gap_pct": gap_f,
        "rivais_no_tam": rivais,
        "nosso_preco": comp.get("nosso_preco"),
        "rival_min": comp.get("rival_min"),
        "papel": papel,
        "prio": prio,
        "mlb_ok": mlb_ok,
        "fonte_rival": "ao_vivo" if ao_vivo else "ausente",
        "critica": acao in ("revisar_preco", "publicar_mlb"),
    }


def gerar_acoes_batalha(
    batalha: dict[str, Any] | None,
    *,
    limite: int = 5,
) -> dict[str, Any]:
    """Ranqueia comparações da batalha. Nunca lança."""
    bat = batalha if isinstance(batalha, dict) else {}
    comps = bat.get("comparacoes") or []
    acoes: list[dict[str, Any]] = []
    for c in comps:
        if not isinstance(c, dict):
            continue
        row = classificar_acao(c)
        if row:
            acoes.append(row)
    acoes.sort(key=lambda r: float(r.get("score") or 0), reverse=True)
    top = acoes[: max(1, int(limite or 5))]

    contagem = {
        "revisar_preco": 0,
        "melhorar_listing": 0,
        "publicar_mlb": 0,
        "observar": 0,
    }
    for a in acoes:
        k = str(a.get("acao") or "observar")
        if k in contagem:
            contagem[k] += 1

    return {
        "ok": True,
        "total": len(acoes),
        "criticas": sum(1 for a in acoes if a.get("critica")),
        "por_acao": contagem,
        "top": top,
        "anuncios_unicos": bat.get("anuncios_unicos"),
        "sellers_unicos": bat.get("sellers_unicos"),
        "nossos_acima_rival": bat.get("nossos_acima_rival"),
    }


def emitir_metricas_agir(acoes: dict[str, Any] | None) -> None:
    data = acoes if isinstance(acoes, dict) else {}
    por = data.get("por_acao") or {}
    gauge("impala.batalha.agir_preco", float(por.get("revisar_preco") or 0))
    gauge("impala.batalha.agir_listing", float(por.get("melhorar_listing") or 0))
    gauge("impala.batalha.agir_publicar_mlb", float(por.get("publicar_mlb") or 0))
    gauge("impala.batalha.agir_observar", float(por.get("observar") or 0))
    gauge("impala.batalha.agir_criticas", float(data.get("criticas") or 0))
    gauge("impala.batalha.agir_total", float(data.get("total") or 0))
    for i, row in enumerate(data.get("top") or []):
        tags = [
            str(row.get("kit_tag") or "kit:x"),
            f"acao:{row.get('acao') or 'observar'}",
            f"rank:{i + 1}",
        ]
        gauge("impala.batalha.agir_score", float(row.get("score") or 0), tags=tags)
    incrementar("impala.batalha.agir_rodadas")


def formatar_secao_agir(acoes: dict[str, Any] | None) -> list[str]:
    data = acoes if isinstance(acoes, dict) else {}
    top = data.get("top") or []
    if not top:
        return []
    linhas = [
        "",
        f"*AGIR hoje — batalha Impala* _(críticas: {int(data.get('criticas') or 0)})_",
        "_Sugestão automática — não altera preço no ML._",
    ]
    for row in top[:5]:
        marca = "🔴" if row.get("critica") else "•"
        linhas.append(
            f"{marca} `{row.get('sku')}` → *{row.get('acao')}* "
            f"(score {row.get('score')}) — {row.get('motivo')}"
        )
    return linhas


def resumo_claude_opcional(acoes: dict[str, Any] | None) -> str:
    """Texto curto via Claude se BATALHA_AGIR_CLAUDE=1; senão vazio."""
    if not _CLAUDE:
        return ""
    data = acoes if isinstance(acoes, dict) else {}
    top = data.get("top") or []
    if not top:
        return ""
    try:
        from core.resumo_ia import sintetizar_claude

        bullets = "\n".join(
            f"- {r.get('sku')}: {r.get('acao')} — {r.get('motivo')}" for r in top[:5]
        )
        return sintetizar_claude(
            (
                "Em até 4 linhas, priorize o que o gestor deve fazer HOJE no Mercado Livre "
                "com base nestas sugestões (não invente preço nem frete):\n"
                f"{bullets}"
            ),
            contexto="batalha_impala_agir",
            fallback="",
            max_tokens=120,
        )
    except Exception as exc:
        logger.info("resumo Claude batalha agir indisponível: %s", exc)
        return ""


def processar_agir_batalha(batalha: dict[str, Any] | None, *, limite: int = 5) -> dict[str, Any]:
    """Gera ações, emite métricas, Claude só no momento de lucro. Nunca lança."""
    try:
        acoes = gerar_acoes_batalha(batalha, limite=limite)
        emitir_metricas_agir(acoes)
        texto_ia = resumo_claude_opcional(acoes)
        if not texto_ia:
            try:
                from integracoes.esmaltes.claude_lucro_ml import (
                    momento_lucro_ml,
                    sintetizar_lucro_ml,
                )

                momento = momento_lucro_ml(acoes=acoes)
                texto_ia = sintetizar_lucro_ml(
                    {"acoes": acoes.get("top"), "cnpj": "52.668.583/0001-27"},
                    "",
                    momento=momento,
                )
            except Exception as exc:
                logger.info("Claude lucro batalha: %s", exc)
        if texto_ia:
            acoes["resumo_claude"] = texto_ia
        return acoes
    except Exception as exc:
        logger.warning("processar_agir_batalha: %s", exc)
        incrementar("impala.batalha.agir_erro")
        return {"ok": False, "erro": str(exc), "top": [], "por_acao": {}}
