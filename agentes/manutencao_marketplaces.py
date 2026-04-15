"""
agentes/manutencao_marketplaces.py
Executa keepalive de marketplaces para evitar longos períodos sem acesso.
"""
import logging

from core.notificador import alertar_gestor
from integracoes.shopee.shopee_client import manter_conta_ativa as keepalive_shopee
from integracoes.magalu.magalu_client import manter_conta_ativa as keepalive_magalu

logger = logging.getLogger("manutencao_marketplaces")


def executar(limite_dias_sem_acesso: int = 5) -> dict:
    resultado_shopee = keepalive_shopee(limite_dias_sem_acesso=limite_dias_sem_acesso)
    resultado_magalu = keepalive_magalu(limite_dias_sem_acesso=limite_dias_sem_acesso)
    resultados = [resultado_shopee, resultado_magalu]

    for r in resultados:
        if not r.get("ok") or r.get("alerta"):
            alertar_gestor(
                f"Keepalive {r.get('marketplace')}: {r.get('acao')}\n"
                f"Dias sem acesso: {r.get('dias_sem_acesso')}"
            )

    payload = {"limite_dias_sem_acesso": limite_dias_sem_acesso, "resultados": resultados}
    logger.info("Manutenção marketplaces: %s", payload)
    return payload


if __name__ == "__main__":
    print(executar())
