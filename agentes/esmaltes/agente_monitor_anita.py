"""
agentes/esmaltes/agente_monitor_anita.py
Monitora anúncios de esmaltes Anita no ML: diferença de cores/kits vs preferência,
ranking de marcas por vendas e margem de lucro.

Catálogo: catalogo/anita_esmaltes_monitorados.json

Uso:
  python -m agentes.esmaltes.agente_monitor_anita
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    ANITA_ALERTA_RESUMO,
    ANITA_ALERTA_RESUMO_COOLDOWN_SEG,
    ANITA_ESMALTES_CATALOGO,
    ANITA_PAUSA_ENTRE_BUSCAS_SEG,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.esmaltes.analise_anita import analisar_produto
from integracoes.ml import ml_client

logger = logging.getLogger("agente_monitor_anita")

HISTORY_PATH = ROOT / "logs" / "anita_esmaltes_history.json"
SNAPSHOT_PATH = ROOT / "logs" / "anita_esmaltes_ultima.json"


def _carregar_produtos() -> list[dict[str, Any]]:
    caminho = ROOT / ANITA_ESMALTES_CATALOGO
    try:
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        return [p for p in data if isinstance(p, dict) and p.get("ativo")]
    except Exception as exc:
        logger.error("Erro ao carregar catálogo Anita: %s", exc)
        return []


def consolidar_impala(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    """Consolida KPIs Impala entre todos os termos monitorados."""
    ok = [r for r in resultados if r.get("ok")]
    if not ok:
        return {}

    vendas_impala = sum(int(r.get("unidades_vendidas_impala") or 0) for r in ok)
    vendas_anita = sum(int(r.get("unidades_vendidas_anita") or 0) for r in ok)
    total_marcas = vendas_impala + vendas_anita
    lider_impala = sum(1 for r in ok if r.get("impala_lider_vendas"))
    termos_com_impala = sum(1 for r in ok if int(r.get("total_impala") or 0) > 0)

    menores_impala = [float(r["menor_preco_impala"]) for r in ok if r.get("menor_preco_impala")]
    shares = [float(r["share_impala_pct"]) for r in ok if r.get("share_impala_pct") is not None]

    return {
        "termos_monitorados": len(ok),
        "termos_com_impala": termos_com_impala,
        "termos_impala_lider": lider_impala,
        "unidades_vendidas_impala": vendas_impala,
        "unidades_vendidas_anita": vendas_anita,
        "share_impala_global_pct": round(100.0 * vendas_impala / total_marcas, 1) if total_marcas else None,
        "share_impala_medio_pct": round(sum(shares) / len(shares), 1) if shares else None,
        "menor_preco_impala": min(menores_impala) if menores_impala else None,
        "margem_media_pct": round(
            sum(float((r.get("margem_minha") or {}).get("margem_operacional_pct") or 0) for r in ok) / len(ok),
            1,
        )
        if ok
        else None,
    }


def montar_resumo_orquestrador_impala(
    total_produtos: int,
    consolidado: dict[str, Any],
    *,
    alerta_enviado: bool,
) -> str:
    partes = [f"{total_produtos} produtos"]
    if not consolidado:
        partes.append("sem dados Impala")
    else:
        lider = int(consolidado.get("termos_impala_lider") or 0)
        termos = int(consolidado.get("termos_monitorados") or 0)
        if termos:
            partes.append(f"Impala líder em {lider}/{termos} termos")
        vendas = int(consolidado.get("unidades_vendidas_impala") or 0)
        if vendas:
            partes.append(f"{vendas} vend. Impala")
        share = consolidado.get("share_impala_global_pct")
        if share is not None:
            partes.append(f"share {share:.0f}%")
        menor = consolidado.get("menor_preco_impala")
        if menor is not None:
            partes.append(f"menor Impala R$ {float(menor):.2f}")
        margem = consolidado.get("margem_media_pct")
        if margem is not None:
            partes.append(f"margem média {margem:.0f}%")
    if alerta_enviado:
        partes.append("alerta enviado")
    return ", ".join(partes)


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def _fmt_pct(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"{float(valor):+.1f}%"
    except (TypeError, ValueError):
        return "n/d"


def _montar_resumo_produto(r: dict[str, Any]) -> list[str]:
    linhas = [f"*{r.get('nome', r.get('id', '?'))}*"]
    margem = r.get("margem_minha") or {}
    meu = r.get("meu_preco")
    linhas.append(
        f"  Seu preço {_fmt_brl(meu)} | margem {margem.get('margem_operacional_pct', 'n/d')}% "
        f"({_fmt_brl(margem.get('lucro_reais'))} lucro)"
    )

    linhas.append(
        f"  Anúncios: {r.get('total_anuncios', 0)} | Anita: {r.get('total_anita', 0)} | "
        f"Impala: {r.get('total_impala', 0)} | Líder: *{r.get('marca_mais_vendida', '?')}*"
    )
    if int(r.get("unidades_vendidas_impala") or 0) > 0 or int(r.get("unidades_vendidas_anita") or 0) > 0:
        share = r.get("share_impala_pct")
        share_txt = f"{share:.0f}%" if share is not None else "n/d"
        linhas.append(
            f"  Vendas Impala: {r.get('unidades_vendidas_impala', 0)} | Anita: {r.get('unidades_vendidas_anita', 0)} "
            f"| share Impala {share_txt}"
        )
    if r.get("menor_preco_impala"):
        linhas.append(
            f"  Menor Impala: {_fmt_brl(r['menor_preco_impala'])} "
            f"({_fmt_pct(r.get('diff_preco_impala_vs_meu_pct'))} vs seu preço) | "
            f"média {_fmt_brl(r.get('preco_medio_impala'))}"
        )
    if r.get("menor_preco_anita"):
        diff = None
        if meu and r["menor_preco_anita"]:
            diff = round((float(r["menor_preco_anita"]) - float(meu)) / float(meu) * 100, 1)
        linhas.append(
            f"  Menor Anita: {_fmt_brl(r['menor_preco_anita'])} ({_fmt_pct(diff)} vs seu preço)"
        )

    if r.get("tipo") == "kit":
        qtd_pref = None
        for a in r.get("analises") or []:
            if a.get("qtd_kit_preferencia"):
                qtd_pref = a.get("qtd_kit_preferencia")
                break
        if qtd_pref:
            linhas.append(f"  Kit preferência: {qtd_pref} esmaltes | divergências kit: {r.get('divergencias_kit', 0)}")
    if r.get("divergencias_cor", 0) > 0:
        linhas.append(f"  ⚠️ Divergências de cor: {r['divergencias_cor']}")

    ranking = r.get("ranking_marcas") or []
    if ranking:
        top3 = ranking[:3]
        partes = [f"{x['marca']} ({x['vendidos']} vend.)" for x in top3]
        linhas.append(f"  Top marcas: {', '.join(partes)}")

    # Destaque anúncios Anita fora da preferência
    for a in (r.get("analises") or [])[:4]:
        if a.get("marca_detectada") != "Anita":
            continue
        if a.get("conforme_preferencia"):
            continue
        titulo = str(a.get("titulo") or "")[:55]
        detalhes: list[str] = []
        if a.get("diff_qtd_kit") not in (None, 0):
            detalhes.append(f"kit {a.get('qtd_kit_detectada')} vs pref {a.get('qtd_kit_preferencia')}")
        if a.get("cores_faltando"):
            detalhes.append(f"falta: {', '.join(a['cores_faltando'][:3])}")
        if detalhes:
            linhas.append(f"  • {titulo} — {'; '.join(detalhes)}")
    return linhas


def diagnosticar_coleta_vazia(resultados: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Todos os termos sem anúncios = falha de busca ML/Brave, não mercado vazio."""
    ok = [r for r in resultados if r.get("ok")]
    if not ok:
        return None
    total_anuncios = sum(int(r.get("total_anuncios") or 0) for r in ok)
    if total_anuncios > 0:
        return None

    from core.ddg_lite import mensagem_circuit_breaker
    from core.prontidao import brave_configurado, ml_configurado

    dicas: list[str] = []
    if brave_configurado():
        dicas.append(
            "Brave Search retornou 0 — verifique cota/plano da `BRAVE_SEARCH_API_KEY` "
            "(fallback da busca ML)"
        )
    else:
        dicas.append("Configure `BRAVE_SEARCH_API_KEY` para fallback quando a API ML bloqueia")
    if ml_configurado():
        dicas.append("API ML `/sites/search` costuma retornar 403 — depende de Brave/DDG")
    ddg_msg = mensagem_circuit_breaker("ml_busca_termo")
    if ddg_msg:
        dicas.append(ddg_msg)
    else:
        dicas.append("DDG sem resultados (comum em IP de datacenter/CI)")

    return {"coleta_vazia": True, "produtos": len(ok), "dicas": dicas}


def _formatar_aviso_coleta_vazia(diag: dict[str, Any]) -> str:
    linhas = [
        "⚠️ *Busca ML sem resultados* — os zeros abaixo *não* significam mercado vazio.",
        f"Monitorados *{diag.get('produtos', 0)}* produto(s), mas nenhum anúncio foi encontrado.",
        "",
        "*O que verificar:*",
    ]
    for dica in diag.get("dicas") or []:
        linhas.append(f"• {dica}")
    return "\n".join(linhas)


def _montar_painel(
    resultados: list[dict[str, Any]],
    consolidado_impala: dict[str, Any] | None = None,
    *,
    diag_coleta: dict[str, Any] | None = None,
) -> str:
    from core.telegram_explicacao import cabecalho_agente

    linhas = [
        cabecalho_agente("monitor_anita", "💅 *Seus kits Impala vs mercado ML*"),
        "_Compara seu preço/margem com Anita e outras marcas no mesmo termo de busca._",
        "",
    ]
    if diag_coleta and diag_coleta.get("coleta_vazia"):
        linhas.extend([_formatar_aviso_coleta_vazia(diag_coleta), ""])
    if consolidado_impala:
        linhas.extend(
            [
                "*Desempenho Impala (consolidado)*",
                f"  • Líder de vendas em *{consolidado_impala.get('termos_impala_lider', 0)}/"
                f"{consolidado_impala.get('termos_monitorados', 0)}* termos",
                f"  • Vendas Impala: *{consolidado_impala.get('unidades_vendidas_impala', 0)}* | "
                f"Anita: {consolidado_impala.get('unidades_vendidas_anita', 0)}",
            ]
        )
        if consolidado_impala.get("share_impala_global_pct") is not None:
            linhas.append(
                f"  • Share Impala (Impala+Anita): *{consolidado_impala['share_impala_global_pct']:.0f}%*"
            )
        if consolidado_impala.get("menor_preco_impala") is not None:
            linhas.append(f"  • Menor preço Impala: {_fmt_brl(consolidado_impala['menor_preco_impala'])}")
        if consolidado_impala.get("margem_media_pct") is not None:
            linhas.append(f"  • Sua margem média: *{consolidado_impala['margem_media_pct']:.1f}%*")
        linhas.append("")

    ranking_global: dict[str, int] = {}
    for r in resultados:
        for item in r.get("ranking_marcas") or []:
            marca = str(item.get("marca") or "?")
            ranking_global[marca] = ranking_global.get(marca, 0) + int(item.get("vendidos") or 0)

    if ranking_global:
        ordenado = sorted(ranking_global.items(), key=lambda x: x[1], reverse=True)
        linhas.append("*Marca mais vendida no mercado (soma dos termos):*")
        for marca, vend in ordenado[:5]:
            linhas.append(f"  • {marca}: {vend} vendas")
        linhas.append("")

    for r in sorted(resultados, key=lambda x: int(x.get("prioridade") or 99)):
        linhas.extend(_montar_resumo_produto(r))
        linhas.append("")

    return "\n".join(linhas).strip()


def _monitorar_produto(produto: dict[str, Any]) -> dict[str, Any]:
    termo = str(produto.get("termo_busca") or "").strip()
    limite = int(produto.get("limite_resultados") or 12)
    if not termo:
        return {"id": produto.get("id"), "ok": False, "motivo": "termo vazio"}

    anuncios = ml_client.buscar_concorrentes_por_termo(termo, limite=limite)
    analise = analisar_produto(produto, anuncios)
    analise["ok"] = True
    analise["prioridade"] = int(produto.get("prioridade") or 99)
    analise["meu_preco"] = produto.get("meu_preco")

    pid = str(produto.get("id") or "")
    gauge("anita.total_anuncios", float(len(anuncios)), tags=[f"produto:{pid}"])
    gauge("anita.total_anita", float(analise.get("total_anita") or 0), tags=[f"produto:{pid}"])
    gauge("anita.total_impala", float(analise.get("total_impala") or 0), tags=[f"produto:{pid}"])
    gauge("anita.vendas_impala", float(analise.get("unidades_vendidas_impala") or 0), tags=[f"produto:{pid}"])
    if analise.get("share_impala_pct") is not None:
        gauge("anita.share_impala_pct", float(analise["share_impala_pct"]), tags=[f"produto:{pid}"])
    margem = analise.get("margem_minha") or {}
    if margem.get("margem_operacional_pct") is not None:
        gauge("anita.margem_pct", float(margem["margem_operacional_pct"]), tags=[f"produto:{pid}"])

    logger.info(
        "Anita %s: %s anúncio(s) | Anita %s | Impala %s (%s vend., share %s%%) | líder %s | "
        "menor Impala %s | margem %.1f%%",
        produto.get("nome"),
        len(anuncios),
        analise.get("total_anita"),
        analise.get("total_impala"),
        analise.get("unidades_vendidas_impala"),
        analise.get("share_impala_pct", "n/d"),
        analise.get("marca_mais_vendida"),
        analise.get("menor_preco_impala"),
        float(margem.get("margem_operacional_pct") or 0),
    )
    return analise


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — alertas Anita não serão entregues")

        produtos = sorted(_carregar_produtos(), key=lambda p: int(p.get("prioridade") or 99))
        if not produtos:
            return {"ok": True, "total_produtos": 0, "resultados": []}

        resultados: list[dict[str, Any]] = []
        agora = datetime.now(timezone.utc).isoformat()

        for i, produto in enumerate(produtos):
            if i > 0 and ANITA_PAUSA_ENTRE_BUSCAS_SEG > 0:
                time.sleep(ANITA_PAUSA_ENTRE_BUSCAS_SEG)
            resultados.append(_monitorar_produto(produto))

        consolidado_impala = consolidar_impala(resultados)
        diag_coleta = diagnosticar_coleta_vazia(resultados)
        if diag_coleta:
            logger.warning(
                "Monitor Impala: coleta vazia em %s produto(s) — busca ML/Brave sem resultados",
                diag_coleta.get("produtos"),
            )

        historico = ler_json(HISTORY_PATH, default={})
        historico["ultima_varredura"] = agora
        historico["impala"] = consolidado_impala
        if diag_coleta:
            historico["coleta_vazia"] = True
            historico["diag_coleta"] = diag_coleta
        historico["produtos"] = {
            str(r.get("id")): {
                "marca_mais_vendida": r.get("marca_mais_vendida"),
                "menor_preco_anita": r.get("menor_preco_anita"),
                "menor_preco_impala": r.get("menor_preco_impala"),
                "unidades_vendidas_impala": r.get("unidades_vendidas_impala"),
                "share_impala_pct": r.get("share_impala_pct"),
                "impala_lider_vendas": r.get("impala_lider_vendas"),
                "margem_pct": (r.get("margem_minha") or {}).get("margem_operacional_pct"),
                "divergencias_kit": r.get("divergencias_kit"),
                "divergencias_cor": r.get("divergencias_cor"),
            }
            for r in resultados
            if r.get("ok")
        }
        escrever_json_atomico(HISTORY_PATH, historico)
        escrever_json_atomico(
            SNAPSHOT_PATH,
            {
                "timestamp": agora,
                "consolidado_impala": consolidado_impala,
                "coleta_vazia": bool(diag_coleta),
                "diag_coleta": diag_coleta,
                "resultados": resultados,
            },
        )

        alerta_enviado = False
        if enviar_alerta and ANITA_ALERTA_RESUMO and resultados:
            painel = _montar_painel(resultados, consolidado_impala, diag_coleta=diag_coleta)
            alerta_enviado = bool(
                alertar_gestor(
                    painel,
                    chave=chave_resumo_periodo("anita:esmaltes", horas_por_bucket=2),
                    cooldown_segundos=ANITA_ALERTA_RESUMO_COOLDOWN_SEG,
                    agente_id="monitor_anita",
                )
            )

        incrementar("anita.rodadas", tags=[f"produtos:{len(resultados)}"])
        resumo_orq = montar_resumo_orquestrador_impala(
            len(resultados),
            consolidado_impala,
            alerta_enviado=alerta_enviado,
        )
        logger.info("Impala consolidado: %s", resumo_orq)
        return {
            "ok": True,
            "total_produtos": len(resultados),
            "alerta_enviado": alerta_enviado,
            "coleta_vazia": bool(diag_coleta),
            "consolidado_impala": consolidado_impala,
            "resumo_orquestrador": resumo_orq,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Agente monitor Anita erro: %s", exc)
        return {"ok": False, "erro": str(exc), "resultados": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor Anita esmaltes ML")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)

    logger.info("=== Monitor Anita esmaltes ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    logger.info(
        "Concluído: %s | alerta=%s",
        out.get("resumo_orquestrador") or f"{out.get('total_produtos')} produto(s)",
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
