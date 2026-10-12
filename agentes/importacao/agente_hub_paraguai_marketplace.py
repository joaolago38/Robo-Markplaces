"""
agentes/importacao/agente_hub_paraguai_marketplace.py
Avalia hub comercial PY (planejado): custos, multi-cliente e lucro em marketplaces.

Uso:
  python -m agentes.importacao.agente_hub_paraguai_marketplace
  python -m agentes.importacao.agente_hub_paraguai_marketplace --alerta
  python -m agentes.importacao.agente_hub_paraguai_marketplace --tributacao
  python -m agentes.importacao.agente_hub_paraguai_marketplace --fob 4.5 --venda 95 --qty 50
"""
from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from core.config import HUB_PARAGUAI_ATIVO
from core.datadog_metrics import incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.importacao.hub_paraguai_marketplace import (
    avaliar_hub_multi_cliente,
    formatar_hub_py_telegram,
    verificar_hub_lucro_20_marketplace,
)
from integracoes.importacao.tributacao_py_br import (
    avaliar_tributacao_produtos_marketplace,
    formatar_tributacao_py_br_telegram,
)

logger = logging.getLogger("agente_hub_paraguai_marketplace")


def executar(
    *,
    fob_usd: float | None = None,
    preco_venda_brl: float | None = None,
    quantidade: int = 50,
    lucro_alvo_pct: float = 20.0,
    enviar_alerta: bool = False,
    cruzar_tributacao: bool = False,
    regime_maquila: bool = False,
) -> dict[str, Any]:
    if not HUB_PARAGUAI_ATIVO:
        incrementar("hub_py.inativo")
        logger.warning("hub_py agente: HUB_PARAGUAI_ATIVO=0 — avaliação ignorada")
        return {"ok": False, "motivo": "HUB_PARAGUAI_ATIVO=0"}

    if cruzar_tributacao and fob_usd is None:
        trib = avaliar_tributacao_produtos_marketplace(
            lucro_alvo_pct=lucro_alvo_pct,
            regime_maquila=regime_maquila,
        )
        trib["mensagem"] = formatar_tributacao_py_br_telegram(trib)
        if enviar_alerta and trib.get("ok") and gestor_telegram_configurado():
            try:
                alertar_gestor(
                    trib["mensagem"],
                    chave=chave_resumo_periodo("trib_py_br", horas_por_bucket=24),
                    cooldown_segundos=86400,
                    agente_id="tributacao_py_br",
                )
                incrementar("trib_py_br.telegram_ok")
            except Exception as exc:
                logger.warning("telegram trib: %s", exc)
                incrementar("trib_py_br.telegram_erro")
        logger.info(
            "hub_py agente trib: ok=%s produtos=%s lucro_ok=%s",
            trib.get("ok"),
            trib.get("total_produtos"),
            trib.get("atingem_lucro_alvo"),
        )
        return trib

    produtos = None
    if fob_usd is not None:
        produtos = [
            {
                "id": "adhoc",
                "nome": "Produto ad-hoc hub PY",
                "ativo": True,
                "fob_usd": float(fob_usd),
                "peso_kg": 1.0,
                "quantidade": quantidade,
                "preco_venda_ml_brl": float(preco_venda_brl or 0),
                "cliente_id": "cliente_proprio_masterprint",
                "tipo_cliente": "proprio",
                "fonte_marketplace": "mercadolivre",
                "regime_maquila": regime_maquila,
            }
        ]

    if produtos is None:
        out = verificar_hub_lucro_20_marketplace(lucro_alvo_pct=lucro_alvo_pct)
        # enriquecer com avaliação multi para telegram unificado
        multi = avaliar_hub_multi_cliente(lucro_alvo_pct=lucro_alvo_pct)
        out["analises"] = multi.get("analises")
        out["verificacao_custos_operacionais"] = out.get("verificacoes")
        out["lucrativos_marketplace_hub"] = out.get("atingem_lucro_alvo")
        out["atingem_lucro_20_com_overhead"] = out.get("atingem_lucro_alvo_com_overhead")
        out["total_produtos"] = out.get("total_produtos_marketplace")
        out["status_hub"] = (out.get("hub") or {}).get("status_hub")
    else:
        out = avaliar_hub_multi_cliente(produtos=produtos, lucro_alvo_pct=lucro_alvo_pct)

    if cruzar_tributacao:
        trib = avaliar_tributacao_produtos_marketplace(
            produtos=produtos,
            lucro_alvo_pct=lucro_alvo_pct,
            regime_maquila=regime_maquila,
        )
        out["tributacao_py_br"] = trib

    msg = formatar_hub_py_telegram(out)
    if cruzar_tributacao and out.get("tributacao_py_br"):
        msg = msg + "\n\n" + formatar_tributacao_py_br_telegram(out["tributacao_py_br"])
    out["mensagem"] = msg

    if enviar_alerta and out.get("ok") and gestor_telegram_configurado():
        try:
            alertar_gestor(
                msg,
                chave=chave_resumo_periodo("hub_py_marketplace", horas_por_bucket=24),
                cooldown_segundos=86400,
                agente_id="hub_paraguai_marketplace",
            )
            incrementar("hub_py.telegram_ok")
        except Exception as exc:
            logger.warning("telegram hub py: %s", exc)
            incrementar("hub_py.telegram_erro")

    logger.info(
        "hub_py agente: ok=%s produtos=%s lucrativos=%s lucro20_oh=%s trib=%s",
        out.get("ok"),
        out.get("total_produtos"),
        out.get("lucrativos_marketplace_hub"),
        out.get("atingem_lucro_20_com_overhead"),
        bool(out.get("tributacao_py_br")),
    )
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser(description="Hub Paraguai × marketplaces — lucro operacional 20%")
    p.add_argument("--fob", type=float, default=None, help="FOB USD unitário (adhoc)")
    p.add_argument("--venda", type=float, default=None, help="Preço venda ML BRL")
    p.add_argument("--qty", type=int, default=50)
    p.add_argument("--lucro", type=float, default=20.0, help="Lucro alvo %% sobre venda ML")
    p.add_argument(
        "--tributacao",
        action="store_true",
        help="Cruzar tributação PY×BR (Mercosul II=0 vs China)",
    )
    p.add_argument("--maquila", action="store_true", help="Incluir regime Maquila PY na simulação")
    p.add_argument("--alerta", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    out = executar(
        fob_usd=args.fob,
        preco_venda_brl=args.venda,
        quantidade=args.qty,
        lucro_alvo_pct=args.lucro,
        enviar_alerta=args.alerta,
        cruzar_tributacao=args.tributacao,
        regime_maquila=args.maquila,
    )
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    else:
        print(out.get("mensagem") or out)


if __name__ == "__main__":
    main()
