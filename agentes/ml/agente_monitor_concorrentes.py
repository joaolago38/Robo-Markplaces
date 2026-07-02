"""
agentes/ml/agente_monitor_concorrentes.py
Monitor de concorrentes ML por termo de busca (catalogo/concorrentes_monitorados.json).
Somente leitura — não altera preços nem anúncios.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.config import (
    MONITOR_CONCORRENTES_ARQUIVO,
    MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor
from integracoes.ml import ml_client

logger = logging.getLogger("agente_monitor_concorrentes")

HISTORY_PATH = ROOT / "logs" / "concorrentes_ml_history.json"


def _carregar_lista() -> list[dict]:
    caminho = ROOT / MONITOR_CONCORRENTES_ARQUIVO
    try:
        if not caminho.is_file():
            logger.warning("Arquivo de monitoramento não encontrado: %s", caminho)
            return []
        with caminho.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.error("Erro ao carregar %s: %s", caminho, exc)
        return []


def _carregar_historico() -> dict[str, Any]:
    try:
        if not HISTORY_PATH.is_file():
            return {}
        with HISTORY_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.error("Erro ao carregar histórico: %s", exc)
        return {}


def _salvar_historico(historico: dict[str, Any]) -> None:
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = HISTORY_PATH.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(historico, f, ensure_ascii=False, indent=2)
            f.write("\n")
        tmp.replace(HISTORY_PATH)
    except Exception as exc:
        logger.error("Erro ao salvar histórico: %s", exc)


def _pct_variacao(anterior: float, atual: float) -> float:
    if anterior <= 0 or atual <= 0:
        return 0.0
    return abs(atual - anterior) / anterior * 100.0


def _menor_preco(concorrentes: list[dict]) -> float:
    precos = [float(c.get("preco") or 0) for c in concorrentes if float(c.get("preco") or 0) > 0]
    return min(precos) if precos else 0.0


def _leituras_recentes(entrada_hist: dict, limite: int = 5) -> list[dict]:
    leituras = entrada_hist.get("leituras")
    if isinstance(leituras, list) and leituras:
        return [x for x in leituras if isinstance(x, dict)][-limite:]
    if entrada_hist.get("menor_preco"):
        return [{"menor_preco": float(entrada_hist["menor_preco"]), "ts": entrada_hist.get("atualizado_em")}]
    return []


def _classificar_variacao_preco(
    eid: str,
    nome: str,
    termo: str,
    menor_atual: float,
    historico: dict[str, Any],
) -> str | None:
    """
    Classifica padrão de variação com histórico (3-5 leituras). Retorna None se <2 pontos.
    """
    anterior = historico.get(eid) if isinstance(historico.get(eid), dict) else {}
    leituras = _leituras_recentes(anterior, limite=5)
    if len(leituras) < 2:
        return None
    contexto = {
        "produto": nome,
        "termo_busca": termo,
        "menor_preco_atual": menor_atual,
        "leituras_recentes": leituras,
    }
    quedas = 0
    for i in range(1, len(leituras)):
        p_ant = float(leituras[i - 1].get("menor_preco") or 0)
        p_at = float(leituras[i].get("menor_preco") or 0)
        if p_ant > 0 and p_at < p_ant:
            quedas += 1
    fallback = "queda pontual"
    if quedas >= 3:
        fallback = f"tendência de baixa ({quedas}ª queda seguida)"
    elif quedas >= 2:
        fallback = "tendência de baixa (2 quedas seguidas)"
    from core.claude_client import MODELO_RAPIDO
    from core.resumo_ia import sintetizar_claude

    prompt = (
        "Em UMA linha, classifique o padrão da variação de preço do concorrente "
        "(ex.: 'queda pontual' vs 'tendência de baixa (3ª queda seguida)')."
    )
    texto = sintetizar_claude(
        prompt, contexto, fallback, max_tokens=60, modelo=MODELO_RAPIDO
    )
    return (texto or "").strip() or None


def _monitorar_entrada(entrada: dict, historico: dict[str, Any]) -> dict[str, Any]:
    eid = str(entrada.get("id") or "").strip()
    nome = str(entrada.get("nome") or eid)
    termo = str(entrada.get("termo_busca") or "").strip()
    meu_preco = float(entrada.get("meu_preco") or 0)
    limite = int(entrada.get("limite_resultados") or 10)

    if not termo:
        return {"id": eid, "ok": False, "erro": "termo_busca vazio", "alertas": []}

    concorrentes = ml_client.buscar_concorrentes_por_termo(termo, limite=limite)
    menor = _menor_preco(concorrentes)
    anterior = historico.get(eid) if isinstance(historico.get(eid), dict) else {}
    menor_ant = float(anterior.get("menor_preco") or 0)

    alertas: list[str] = []
    if menor > 0 and meu_preco > menor:
        diff = (meu_preco - menor) / menor * 100.0
        if diff >= MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT:
            alertas.append(
                f"{nome}: seu preço R$ {meu_preco:.2f} está {diff:.1f}% acima do menor "
                f"concorrente (R$ {menor:.2f}) no termo '{termo}'."
            )

    if menor_ant > 0 and menor > 0:
        var = _pct_variacao(menor_ant, menor)
        if var >= MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT:
            direcao = "caiu" if menor < menor_ant else "subiu"
            linha = (
                f"{nome}: menor preço do termo '{termo}' {direcao} de R$ {menor_ant:.2f} "
                f"para R$ {menor:.2f} ({var:.1f}%)."
            )
            classificacao = _classificar_variacao_preco(eid, nome, termo, menor, historico)
            if classificacao:
                linha += f" [{classificacao}]"
            alertas.append(linha)

    leituras_ant = _leituras_recentes(anterior, limite=4)
    leituras_ant.append(
        {"menor_preco": menor, "ts": datetime.now(timezone.utc).isoformat()}
    )
    historico[eid] = {
        "menor_preco": menor,
        "meu_preco": meu_preco,
        "total_concorrentes": len(concorrentes),
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
        "leituras": leituras_ant[-5:],
    }

    # ── Datadog ──────────────────────────────────────────────────────────
    # tag `produto` usa o `id` do JSON (ex.: "kit3-mimo-carmed") para
    # aparecer como facet no Metrics Explorer e facilitar filtrar por SKU.
    _tags = [f"produto:{eid}", f"termo:{termo[:40]}"]
    if meu_preco > 0:
        gauge("mercado.meu_preco", meu_preco, tags=_tags)
    if menor > 0:
        gauge("mercado.menor_preco_concorrente", menor, tags=_tags)
    if meu_preco > 0 and menor > 0:
        gap_pct = (meu_preco - menor) / menor * 100.0
        gauge("mercado.gap_preco_pct", gap_pct, tags=_tags)
    gauge("mercado.total_concorrentes", float(len(concorrentes)), tags=_tags)
    if alertas:
        incrementar("mercado.alertas_preco", float(len(alertas)), tags=_tags)
    # ─────────────────────────────────────────────────────────────────────

    return {
        "id": eid,
        "ok": True,
        "nome": nome,
        "termo_busca": termo,
        "meu_preco": meu_preco,
        "menor_preco": menor,
        "total_concorrentes": len(concorrentes),
        "concorrentes_amostra": concorrentes[:5],
        "alertas": alertas,
    }


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    """Monitora todos os itens ativos da lista. Nunca lança exceção."""
    try:
        lista = _carregar_lista()
        historico = _carregar_historico()
        resultados: list[dict[str, Any]] = []
        alertas_todos: list[str] = []

        for entrada in lista:
            if not isinstance(entrada, dict) or not entrada.get("ativo"):
                continue
            resultado = _monitorar_entrada(entrada, historico)
            resultados.append(resultado)
            alertas_todos.extend(resultado.get("alertas") or [])

        _salvar_historico(historico)

        enviado = False
        if enviar_alerta and alertas_todos:
            msg = "🔎 Monitor concorrentes ML\n\n" + "\n".join(f"• {a}" for a in alertas_todos)
            enviado = bool(alertar_gestor(msg))

        payload = {
            "ok": True,
            "total_monitorados": len(resultados),
            "total_alertas": len(alertas_todos),
            "alertas": alertas_todos,
            "resultados": resultados,
            "enviado": enviado,
        }
        logger.info(
            "Monitor concorrentes: %s itens, %s alertas, enviado=%s",
            len(resultados),
            len(alertas_todos),
            enviado,
        )
        return payload
    except Exception as exc:
        logger.error("Monitor concorrentes erro: %s", exc)
        return {"ok": False, "erro": str(exc), "resultados": []}


def main() -> int:
    logger.info("=== Monitor concorrentes ML ===")
    resultado = executar(enviar_alerta=True)
    if not resultado.get("ok"):
        logger.error("Falha: %s", resultado.get("erro"))
        return 1
    if resultado.get("alertas"):
        for linha in resultado["alertas"]:
            print(f"[ALERTA] {linha}")
    else:
        print(f"[OK] {resultado.get('total_monitorados', 0)} item(ns) monitorado(s), sem alertas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
