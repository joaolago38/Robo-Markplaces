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
    ALIBABA_IMPORTACAO_CATALOGO,
    ALIBABA_PAUSA_ENTRE_BUSCAS_SEG,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, gestor_telegram_configurado
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
            moq = item.get("moq")
            moq_txt = f"MOQ {moq}" if moq else "MOQ n/d"
            linhas.append(f"• {titulo} — {preco}, {moq_txt}")
            linhas.append(f"  {item.get('url', '')}")
        if len(novos) > 6:
            linhas.append(f"  … e mais {len(novos) - 6}")
        linhas.append("")
    return "\n".join(linhas).strip()


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
        alerta_enviado = False
        if enviar_alerta and com_novos:
            msg = _montar_alerta(com_novos)
            if msg:
                alerta_enviado = bool(
                    alertar_gestor(msg, chave="alibaba:importacao:novos", cooldown_segundos=7200)
                )
                if not alerta_enviado:
                    logger.warning(
                        "%s oportunidade(s) nova(s) mas alerta não enviado (cooldown ou falha Telegram)",
                        sum(len(r.get("novos") or []) for r in com_novos),
                    )

        return {
            "ok": True,
            "total_produtos": len(resultados),
            "com_novos": len(com_novos),
            "alerta_enviado": alerta_enviado,
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
