"""
core/graficos.py
Geração de gráficos PNG para os monitores (evolução temporal de métricas).

matplotlib é opcional: se não estiver instalado, todas as funções retornam
None e o agente segue apenas com o alerta de texto. Nunca lança exceção.
"""
from __future__ import annotations

import logging
from typing import Any, Sequence

logger = logging.getLogger("graficos")

_MPL_OK: bool | None = None


def disponivel() -> bool:
    """True se matplotlib pode ser importado."""
    global _MPL_OK
    if _MPL_OK is None:
        try:
            import matplotlib  # noqa: F401

            _MPL_OK = True
        except Exception:
            _MPL_OK = False
            logger.info("matplotlib indisponível — gráficos desativados (segue só texto)")
    return _MPL_OK


def _rotulos_x(serie: Sequence[dict[str, Any]]) -> list[str]:
    rotulos: list[str] = []
    for p in serie:
        ts = str(p.get("ts") or "")
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            rotulos.append(dt.strftime("%d/%m %Hh"))
        except Exception:
            rotulos.append(ts[:10])
    return rotulos


def grafico_evolucao(
    serie: Sequence[dict[str, Any]],
    campos: Sequence[tuple[str, str]],
    caminho_saida: Any,
    *,
    titulo: str = "Evolução",
    max_pontos: int = 30,
) -> Any | None:
    """
    Gera PNG com um subplot por métrica (compartilhando o eixo X temporal).
    campos: lista de (campo, rótulo). Retorna o caminho salvo ou None.
    """
    if not disponivel():
        return None

    pontos = list(serie)[-max_pontos:]
    if len(pontos) < 2:
        logger.info("Série curta (%d pontos) — gráfico não gerado", len(pontos))
        return None

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        nan = float("nan")
        rotulos = _rotulos_x(pontos)
        x = list(range(len(pontos)))
        n = len(campos)
        fig, axes = plt.subplots(n, 1, figsize=(9, 2.4 * n + 0.6), sharex=True)
        if n == 1:
            axes = [axes]

        cores = ["#2563eb", "#16a34a", "#db2777", "#f59e0b", "#7c3aed", "#0891b2"]
        for i, (campo, rotulo) in enumerate(campos):
            ax = axes[i]
            valores = [
                float(p.get(campo)) if isinstance(p.get(campo), (int, float)) and not isinstance(p.get(campo), bool) else nan
                for p in pontos
            ]
            cor = cores[i % len(cores)]
            ax.plot(x, valores, marker="o", markersize=3, color=cor, linewidth=1.8)
            ax.fill_between(x, valores, alpha=0.08, color=cor)
            ax.set_ylabel(rotulo, fontsize=9)
            ax.grid(True, alpha=0.25, linestyle="--")

            vlim = [v for v in valores if v == v]  # remove nan
            if vlim:
                ultimo = vlim[-1]
                ax.annotate(
                    f"{ultimo:,.0f}".replace(",", "."),
                    xy=(x[-1], ultimo),
                    xytext=(4, 4),
                    textcoords="offset points",
                    fontsize=8,
                    color=cor,
                    fontweight="bold",
                )

        passo = max(1, len(rotulos) // 8)
        axes[-1].set_xticks(x[::passo])
        axes[-1].set_xticklabels(rotulos[::passo], rotation=45, ha="right", fontsize=8)

        fig.suptitle(titulo, fontsize=12, fontweight="bold")
        fig.tight_layout(rect=(0, 0, 1, 0.98))

        caminho = str(caminho_saida)
        import os

        os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
        fig.savefig(caminho, dpi=110, bbox_inches="tight")
        plt.close(fig)
        return caminho_saida
    except Exception as exc:
        logger.warning("Falha ao gerar gráfico %s: %s", titulo, exc)
        return None


def grafico_barras(
    categorias: Sequence[str],
    valores: Sequence[float],
    caminho_saida: Any,
    *,
    titulo: str = "Ranking",
    rotulo_x: str = "",
) -> Any | None:
    """Gráfico de barras horizontais (ex.: ranking de marcas/cores). PNG ou None."""
    if not disponivel():
        return None
    cats = list(categorias)
    vals = [float(v) for v in valores]
    if not cats or not vals or len(cats) != len(vals):
        return None

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 0.5 * len(cats) + 1.5))
        y = list(range(len(cats)))
        ax.barh(y, vals, color="#2563eb", alpha=0.85)
        ax.set_yticks(y)
        ax.set_yticklabels(cats, fontsize=9)
        ax.invert_yaxis()
        if rotulo_x:
            ax.set_xlabel(rotulo_x, fontsize=9)
        for i, v in enumerate(vals):
            ax.annotate(
                f"{v:,.0f}".replace(",", "."),
                xy=(v, i),
                xytext=(4, 0),
                textcoords="offset points",
                va="center",
                fontsize=8,
            )
        ax.set_title(titulo, fontsize=12, fontweight="bold")
        ax.grid(True, axis="x", alpha=0.25, linestyle="--")
        fig.tight_layout()

        caminho = str(caminho_saida)
        import os

        os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
        fig.savefig(caminho, dpi=110, bbox_inches="tight")
        plt.close(fig)
        return caminho_saida
    except Exception as exc:
        logger.warning("Falha ao gerar gráfico de barras %s: %s", titulo, exc)
        return None
