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


def _fmt_numero(valor: float) -> str:
    if abs(valor - round(valor)) < 1e-9:
        return f"{int(round(valor)):,}".replace(",", ".")
    return f"{valor:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _parse_campo(item: Sequence[Any]) -> tuple[str, str, str | None]:
    """Aceita (campo, rótulo) ou (campo, rótulo, descrição str). Ignora 3º int (casas decimais)."""
    campo = str(item[0])
    rotulo = str(item[1]) if len(item) > 1 else campo
    desc = None
    if len(item) > 2 and isinstance(item[2], str) and str(item[2]).strip():
        desc = str(item[2]).strip()
    return campo, rotulo, desc


def grafico_evolucao(
    serie: Sequence[dict[str, Any]],
    campos: Sequence[tuple[Any, ...]],
    caminho_saida: Any,
    *,
    titulo: str = "Evolução",
    max_pontos: int = 30,
) -> Any | None:
    """
    Gera PNG com um subplot por métrica (compartilhando o eixo X temporal).
    campos: (campo, rótulo) ou (campo, rótulo, descrição curta).
    Retorna o caminho salvo ou None.
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
        from matplotlib.ticker import MaxNLocator

        nan = float("nan")
        rotulos_x = _rotulos_x(pontos)
        x = list(range(len(pontos)))
        n = len(campos)
        fig, axes = plt.subplots(
            n,
            1,
            figsize=(10, 2.6 * n + 0.8),
            sharex=True,
            constrained_layout=False,
        )
        if n == 1:
            axes = [axes]

        cores = ["#1d4ed8", "#15803d", "#be185d", "#c2410c", "#6d28d9", "#0e7490"]
        for i, item in enumerate(campos):
            campo, rotulo, desc = _parse_campo(item)
            ax = axes[i]
            valores = [
                float(p.get(campo))
                if isinstance(p.get(campo), (int, float)) and not isinstance(p.get(campo), bool)
                else nan
                for p in pontos
            ]
            cor = cores[i % len(cores)]
            ax.plot(
                x,
                valores,
                marker="o",
                markersize=4,
                color=cor,
                linewidth=2.0,
                label=rotulo,
            )
            ax.fill_between(x, valores, alpha=0.12, color=cor)

            titulo_painel = rotulo
            if desc:
                titulo_painel = f"{rotulo}  ·  {desc}"
            ax.set_title(titulo_painel, fontsize=10, fontweight="semibold", loc="left", pad=6, color="#111827")
            ax.set_ylabel("qtd", fontsize=8, color="#6b7280")
            ax.grid(True, alpha=0.28, linestyle="--")
            ax.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
            ax.tick_params(axis="y", labelsize=8)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)

            vlim = [v for v in valores if v == v]
            if vlim:
                ultimo = vlim[-1]
                ax.annotate(
                    f"{rotulo.split('(')[0].strip()}: {_fmt_numero(ultimo)}",
                    xy=(x[-1], ultimo),
                    xytext=(6, 6),
                    textcoords="offset points",
                    fontsize=8,
                    color=cor,
                    fontweight="bold",
                    bbox={
                        "boxstyle": "round,pad=0.25",
                        "facecolor": "white",
                        "edgecolor": cor,
                        "alpha": 0.9,
                        "linewidth": 0.8,
                    },
                )
                ax.legend(loc="upper right", fontsize=8, framealpha=0.9)

        passo = max(1, len(rotulos_x) // 8)
        axes[-1].set_xticks(x[::passo])
        axes[-1].set_xticklabels(rotulos_x[::passo], rotation=35, ha="right", fontsize=8)
        axes[-1].set_xlabel("Rodada (data/hora)", fontsize=9, color="#4b5563")

        periodo = ""
        if rotulos_x:
            periodo = f"{rotulos_x[0]} → {rotulos_x[-1]}"
        fig.suptitle(titulo, fontsize=13, fontweight="bold", y=0.995)
        if periodo:
            fig.text(0.5, 0.965, periodo, ha="center", fontsize=9, color="#6b7280")

        fig.tight_layout(rect=(0, 0, 1, 0.95 if periodo else 0.97))

        caminho = str(caminho_saida)
        import os

        os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
        fig.savefig(caminho, dpi=130, bbox_inches="tight", facecolor="white")
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
                _fmt_numero(v),
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
        fig.savefig(caminho, dpi=130, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return caminho_saida
    except Exception as exc:
        logger.warning("Falha ao gerar gráfico de barras %s: %s", titulo, exc)
        return None
