"""
Detecta oscilação nas métricas de decisão (além da margem de erro âncora).
Widget Datadog fica vermelho; Telegram pede cuidado para decidir.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar

logger = logging.getLogger("oscilacao_decisao")

SNAPSHOT_PATH = ROOT / "logs" / "decisao_oscilacao_ultima.json"
COOLDOWN_SEG = 3600

# Limiar = mudança que ultrapassa a margem de erro declarada (âncora).
# 0.0 = qualquer variação (0/1, contagens).
LIMIARES: dict[str, float] = {
    "saude_score": 2.0,
    "produtos_seguros": 0.0,
    "esforco_faltando": 0.0,
    "kit_condicao_ok": 0.0,
    "progresso_pct": 5.0,
    "claude_ok": 0.0,
    "aproximando": 0.0,
    "anuncios_foco": 0.0,
}


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def comparar(anterior: dict[str, Any] | None, atual: dict[str, Any]) -> dict[str, Any]:
    """Compara amostras. Primeira amostra / chave nova não é oscilação.

    Ausência não vira 0 — senão o vigia no Actions (checkout sem snapshot)
    zera saude/progresso e o gauge fica preso em 1.
    """
    if not anterior:
        return {
            "oscilacao": False,
            "cuidado": False,
            "primeira_amostra": True,
            "mudancas": [],
        }
    mudancas: list[dict[str, Any]] = []
    for chave, limiar in LIMIARES.items():
        if chave not in atual or chave not in anterior:
            continue
        a = _f(anterior.get(chave))
        b = _f(atual.get(chave))
        delta = abs(b - a)
        if delta > limiar + 1e-9:
            mudancas.append(
                {
                    "metrica": chave,
                    "de": a,
                    "para": b,
                    "delta": round(delta, 2),
                    "limiar": limiar,
                }
            )
    osc = bool(mudancas)
    return {
        "oscilacao": osc,
        "cuidado": osc,
        "primeira_amostra": False,
        "mudancas": mudancas,
    }


def registrar_e_avaliar(
    atualizacao: dict[str, float],
    *,
    alertar: bool = True,
) -> dict[str, Any]:
    """Mescla valores, avalia oscilação, emite gauges e opcionalmente Telegram."""
    prev = ler_json(SNAPSHOT_PATH, default={})
    if not isinstance(prev, dict):
        prev = {}
    anterior = prev.get("atual") if isinstance(prev.get("atual"), dict) else {}
    delta = {k: _f(v) for k, v in atualizacao.items() if k in LIMIARES}
    merged = {**anterior, **delta}
    # Só compara o que esta rodada trouxe — update parcial (kits) não
    # reavalia saude/progresso como se tivessem ido a zero.
    result = comparar(
        {k: anterior[k] for k in delta if k in anterior} or None,
        delta,
    )
    agora = datetime.now(timezone.utc).isoformat()
    out = {
        "timestamp": agora,
        "atual": merged,
        "anterior": anterior,
        "oscilacao": result["oscilacao"],
        "cuidado": result["cuidado"],
        "primeira_amostra": result["primeira_amostra"],
        "mudancas": result["mudancas"],
    }
    try:
        escrever_json_atomico(SNAPSHOT_PATH, out)
    except Exception:
        pass

    gauge("decisao.oscilacao", 1.0 if result["oscilacao"] else 0.0)
    gauge("decisao.cuidado", 1.0 if result["cuidado"] else 0.0)
    gauge("decisao.oscilacao.n", float(len(result["mudancas"])))
    incrementar("decisao.oscilacao.rodadas")

    if alertar and result["oscilacao"] and not os.environ.get("PYTEST_CURRENT_TEST"):
        _alertar_cuidado(result["mudancas"])
    return out


def formatar_alerta(mudancas: list[dict[str, Any]]) -> str:
    linhas = [
        "CUIDADO para tomar decisão",
        "",
        "O Datadog oscilou além da margem de erro âncora. "
        "O widget ficou vermelho. Não escale Ads, volume nem 2º CNPJ até estabilizar.",
        "",
        "*O que mudou:*",
    ]
    for m in mudancas[:8]:
        linhas.append(
            f"• `{m.get('metrica')}` {m.get('de')} → {m.get('para')} "
            f"(Δ {m.get('delta')}, limiar {m.get('limiar')})"
        )
    linhas.extend(
        [
            "",
            "Claude segue em *uso moderado* (números âncora; não inventa venda ao vivo).",
        ]
    )
    return "\n".join(linhas)


def _alertar_cuidado(mudancas: list[dict[str, Any]]) -> None:
    try:
        from core.notificador import alertar_gestor
        from core.telegram_explicacao import cabecalho_agente

        msg = cabecalho_agente("vigia_datadog", "Cuidado — oscilação no Datadog")
        msg = f"{msg}\n\n{formatar_alerta(mudancas)}"
        alertar_gestor(
            msg,
            chave="decisao:oscilacao_datadog",
            cooldown_segundos=COOLDOWN_SEG,
            agente_id="vigia_datadog",
        )
    except Exception as exc:
        logger.info("alerta oscilação: %s", exc)


def _amostra_de_snapshots() -> dict[str, float]:
    """Só inclui chaves cujo arquivo-fonte existe e tem dado — não zera o resto."""
    amostra: dict[str, float] = {}
    briefing = ler_json(ROOT / "logs" / "briefing_ruptura_impala_ultima.json", default={})
    kits = ler_json(ROOT / "logs" / "kits_compativeis_manicures_ultima.json", default={})
    rup = ler_json(ROOT / "logs" / "ponto_ruptura_segundo_cnpj_ultima.json", default={})
    if not isinstance(briefing, dict):
        briefing = {}
    if not isinstance(kits, dict):
        kits = {}
    if not isinstance(rup, dict):
        rup = {}
    previa = briefing.get("previa_ml") if isinstance(briefing.get("previa_ml"), dict) else {}
    produtos = briefing.get("produtos") if isinstance(briefing.get("produtos"), dict) else {}
    esforco = briefing.get("esforco") if isinstance(briefing.get("esforco"), dict) else {}
    if briefing:
        if "saude_score" in briefing:
            amostra["saude_score"] = _f(briefing.get("saude_score"))
        if "seguros_n" in produtos:
            amostra["produtos_seguros"] = _f(produtos.get("seguros_n"))
        if "faltando_n" in esforco:
            amostra["esforco_faltando"] = _f(esforco.get("faltando_n"))
        if "claude_ok" in briefing:
            amostra["claude_ok"] = 1.0 if briefing.get("claude_ok") else 0.0
        if "anuncios_ativos_foco" in previa:
            amostra["anuncios_foco"] = _f(previa.get("anuncios_ativos_foco"))
    if kits and "condicao_n" in kits:
        amostra["kit_condicao_ok"] = _f(kits.get("condicao_n"))
    if rup:
        if "progresso_pct" in rup:
            amostra["progresso_pct"] = _f(rup.get("progresso_pct"))
        if "veredito" in rup:
            amostra["aproximando"] = 1.0 if str(rup.get("veredito") or "") == "aproximando" else 0.0
    return amostra


def avaliar_de_snapshots() -> dict[str, Any]:
    """Lê snapshots de ruptura/kits e avalia (uso no vigia)."""
    return registrar_e_avaliar(_amostra_de_snapshots(), alertar=True)
