"""
core/series_historica.py
Série temporal leve para monitores: registra pontos, calcula variação vs.
rodada anterior e formata comparativo em texto (setas + sparkline unicode).

Sem dependências externas — usado para dar contexto de "o que mudou" nos
alertas do Telegram e alimentar os gráficos em core/graficos.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json

logger = logging.getLogger("series_historica")

_BLOCOS = "▁▂▃▄▅▆▇█"


def carregar_serie(caminho: Any) -> list[dict[str, Any]]:
    """Lê a série (lista de pontos). Retorna [] se ausente/corrompida."""
    data = ler_json(caminho, default=[])
    return data if isinstance(data, list) else []


def registrar_ponto(
    caminho: Any,
    ponto: dict[str, Any],
    *,
    max_pontos: int = 180,
) -> list[dict[str, Any]]:
    """Anexa um ponto à série (com timestamp) e trunca em max_pontos."""
    serie = carregar_serie(caminho)
    registro = dict(ponto)
    registro.setdefault("ts", datetime.now(timezone.utc).isoformat())
    serie.append(registro)
    if len(serie) > max_pontos:
        serie = serie[-max_pontos:]
    try:
        escrever_json_atomico(caminho, serie)
    except Exception as exc:
        logger.warning("Falha ao gravar série %s: %s", caminho, exc)
    return serie


def _valores(serie: list[dict[str, Any]], campo: str) -> list[float]:
    out: list[float] = []
    for p in serie:
        v = p.get(campo)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out.append(float(v))
    return out


def variacao(serie: list[dict[str, Any]], campo: str) -> dict[str, Any]:
    """Compara os dois últimos valores do campo."""
    vals = _valores(serie, campo)
    if not vals:
        return {"atual": None, "anterior": None, "delta": None, "pct": None}
    atual = vals[-1]
    anterior = vals[-2] if len(vals) >= 2 else None
    delta = None if anterior is None else round(atual - anterior, 2)
    pct = None
    if anterior not in (None, 0):
        pct = round(100.0 * (atual - anterior) / abs(anterior), 1)
    return {"atual": atual, "anterior": anterior, "delta": delta, "pct": pct}


def seta(delta: float | None) -> str:
    if delta is None:
        return "•"
    if delta > 0:
        return "🔺"
    if delta < 0:
        return "🔻"
    return "▪️"


def sparkline(valores: list[float], largura: int = 24) -> str:
    """Mini gráfico textual com blocos unicode."""
    vals = [v for v in valores if isinstance(v, (int, float))]
    if not vals:
        return ""
    if len(vals) > largura:
        vals = vals[-largura:]
    lo = min(vals)
    hi = max(vals)
    if hi == lo:
        return _BLOCOS[len(_BLOCOS) // 2] * len(vals)
    escala = len(_BLOCOS) - 1
    return "".join(_BLOCOS[int(round((v - lo) / (hi - lo) * escala))] for v in vals)


def _fmt_num(valor: float | None, casas: int = 0) -> str:
    if valor is None:
        return "n/d"
    if casas <= 0:
        return f"{int(round(valor)):,}".replace(",", ".")
    return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def linha_comparativa(
    serie: list[dict[str, Any]],
    campo: str,
    rotulo: str,
    *,
    casas: int = 0,
    prefixo: str = "",
) -> str:
    """Uma linha: rótulo, valor atual, variação vs anterior e sparkline."""
    var = variacao(serie, campo)
    atual = var["atual"]
    delta = var["delta"]
    pct = var["pct"]
    spark = sparkline(_valores(serie, campo))

    partes = [f"{rotulo}: *{prefixo}{_fmt_num(atual, casas)}*"]
    if delta is not None:
        sinal = "+" if delta >= 0 else ""
        pct_txt = f" ({sinal}{pct:.1f}%)" if pct is not None else ""
        partes.append(f"{seta(delta)} {sinal}{prefixo}{_fmt_num(delta, casas)}{pct_txt}")
    if spark:
        partes.append(f"`{spark}`")
    return " ".join(partes)


def formatar_comparativo(
    serie: list[dict[str, Any]],
    campos: list[tuple[str, str]] | list[tuple[str, str, int]],
    *,
    titulo: str = "Comparativo vs rodada anterior",
) -> str:
    """
    Bloco de texto com variação de cada campo.
    campos: lista de (campo, rotulo) ou (campo, rotulo, casas_decimais).
    """
    if len(serie) < 1:
        return ""
    linhas = [f"📈 *{titulo}*"]
    for item in campos:
        campo = item[0]
        rotulo = item[1]
        casas = item[2] if len(item) > 2 else 0
        prefixo = "R$ " if casas and "reço" in rotulo else ""
        linhas.append("• " + linha_comparativa(serie, campo, rotulo, casas=casas, prefixo=prefixo))
    if len(serie) >= 2:
        linhas.append(f"_{len(serie)} rodadas registradas_")
    return "\n".join(linhas)
