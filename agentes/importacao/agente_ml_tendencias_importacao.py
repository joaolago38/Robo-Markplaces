"""
agentes/importacao/agente_ml_tendencias_importacao.py
Cruza tendências do Mercado Livre com o mesmo produto no Alibaba e indica se vale importar.

Catálogo: catalogo/alibaba_produtos_importacao.json (termo_marketplace + termo_busca)

Uso:
  python -m agentes.importacao.agente_ml_tendencias_importacao
  python -m agentes.importacao.agente_ml_tendencias_importacao --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    ALIBABA_IMPORTACAO_CATALOGO,
    ALIBABA_PAUSA_ENTRE_BUSCAS_SEG,
    ML_TENDENCIAS_IMPORTACAO_ALERTA_RESUMO,
    ML_TENDENCIAS_IMPORTACAO_COOLDOWN_SEG,
    ML_TENDENCIAS_IMPORTACAO_PAUSA_SEG,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.cambio.cotacao_usd import obter_cotacao_usd
from integracoes.importacao.calculo_importacao_aerea import formatar_breakdown_viracopos_telegram
from integracoes.importacao.tendencias_ml_importacao import (
    analisar_produto_ml_vs_alibaba,
    consolidar_varredura,
    diagnosticar_coleta_vazia,
)

logger = logging.getLogger("agente_ml_tendencias_importacao")

HISTORY_PATH = ROOT / "logs" / "ml_tendencias_importacao_history.json"
SNAPSHOT_PATH = ROOT / "logs" / "ml_tendencias_importacao_ultima.json"


def _carregar_produtos() -> list[dict[str, Any]]:
    from agentes.importacao.agente_alibaba_importacao import _carregar_produtos

    return sorted(_carregar_produtos(), key=lambda p: int(p.get("prioridade") or 99))


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def _fmt_usd(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"US$ {float(valor):.2f}"
    except (TypeError, ValueError):
        return "n/d"


def _resumo_produto(r: dict[str, Any], *, cambio: float) -> list[str]:
    ml = r.get("sinais_ml") or {}
    ver = r.get("veredito") or {}
    melhor = r.get("melhor_analise") or {}
    mm = melhor.get("margem_melhor") or {}
    formal = melhor.get("calculo_aereo_formal") or {}
    preco_norm = melhor.get("preco_normalizado") or {}
    unidade_mk = int(melhor.get("unidade_marketplace_qtd") or produto_unidade_mk(r) or 1)

    linhas = [
        f"*{r.get('produto', '?')}* — {ver.get('label', '?')}",
        f"  ML: {ml.get('total_anuncios', 0)} anúncios | {ml.get('vendas_totais', 0)} vendas (proxy) | "
        f"demanda {ml.get('score_demanda', 0):.0f}%",
    ]
    pack = f" (pacote {unidade_mk})" if unidade_mk > 1 else ""
    if ml.get("preco_mediana_brl"):
        linhas.append(
            f"  Preço ML mediana {_fmt_brl(ml.get('preco_mediana_brl'))}{pack} | "
            f"min {_fmt_brl(ml.get('preco_min_brl'))}"
        )
    if melhor.get("preco_usd") is not None:
        linhas.append(
            f"  Alibaba: {_fmt_usd(melhor.get('preco_usd'))} | MOQ {melhor.get('moq', '?')}"
        )
        if preco_norm.get("unidade_por_preco", 1) > 1:
            linhas.append(
                f"  → US$ {preco_norm.get('preco_usd_unit', 0):.4f}/un "
                f"({preco_norm.get('unidade_rotulo', '?')})"
            )
    if formal.get("ok"):
        linhas.append(
            formatar_breakdown_viracopos_telegram(
                formal,
                cambio_usd_brl=cambio,
                preco_norm=preco_norm,
            ).replace("\n", "\n  ")
        )
    elif mm.get("ok"):
        linhas.append(
            f"  Custo import. {_fmt_brl(mm.get('custo_unitario_brl'))} | "
            f"margem {_fmt_brl(mm.get('margem_brl'))} ({mm.get('margem_pct', 0)}%)"
        )
    if melhor.get("url"):
        linhas.append(f"  🔗 {melhor['url']}")
    return linhas


def produto_unidade_mk(r: dict[str, Any]) -> int:
    try:
        return int((r.get("melhor_analise") or {}).get("unidade_marketplace_qtd") or 1)
    except (TypeError, ValueError):
        return 1


def montar_mensagem_telegram(
    consolidado: dict[str, Any],
    resultados: list[dict[str, Any]],
    *,
    cotacao: dict[str, Any],
    diag_coleta: dict[str, Any] | None = None,
) -> str:
    cambio = float(cotacao.get("usd_brl") or 0)
    linhas = [
        "🛒 *Mercado Livre × Alibaba — vale importar?*",
        "",
        f"💵 Dólar: R$ {cotacao.get('usd_brl')} ({cotacao.get('fonte', '?')})",
        f"Produtos: *{consolidado.get('produtos_varridos', 0)}* | "
        f"Vale importar: *{consolidado.get('vale_importar', 0)}* | "
        f"Avaliar: *{consolidado.get('avaliar', 0)}*",
        "",
    ]

    if diag_coleta and diag_coleta.get("coleta_vazia"):
        linhas.extend(
            [
                "⚠️ *Fontes sem dados* — zeros não significam mercado vazio.",
                f"*{diag_coleta.get('produtos', 0)}* produto(s) sem ML e sem Alibaba nesta rodada.",
                "",
                "*Verificar:*",
            ]
        )
        for dica in diag_coleta.get("dicas") or []:
            linhas.append(f"• {dica}")
        linhas.append("")

    top = consolidado.get("top_importar") or []
    if top:
        linhas.append("*✅ Vale importar (demanda ML + margem)*")
        for r in top[:6]:
            linhas.extend(_resumo_produto(r, cambio=cambio))
            linhas.append("")

    avaliar = consolidado.get("top_avaliar") or []
    if avaliar:
        linhas.append("*🟡 Avaliar com cautela*")
        for r in avaliar[:4]:
            linhas.extend(_resumo_produto(r, cambio=cambio))
            linhas.append("")

    outros = [
        r
        for r in resultados
        if r.get("ok")
        and (r.get("veredito") or {}).get("codigo") in ("nao_vale", "sem_ml", "sem_alibaba", "sem_dados")
    ]
    if outros and not diag_coleta:
        linhas.append("*Outros produtos*")
        for r in outros[:5]:
            ver = r.get("veredito") or {}
            ml = r.get("sinais_ml") or {}
            linhas.append(
                f"• {r.get('produto', '?')}: {ver.get('label', '?')} | "
                f"ML {ml.get('total_anuncios', 0)} anúncios | "
                f"Alibaba {r.get('total_oportunidades_alibaba', 0)} cotações"
            )

    return "\n".join(linhas).strip()


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — alertas não serão entregues")

        cotacao = obter_cotacao_usd()
        cambio = float(cotacao.get("usd_brl") or 0)
        if cambio <= 0:
            return {"ok": False, "erro": "câmbio inválido"}

        produtos = _carregar_produtos()
        if not produtos:
            logger.info("Nenhum produto ativo em %s", ALIBABA_IMPORTACAO_CATALOGO)
            return {"ok": True, "total_produtos": 0, "cotacao": cotacao, "resultados": []}

        agora = datetime.now(timezone.utc).isoformat()
        resultados: list[dict[str, Any]] = []

        for i, produto in enumerate(produtos):
            logger.info("ML×Alibaba: %s", produto.get("nome"))
            resultado = analisar_produto_ml_vs_alibaba(
                produto,
                cambio_usd_brl=cambio,
                pausa_alibaba_seg=ALIBABA_PAUSA_ENTRE_BUSCAS_SEG,
            )
            resultados.append(resultado)

            ver = resultado.get("veredito") or {}
            ml = resultado.get("sinais_ml") or {}
            gauge(
                "ml_tendencias_importacao.score_demanda",
                float(ml.get("score_demanda") or 0),
                tags=[f"produto:{produto.get('id', '?')}"],
            )
            gauge(
                "ml_tendencias_importacao.margem_pct",
                float(ver.get("margem_pct") or 0),
                tags=[f"produto:{produto.get('id', '?')}"],
            )
            incrementar(
                "ml_tendencias_importacao.produto",
                tags=[f"veredito:{ver.get('codigo', '?')}"],
            )

            if i < len(produtos) - 1 and ML_TENDENCIAS_IMPORTACAO_PAUSA_SEG > 0:
                time.sleep(ML_TENDENCIAS_IMPORTACAO_PAUSA_SEG)

        consolidado = consolidar_varredura(resultados)
        diag_coleta = diagnosticar_coleta_vazia(resultados)
        if diag_coleta:
            logger.warning(
                "ML×Alibaba: coleta vazia em %s produto(s)",
                diag_coleta.get("produtos"),
            )
            consolidado["coleta_vazia"] = True

        escrever_json_atomico(
            SNAPSHOT_PATH,
            {
                "timestamp": agora,
                "cotacao": cotacao,
                "consolidado": consolidado,
                "diag_coleta": diag_coleta,
                "resultados": resultados,
            },
        )
        historico = ler_json(HISTORY_PATH, default={})
        if not isinstance(historico, dict):
            historico = {}
        historico["ultima_varredura"] = agora
        historico["vale_importar"] = consolidado.get("vale_importar")
        historico["cotacao_usd_brl"] = cambio
        escrever_json_atomico(HISTORY_PATH, historico)

        alerta_enviado = False
        if enviar_alerta and ML_TENDENCIAS_IMPORTACAO_ALERTA_RESUMO and resultados:
            msg = montar_mensagem_telegram(
                consolidado,
                resultados,
                cotacao=cotacao,
                diag_coleta=diag_coleta,
            )
            alerta_enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave_resumo_periodo("importacao:ml_tendencias", horas_por_bucket=4),
                    cooldown_segundos=ML_TENDENCIAS_IMPORTACAO_COOLDOWN_SEG,
                )
            )

        gauge("ml_tendencias_importacao.vale_importar", float(consolidado.get("vale_importar") or 0))
        incrementar("ml_tendencias_importacao.rodadas")

        return {
            "ok": True,
            "cotacao": cotacao,
            "total_produtos": len(resultados),
            "consolidado": consolidado,
            "coleta_vazia": bool(diag_coleta),
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Agente ML tendências importação erro: %s", exc)
        incrementar("ml_tendencias_importacao.erro")
        return {"ok": False, "erro": str(exc), "resultados": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ML tendências × Alibaba — viabilidade de importação")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)

    logger.info("=== ML tendências × Alibaba (vale importar?) ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    c = out.get("consolidado") or {}
    logger.info(
        "Concluído: %s produto(s), %s vale importar, alerta=%s",
        out.get("total_produtos"),
        c.get("vale_importar"),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
