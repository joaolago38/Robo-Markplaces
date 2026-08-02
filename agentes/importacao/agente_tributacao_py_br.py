"""
agentes/importacao/agente_tributacao_py_br.py
Cruza tributação Paraguai × Brasil (Mercosul) para maximizar lucro no marketplace.

Uso:
  python -m agentes.importacao.agente_tributacao_py_br
  python -m agentes.importacao.agente_tributacao_py_br --lucro 20 --maquila
  python -m agentes.importacao.agente_tributacao_py_br --fob 4.5 --venda 95 --qty 200
"""
from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from core.config import HUB_PARAGUAI_ATIVO
from core.datadog_metrics import incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.importacao.tributacao_py_br import (
    avaliar_tributacao_produtos_marketplace,
    cruzar_tributacao_py_br_produto,
    formatar_tributacao_py_br_telegram,
)

logger = logging.getLogger("agente_tributacao_py_br")


def executar(
    *,
    fob_usd: float | None = None,
    preco_venda_brl: float | None = None,
    quantidade: int = 200,
    lucro_alvo_pct: float = 20.0,
    regime_maquila: bool = False,
    enviar_alerta: bool = False,
) -> dict[str, Any]:
    if not HUB_PARAGUAI_ATIVO:
        return {"ok": False, "motivo": "HUB_PARAGUAI_ATIVO=0"}

    if fob_usd is not None:
        out = cruzar_tributacao_py_br_produto(
            fob_usd=float(fob_usd),
            quantidade=quantidade,
            preco_venda_ml_brl=float(preco_venda_brl or 0) or None,
            lucro_alvo_pct=lucro_alvo_pct,
            regime_maquila=regime_maquila,
            ii_pct_china=12.6,
        )
        # envelopar no formato telegram
        out = {
            "ok": out.get("ok"),
            "cambio_usd_brl": out.get("preco_origem_unit_brl"),  # placeholder display
            "lucro_alvo_pct": lucro_alvo_pct,
            "total_produtos": 1,
            "recomendam_origem_mercosul": 1
            if (out.get("recomendacao") or {}).get("cenario_sugerido") == "py_origem_mercosul"
            else 0,
            "atingem_lucro_alvo": 1
            if any(c.get("atinge_lucro_alvo") for c in (out.get("cenarios") or []))
            else 0,
            "analises": [
                {
                    "produto_id": "adhoc",
                    "nome": "Produto ad-hoc PY×BR",
                    "cruzamento": out,
                    "recomendacao": (out.get("recomendacao") or {}).get("cenario_sugerido"),
                    "atinge_lucro_alvo": any(
                        c.get("atinge_lucro_alvo") for c in (out.get("cenarios") or [])
                    ),
                }
            ],
            "aviso_legal": out.get("aviso_legal"),
            "cruzamento_adhoc": out,
        }
        # fix cambio display
        try:
            from integracoes.cambio.cotacao_usd import obter_cotacao_usd

            out["cambio_usd_brl"] = float(obter_cotacao_usd().get("usd_brl") or 5.5)
        except Exception:
            out["cambio_usd_brl"] = 5.5
    else:
        out = avaliar_tributacao_produtos_marketplace(
            lucro_alvo_pct=lucro_alvo_pct,
            regime_maquila=regime_maquila,
        )

    msg = formatar_tributacao_py_br_telegram(out)
    out["mensagem"] = msg

    if enviar_alerta and out.get("ok") and gestor_telegram_configurado():
        try:
            alertar_gestor(
                msg,
                chave=chave_resumo_periodo("trib_py_br", horas_por_bucket=24),
                cooldown_segundos=86400,
                agente_id="tributacao_py_br",
            )
            incrementar("trib_py_br.telegram_ok")
        except Exception as exc:
            logger.warning("telegram trib py br: %s", exc)
            incrementar("trib_py_br.telegram_erro")

    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser(
        description="Cruzar tributação Paraguai × Brasil (Mercosul) × lucro marketplace"
    )
    p.add_argument("--fob", type=float, default=None)
    p.add_argument("--venda", type=float, default=None)
    p.add_argument("--qty", type=int, default=200)
    p.add_argument("--lucro", type=float, default=20.0)
    p.add_argument("--maquila", action="store_true", help="Simular regime Maquila PY (~1%% VA)")
    p.add_argument("--alerta", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    out = executar(
        fob_usd=args.fob,
        preco_venda_brl=args.venda,
        quantidade=args.qty,
        lucro_alvo_pct=args.lucro,
        regime_maquila=args.maquila,
        enviar_alerta=args.alerta,
    )
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    else:
        print(out.get("mensagem") or out)


if __name__ == "__main__":
    main()
