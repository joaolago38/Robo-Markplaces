"""
agentes/relatorio.py
Relatório diário consolidado via Telegram.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from core.marketplace_algorithm import HISTORY_FILE, _classificar
from core.notificador import alertar, alertar_critico
from core.resumo_ia import sintetizar_claude
from integracoes.bling.bling_client import estoques_criticos, listar_produtos

logger = logging.getLogger("relatorio")


def _ler_saude_do_historico() -> dict | None:
    """
    Reaproveita logs/marketplace_algorithm_history.json (gravado por
    algoritmo_marketplaces via avaliar_marketplace) — evita nova chamada às APIs.
    """
    try:
        if not HISTORY_FILE.is_file():
            return None
        historico = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if not isinstance(historico, dict):
            return None
        resumo = {"saudavel": 0, "atencao": 0, "critico": 0}
        por_marketplace: dict[str, dict] = {}
        for nome, pontos in historico.items():
            if not isinstance(pontos, list) or not pontos:
                continue
            ultimo = pontos[-1] if isinstance(pontos[-1], dict) else {}
            score = int(ultimo.get("score") or 0)
            status = _classificar(score)
            resumo[status] = resumo.get(status, 0) + 1
            por_marketplace[str(nome)] = {"status": status, "score": score}
        if not por_marketplace:
            return None
        return {"resumo": resumo, "marketplaces": por_marketplace}
    except Exception as exc:
        logger.warning("relatorio saude historico: %s", exc)
        return None


def _ler_repricing_do_dia() -> dict | None:
    """
    Não há snapshot JSON persistido do repricing/operacao_24h em logs/.
    operacao_24h só registra via logger.info — sem arquivo reaproveitável hoje.
    """
    return None


def _ler_ultima_decisao_ads() -> dict | None:
    """Sem arquivo persistido da última decisão de ads — dado omitido se ausente."""
    return None


def _montar_dados_relatorio(produtos: list, criticos: list) -> dict:
    dados: dict = {
        "data": datetime.now().strftime("%d/%m/%Y"),
        "estoque": {
            "total_produtos": len(produtos),
            "criticos": len(criticos),
            "nomes_criticos": [p["nome"] for p in criticos[:3]],
        },
    }
    saude = _ler_saude_do_historico()
    if saude:
        dados["saude_marketplaces"] = saude
    repricing = _ler_repricing_do_dia()
    if repricing:
        dados["repricing_dia"] = repricing
    ads = _ler_ultima_decisao_ads()
    if ads:
        dados["decisao_ads_recente"] = ads
    return dados


def executar() -> bool:
    logger.info("=== Relatório diário ===")
    try:
        produtos = listar_produtos()
        criticos = estoques_criticos()
        dados = _montar_dados_relatorio(produtos, criticos)
        fallback = (
            f"Produtos ativos: {dados['estoque']['total_produtos']}. "
            f"Estoque crítico: {dados['estoque']['criticos']} produto(s)."
        )
        prompt = (
            "Analise em 5 bullet points curtos para o dono do negócio, cobrindo venda, "
            "saúde das contas nos marketplaces, estoque, repricing e ads quando presentes no JSON. "
            "Se algum bloco estiver ausente no contexto, não invente — comente só o que houver."
        )
        analise = sintetizar_claude(prompt, dados, fallback, max_tokens=400)
        msg = (
            f"📊 *Relatório {dados['data']}*\n\n"
            f"Produtos ativos: {dados['estoque']['total_produtos']}\n"
            f"Estoque crítico: {dados['estoque']['criticos']} produtos\n\n"
            f"*Análise IA:*\n{analise}"
        )
        if criticos:
            alertar_critico(f"Estoque crítico: {', '.join(dados['estoque']['nomes_criticos'])}")
        return alertar(msg)
    except Exception as e:
        logger.error("Relatório erro: %s", e)
        return False
