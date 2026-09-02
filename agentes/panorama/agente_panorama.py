"""
agentes/panorama/agente_panorama.py
Orquestrador de visão geral: ML + Magalu + Bling, NF-e (dry-run), alertas e síntese Claude.
Modo padrão: somente leitura e recomendação — sem escrita na conta.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agentes.faturamento.agente_faturamento import emitir_nfe_pedido
from agentes.ml import agente_monitor_ml
from core import config as cfg
from core.claude_client import perguntar
from core.notificador import alertar_critico, alertar_gestor
from integracoes.bling import bling_client
from integracoes.magalu import magalu_client
from integracoes.ml import ml_client

logger = logging.getLogger("agente_panorama")

LIMIAR_PRECO_PCT = 5.0


def _safe_int(val, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _bling_configurado() -> bool:
    return bool((cfg.BLING_ACCESS_TOKEN or "").strip())


def _alguma_integracao() -> bool:
    return ml_client._enabled() or magalu_client._enabled() or _bling_configurado()


def _pct_acima(maior: float, menor: float) -> float:
    if menor <= 0:
        return 0.0
    return round((maior - menor) / menor * 100, 1)


def classificar_decisao_ml(item: dict) -> str:
    """Classifica um item ML em decisão objetiva para o panorama."""
    menor = float(item.get("menor_concorrente") or 0)
    meu = float(item.get("meu_preco") or 0)
    if menor <= 0:
        return "SEM DADOS DE CATÁLOGO"

    diff = _pct_acima(meu, menor)
    if diff > LIMIAR_PRECO_PCT:
        return f"BAIXAR PREÇO (estou {diff:.1f}% acima)"

    visitas_7 = int(item.get("visitas_7d") or 0)
    estoque = item.get("estoque")
    if meu <= menor and visitas_7 >= 20 and isinstance(estoque, int) and estoque > 10:
        return "REVISAR ANÚNCIO (visitas altas, sem giro)"

    return "MANTER"


def _pedido_para_nfe(pedido_raw: dict, origem: str) -> dict | None:
    itens_fmt = []
    for it in pedido_raw.get("itens") or []:
        sku = str(it.get("sku") or "").strip()
        if not sku:
            continue
        try:
            qtd = int(it.get("quantidade") or 1)
        except (TypeError, ValueError):
            qtd = 1
        try:
            pu = float(it.get("preco_unitario") or it.get("valor_unitario") or 0)
        except (TypeError, ValueError):
            pu = 0.0
        itens_fmt.append({"sku": sku, "quantidade": qtd, "valor_unitario": pu})

    if not itens_fmt:
        return None

    oid = str(pedido_raw.get("order_id") or pedido_raw.get("pedido_id") or "?")
    return {
        "pedido_id": f"{origem}-{oid}",
        "cliente": {"nome": "Consumidor Final", "documento": ""},
        "itens": itens_fmt,
    }


def _coletar_mercado_livre(limite_itens: int) -> dict[str, Any]:
    if not ml_client._enabled():
        return {"configurado": False}

    try:
        monitor = agente_monitor_ml.analisar(
            enviar_alerta=False,
            limite_itens=limite_itens,
        )
    except Exception as exc:
        logger.error("panorama monitor_ml: %s", exc)
        monitor = {"ok": False, "erro": str(exc)}

    concorrencia = monitor.get("concorrencia") or []
    decisoes: list[dict] = []
    for item in concorrencia:
        decisao = classificar_decisao_ml(item)
        decisoes.append(
            {
                "item_id": item.get("item_id"),
                "titulo": item.get("titulo", ""),
                "decisao": decisao,
                "prioridade": float(item.get("prioridade") or 0),
                "meu_preco": item.get("meu_preco"),
                "menor_concorrente": item.get("menor_concorrente"),
                "concorrentes": item.get("concorrentes") or [],
            }
        )

    decisoes.sort(key=lambda x: x.get("prioridade", 0), reverse=True)

    return {
        "configurado": True,
        "monitor": monitor,
        "decisoes": decisoes,
        "urgentes": decisoes[:5],
        "recomendacoes": monitor.get("recomendacoes") or [],
    }


def _coletar_magalu() -> dict[str, Any]:
    if not magalu_client._enabled():
        return {"configurado": False}

    bloco: dict[str, Any] = {"configurado": True}
    try:
        bloco["saude"] = magalu_client.obter_saude_conta()
    except Exception as exc:
        logger.error("panorama magalu saude: %s", exc)
        bloco["erro_saude"] = str(exc)

    try:
        perguntas = magalu_client.listar_perguntas_nao_respondidas()
        bloco["perguntas"] = perguntas
        bloco["perguntas_pendentes"] = len(perguntas)
    except Exception as exc:
        logger.error("panorama magalu perguntas: %s", exc)
        bloco["perguntas_pendentes"] = 0

    try:
        pedidos = magalu_client.listar_pedidos(dias=7)
        bloco["pedidos"] = pedidos
        bloco["pedidos_total"] = len(pedidos)
    except Exception as exc:
        logger.error("panorama magalu pedidos: %s", exc)
        bloco["pedidos"] = []
        bloco["pedidos_total"] = 0

    return bloco


def _coletar_bling() -> dict[str, Any]:
    if not _bling_configurado():
        return {"configurado": False}

    bloco: dict[str, Any] = {"configurado": True}
    try:
        produtos = bling_client.listar_produtos()
        bloco["total_produtos"] = len(produtos)
    except Exception as exc:
        logger.error("panorama bling produtos: %s", exc)
        bloco["total_produtos"] = 0
        bloco["erro_produtos"] = str(exc)

    try:
        criticos = bling_client.estoques_criticos()
        bloco["estoque_critico"] = criticos
        bloco["estoque_critico_total"] = len(criticos)
    except Exception as exc:
        logger.error("panorama bling estoque: %s", exc)
        bloco["estoque_critico"] = []
        bloco["estoque_critico_total"] = 0

    return bloco


def _coletar_dados_ml(limite_itens: int) -> dict[str, Any]:
    try:
        return _coletar_mercado_livre(limite_itens)
    except Exception as exc:
        logger.error("panorama coletar ml: %s", exc)
        return {"erro": str(exc)}


def _coletar_dados_magalu() -> dict[str, Any]:
    try:
        return _coletar_magalu()
    except Exception as exc:
        logger.error("panorama coletar magalu: %s", exc)
        return {"erro": str(exc)}


def _coletar_dados_bling() -> dict[str, Any]:
    try:
        return _coletar_bling()
    except Exception as exc:
        logger.error("panorama coletar bling: %s", exc)
        return {"erro": str(exc)}


def _processar_nfe(
    pedidos_brutos: list[tuple[str, dict]],
    *,
    emitir_nfe: bool,
) -> dict[str, Any]:
    resultado = {
        "a_faturar": 0,
        "prontos": 0,
        "pendencias": [],
        "emitidos": 0,
        "dry_run": not emitir_nfe,
    }

    for origem, pedido_raw in pedidos_brutos:
        pedido_nfe = _pedido_para_nfe(pedido_raw, origem)
        if not pedido_nfe:
            continue

        resultado["a_faturar"] += 1
        try:
            dry = emitir_nfe_pedido(pedido_nfe, dry_run=True)
        except Exception as exc:
            logger.error("panorama nfe dry-run %s: %s", pedido_nfe.get("pedido_id"), exc)
            resultado["pendencias"].append(
                {"pedido_id": pedido_nfe["pedido_id"], "erro": str(exc)}
            )
            continue

        if dry.get("ok"):
            resultado["prontos"] += 1
            if emitir_nfe:
                try:
                    real = emitir_nfe_pedido(pedido_nfe, dry_run=False)
                    if real.get("ok"):
                        resultado["emitidos"] += 1
                    else:
                        resultado["pendencias"].append(
                            {
                                "pedido_id": pedido_nfe["pedido_id"],
                                "erro": real.get("erro", "falha na emissão"),
                            }
                        )
                except Exception as exc:
                    logger.error("panorama nfe emitir %s: %s", pedido_nfe["pedido_id"], exc)
                    resultado["pendencias"].append(
                        {"pedido_id": pedido_nfe["pedido_id"], "erro": str(exc)}
                    )
        else:
            resultado["pendencias"].append(
                {
                    "pedido_id": pedido_nfe["pedido_id"],
                    "erro": dry.get("erro", ""),
                    "detalhes": dry.get("erros") or [],
                }
            )

    return resultado


def _montar_alertas(
    ml: dict,
    magalu: dict,
    bling: dict,
    nfe: dict,
) -> list[str]:
    alertas: list[str] = []

    if ml.get("configurado"):
        monitor = ml.get("monitor") or {}
        conta = monitor.get("conta") or {}
        if _safe_int(conta.get("perguntas_pendentes")) > 0:
            alertas.append(f"ML: {conta['perguntas_pendentes']} pergunta(s) sem resposta")
        ads = monitor.get("ads") or {}
        acima = ads.get("campanhas_acos_alto") or []
        if acima:
            alertas.append(f"ML Ads: {len(acima)} campanha(s) com ACOS alto")

    if magalu.get("configurado") and _safe_int(magalu.get("perguntas_pendentes")) > 0:
        alertas.append(f"Magalu: {magalu['perguntas_pendentes']} pergunta(s) pendentes")

    if bling.get("configurado") and _safe_int(bling.get("estoque_critico_total")) > 0:
        alertas.append(f"Bling: {bling['estoque_critico_total']} produto(s) com estoque crítico")

    if nfe.get("pendencias"):
        alertas.append(f"NF-e: {len(nfe['pendencias'])} pedido(s) com pendência fiscal")

    return alertas


def _montar_parametros_financeiros() -> dict[str, float]:
    return {
        "acos_maximo_pct": round(cfg.ACOS_MAXIMO * 100, 1),
        "margem_minima_pct": round(cfg.MARGEM_MINIMA, 1),
        "margem_fase_1_pct": round(cfg.MARGEM_FASE_1_PCT, 1),
        "margem_fase_2_pct": round(cfg.MARGEM_FASE_2_PCT, 1),
        "margem_fase_3_pct": round(cfg.MARGEM_FASE_3_PCT, 1),
    }


def _formatar_linha_parametros_financeiros(params: dict[str, float]) -> str:
    return (
        f"⚙️ Parâmetros atuais: ACOS máx {params['acos_maximo_pct']:.0f}% | "
        f"Margem mínima {params['margem_minima_pct']:.0f}% | "
        f"Fases {params['margem_fase_1_pct']:.0f}/"
        f"{params['margem_fase_2_pct']:.0f}/"
        f"{params['margem_fase_3_pct']:.0f}%"
    )


def _montar_contexto_claude(
    ml: dict,
    magalu: dict,
    bling: dict,
    nfe: dict,
    alertas: list[str],
    decisoes: list[str],
) -> str:
    dados = {
        "mercado_livre": ml,
        "magalu": magalu,
        "bling": bling,
        "nfe": nfe,
        "alertas": alertas,
        "decisoes_prioritarias": decisoes,
        "fiscal_defaults": {
            "NFE_NATUREZA_OPERACAO": cfg.NFE_NATUREZA_OPERACAO,
            "NFE_CFOP_PADRAO": cfg.NFE_CFOP_PADRAO,
            "NFE_CST_PADRAO": cfg.NFE_CST_PADRAO,
            "NFE_CSOSN_PADRAO": cfg.NFE_CSOSN_PADRAO,
            "NFE_ORIGEM_PADRAO": cfg.NFE_ORIGEM_PADRAO,
            "NFE_SERIE_PADRAO": cfg.NFE_SERIE_PADRAO,
        },
    }
    return json.dumps(dados, ensure_ascii=False, default=str)[:12000]


def _resumo_por_regras(
    ml: dict,
    magalu: dict,
    bling: dict,
    nfe: dict,
    alertas: list[str],
    decisoes: list[str],
) -> str:
    linhas = ["*Situação*"]
    if ml.get("configurado"):
        monitor = ml.get("monitor") or {}
        conta = monitor.get("conta") or {}
        linhas.append(
            f"- ML: {conta.get('perguntas_pendentes', 0)} pergunta(s); "
            f"urgentes concorrência: {len(ml.get('urgentes', []))}"
        )
    else:
        linhas.append("- ML: não configurado")

    if magalu.get("configurado"):
        linhas.append(
            f"- Magalu: {magalu.get('perguntas_pendentes', 0)} pergunta(s), "
            f"{magalu.get('pedidos_total', 0)} pedido(s)/7d"
        )
    else:
        linhas.append("- Magalu: não configurado")

    if bling.get("configurado"):
        linhas.append(
            f"- Bling: {bling.get('total_produtos', 0)} produto(s), "
            f"{bling.get('estoque_critico_total', 0)} crítico(s)"
        )
    else:
        linhas.append("- Bling: não configurado")

    linhas.append(f"- NF-e: {nfe.get('prontos', 0)}/{nfe.get('a_faturar', 0)} prontos (dry-run)")

    linhas.append("")
    linhas.append("*Riscos*")
    if alertas:
        for a in alertas[:8]:
            linhas.append(f"- {a}")
    else:
        linhas.append("- Nenhum alerta crítico imediato")

    linhas.append("")
    linhas.append("*Ações recomendadas (priorizadas)*")
    if decisoes:
        for i, d in enumerate(decisoes[:10], start=1):
            linhas.append(f"{i}. {d}")
    else:
        linhas.append("1. Manter monitoramento diário")

    return "\n".join(linhas)


def _sintetizar_claude(contexto: str, fallback: str) -> str:
    if not (cfg.ANTHROPIC_API_KEY or "").strip():
        return fallback

    try:
        from core.claude_client import contexto_suficiente

        if not contexto_suficiente(contexto):
            return fallback
        prompt = (
            "Com base no contexto JSON acima, responda de forma OBJETIVA em tópicos:\n"
            "1. Situação\n2. Riscos\n3. Ações recomendadas (priorizadas)\n"
            "Seja conciso. Priorize o que gera receita ou reduz risco hoje.\n"
            "Ao comentar concorrência, use APENAS os campos presentes no JSON "
            "(ex.: titulo, preco, frete_gratis, condicao, quantidade_vendida em "
            "mercado_livre.monitor.concorrencia[].concorrentes). "
            "Não invente dados que não estejam no contexto. "
            "Sugira FAZER/NÃO FAZER/OBSERVAR — o gestor autoriza; não publique nem ligue Ads."
        )
        from core.claude_roteador import resolver_modelo_vendas

        rota = resolver_modelo_vendas(proposito="panorama")
        resposta = perguntar(
            prompt,
            max_tokens=800,
            contexto=contexto,
            origem="panorama.agente_panorama",
            exigir_contexto=True,
            modelo=rota.get("modelo"),
            forcar_modelo=bool(rota.get("forcar_modelo")),
        )
        if not resposta or resposta.startswith("⚠️") or "API" in resposta:
            return fallback
        return resposta.strip()
    except Exception as exc:
        logger.error("panorama claude: %s", exc)
        return fallback


def _coletar_decisoes_texto(ml: dict, alertas: list[str]) -> list[str]:
    decisoes: list[str] = []
    for item in ml.get("urgentes") or []:
        titulo = str(item.get("titulo", item.get("item_id", "?")))[:40]
        decisoes.append(f"{item.get('decisao')} — {titulo}")

    if ml.get("configurado"):
        for rec in (ml.get("recomendacoes") or [])[:5]:
            decisoes.append(rec)

    for a in alertas:
        if a not in decisoes:
            decisoes.append(a)

    return list(dict.fromkeys(decisoes))


def gerar_panorama(
    *,
    enviar_alerta: bool = True,
    emitir_nfe: bool = False,
    limite_itens: int | None = None,
) -> dict[str, Any]:
    """
    Coleta panorama ML + Magalu + Bling, valida NF-e (dry-run por padrão) e sintetiza com Claude.
    """
    if limite_itens is None:
        limite_itens = agente_monitor_ml.MAX_ITENS_ANALISE

    if not _alguma_integracao():
        motivo = "nenhuma integração configurada"
        msg = (
            "Panorama: nenhuma integração ativa — configure ML, Magalu e/ou Bling."
        )
        enviado = False
        if enviar_alerta:
            try:
                enviado = bool(alertar_gestor(msg))
            except Exception as exc:
                logger.error("panorama alerta sem integracao: %s", exc)
        return {
            "ok": False,
            "motivo": motivo,
            "enviado": enviado,
            "resumo_claude": msg,
        }

    mercado_livre: dict[str, Any]
    magalu: dict[str, Any]
    bling: dict[str, Any]
    with ThreadPoolExecutor(max_workers=3) as ex:
        fut_ml = ex.submit(_coletar_dados_ml, limite_itens)
        fut_magalu = ex.submit(_coletar_dados_magalu)
        fut_bling = ex.submit(_coletar_dados_bling)
        mercado_livre = fut_ml.result()
        magalu = fut_magalu.result()
        bling = fut_bling.result()

    pedidos_brutos: list[tuple[str, dict]] = []
    if mercado_livre.get("configurado"):
        try:
            for p in ml_client.listar_pedidos(dias=7):
                pedidos_brutos.append(("ML", p))
        except Exception as exc:
            logger.error("panorama ml pedidos: %s", exc)

    if magalu.get("configurado"):
        for p in magalu.get("pedidos") or []:
            pedidos_brutos.append(("MAGALU", p))

    nfe = _processar_nfe(pedidos_brutos, emitir_nfe=emitir_nfe)
    alertas = _montar_alertas(mercado_livre, magalu, bling, nfe)
    decisoes = _coletar_decisoes_texto(mercado_livre, alertas)

    contexto = _montar_contexto_claude(
        mercado_livre, magalu, bling, nfe, alertas, decisoes
    )
    fallback = _resumo_por_regras(
        mercado_livre, magalu, bling, nfe, alertas, decisoes
    )
    resumo_claude = _sintetizar_claude(contexto, fallback)
    parametros_financeiros = _montar_parametros_financeiros()
    linha_parametros = _formatar_linha_parametros_financeiros(parametros_financeiros)

    if alertas:
        try:
            alertar_critico("Panorama — alertas:\n" + "\n".join(f"• {a}" for a in alertas[:6]))
        except Exception as exc:
            logger.error("panorama alertar_critico: %s", exc)

    enviado = False
    if enviar_alerta:
        try:
            mensagem_gestor = f"{resumo_claude}\n\n{linha_parametros}"
            enviado = bool(alertar_gestor(mensagem_gestor))
        except Exception as exc:
            logger.error("panorama alertar_gestor: %s", exc)

    return {
        "ok": True,
        "mercado_livre": mercado_livre,
        "magalu": magalu,
        "bling": bling,
        "nfe": nfe,
        "alertas": alertas,
        "resumo_claude": resumo_claude,
        "parametros_financeiros": parametros_financeiros,
        "linha_parametros_financeiros": linha_parametros,
        "decisoes": decisoes,
        "enviado": enviado,
    }


def main() -> int:
    resultado = gerar_panorama(enviar_alerta=False, emitir_nfe=False)
    print(resultado.get("resumo_claude") or resultado.get("motivo", "Sem resultado"))
    if resultado.get("ok"):
        print()
        print(f"[INFO] Alertas: {len(resultado.get('alertas', []))}")
        print(f"[INFO] Decisões: {len(resultado.get('decisoes', []))}")
        nfe = resultado.get("nfe") or {}
        print(
            f"[INFO] NF-e dry-run: {nfe.get('prontos', 0)}/{nfe.get('a_faturar', 0)} prontos"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
