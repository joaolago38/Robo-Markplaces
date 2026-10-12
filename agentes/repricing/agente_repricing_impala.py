"""
agentes/repricing/agente_repricing_impala.py
Repricing consciente de fase para kits Impala.
Quando dry_run=False, aplica preço no ML (itens com MLB válido) e atualiza catálogo.
Respeita congelar_repricing do algoritmo e kill switch global.
"""
from __future__ import annotations

import logging
from typing import Any

from core.algoritmo_eventos import deve_congelar_repricing
from core.atomic_io import escrever_json_atomico
from core.catalogo_produtos import CATALOGO_PATH, carregar_produtos_catalogo
from core.datadog_metrics import incrementar
from core.notificador import alertar_gestor
from integracoes.esmaltes.crescimento_esmaltes import _item_id_ml, _mlb_valido
from integracoes.ml.ml_client import atualizar_preco_item as atualizar_preco_ml

logger = logging.getLogger("agente_repricing_impala")

TAXA_ML = 0.18  # alinhado a TAXA_CANAL_PADRAO típica ML

MARGEM_POR_FASE = {
    1: 0.10,
    2: 0.18,
    3: 0.25,
}


def calcular_preco_ideal(kit: dict, fase: int | None = None) -> dict:
    fase = fase or kit.get("fase_atual", 1)
    custo = float(kit.get("custo_total") or kit.get("custo") or 0.0)
    margem_min = MARGEM_POR_FASE.get(int(fase), 0.10)

    if custo <= 0:
        return {"sku": kit.get("sku"), "erro": "custo_total ausente ou zero"}

    denom = 1 - TAXA_ML - margem_min
    if denom <= 0:
        return {"sku": kit.get("sku"), "erro": "parametros_margem_invalidos"}

    preco_min_lucro = custo / denom
    preco_fase = float(kit.get("precos_por_fase", {}).get(f"fase{fase}", preco_min_lucro))
    preco_sugerido = round(max(preco_fase, preco_min_lucro), 2)

    lucro = preco_sugerido * (1 - TAXA_ML) - custo
    margem_real = lucro / preco_sugerido if preco_sugerido > 0 else 0.0

    ml = (kit.get("canais") or {}).get("mercadolivre") or {}
    preco_atual = float(ml.get("preco") or kit.get("preco") or 0.0)
    item_id = _item_id_ml(kit)
    ajuste_necessario = abs(preco_sugerido - preco_atual) >= 0.50

    return {
        "sku": kit.get("sku"),
        "nome": kit.get("nome"),
        "fase": fase,
        "custo_total": round(custo, 2),
        "preco_atual": round(preco_atual, 2),
        "preco_sugerido": preco_sugerido,
        "lucro_estimado": round(lucro, 2),
        "margem_real_pct": round(margem_real * 100, 1),
        "ajuste_necessario": ajuste_necessario,
        "item_id": item_id if _mlb_valido(item_id) else None,
        "mlb_ok": _mlb_valido(item_id),
        "motivo": f"margem mínima fase {fase}: {margem_min*100:.0f}%",
    }


def _aplicar_no_catalogo(sku: str, novo_preco: float, produtos: list[dict[str, Any]]) -> None:
    alvo = sku.strip().upper()
    for p in produtos:
        if str(p.get("sku") or "").strip().upper() != alvo:
            continue
        p["preco"] = float(novo_preco)
        ml = (p.get("canais") or {}).setdefault("mercadolivre", {})
        ml["preco"] = float(novo_preco)
        break
    escrever_json_atomico(CATALOGO_PATH, produtos)


def executar(dry_run: bool = True, fase_override: int | None = None) -> dict:
    """Nunca lança. dry_run=False aplica preço no ML quando MLB válido."""
    try:
        congelar, motivo_cong = deve_congelar_repricing("mercadolivre")
        kits = carregar_produtos_catalogo()
        # só kits Impala / com custo
        kits = [
            k
            for k in kits
            if isinstance(k, dict)
            and (
                "impala" in str(k.get("nome") or "").lower()
                or str(k.get("sku") or "").upper().startswith("IMP-")
                or str(k.get("sku") or "").upper().startswith("KIT-")
            )
        ]
        resultados = [calcular_preco_ideal(k, fase_override) for k in kits]
        for r in resultados:
            sku_r = str(r.get("sku") or "")
            try:
                from integracoes.esmaltes.doutrina_guerra_impala import sku_pode_mexer_preco

                if r.get("ajuste_necessario") and not sku_pode_mexer_preco(sku_r):
                    r["ajuste_necessario"] = False
                    r["congelado_doutrina"] = True
                    r["motivo"] = "doutrina: só PERL mexe preço na frente"
            except Exception as exc:
                logger.debug("doutrina repricing %s: %s", sku_r, exc)
        ajustes = [r for r in resultados if r.get("ajuste_necessario") and not r.get("erro")]

        aplicados = []
        if not dry_run:
            if congelar:
                logger.warning("Repricing Impala congelado pelo algoritmo: %s", motivo_cong)
                alertar_gestor(
                    f"⏸ Repricing Impala *congelado* (algoritmo)\n_{motivo_cong}_",
                    chave="repricing_impala:congelado",
                    cooldown_segundos=3600,
                    agente_id="repricing_impala",
                )
            else:
                from core.guardrails import alertar_bloqueio_escrita_global, bloqueio_escrita_global

                if bloqueio_escrita_global():
                    alertar_bloqueio_escrita_global()
                else:
                    produtos_full = carregar_produtos_catalogo()
                    for aj in ajustes:
                        item_id = aj.get("item_id")
                        if not item_id:
                            aj["aplicado"] = False
                            aj["erro_aplicacao"] = "sem_mlb"
                            continue
                        ok = bool(atualizar_preco_ml(str(item_id), float(aj["preco_sugerido"])))
                        aj["aplicado"] = ok
                        if ok:
                            _aplicar_no_catalogo(str(aj["sku"]), float(aj["preco_sugerido"]), produtos_full)
                            aplicados.append(aj["sku"])
                            incrementar("repricing_impala.aplicado")
                        else:
                            aj["erro_aplicacao"] = "falha_api_ml"
                            incrementar("repricing_impala.falha_aplicacao")

        if ajustes:
            nomes = ", ".join(str(r["sku"]) for r in ajustes[:12])
            alertar_gestor(
                f"Repricing Impala: {len(ajustes)} kit(s) precisam ajuste\n"
                f"SKUs: {nomes}\n"
                f"Modo: {'simulação' if dry_run else 'aplicação'}"
                + (f"\nAplicados: {', '.join(aplicados)}" if aplicados else "")
                + (f"\nCongelado: {motivo_cong}" if congelar and not dry_run else ""),
                chave="repricing_impala:resumo",
                cooldown_segundos=7200,
                agente_id="repricing_impala",
            )

        payload = {
            "dry_run": dry_run,
            "congelado": congelar and not dry_run,
            "motivo_congelamento": motivo_cong if congelar else "",
            "total_kits": len(resultados),
            "total_ajustes": len(ajustes),
            "total_aplicados": len(aplicados),
            "ajustes": ajustes,
            "detalhes": resultados,
        }
        logger.info("Repricing Impala: %s", {k: payload[k] for k in ("dry_run", "total_ajustes", "total_aplicados", "congelado")})
        return payload
    except Exception as exc:
        logger.error("repricing_impala erro: %s", exc)
        incrementar("repricing_impala.erro")
        return {"dry_run": dry_run, "erro": str(exc), "total_ajustes": 0, "ajustes": []}


if __name__ == "__main__":
    import pprint

    pprint.pprint(executar(dry_run=True))
