"""
agentes/relatorio.py
Relatório diário consolidado via Telegram.
"""
import logging
from datetime import datetime
from integracoes.bling.bling_client import listar_produtos, estoques_criticos
from core.claude_client import perguntar
from core.notificador import alertar, alertar_critico

logger = logging.getLogger("relatorio")

def executar() -> bool:
    logger.info("=== Relatório diário ===")
    try:
        produtos = listar_produtos()
        criticos = estoques_criticos()
        dados = {
            "data": datetime.now().strftime("%d/%m/%Y"),
            "total_produtos": len(produtos),
            "criticos": len(criticos),
            "nomes_criticos": [p["nome"] for p in criticos[:3]],
        }
        analise = perguntar(
            f"Analise em 3 bullet points curtos para dono de negócio: {dados}",
            max_tokens=300
        )
        msg = (
            f"📊 *Relatório {dados['data']}*\n\n"
            f"Produtos ativos: {dados['total_produtos']}\n"
            f"Estoque crítico: {dados['criticos']} produtos\n\n"
            f"*Análise IA:*\n{analise}"
        )
        if criticos:
            alertar_critico(f"Estoque crítico: {', '.join(dados['nomes_criticos'])}")
        return alertar(msg)
    except Exception as e:
        logger.error(f"Relatório erro: {e}")
        return False
