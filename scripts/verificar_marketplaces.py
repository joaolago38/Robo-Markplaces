"""
scripts/verificar_marketplaces.py
Validação rápida de configuração e conectividade REAL dos
marketplaces — usa probe_conexao() de cada client (uma chamada de
verdade contra a API), em vez de chamar uma função de listagem dentro
de um try/except.

Por que a versão anterior estava quebrada: as funções de listagem
(listar_perguntas_nao_respondidas, etc.) já capturam toda exceção
internamente e retornam lista vazia — então o try/except deste script
NUNCA disparava, e ele reportava "conectado: True" mesmo quando a
chamada real tinha falhado por dentro. `probe_conexao()` não tem esse
problema: ela já devolve {ok, status, msg} explicitamente, sem
precisar de try/except por fora.

Uso:
    py scripts/verificar_marketplaces.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import (  # noqa: E402
    AMAZON_ACCESS_TOKEN,
    MAGALU_ACCESS_TOKEN,
    MAGALU_MERCHANT_ID,
    MAGALU_REFRESH_TOKEN,
    ML_ACCESS_TOKEN,
    ML_SELLER_ID,
    SHOPEE_ACCESS_TOKEN,
    SHOPEE_PARTNER_ID,
    SHOPEE_PARTNER_KEY,
    SHOPEE_REFRESH_TOKEN,
    SHOPEE_SHOP_ID,
)
from integracoes.amazon.amazon_client import probe_conexao as probe_amazon  # noqa: E402
from integracoes.magalu.magalu_client import probe_conexao as probe_magalu  # noqa: E402
from integracoes.ml.ml_client import probe_conexao as probe_ml  # noqa: E402
from integracoes.shopee.shopee_client import probe_conexao as probe_shopee  # noqa: E402


def _ok_config_ml() -> bool:
    return bool(ML_ACCESS_TOKEN and ML_SELLER_ID)


def _ok_config_shopee() -> bool:
    tem_token = bool(SHOPEE_ACCESS_TOKEN or SHOPEE_REFRESH_TOKEN)
    return bool(SHOPEE_PARTNER_ID and SHOPEE_PARTNER_KEY and SHOPEE_SHOP_ID and tem_token)


def _ok_config_magalu() -> bool:
    tem_token = bool(MAGALU_ACCESS_TOKEN or MAGALU_REFRESH_TOKEN)
    return bool(tem_token and MAGALU_MERCHANT_ID)


def _ok_config_amazon() -> bool:
    return bool(AMAZON_ACCESS_TOKEN)


def _testar(nome: str, configurado: bool, probe) -> dict:
    if not configurado:
        return {
            "marketplace": nome,
            "configurado": False,
            "conectado": False,
            "status_http": 0,
            "mensagem": "credenciais ausentes no .env",
        }

    resultado = probe() or {}
    ok = bool(resultado.get("ok"))
    status = resultado.get("status", 0)
    msg = str(resultado.get("msg", "") or "") or ("conexão válida" if ok else "falha de conexão")
    return {
        "marketplace": nome,
        "configurado": True,
        "conectado": ok,
        "status_http": status,
        "mensagem": msg,
    }


def main() -> int:
    resultados = [
        _testar("mercadolivre", _ok_config_ml(), probe_ml),
        _testar("shopee", _ok_config_shopee(), probe_shopee),
        _testar("magalu", _ok_config_magalu(), probe_magalu),
        _testar("amazon", _ok_config_amazon(), probe_amazon),
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
