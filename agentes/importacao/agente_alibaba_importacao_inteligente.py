"""
agentes/importacao/agente_alibaba_importacao_inteligente.py
Monitora câmbio USD, varre Alibaba e calcula custo landed + margem vs marketplace.

Uso:
  python -m agentes.importacao.agente_alibaba_importacao_inteligente
  python -m agentes.importacao.agente_alibaba_importacao_inteligente --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    ALIBABA_IMPORTACAO_CATALOGO,
    ALIBABA_IA_AVALIAR_PARAMETROS,
    ALIBABA_INTELIGENCIA_ALERTA_RESUMO,
    ALIBABA_INTELIGENCIA_COOLDOWN_SEG,
    ALIBABA_MARGEM_ALERTA_COOLDOWN_SEG,
    ALIBABA_PAUSA_ENTRE_BUSCAS_SEG,
    CAMBIO_ALERTA_VARIACAO_PCT,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.alibaba.busca import buscar_oportunidades, montar_termo_busca
from integracoes.cambio.cotacao_usd import (
    cotacao_confiavel_para_margem,
    obter_cotacao_usd,
    variacao_desde_ultima_rodada,
)
from integracoes.importacao.analise_margem import analisar_produto_catalogo
from integracoes.importacao.avaliacao_ia_parametros import (
    avaliar_parametros_alibaba_inteligencia,
    formatar_secao_ia,
)
from integracoes.importacao.calculo_importacao_aerea import exportar_csv_resultado, formatar_breakdown_viracopos_telegram

logger = logging.getLogger("agente_alibaba_importacao_inteligente")

HISTORY_PATH = ROOT / "logs" / "alibaba_inteligencia_history.json"
SNAPSHOT_PATH = ROOT / "logs" / "alibaba_inteligencia_ultima.json"


def _carregar_produtos() -> list[dict[str, Any]]:
    from agentes.importacao.agente_alibaba_importacao import _carregar_produtos as carregar

    return carregar()


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


def _montar_alerta_cambio(cotacao: dict[str, Any], variacao: dict[str, Any]) -> str | None:
    if not variacao.get("ok"):
        return None
    diff = float(variacao.get("variacao_pct") or 0)
    if abs(diff) < CAMBIO_ALERTA_VARIACAO_PCT:
        return None
    seta = "📈" if diff > 0 else "📉"
    linhas = [
        f"{seta} *Dólar variou {diff:+.2f}%*",
        f"Atual: R$ {cotacao.get('usd_brl')} | Anterior: R$ {variacao.get('usd_brl_anterior')}",
        f"Fonte: {cotacao.get('fonte', '?')}",
        "_Impacta diretamente o custo de importação Alibaba._",
    ]
    if not cotacao_confiavel_para_margem(cotacao):
        linhas.append("_⚠️ Cotação não confiável para margem (fallback/desatualizada)._")
    return "\n".join(linhas)


def _resumo_custo(analise: dict[str, Any], *, cambio_usd_brl: float | None = None) -> str:
    cenarios = analise.get("cenarios_frete") or {}
    mar = cenarios.get("maritimo") or {}
    formal = analise.get("calculo_aereo_formal") or {}
    mk = analise.get("precos_marketplace") or {}
    margens = analise.get("margens") or {}
    mm = margens.get(analise.get("melhor_frete") or "aereo") or {}
    preco_norm = analise.get("preco_normalizado") or {}
    unidade_mk = int(analise.get("unidade_marketplace_qtd") or 1)

    linhas = [
        f"  Cotação Alibaba: {_fmt_usd(analise.get('preco_usd'))} | MOQ {analise.get('moq', '?')}",
    ]
    if preco_norm.get("unidade_por_preco", 1) > 1:
        linhas.append(
            f"  → US$ {preco_norm.get('preco_usd_unit', 0):.4f}/un "
            f"(listing / {preco_norm.get('unidade_rotulo', '?')})"
        )
    if formal.get("ok"):
        linhas.append(
            formatar_breakdown_viracopos_telegram(
                formal,
                cambio_usd_brl=cambio_usd_brl,
                preco_norm=preco_norm,
            )
        )
    else:
        aer = cenarios.get("aereo") or {}
        linhas.append(
            f"  Custo landed 🚢 {_fmt_brl(mar.get('custo_unitario_brl'))} | "
            f"✈️ {_fmt_brl(aer.get('custo_unitario_brl'))}"
        )
    if mk.get("ok"):
        pack = f" (pacote {unidade_mk} un.)" if unidade_mk > 1 else ""
        linhas.append(
            f"  Mercado BR (ML): mediana {_fmt_brl(mk.get('preco_mediana_brl'))}{pack} | "
            f"min {_fmt_brl(mk.get('preco_min_brl'))} ({mk.get('total_anuncios', 0)} anúncios)"
        )
    if mm.get("ok"):
        emoji = "✅" if mm.get("lucro_razoavel") else "⚠️"
        linhas.append(
            f"  {emoji} Margem ({analise.get('melhor_frete', 'aereo')}): "
            f"{_fmt_brl(mm.get('margem_brl'))} ({mm.get('margem_pct', 0)}%)"
        )
    return "\n".join(linhas)


def _montar_painel_produtos(
    resultados: list[dict[str, Any]],
    cotacao: dict[str, Any],
    ia: dict[str, Any] | None = None,
) -> str:
    linhas = [
        "📊 *Alibaba — painel de importação (todos os produtos)*",
        "",
        f"💵 Dólar: R$ {cotacao.get('usd_brl')} ({cotacao.get('fonte', '?')})",
    ]
    if not cotacao_confiavel_para_margem(cotacao):
        linhas.append("_⚠️ Margens abaixo são estimativa — câmbio fallback/desatualizado._")
    linhas.append("")
    for r in resultados:
        nome = r.get("produto") or r.get("id") or "?"
        mk = r.get("precos_marketplace") or {}
        melhor = r.get("melhor_analise")
        linhas.append(f"*{nome}*")
        linhas.append(
            f"  Oportunidades: {r.get('total_oportunidades', 0)} | "
            f"Lucrativas: {r.get('lucrativas', 0)}"
        )
        if mk.get("ok"):
            linhas.append(
                f"  Mercado Livre: mediana {_fmt_brl(mk.get('preco_mediana_brl'))} "
                f"({mk.get('total_anuncios', 0)} anúncios)"
            )
        if melhor and melhor.get("ok"):
            linhas.append(_resumo_custo(melhor, cambio_usd_brl=float(cotacao.get("usd_brl") or 0)))
            if melhor.get("url"):
                linhas.append(f"  🔗 {melhor['url']}")
        elif not r.get("analises"):
            linhas.append("  _Sem preço Alibaba parseado nesta rodada_")
        linhas.append("")

    secao_ia = formatar_secao_ia(ia)
    if secao_ia:
        linhas.append(secao_ia)

    return "\n".join(linhas).strip()


def _montar_alerta_lucrativos(resultados: list[dict[str, Any]], cotacao: dict[str, Any]) -> str | None:
    itens: list[str] = []
    for r in resultados:
        for a in r.get("analises") or []:
            if not a.get("lucro_razoavel"):
                continue
            mm = a.get("margem_melhor") or {}
            formal = a.get("calculo_aereo_formal") or {}
            custo_unit = formal.get("custo_unitario_brl") if formal.get("ok") else (
                (a.get("cenarios_frete") or {}).get(a.get("melhor_frete") or "aereo", {}).get("custo_unitario_brl")
            )
            titulo = str(a.get("titulo") or "Fornecedor")[:65]
            itens.append(
                f"• *{r.get('produto', '?')}* — {titulo}\n"
                f"  FOB {_fmt_usd(a.get('preco_usd'))} | formal VCP {_fmt_brl(custo_unit)}\n"
                f"  Margem {_fmt_brl(mm.get('margem_brl'))} ({mm.get('margem_pct')}%) via {a.get('melhor_frete')}\n"
                f"  🔗 {a.get('url', '')}"
            )
    if not itens:
        return None
    cab = [
        "💰 *Alibaba — oportunidades com lucro razoável*",
        "",
        f"Dólar: R$ {cotacao.get('usd_brl')}",
        "",
    ]
    return "\n".join(cab + itens[:8]).strip()


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — alertas não serão entregues")

        cotacao = obter_cotacao_usd()
        cambio = float(cotacao.get("usd_brl") or 0)
        if cambio <= 0:
            return {"ok": False, "erro": "câmbio inválido"}

        variacao = variacao_desde_ultima_rodada()
        gauge("alibaba_inteligencia.usd_brl", cambio)

        produtos = _carregar_produtos()
        if not produtos:
            logger.info("Nenhum produto ativo em %s", ALIBABA_IMPORTACAO_CATALOGO)
            return {"ok": True, "total_produtos": 0, "cotacao": cotacao, "resultados": []}

        historico = ler_json(HISTORY_PATH, default={})
        resultados: list[dict[str, Any]] = []
        agora = datetime.now(timezone.utc).isoformat()

        for produto in produtos:
            pid = str(produto.get("id") or "").strip()
            if not pid:
                continue
            termo = montar_termo_busca(produto)
            logger.info("Alibaba inteligência: %s | dólar R$ %.4f", termo, cambio)
            oportunidades = buscar_oportunidades(produto, pausa_seg=ALIBABA_PAUSA_ENTRE_BUSCAS_SEG)
            analise = analisar_produto_catalogo(
                produto,
                oportunidades,
                cambio_usd_brl=cambio,
            )
            resultados.append(analise)
            melhor = analise.get("melhor_analise") or {}
            formal = melhor.get("calculo_aereo_formal") or {}
            if formal.get("ok") and pid:
                csv_path = ROOT / "logs" / f"importacao_aerea_{pid}.csv"
                csv_path.parent.mkdir(parents=True, exist_ok=True)
                csv_path.write_text(exportar_csv_resultado(formal), encoding="utf-8")
            historico[pid] = {
                "produto": produto.get("nome"),
                "ultima_varredura": agora,
                "cambio_usd_brl": cambio,
                "total_oportunidades": len(oportunidades),
                "lucrativas": analise.get("lucrativas", 0),
                "precos_marketplace": analise.get("precos_marketplace"),
                "melhor_analise": analise.get("melhor_analise"),
            }
            incrementar(
                "alibaba_inteligencia.produto",
                tags=[f"lucrativas:{analise.get('lucrativas', 0)}"],
            )

        escrever_json_atomico(HISTORY_PATH, historico)

        ia_parametros = None
        if ALIBABA_IA_AVALIAR_PARAMETROS:
            ia_parametros = avaliar_parametros_alibaba_inteligencia(
                produtos_catalogo=produtos,
                resultados=resultados,
                cotacao=cotacao,
                variacao_cambio=variacao,
            )
        escrever_json_atomico(
            SNAPSHOT_PATH,
            {
                "timestamp": agora,
                "cotacao": cotacao,
                "variacao_cambio": variacao,
                "resultados": resultados,
                "avaliacao_ia_parametros": ia_parametros,
            },
        )

        alerta_cambio = False
        alerta_painel = False
        alerta_lucro = False

        if enviar_alerta:
            msg_cambio = _montar_alerta_cambio(cotacao, variacao)
            if msg_cambio:
                alerta_cambio = bool(
                    alertar_gestor(
                        msg_cambio,
                        chave=chave_resumo_periodo("cambio:usd", horas_por_bucket=2),
                        cooldown_segundos=ALIBABA_INTELIGENCIA_COOLDOWN_SEG,
                    )
                )

            if ALIBABA_INTELIGENCIA_ALERTA_RESUMO:
                painel = _montar_painel_produtos(resultados, cotacao, ia_parametros)
                alerta_painel = bool(
                    alertar_gestor(
                        painel,
                        chave=chave_resumo_periodo("alibaba:inteligencia:painel", horas_por_bucket=2),
                        cooldown_segundos=ALIBABA_INTELIGENCIA_COOLDOWN_SEG,
                    )
                )

            lucro = None
            if cotacao_confiavel_para_margem(cotacao):
                lucro = _montar_alerta_lucrativos(resultados, cotacao)
            else:
                logger.warning(
                    "Alibaba inteligência: pulando alerta de lucro — câmbio não confiável "
                    "(fonte=%s)",
                    cotacao.get("fonte"),
                )
            if lucro:
                alerta_lucro = bool(
                    alertar_gestor(
                        lucro,
                        chave=chave_resumo_periodo("alibaba:inteligencia:lucro", horas_por_bucket=2),
                        cooldown_segundos=ALIBABA_MARGEM_ALERTA_COOLDOWN_SEG,
                    )
                )

        total_lucrativas = sum(int(r.get("lucrativas") or 0) for r in resultados)
        return {
            "ok": True,
            "cotacao": cotacao,
            "variacao_cambio": variacao,
            "total_produtos": len(resultados),
            "total_lucrativas": total_lucrativas,
            "alerta_cambio": alerta_cambio,
            "alerta_painel": alerta_painel,
            "alerta_lucro": alerta_lucro,
            "avaliacao_ia_parametros": ia_parametros,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Agente Alibaba inteligência erro: %s", exc)
        return {"ok": False, "erro": str(exc), "resultados": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Alibaba + câmbio + custo landed + margem ML")
    parser.add_argument("--sem-alerta", action="store_true", help="Não envia Telegram")
    args = parser.parse_args(argv)

    logger.info("=== Alibaba importação inteligente ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    logger.info(
        "Concluído: %s produto(s), %s lucrativa(s), dólar R$ %s",
        out.get("total_produtos"),
        out.get("total_lucrativas"),
        (out.get("cotacao") or {}).get("usd_brl"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
