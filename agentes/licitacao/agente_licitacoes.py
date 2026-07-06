"""
agentes/licitacao/agente_licitacoes.py
Monitora licitações públicas em todos os estados (PNCP + portais estaduais).

Catálogo: catalogo/licitacoes_monitoradas.json
Somente leitura + alertas — não envia propostas.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    LICITACOES_ALERTA_RESUMO,
    LICITACOES_ALERTA_RESUMO_COOLDOWN_SEG,
    LICITACOES_CATALOGO,
    LICITACOES_PAUSA_ENTRE_FONTES_SEG,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.ddg_lite import mensagem_circuit_breaker
from core.notificador import alertar_gestor, chave_itens_novos, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.licitacao.busca import buscar_licitacoes_em_fontes

logger = logging.getLogger("agente_licitacoes")

HISTORY_PATH = ROOT / "logs" / "licitacoes_history.json"
SNAPSHOT_PATH = ROOT / "logs" / "licitacoes_ultima_rodada.json"


def _carregar_itens() -> list[dict[str, Any]]:
    caminho = ROOT / LICITACOES_CATALOGO
    try:
        if not caminho.is_file():
            logger.warning("Catálogo licitações não encontrado: %s", caminho)
            return []
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        return [i for i in data if isinstance(i, dict) and i.get("ativo")]
    except Exception as exc:
        logger.error("Erro ao carregar catálogo licitações: %s", exc)
        return []


def _carregar_historico() -> dict[str, Any]:
    return ler_json(HISTORY_PATH, default={})


def _salvar_historico(historico: dict[str, Any]) -> None:
    try:
        escrever_json_atomico(HISTORY_PATH, historico)
    except Exception as exc:
        logger.error("Erro ao salvar histórico licitações: %s", exc)


def _formatar_local(item: dict[str, Any]) -> str:
    cidade = str(item.get("cidade") or "").strip()
    uf = str(item.get("uf") or "").strip()
    orgao = str(item.get("orgao") or item.get("fonte_nome") or "").strip()
    if cidade and uf:
        return f"{cidade}/{uf} — {orgao}" if orgao else f"{cidade}/{uf}"
    if uf:
        return f"{uf} — {orgao}" if orgao else uf
    return orgao or "?"


def _formatar_requisitos(item: dict[str, Any], *, max_itens: int = 4) -> str:
    part = item.get("participacao") or {}
    checklist = part.get("checklist") or []
    linhas = [f"  - {c}" for c in checklist[:max_itens]]
    if len(checklist) > max_itens:
        linhas.append(f"  - … +{len(checklist) - max_itens} no snapshot")
    cadastro = part.get("url_cadastro_fornecedor")
    if cadastro:
        linhas.append(f"  - Cadastro: {cadastro}")
    return "\n".join(linhas)


def _logar_achados(nome: str, achados: list[dict[str, Any]], novos: list[dict[str, Any]]) -> None:
    if not achados:
        logger.info("Licitação %s: nenhum achado nesta rodada", nome)
        ddg = mensagem_circuit_breaker("licitacao")
        if ddg:
            logger.warning("Licitação %s: %s", nome, ddg)
        return
    logger.info("Licitação %s: %s achado(s)", nome, len(achados))
    for item in achados[:6]:
        logger.info(
            "  • %s | %s | %s | encerra %s | %s",
            _formatar_local(item),
            (item.get("produto") or item.get("titulo") or "")[:80],
            item.get("valor_estimado") or "valor n/d",
            item.get("data_encerramento") or "n/d",
            item.get("url") or "",
        )
    if novos:
        logger.info("Licitação %s: %s NOVO(S)", nome, len(novos))


def _monitorar_item(item_cat: dict[str, Any], historico: dict[str, Any]) -> dict[str, Any]:
    iid = str(item_cat.get("id") or "").strip()
    nome = str(item_cat.get("nome") or iid)
    entrada = historico.get(iid) if isinstance(historico.get(iid), dict) else {}
    vistos: dict[str, Any] = dict(entrada.get("vistos") or {})

    achados = buscar_licitacoes_em_fontes(
        item_cat,
        pausa_entre_fontes_seg=LICITACOES_PAUSA_ENTRE_FONTES_SEG,
    )
    novos: list[dict[str, Any]] = []
    agora = datetime.now(timezone.utc).isoformat()

    for item in achados:
        h = item.get("hash") or ""
        if not h:
            continue
        if h not in vistos:
            registro = {**item, "visto_em": agora}
            vistos[h] = registro
            novos.append(registro)

    historico[iid] = {
        "nome": nome,
        "vistos": vistos,
        "ultima_varredura": agora,
        "total_achados_rodada": len(achados),
    }

    gauge("licitacao.achados_por_item", len(achados), tags=[f"item:{iid}"])
    incrementar("licitacao.novos", len(novos), tags=[f"item:{iid}"])
    _logar_achados(nome, achados, novos)

    return {
        "id": iid,
        "nome": nome,
        "prioridade": int(item_cat.get("prioridade") or 99),
        "achados_total": len(achados),
        "novos": novos,
        "ok": True,
    }


def _montar_alerta_novos(resultados: list[dict[str, Any]]) -> str:
    linhas = ["📋 *Licitações públicas — novas oportunidades*", ""]
    ordenados = sorted(resultados, key=lambda r: int(r.get("prioridade") or 99))
    for r in ordenados:
        novos = r.get("novos") or []
        if not novos:
            continue
        linhas.append(f"*{r.get('nome', r.get('id', ''))}* ({len(novos)} novo(s)):")
        for item in novos[:5]:
            linhas.append(f"📍 {_formatar_local(item)}")
            linhas.append(f"📦 {(item.get('produto') or item.get('titulo') or '')[:120]}")
            if item.get("valor_estimado"):
                linhas.append(f"💰 {item['valor_estimado']}")
            elif item.get("orcamento_sigiloso"):
                linhas.append("💰 Orçamento sigiloso")
            if item.get("modalidade"):
                linhas.append(f"⚖️ {item['modalidade']}")
            if item.get("data_encerramento"):
                linhas.append(f"⏰ Propostas até {item['data_encerramento']}")
            linhas.append("📝 *Para participar:*")
            linhas.append(_formatar_requisitos(item))
            linhas.append(f"🔗 {item.get('url') or ''}")
            linhas.append("")
        if len(novos) > 5:
            linhas.append(f"… e mais {len(novos) - 5}")
        linhas.append("")
    return "\n".join(linhas).strip()


def _montar_resumo_varredura(resultados: list[dict[str, Any]]) -> str:
    total_achados = sum(int(r.get("achados_total") or 0) for r in resultados)
    total_novos = sum(len(r.get("novos") or []) for r in resultados)
    linhas = [
        "📋 *Licitações — resumo da varredura (27 UFs via PNCP)*",
        "",
        f"Itens monitorados: {len(resultados)}",
        f"Achados nesta rodada: {total_achados}",
        f"Novos: {total_novos}",
        "",
    ]
    for r in sorted(resultados, key=lambda x: int(x.get("prioridade") or 99)):
        linhas.append(
            f"• {r.get('nome', r.get('id', '?'))}: "
            f"{int(r.get('achados_total') or 0)} achado(s), {len(r.get('novos') or [])} novo(s)"
        )
    ddg = mensagem_circuit_breaker("licitacao")
    if ddg:
        linhas.extend(["", f"⚠️ {ddg}"])
    elif total_achados == 0:
        linhas.extend(["", "_Nenhuma licitação encontrada nesta rodada para o catálogo._"])
    return "\n".join(linhas).strip()


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning(
                "Telegram gestor não configurado — alertas de licitação não serão entregues"
            )

        itens = _carregar_itens()
        if not itens:
            logger.info("Nenhum item ativo em %s", LICITACOES_CATALOGO)
            return {"ok": True, "total_itens": 0, "resultados": [], "alerta_enviado": False}

        itens = sorted(itens, key=lambda i: int(i.get("prioridade") or 99))
        historico = _carregar_historico()
        resultados: list[dict[str, Any]] = []

        for item_cat in itens:
            iid = str(item_cat.get("id") or "").strip()
            if not iid:
                continue
            logger.info("Varrendo licitações: %s", item_cat.get("nome") or iid)
            resultados.append(_monitorar_item(item_cat, historico))

        _salvar_historico(historico)

        agora = datetime.now(timezone.utc).isoformat()
        escrever_json_atomico(
            SNAPSHOT_PATH,
            {
                "timestamp": agora,
                "total_itens": len(resultados),
                "resultados": resultados,
            },
        )

        com_novos = [r for r in resultados if r.get("novos")]
        alerta_novos_enviado = False
        alerta_resumo_enviado = False

        if enviar_alerta and com_novos:
            novos_flat = [n for r in com_novos for n in (r.get("novos") or [])]
            msg = _montar_alerta_novos(com_novos)
            if msg:
                alerta_novos_enviado = bool(
                    alertar_gestor(
                        msg,
                        chave=chave_itens_novos("licitacao:novos", novos_flat),
                        cooldown_segundos=86400,
                    )
                )

        if enviar_alerta and LICITACOES_ALERTA_RESUMO:
            alerta_resumo_enviado = bool(
                alertar_gestor(
                    _montar_resumo_varredura(resultados),
                    chave=chave_resumo_periodo("licitacao", horas_por_bucket=4),
                    cooldown_segundos=LICITACOES_ALERTA_RESUMO_COOLDOWN_SEG,
                )
            )

        return {
            "ok": True,
            "total_itens": len(resultados),
            "com_novos": len(com_novos),
            "alerta_enviado": alerta_novos_enviado or alerta_resumo_enviado,
            "alerta_novos_enviado": alerta_novos_enviado,
            "alerta_resumo_enviado": alerta_resumo_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Agente licitações erro: %s", exc)
        return {"ok": False, "erro": str(exc), "resultados": []}


def main() -> int:
    logger.info("=== Monitor de licitações públicas (PNCP + estados) ===")
    resultado = executar(enviar_alerta=True)
    if not resultado.get("ok"):
        logger.error("Monitor licitações falhou: %s", resultado.get("erro"))
        return 1
    logger.info(
        "Monitor licitações: %s item(ns), %s com novos, alerta=%s",
        resultado.get("total_itens"),
        resultado.get("com_novos"),
        resultado.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
