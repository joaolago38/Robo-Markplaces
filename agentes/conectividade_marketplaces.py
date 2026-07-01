"""
agentes/conectividade_marketplaces.py
Testa conectividade REAL com os marketplaces — não apenas se o OAuth
renovou o token. Usa as funções `probe_conexao()` de cada client, que
já existiam no código de cada integração mas nunca eram chamadas em
produção (renovação de token e conectividade real são coisas
diferentes: um token pode "renovar" com sucesso no OAuth e ainda
assim não funcionar de verdade contra a API — escopo errado, conta
suspensa, permissão revogada etc.).

Nunca lança exceção — um erro inesperado num marketplace não pode
impedir a checagem dos demais.
"""
from __future__ import annotations

import logging

from core.config import SPEC
from core.datadog_metrics import gauge, incrementar
from core.marketplace_keepalive import dias_sem_acesso, registrar_acesso
from core.notificador import alertar_critico

logger = logging.getLogger("conectividade_marketplaces")

_MARKETPLACES_ATIVOS_SPEC: set[str] = {
    m["id"] for m in SPEC.get("marketplaces", []) if m.get("ativo", False)
}

_MARKETPLACES = ("mercadolivre", "magalu", "shopee", "amazon")
if "magalu" not in _MARKETPLACES_ATIVOS_SPEC:
    _MARKETPLACES = tuple(m for m in _MARKETPLACES if m != "magalu")


def _probe(nome_marketplace: str) -> dict:
    if nome_marketplace == "mercadolivre":
        from integracoes.ml.ml_client import probe_conexao
    elif nome_marketplace == "magalu":
        from integracoes.magalu.magalu_client import probe_conexao
    elif nome_marketplace == "shopee":
        from integracoes.shopee.shopee_client import probe_conexao
    elif nome_marketplace == "amazon":
        from integracoes.amazon.amazon_client import probe_conexao
    else:
        return {"ok": False, "status": 0, "msg": "marketplace desconhecido"}
    return probe_conexao()


def _avaliar_um(nome_marketplace: str) -> dict:
    resultado = _probe(nome_marketplace) or {}
    ok = bool(resultado.get("ok"))
    status_http = resultado.get("status", 0)
    msg = str(resultado.get("msg", "") or "")

    # Gauge contínuo (1=ok, 0=falha) — no Datadog, a média desse valor
    # ao longo do tempo já é, na prática, o % de uptime de conectividade.
    gauge("conectividade.status", 1.0 if ok else 0.0, tags=[f"marketplace:{nome_marketplace}"])

    if ok:
        # Uma chamada real que funcionou conta como acesso de verdade —
        # mesmo critério já usado em obter_saude_conta()/manter_conta_ativa().
        registrar_acesso(nome_marketplace)
    else:
        incrementar(
            "conectividade.falha",
            tags=[f"marketplace:{nome_marketplace}", f"status_http:{status_http}"],
        )
        logger.error(
            "Conectividade %s FALHOU (status=%s): %s",
            nome_marketplace,
            status_http,
            msg,
        )
        alertar_critico(
            f"🔌 Falha de conectividade REAL com {nome_marketplace}.\n"
            f"Status HTTP: {status_http}\n"
            f"Detalhe: {msg}\n"
            "Isto é diferente de uma falha de renovação de token: o OAuth "
            "pode ter respondido com sucesso e a API mesmo assim recusar o "
            "acesso (escopo, permissão, conta suspensa). Verifique as "
            "credenciais e os escopos do app.",
            chave=f"conectividade:{nome_marketplace}",
        )

    return {
        "marketplace": nome_marketplace,
        "ok": ok,
        "status_http": status_http,
        "msg": msg,
        "dias_sem_acesso": dias_sem_acesso(nome_marketplace) or 0,
    }


def executar() -> dict:
    """
    Testa conectividade real (não apenas renovação de token) de todos os
    marketplaces configurados. Retorna um resumo com o resultado de cada um.
    """
    resultados: list[dict] = []
    for nome in _MARKETPLACES:
        try:
            resultados.append(_avaliar_um(nome))
        except Exception as exc:
            logger.error("Erro inesperado ao testar conectividade %s: %s", nome, exc)
            incrementar(
                "conectividade.falha",
                tags=[f"marketplace:{nome}", "motivo:excecao_inesperada"],
            )
            resultados.append(
                {
                    "marketplace": nome,
                    "ok": False,
                    "status_http": 0,
                    "msg": str(exc),
                    "dias_sem_acesso": -1,
                }
            )

    payload = {
        "total": len(resultados),
        "ok": sum(1 for r in resultados if r["ok"]),
        "falha": sum(1 for r in resultados if not r["ok"]),
        "resultados": resultados,
    }
    logger.info("Conectividade marketplaces: %s", payload)
    return payload


if __name__ == "__main__":
    import pprint

    pprint.pprint(executar())
