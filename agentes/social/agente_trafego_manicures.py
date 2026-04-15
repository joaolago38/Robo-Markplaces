"""
agentes/social/agente_trafego_manicures.py
Mede eficiência de tráfego pago para manicures (Instagram/Facebook),
priorizando Impala/Anita e kits.
"""
from __future__ import annotations

import logging

from core.config import META_ROAS_MINIMO_MANICURES, META_CTR_MINIMO_MANICURES, META_CPC_MAXIMO
from core.notificador import alertar_gestor
from integracoes.meta.meta_ads_client import listar_metricas_campanhas, normalizar_metrica_campanha

logger = logging.getLogger("agente_trafego_manicures")

_BRAND_KEYS = {
    "impala": ["impala"],
    "anita": ["anita"],
    "kits": ["kit", "kits", "combo", "manicure kit"],
}


def _classificar_campanha(nome: str) -> str:
    low = (nome or "").lower()
    if any(k in low for k in _BRAND_KEYS["impala"]):
        return "impala"
    if any(k in low for k in _BRAND_KEYS["anita"]):
        return "anita"
    if any(k in low for k in _BRAND_KEYS["kits"]):
        return "kits"
    return "outras"


def _eficiencia(c: dict) -> dict:
    score = 100
    motivos = []
    if c["roas"] < META_ROAS_MINIMO_MANICURES:
        score -= 35
        motivos.append(f"ROAS abaixo da meta ({c['roas']:.2f})")
    if c["ctr"] < META_CTR_MINIMO_MANICURES:
        score -= 25
        motivos.append(f"CTR baixo ({c['ctr']:.2f}%)")
    if c["cpc"] > META_CPC_MAXIMO:
        score -= 20
        motivos.append(f"CPC alto ({c['cpc']:.2f})")
    if c["compras"] <= 0 and c["gasto"] > 0:
        score -= 20
        motivos.append("sem compras no período")
    score = max(0, score)
    status = "alta" if score >= 80 else "media" if score >= 60 else "baixa"
    return {"score": score, "status": status, "motivos": motivos}


def _agrupar_metricas(campanhas: list[dict]) -> dict:
    grupos = {"impala": [], "anita": [], "kits": [], "outras": []}
    for c in campanhas:
        grupos[_classificar_campanha(c["nome"])].append(c)

    resumo = {}
    for grupo, itens in grupos.items():
        gasto = sum(i["gasto"] for i in itens)
        receita = sum(i["receita"] for i in itens)
        compras = sum(i["compras"] for i in itens)
        roas = (receita / gasto) if gasto > 0 else 0.0
        resumo[grupo] = {
            "campanhas": len(itens),
            "gasto": round(gasto, 2),
            "receita": round(receita, 2),
            "compras": round(compras, 2),
            "roas": round(roas, 2),
        }
    return resumo


def executar(periodo_dias: int = 1, alertar_todo_relatorio: bool = True) -> dict:
    rows = listar_metricas_campanhas(periodo_dias=periodo_dias, limite=100)
    campanhas = []
    for row in rows:
        c = normalizar_metrica_campanha(row)
        ef = _eficiencia(c)
        campanhas.append(
            {
                "id": c["id"],
                "nome": c["nome"],
                "grupo": _classificar_campanha(c["nome"]),
                "score_eficiencia": ef["score"],
                "status_eficiencia": ef["status"],
                "motivos": ef["motivos"],
                "metricas": c,
            }
        )

    resumo = _agrupar_metricas([c["metricas"] | {"nome": c["nome"]} for c in campanhas])
    priorizadas = [c for c in campanhas if c["grupo"] in ("impala", "anita", "kits")]
    prioridade_score_medio = round(
        sum(c["score_eficiencia"] for c in priorizadas) / max(1, len(priorizadas)), 1
    )

    top_baixa = sorted(campanhas, key=lambda x: x["score_eficiencia"])[:3]
    recomendacoes = []
    if resumo["kits"]["roas"] < META_ROAS_MINIMO_MANICURES:
        recomendacoes.append("Aumentar verba de teste em criativos de kits com prova social para manicures.")
    if resumo["impala"]["roas"] < resumo["anita"]["roas"]:
        recomendacoes.append("Revisar oferta de Impala e replicar formato criativo vencedor da Anita.")
    if any(c["status_eficiencia"] == "baixa" for c in priorizadas):
        recomendacoes.append("Pausar criativos com eficiência baixa e subir 2 novas variações por marca.")
    if not recomendacoes:
        recomendacoes.append("Eficiência estável: manter distribuição e escalar 10% nas campanhas vencedoras.")

    payload = {
        "periodo_dias": periodo_dias,
        "total_campanhas": len(campanhas),
        "eficiencia_media_priorizadas": prioridade_score_medio,
        "resumo_grupos": resumo,
        "campanhas_criticas": top_baixa,
        "recomendacoes": recomendacoes,
        "campanhas": campanhas,
    }

    if alertar_todo_relatorio:
        alertar_gestor(
            f"Tráfego manicures (Meta): score médio {prioridade_score_medio}\n"
            f"ROAS Impala {resumo['impala']['roas']:.2f} | Anita {resumo['anita']['roas']:.2f} | Kits {resumo['kits']['roas']:.2f}\n"
            f"Ações: {'; '.join(recomendacoes[:2])}"
        )

    logger.info("Trafego manicures: %s", payload)
    return payload


def executar_resumo_madrugada(periodo_dias: int = 1) -> dict:
    """
    Gera resumo com as 3 campanhas de pior eficiência e dispara alerta direcionado.
    """
    resultado = executar(periodo_dias=periodo_dias, alertar_todo_relatorio=False)
    piores = sorted(resultado.get("campanhas", []), key=lambda c: c.get("score_eficiencia", 0))[:3]

    linhas = []
    for c in piores:
        acao = (resultado.get("recomendacoes", ["Revisar campanha."])[0])
        linhas.append(
            f"- {c['nome']} | score {c['score_eficiencia']} | {c['status_eficiencia']} | ação: {acao}"
        )

    if linhas:
        alertar_gestor(
            "Resumo madrugada tráfego manicures (top 3 piores):\n" + "\n".join(linhas)
        )

    return {"top3_piores": piores, "recomendacoes_globais": resultado.get("recomendacoes", []), "base": resultado}


if __name__ == "__main__":
    print(executar(periodo_dias=1, alertar_todo_relatorio=True))
