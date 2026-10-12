"""
agentes/ml/agente_monitor_buybox.py
Monitor de buy box em catálogo compartilhado ML (posição 0 nas ofertas).
Somente leitura — não altera preços nem anúncios.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from core.config import ML_SELLER_ID, MONITOR_CONCORRENTES_ARQUIVO, ROOT
from integracoes.ml.monitor_buybox import (
    analisar_estabilidade_vencedor,
    consultar_ofertas_catalogo,
    emitir_metricas_buybox,
    registrar_snapshot_buybox,
)

logger = logging.getLogger("agente_monitor_buybox")


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


def _fmt_preco(val: Any) -> str:
    try:
        return f"{float(val):.2f}".replace(".", ",")
    except (TypeError, ValueError):
        return "0,00"


def _linha_resumo(
    pid: str,
    vencedor: dict[str, Any] | None,
    analise: dict[str, Any],
) -> str:
    if not isinstance(vencedor, dict):
        return f"[BUYBOX] {pid} — sem ofertas na API"
    sid = str(vencedor.get("seller_id") or "?")
    preco = _fmt_preco(vencedor.get("preco"))
    pct_map = analise.get("pct_tempo_cada_seller") if analise.get("ok") else None
    n_snaps = int(analise.get("snapshots_janela") or 0)
    if isinstance(pct_map, dict) and sid in pct_map:
        return (
            f"[BUYBOX] {pid} — vencedor atual: seller {sid} a R${preco} "
            f"(ganhando {pct_map[sid]:.0f}% dos últimos {n_snaps} snapshots)"
        )
    return f"[BUYBOX] {pid} — vencedor atual: seller {sid} a R${preco} (histórico ainda curto)"


def executar() -> dict[str, Any]:
    """Percorre catalog_product_id opcional na lista de concorrentes. Nunca lança."""
    try:
        lista = _carregar_lista()
        resultados: list[dict[str, Any]] = []
        linhas: list[str] = []
        for entrada in lista:
            if not isinstance(entrada, dict) or not entrada.get("ativo"):
                continue
            pid = str(entrada.get("catalog_product_id") or "").strip()
            if not pid:
                continue
            ofertas = consultar_ofertas_catalogo(pid)
            snap = registrar_snapshot_buybox(pid, ofertas)
            analise = analisar_estabilidade_vencedor(pid, dias=7)
            vencedor = snap.get("vencedor_atual")
            linha = _linha_resumo(pid, vencedor if isinstance(vencedor, dict) else None, analise)
            logger.info("%s", linha)
            linhas.append(linha)
            emitir_metricas_buybox(
                pid,
                ofertas,
                vencedor if isinstance(vencedor, dict) else None,
                analise,
                produto_id=str(entrada.get("id") or ""),
                nosso_seller_id=str(ML_SELLER_ID or ""),
            )
            resultados.append(
                {
                    "catalog_product_id": pid,
                    "id": entrada.get("id"),
                    "ok": True,
                    "n_ofertas": len(ofertas),
                    "vencedor_atual": vencedor,
                    "analise": analise,
                    "resumo": linha,
                }
            )
        payload = {
            "ok": True,
            "total_catalogos": len(resultados),
            "resultados": resultados,
            "resumos": linhas,
        }
        logger.info("Monitor buy box: %s catálogo(s)", len(resultados))
        return payload
    except Exception as exc:
        logger.error("Monitor buy box erro: %s", exc)
        return {"ok": False, "erro": str(exc), "resultados": []}


def main() -> int:
    logger.info("=== Monitor buy box ML ===")
    resultado = executar()
    if not resultado.get("ok"):
        logger.error("Falha: %s", resultado.get("erro"))
        return 1
    if resultado.get("resumos"):
        for linha in resultado["resumos"]:
            print(linha)
    else:
        print("[OK] Nenhum catalog_product_id ativo na lista.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
