"""
agentes/comparativo/agente_comparativo_ml_shopee.py
Compara esmaltes e filamentos 3D no Mercado Livre × Shopee e indica onde vender.

Catálogo: catalogo/comparativo_ml_shopee_categorias.json

Uso:
  python -m agentes.comparativo.agente_comparativo_ml_shopee
  python -m agentes.comparativo.agente_comparativo_ml_shopee --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    COMPARATIVO_ML_SHOPEE_ALERTA_COOLDOWN_SEG,
    COMPARATIVO_ML_SHOPEE_ALERTA_RESUMO,
    COMPARATIVO_ML_SHOPEE_CATALOGO,
    COMPARATIVO_ML_SHOPEE_PAUSA_SEG,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.comparativo.ml_shopee_categorias import (
    analisar_termo,
    consolidar_categoria,
    consolidar_geral,
    gerar_recomendacoes,
    label_marketplace,
    resumir_pedidos_proprios,
)
from integracoes.marketplaces.busca_multi_marketplace import buscar_todos_marketplaces
from integracoes.ml import ml_client
from integracoes.shopee import shopee_client

logger = logging.getLogger("agente_comparativo_ml_shopee")

HISTORY_PATH = ROOT / "logs" / "comparativo_ml_shopee_history.json"
SNAPSHOT_PATH = ROOT / "logs" / "comparativo_ml_shopee_ultima.json"

_MARKETPLACES = ["mercadolivre", "shopee"]


def _carregar_segmentos() -> list[dict[str, Any]]:
    caminho = ROOT / COMPARATIVO_ML_SHOPEE_CATALOGO
    try:
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        return [s for s in data if isinstance(s, dict) and s.get("ativo")]
    except Exception as exc:
        logger.error("Erro ao carregar catálogo comparativo ML×Shopee: %s", exc)
        return []


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def _coletar_pedidos_proprios(categorias: list[str]) -> dict[str, Any]:
    try:
        pedidos_ml = ml_client.listar_pedidos(dias=7)
    except Exception as exc:
        logger.warning("Pedidos ML indisponíveis: %s", exc)
        pedidos_ml = []
    try:
        pedidos_shopee = shopee_client.listar_pedidos(dias=7)
    except Exception as exc:
        logger.warning("Pedidos Shopee indisponíveis: %s", exc)
        pedidos_shopee = []
    return resumir_pedidos_proprios(
        pedidos_ml=pedidos_ml or [],
        pedidos_shopee=pedidos_shopee or [],
        categorias=categorias,
    )


def _montar_painel(
    consolidado: dict[str, Any],
    recomendacoes: list[str],
    pedidos: dict[str, Any] | None = None,
) -> str:
    vencedor = consolidado.get("vencedor_global")
    if vencedor == "empate":
        titulo_veredito = "Empate técnico"
    elif vencedor:
        titulo_veredito = label_marketplace(str(vencedor))
    else:
        titulo_veredito = "sem dados"

    scores = consolidado.get("scores_globais") or {}
    from core.telegram_explicacao import cabecalho_agente

    linhas = [
        cabecalho_agente(
            "comparativo_ml_shopee",
            "⚖️ *ML × Shopee — esmaltes e filamentos 3D*",
        ),
        "",
        f"*Veredito global:* {titulo_veredito}",
        f"  Score médio — ML: *{scores.get('mercadolivre', 0):.2f}* | "
        f"Shopee: *{scores.get('shopee', 0):.2f}*",
    ]
    vitorias = consolidado.get("vitorias_categoria") or {}
    if vitorias:
        linhas.append(
            f"  Categorias: ML {vitorias.get('mercadolivre', 0)} | "
            f"Shopee {vitorias.get('shopee', 0)} | "
            f"empate {consolidado.get('empates_categoria', 0)}"
        )
    linhas.append("")

    for cat in consolidado.get("categorias") or []:
        nome = str(cat.get("categoria") or "?").title()
        v = cat.get("vencedor")
        v_label = "empate" if v == "empate" else label_marketplace(str(v or "?"))
        linhas.append(f"*{nome}* — líder: {v_label}")
        por = cat.get("por_marketplace") or {}
        for mp in ("mercadolivre", "shopee"):
            m = por.get(mp) or {}
            vol_txt = (
                f"proxy {m.get('volume_sinal', 0)}"
                if m.get("volume_eh_proxy")
                else f"{m.get('vendidos', 0)} un. vendidas"
            )
            linhas.append(
                f"  • {m.get('label', mp)}: score {m.get('score', 0):.2f} | "
                f"{m.get('anuncios', 0)} anúncios | mediana {_fmt_brl(m.get('preco_mediana'))} | "
                f"{vol_txt}"
            )
        linhas.append("")

    if pedidos and pedidos.get("tem_dados"):
        linhas.append("*Suas vendas (7d)*")
        ml_p = pedidos.get("mercadolivre") or {}
        sh_p = pedidos.get("shopee") or {}
        linhas.append(
            f"  • ML: {ml_p.get('pedidos', 0)} pedido(s) | {_fmt_brl(ml_p.get('receita'))}"
        )
        linhas.append(
            f"  • Shopee: {sh_p.get('pedidos', 0)} pedido(s) | {_fmt_brl(sh_p.get('receita'))}"
        )
        for cat, info in (pedidos.get("por_categoria") or {}).items():
            ml_c = info.get("mercadolivre") or {}
            sh_c = info.get("shopee") or {}
            if ml_c.get("pedidos") or sh_c.get("pedidos"):
                linhas.append(
                    f"  · {str(cat).title()}: ML {ml_c.get('pedidos', 0)} | "
                    f"Shopee {sh_c.get('pedidos', 0)}"
                )
        linhas.append("")

    if recomendacoes:
        linhas.append("*Recomendações*")
        for r in recomendacoes[:6]:
            linhas.append(f"  • {r}")
        linhas.append("")

    nota = consolidado.get("nota_metodologica")
    if nota:
        linhas.append(f"_{nota}_")

    return "\n".join(linhas).strip()


def _analisar_segmento(segmento: dict[str, Any]) -> dict[str, Any]:
    termo = str(segmento.get("termo_busca") or "").strip()
    limite = int(segmento.get("limite_resultados") or 24)
    if not termo:
        return {"id": segmento.get("id"), "ok": False, "motivo": "termo vazio"}

    anuncios = buscar_todos_marketplaces(
        termo,
        limite=limite,
        marketplaces=_MARKETPLACES,
    )
    out = analisar_termo(segmento, anuncios)
    fontes = sorted({str(a.get("fonte_busca") or "") for a in anuncios if a.get("fonte_busca")})
    out["fonte_busca"] = fontes[0] if len(fontes) == 1 else ("misto" if fontes else "nenhuma")
    return out


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    """Varre catálogo, compara ML×Shopee e alerta o veredito. Nunca lança."""
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — alerta comparativo não será entregue")

        segmentos = _carregar_segmentos()
        if not segmentos:
            logger.info("Nenhum segmento ativo em %s", COMPARATIVO_ML_SHOPEE_CATALOGO)
            return {"ok": True, "total_segmentos": 0, "alerta_enviado": False}

        resultados: list[dict[str, Any]] = []
        for i, seg in enumerate(segmentos):
            logger.info(
                "Comparativo ML×Shopee: %s (%s)",
                seg.get("nome") or seg.get("id"),
                seg.get("categoria"),
            )
            resultados.append(_analisar_segmento(seg))
            if i < len(segmentos) - 1 and COMPARATIVO_ML_SHOPEE_PAUSA_SEG > 0:
                time.sleep(COMPARATIVO_ML_SHOPEE_PAUSA_SEG)

        por_categoria: dict[str, list[dict[str, Any]]] = {}
        for r in resultados:
            if not r.get("ok"):
                continue
            cat = str(r.get("categoria") or "outros")
            por_categoria.setdefault(cat, []).append(r)

        categorias = [consolidar_categoria(itens) for itens in por_categoria.values()]
        consolidado = consolidar_geral(categorias)
        recomendacoes = gerar_recomendacoes(consolidado)
        pedidos = _coletar_pedidos_proprios(list(por_categoria.keys()))

        agora = datetime.now(timezone.utc).isoformat()
        snapshot = {
            "timestamp": agora,
            "consolidado": consolidado,
            "recomendacoes": recomendacoes,
            "pedidos_proprios": pedidos,
            "resultados": resultados,
        }
        escrever_json_atomico(SNAPSHOT_PATH, snapshot)

        historico = ler_json(HISTORY_PATH, default={"rodadas": []})
        if not isinstance(historico, dict):
            historico = {"rodadas": []}
        rodadas = list(historico.get("rodadas") or [])
        rodadas.append(
            {
                "timestamp": agora,
                "vencedor_global": consolidado.get("vencedor_global"),
                "scores_globais": consolidado.get("scores_globais"),
            }
        )
        historico["rodadas"] = rodadas[-50:]
        historico["ultima"] = snapshot
        escrever_json_atomico(HISTORY_PATH, historico)

        vencedor = consolidado.get("vencedor_global") or "n/d"
        gauge(
            "comparativo_ml_shopee.score_ml",
            float((consolidado.get("scores_globais") or {}).get("mercadolivre") or 0),
        )
        gauge(
            "comparativo_ml_shopee.score_shopee",
            float((consolidado.get("scores_globais") or {}).get("shopee") or 0),
        )
        incrementar("comparativo_ml_shopee.rodadas", tags=[f"vencedor:{vencedor}"])

        alerta_enviado = False
        if enviar_alerta and COMPARATIVO_ML_SHOPEE_ALERTA_RESUMO and consolidado.get("ok"):
            painel = _montar_painel(consolidado, recomendacoes, pedidos)
            alerta_enviado = bool(
                alertar_gestor(
                    painel,
                    chave=chave_resumo_periodo("comparativo:ml_shopee", horas_por_bucket=6),
                    cooldown_segundos=COMPARATIVO_ML_SHOPEE_ALERTA_COOLDOWN_SEG,
                    agente_id="comparativo_ml_shopee",
                )
            )

        return {
            "ok": True,
            "total_segmentos": len(segmentos),
            "vencedor_global": consolidado.get("vencedor_global"),
            "consolidado": consolidado,
            "recomendacoes": recomendacoes,
            "pedidos_proprios": pedidos,
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Comparativo ML×Shopee erro: %s", exc)
        incrementar("comparativo_ml_shopee.erro")
        return {"ok": False, "erro": str(exc), "resultados": []}


def main() -> int:
    parser = argparse.ArgumentParser(description="Comparativo ML × Shopee (esmaltes + filamentos)")
    parser.add_argument("--sem-alerta", action="store_true", help="Não envia Telegram")
    args = parser.parse_args()
    logger.info("=== Comparativo ML × Shopee ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    logger.info(
        "Comparativo OK: %s segmento(s), vencedor=%s, alerta=%s",
        out.get("total_segmentos"),
        out.get("vencedor_global"),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
