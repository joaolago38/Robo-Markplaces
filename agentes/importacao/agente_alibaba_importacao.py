"""
agentes/importacao/agente_alibaba_importacao.py
Monitor de oportunidades de importação no Alibaba.com (a cada 2h).

Configuração: catalogo/alibaba_produtos_importacao.json
Somente leitura + alertas — não compra nem negocia.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    ALIBABA_ALERTA_RESUMO,
    ALIBABA_ALERTA_RESUMO_COOLDOWN_SEG,
    ALIBABA_IMPORTACAO_CATALOGO,
    ALIBABA_PAUSA_ENTRE_BUSCAS_SEG,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.ddg_lite import mensagem_circuit_breaker
from core.notificador import alertar_gestor, chave_itens_novos, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.alibaba.busca import buscar_oportunidades, montar_termo_busca

logger = logging.getLogger("agente_alibaba_importacao")

HISTORY_PATH = ROOT / "logs" / "alibaba_importacao_history.json"


def _carregar_produtos() -> list[dict[str, Any]]:
    caminho = ROOT / ALIBABA_IMPORTACAO_CATALOGO
    try:
        if not caminho.is_file():
            logger.warning("Catálogo Alibaba não encontrado: %s", caminho)
            return []
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        return [p for p in data if isinstance(p, dict) and p.get("ativo")]
    except Exception as exc:
        logger.error("Erro ao carregar catálogo Alibaba: %s", exc)
        return []


def _monitorar_produto(produto: dict[str, Any], historico: dict[str, Any]) -> dict[str, Any]:
    pid = str(produto.get("id") or "").strip()
    nome = str(produto.get("nome") or montar_termo_busca(produto) or pid)
    entrada = historico.get(pid) if isinstance(historico.get(pid), dict) else {}
    vistos: dict[str, Any] = dict(entrada.get("vistos") or {})

    achados = buscar_oportunidades(produto, pausa_seg=ALIBABA_PAUSA_ENTRE_BUSCAS_SEG)
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

    historico[pid] = {
        "produto": nome,
        "vistos": vistos,
        "ultima_varredura": agora,
        "total_oportunidades_rodada": len(achados),
    }

    gauge("alibaba.oportunidades_por_produto", len(achados), tags=[f"produto:{pid}"])
    incrementar("alibaba.novos", len(novos), tags=[f"produto:{pid}"])
    _logar_oportunidades(produto, achados, novos)

    return {
        "id": pid,
        "produto": nome,
        "oportunidades_total": len(achados),
        "novos": novos,
        "ok": True,
    }


def _formatar_preco(preco: Any) -> str:
    if preco is None:
        return "preço n/d"
    try:
        return f"US$ {float(preco):.2f}"
    except (TypeError, ValueError):
        return "preço n/d"


def _formatar_moq(moq: Any) -> str:
    if moq is None:
        return "MOQ n/d"
    try:
        return f"MOQ {int(moq)}"
    except (TypeError, ValueError):
        return "MOQ n/d"


def _formatar_distribuidor(item: dict[str, Any]) -> str:
    nome = str(item.get("distribuidor") or item.get("fornecedor") or "").strip()
    return nome or "distribuidor n/d"


def _resumo_precos(itens: list[dict[str, Any]]) -> str:
    precos: list[float] = []
    for item in itens:
        try:
            if item.get("preco_usd") is not None:
                precos.append(float(item["preco_usd"]))
        except (TypeError, ValueError):
            continue
    if not precos:
        return "sem preço parseado"
    if len(precos) == 1:
        return f"menor {_formatar_preco(precos[0])}"
    return f"menor {_formatar_preco(min(precos))} — maior {_formatar_preco(max(precos))}"


def _logar_oportunidades(
    produto: dict[str, Any],
    achados: list[dict[str, Any]],
    novos: list[dict[str, Any]],
) -> None:
    nome = str(produto.get("nome") or montar_termo_busca(produto) or produto.get("id") or "?")
    preco_max = produto.get("preco_max_usd")
    moq_max = produto.get("moq_max")
    criterios = []
    if preco_max is not None:
        criterios.append(f"até {_formatar_preco(preco_max)}")
    if moq_max is not None:
        criterios.append(f"MOQ ≤ {moq_max}")
    criterio_txt = f" ({', '.join(criterios)})" if criterios else ""

    if not achados:
        logger.info("Alibaba %s: nenhuma oportunidade nesta rodada%s", nome, criterio_txt)
        ddg = mensagem_circuit_breaker()
        if ddg:
            logger.warning("Alibaba %s: %s", nome, ddg)
        return

    logger.info(
        "Alibaba %s: %s oportunidade(s) encontrada(s) — %s%s",
        nome,
        len(achados),
        _resumo_precos(achados),
        criterio_txt,
    )
    for item in achados[:8]:
        titulo = str(item.get("titulo") or "Anúncio")[:70]
        logger.info(
            "  • %s | %s | %s | %s | %s",
            titulo,
            _formatar_preco(item.get("preco_usd")),
            _formatar_moq(item.get("moq")),
            _formatar_distribuidor(item),
            item.get("url", ""),
        )
    if len(achados) > 8:
        logger.info("  … e mais %s anúncio(s) nesta rodada", len(achados) - 8)

    if novos:
        logger.info("Alibaba %s: %s anúncio(s) NOVO(S) nesta rodada", nome, len(novos))
        for item in novos[:5]:
            titulo = str(item.get("titulo") or "Anúncio")[:70]
            logger.info(
                "  ★ NOVO: %s | %s | %s | %s | %s",
                titulo,
                _formatar_preco(item.get("preco_usd")),
                _formatar_moq(item.get("moq")),
                _formatar_distribuidor(item),
                item.get("url", ""),
            )
        if len(novos) > 5:
            logger.info("  … e mais %s novo(s)", len(novos) - 5)


def _montar_alerta(resultados: list[dict[str, Any]]) -> str:
    linhas = ["📦 *Alibaba — oportunidades de importação*", ""]
    for r in resultados:
        novos = r.get("novos") or []
        if not novos:
            continue
        linhas.append(f"*{r.get('produto', r.get('id', ''))}* ({len(novos)} novo(s)):")
        for item in novos[:6]:
            titulo = str(item.get("titulo") or "Anúncio")[:70]
            preco = _formatar_preco(item.get("preco_usd"))
            moq_txt = _formatar_moq(item.get("moq"))
            dist = _formatar_distribuidor(item)
            linhas.append(f"• {titulo} — {preco}, {moq_txt}")
            linhas.append(f"  🏭 {dist}")
            linhas.append(f"  🔗 {item.get('url', '')}")
            if item.get("url_busca"):
                linhas.append(f"  🔍 Busca: {item['url_busca']}")
        if len(novos) > 6:
            linhas.append(f"  … e mais {len(novos) - 6}")
        linhas.append("")
    return "\n".join(linhas).strip()


def _montar_resumo_varredura(resultados: list[dict[str, Any]]) -> str:
    total_oportunidades = sum(int(r.get("oportunidades_total") or 0) for r in resultados)
    total_novos = sum(len(r.get("novos") or []) for r in resultados)
    linhas = [
        "📦 *Alibaba — resumo da varredura*",
        "",
        f"Produtos monitorados: {len(resultados)}",
        f"Oportunidades nesta rodada: {total_oportunidades}",
        f"Novas: {total_novos}",
        "",
    ]
    for r in resultados:
        ops = int(r.get("oportunidades_total") or 0)
        novos = len(r.get("novos") or [])
        linhas.append(f"• {r.get('produto', r.get('id', '?'))}: {ops} oportunidade(s), {novos} nova(s)")
    ddg = mensagem_circuit_breaker()
    if ddg:
        linhas.extend(["", f"⚠️ {ddg}"])
    elif total_oportunidades == 0:
        linhas.extend(["", "_Nenhuma oportunidade nesta rodada (busca direta/DDG)._"])
    return "\n".join(linhas).strip()


def _todos_novos(resultados: list[dict[str, Any]]) -> list[dict[str, Any]]:
    itens: list[dict[str, Any]] = []
    for r in resultados:
        itens.extend(r.get("novos") or [])
    return itens


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    """Varre Alibaba para cada produto ativo. Nunca lança exceção."""
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning(
                "Telegram gestor não configurado (TELEGRAM_TOKEN / TELEGRAM_GESTOR_CHAT_ID) — "
                "alertas Alibaba não serão entregues"
            )

        produtos = _carregar_produtos()
        if not produtos:
            logger.info("Nenhum produto ativo em %s", ALIBABA_IMPORTACAO_CATALOGO)
            return {"ok": True, "total_produtos": 0, "resultados": [], "alerta_enviado": False}

        historico = ler_json(HISTORY_PATH, default={})
        resultados: list[dict[str, Any]] = []

        for produto in produtos:
            pid = str(produto.get("id") or "").strip()
            if not pid:
                continue
            logger.info("Buscando no Alibaba: %s", montar_termo_busca(produto))
            resultados.append(_monitorar_produto(produto, historico))

        escrever_json_atomico(HISTORY_PATH, historico)

        com_novos = [r for r in resultados if r.get("novos")]
        alerta_novos_enviado = False
        alerta_resumo_enviado = False

        if enviar_alerta and com_novos:
            novos_itens = _todos_novos(com_novos)
            msg = _montar_alerta(com_novos)
            if msg:
                alerta_novos_enviado = bool(
                    alertar_gestor(
                        msg,
                        chave=chave_itens_novos("alibaba:importacao:novos", novos_itens),
                        cooldown_segundos=86400,
                    )
                )
                if not alerta_novos_enviado:
                    logger.warning(
                        "%s oportunidade(s) nova(s) mas alerta detalhado não enviado (cooldown ou Telegram)",
                        len(novos_itens),
                    )

        if enviar_alerta and ALIBABA_ALERTA_RESUMO:
            msg_resumo = _montar_resumo_varredura(resultados)
            alerta_resumo_enviado = bool(
                alertar_gestor(
                    msg_resumo,
                    chave=chave_resumo_periodo("alibaba", horas_por_bucket=2),
                    cooldown_segundos=ALIBABA_ALERTA_RESUMO_COOLDOWN_SEG,
                )
            )
            if not alerta_resumo_enviado:
                logger.info("Alibaba: resumo não enviado (cooldown ou Telegram indisponível)")

        return {
            "ok": True,
            "total_produtos": len(resultados),
            "com_novos": len(com_novos),
            "alerta_enviado": alerta_novos_enviado or alerta_resumo_enviado,
            "alerta_novos_enviado": alerta_novos_enviado,
            "alerta_resumo_enviado": alerta_resumo_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Agente Alibaba importação erro: %s", exc)
        return {"ok": False, "erro": str(exc), "resultados": []}


def main() -> int:
    logger.info("=== Monitor Alibaba importação (2h) ===")
    resultado = executar(enviar_alerta=True)
    if not resultado.get("ok"):
        logger.error("Monitor Alibaba falhou: %s", resultado.get("erro"))
        return 1
    logger.info(
        "Monitor Alibaba: %s produto(s), %s com novos, alerta=%s",
        resultado.get("total_produtos"),
        resultado.get("com_novos"),
        resultado.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
