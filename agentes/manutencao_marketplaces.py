"""
agentes/manutencao_marketplaces.py
Executa keepalive de marketplaces para evitar longos períodos sem acesso.

Mercado Livre NÃO está neste agente de propósito — ele não tem uma
função `manter_conta_ativa()` própria, e criar uma seria redundante:
`agentes/conectividade_marketplaces.py` já chama `probe_conexao()` do
ML (e do Magalu) a cada hora e, em caso de sucesso, já chama
`registrar_acesso("mercadolivre")` — o que é exatamente o efeito que
um keepalive teria. Ou seja, o ML está coberto, só que por outro
agente, com uma checagem mais forte (testa conectividade real, não só
"faz uma chamada qualquer").
"""
import logging

from core.config import SPEC
from core.notificador import alertar_gestor
from integracoes.shopee.shopee_client import manter_conta_ativa as keepalive_shopee
from integracoes.magalu.magalu_client import manter_conta_ativa as keepalive_magalu

logger = logging.getLogger("manutencao_marketplaces")

_MARKETPLACES_ATIVOS: set[str] = {
    m["id"] for m in SPEC.get("marketplaces", []) if m.get("ativo", False)
}


def executar(limite_dias_sem_acesso: int = 5) -> dict:
    resultado_shopee = keepalive_shopee(limite_dias_sem_acesso=limite_dias_sem_acesso)
    resultados = [resultado_shopee]

    if "magalu" in _MARKETPLACES_ATIVOS:
        resultado_magalu = keepalive_magalu(limite_dias_sem_acesso=limite_dias_sem_acesso)
        resultados.append(resultado_magalu)

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
