"""
agentes/importacao/agente_comparar_portos_alibaba.py
Compara importação Alibaba em qualquer porto/aeroporto do Brasil (aéreo + marítimo).

Uso:
  python -m agentes.importacao.agente_comparar_portos_alibaba --fob 2.5 --peso 1 --qty 100
  python -m agentes.importacao.agente_comparar_portos_alibaba --produto-id filamento-impressora-3d-pla
  python -m agentes.importacao.agente_comparar_portos_alibaba --modal maritimo --cep 13467-694
"""
from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from core.atomic_io import ler_json
from core.config import ROOT
from core.datadog_metrics import incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.importacao.comparar_portos_alibaba import (
    comparar_portos_para_produto_alibaba,
    formatar_comparacao_telegram,
)
from integracoes.importacao.contexto_importacao_cnpj import (
    CEP_TESTE_PADRAO,
    anexar_contexto_ao_resultado,
)

logger = logging.getLogger("agente_comparar_portos_alibaba")


def _produto_do_catalogo(produto_id: str) -> dict[str, Any]:
    path = ROOT / "catalogo" / "alibaba_produtos_importacao.json"
    data = ler_json(path, default=[])
    itens = data if isinstance(data, list) else []
    for p in itens:
        if isinstance(p, dict) and str(p.get("id") or "") == produto_id:
            return p
    return {}


def executar(
    *,
    produto: dict[str, Any] | None = None,
    produto_id: str | None = None,
    fob_usd: float | None = None,
    peso_kg: float = 1.0,
    quantidade: int = 1,
    modal: str = "todos",
    cep: str | None = None,
    enviar_alerta: bool = False,
) -> dict[str, Any]:
    prod = dict(produto or {})
    if produto_id and not prod:
        prod = _produto_do_catalogo(produto_id)
    if fob_usd is not None:
        prod["preco_fob_usd"] = float(fob_usd)
    if peso_kg:
        prod.setdefault("peso_kg", float(peso_kg))
    if quantidade:
        prod.setdefault("moq_referencia", int(quantidade))
    prod.setdefault("fonte", "alibaba")

    cep_efetivo = cep or CEP_TESTE_PADRAO
    out = comparar_portos_para_produto_alibaba(
        prod,
        cep_destino=cep_efetivo,
        modal=modal,
    )
    msg = formatar_comparacao_telegram(out)
    out["mensagem"] = msg
    out = anexar_contexto_ao_resultado(out, calculo=out)
    msg = out.get("mensagem") or msg

    if enviar_alerta and out.get("ok") and gestor_telegram_configurado():
        try:
            alertar_gestor(
                msg,
                chave=chave_resumo_periodo("portos_alibaba", horas_por_bucket=12),
                cooldown_segundos=43200,
                agente_id="comparar_portos_alibaba",
            )
            incrementar("portos_alibaba.telegram_ok")
        except Exception as exc:
            logger.warning("telegram portos: %s", exc)
            incrementar("portos_alibaba.telegram_erro")

    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser(description="Comparar portos BR × Alibaba (aéreo/marítimo)")
    p.add_argument("--produto-id", default="", help="ID em alibaba_produtos_importacao.json")
    p.add_argument("--fob", type=float, default=None, help="FOB USD unitário")
    p.add_argument("--peso", type=float, default=1.0)
    p.add_argument("--qty", type=int, default=100)
    p.add_argument("--modal", choices=["todos", "aereo", "maritimo"], default="todos")
    p.add_argument("--cep", default=CEP_TESTE_PADRAO, help="CEP destino (teste: 13467-694)")
    p.add_argument("--alerta", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    out = executar(
        produto_id=args.produto_id or None,
        fob_usd=args.fob,
        peso_kg=args.peso,
        quantidade=args.qty,
        modal=args.modal,
        cep=args.cep or CEP_TESTE_PADRAO,
        enviar_alerta=args.alerta,
    )
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    else:
        print(out.get("mensagem") or out)


if __name__ == "__main__":
    main()
