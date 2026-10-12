"""
integracoes/ml/contexto_playbook_operacao.py
Junta o que o robô já mediu (concorrentes, tendência, reclamações, buy box,
custo) para os playbooks Claude. Não é export JoomPulse.
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import ler_json
from core.config import MONITOR_CONCORRENTES_ARQUIVO, ROOT

logger = logging.getLogger("contexto_playbook_operacao")

LACUNAS_PATH = ROOT / "logs" / "lacunas_ml_ultima.json"
HISTORY_CONC = ROOT / "logs" / "concorrentes_ml_history.json"
HISTORY_BUYBOX = ROOT / "logs" / "buybox_history.json"


def _f(val: Any) -> float | None:
    try:
        v = float(val)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def montar_contexto_operacao() -> dict[str, Any]:
    """Snapshot só com o que está em disco. Nunca lança."""
    try:
        lista = ler_json(ROOT / MONITOR_CONCORRENTES_ARQUIVO, default=[])
        if not isinstance(lista, list):
            lista = []
        hist = ler_json(HISTORY_CONC, default={})
        if not isinstance(hist, dict):
            hist = {}
        lacunas = ler_json(LACUNAS_PATH, default={})
        if not isinstance(lacunas, dict):
            lacunas = {}
        buybox = ler_json(HISTORY_BUYBOX, default={})
        if not isinstance(buybox, dict):
            buybox = {}

        from integracoes.ml.coleta_demanda_ml import calcular_tendencia_demanda

        termos: list[dict[str, Any]] = []
        precos: list[float] = []
        padroes_agg: dict[str, int] = {}
        for entrada in lista:
            if not isinstance(entrada, dict) or not entrada.get("ativo"):
                continue
            eid = str(entrada.get("id") or "")
            bloco = hist.get(eid) if isinstance(hist.get(eid), dict) else {}
            termo = str(entrada.get("termo_busca") or entrada.get("nome") or eid)
            tendencia = calcular_tendencia_demanda(termo, dias=14) if termo else {
                "tendencia": "indeterminado",
                "motivo": "historico insuficiente",
            }
            if isinstance(bloco.get("tendencia_demanda"), dict):
                tendencia = bloco["tendencia_demanda"]
            menor = _f(bloco.get("menor_preco"))
            meu = _f(entrada.get("meu_preco")) or _f(bloco.get("meu_preco"))
            if menor and menor > 0:
                precos.append(menor)
            if meu and meu > 0:
                precos.append(meu)
            padroes = bloco.get("padroes_reclamacao") or []
            for p in padroes:
                if isinstance(p, dict) and p.get("padrao"):
                    padroes_agg[str(p["padrao"])] = padroes_agg.get(str(p["padrao"]), 0) + int(
                        p.get("frequencia") or 0
                    )
            termos.append(
                {
                    "id": eid,
                    "nome": entrada.get("nome"),
                    "sku": entrada.get("sku"),
                    "termo_busca": termo,
                    "tipo": entrada.get("tipo") or "termo",
                    "custo_unitario": entrada.get("custo_unitario"),
                    "catalog_product_id": entrada.get("catalog_product_id"),
                    "meu_preco": meu,
                    "menor_preco": menor,
                    "total_concorrentes": bloco.get("total_concorrentes"),
                    "amostra_cega": bloco.get("amostra_cega"),
                    "tendencia_demanda": tendencia,
                    "padroes_reclamacao": padroes,
                    "margem_real": bloco.get("margem_real"),
                }
            )

        for item in lacunas.get("itens") or []:
            if not isinstance(item, dict):
                continue
            for p in item.get("padroes_reclamacao") or []:
                if isinstance(p, dict) and p.get("padrao"):
                    padroes_agg[str(p["padrao"])] = max(
                        padroes_agg.get(str(p["padrao"]), 0),
                        int(p.get("frequencia") or 0),
                    )

        buybox_resumo: list[dict[str, Any]] = []
        for pid, bloco in list(buybox.items())[:8]:
            if not isinstance(bloco, dict):
                continue
            snaps = bloco.get("snapshots") or []
            ultimo = snaps[-1] if snaps else {}
            venc = ultimo.get("vencedor_atual") if isinstance(ultimo, dict) else None
            buybox_resumo.append(
                {
                    "catalog_product_id": pid,
                    "n_snapshots": len(snaps),
                    "vencedor_atual": venc,
                }
            )

        precos_ord = sorted(precos)
        faixas = None
        if len(precos_ord) >= 3:
            n = len(precos_ord)
            faixas = {
                "entrada": [precos_ord[0], precos_ord[max(0, n // 3 - 1)]],
                "intermediaria": [precos_ord[n // 3], precos_ord[max(n // 3, (2 * n) // 3 - 1)]],
                "premium": [precos_ord[(2 * n) // 3], precos_ord[-1]],
                "n_pontos": n,
            }
        elif precos_ord:
            faixas = {"n_pontos": len(precos_ord), "fraco": True, "precos": precos_ord}

        return {
            "nicho": "esmaltes Impala / kits manicure — Mercado Livre Brasil",
            "categoria": "MLB1430 esmaltes / kits",
            "objetivo_90d": "margem",
            "prazo_reposicao": "não informado no JSON operacional",
            "fontes": {
                "joompulse": False,
                "aviso": (
                    "Demanda = proxy do robô (avaliações visíveis / tendência 14d / "
                    "visitas quando a API deixar). Não é export JoomPulse."
                ),
            },
            "termos_monitorados": termos,
            "padroes_reclamacao_agregados": [
                {"padrao": k, "frequencia": v}
                for k, v in sorted(padroes_agg.items(), key=lambda x: -x[1])
            ],
            "precos_observados": precos_ord[:40],
            "faixas_preco": faixas,
            "buybox": buybox_resumo,
            "lacunas_timestamp": lacunas.get("timestamp"),
            "limitacoes": [
                "sold_quantity de rival costuma vir vazio/403",
                "texto de review de rival costuma 403 PolicyAgent",
                "tendencia indeterminado se <2 snapshots em 14 dias; confiabilidade baixa se <5",
            ],
        }
    except Exception as exc:
        logger.warning("montar_contexto_operacao: %s", exc)
        return {
            "nicho": "esmaltes Impala / kits manicure — Mercado Livre Brasil",
            "fontes": {"joompulse": False, "aviso": str(exc)},
            "termos_monitorados": [],
            "limitacoes": ["falha ao ler logs"],
        }
