"""
scripts/verificar_marketplaces.py
Validação rápida de configuração e conectividade dos marketplaces.

Uso:
    py scripts/verificar_marketplaces.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import (  # noqa: E402
    AMAZON_ACCESS_TOKEN,
    MAGALU_ACCESS_TOKEN,
    MAGALU_MERCHANT_ID,
    ML_ACCESS_TOKEN,
    ML_SELLER_ID,
    SHOPEE_ACCESS_TOKEN,
    SHOPEE_PARTNER_ID,
    SHOPEE_PARTNER_KEY,
    SHOPEE_SHOP_ID,
)
from integracoes.amazon.amazon_client import listar_mensagens_nao_respondidas  # noqa: E402
from integracoes.magalu.magalu_client import listar_perguntas_nao_respondidas as listar_magalu  # noqa: E402
from integracoes.ml.ml_client import listar_perguntas_nao_respondidas as listar_ml  # noqa: E402
from integracoes.shopee.shopee_client import listar_perguntas_nao_respondidas as listar_shopee  # noqa: E402


def _ok_config_ml() -> bool:
    return bool(ML_ACCESS_TOKEN and ML_SELLER_ID)


def _ok_config_shopee() -> bool:
    return bool(SHOPEE_PARTNER_ID and SHOPEE_PARTNER_KEY and SHOPEE_SHOP_ID and SHOPEE_ACCESS_TOKEN)


def _ok_config_magalu() -> bool:
    return bool(MAGALU_ACCESS_TOKEN and MAGALU_MERCHANT_ID)


def _ok_config_amazon() -> bool:
    return bool(AMAZON_ACCESS_TOKEN)


def _testar(nome: str, configurado: bool, fn):
    if not configurado:
        return {
            "marketplace": nome,
            "configurado": False,
            "conectado": False,
            "mensagem": "credenciais ausentes no .env",
            "pendencias_detectadas": 0,
        }
    try:
        itens = fn() or []
        return {
            "marketplace": nome,
            "configurado": True,
            "conectado": True,
            "mensagem": "conexão válida",
            "pendencias_detectadas": len(itens),
        }
    except Exception as exc:  # pragma: no cover - rota defensiva
        return {
            "marketplace": nome,
            "configurado": True,
            "conectado": False,
            "mensagem": f"falha de conexão: {exc}",
            "pendencias_detectadas": 0,
        }


def main() -> int:
    resultados = [
        _testar("mercadolivre", _ok_config_ml(), listar_ml),
        _testar("shopee", _ok_config_shopee(), lambda: listar_shopee(page_size=10, max_pages=1)),
        _testar("magalu", _ok_config_magalu(), lambda: listar_magalu(limit=10)),
        _testar("amazon", _ok_config_amazon(), lambda: listar_mensagens_nao_respondidas(limit=10)),
    ]

    resumo = {
        "ok": all(r["conectado"] for r in resultados if r["configurado"]),
        "total_marketplaces": len(resultados),
        "configurados": sum(1 for r in resultados if r["configurado"]),
        "conectados": sum(1 for r in resultados if r["conectado"]),
        "resultados": resultados,
    }

    out_path = ROOT / "logs" / "diagnostico_marketplaces.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    print(f"\nDiagnóstico salvo em: {out_path}")
    return 0 if resumo["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
