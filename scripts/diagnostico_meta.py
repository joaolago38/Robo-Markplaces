#!/usr/bin/env python3
"""
scripts/diagnostico_meta.py

Verifica a conexão com a Meta Ads API (Facebook + Instagram) e mostra como
estão os anúncios. Não vaza o token no log.

Uso:
    .venv\\Scripts\\python.exe scripts/diagnostico_meta.py

Checa:
    1. Credenciais presentes (META_ACCESS_TOKEN / META_AD_ACCOUNT_ID)
    2. Token + conta acessíveis (/me e /act_<id>)
    3. Campanhas — quantas ativas e métricas agregadas
    4. Split por plataforma (Instagram x Facebook)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

OK = "OK"
ERRO = "X"
AVISO = "!"


def executar(periodo_dias: int = 7) -> dict:
    """
    Roda o diagnóstico e devolve um dict estruturado (não lança exceção).
    """
    from integracoes.meta.meta_ads_client import (
        listar_metricas_campanhas,
        listar_metricas_por_plataforma,
        normalizar_metrica_campanha,
        normalizar_por_plataforma,
        validar_conexao,
    )

    resultado: dict = {"ok": False, "etapas": {}}

    conexao = validar_conexao()
    resultado["etapas"]["conexao"] = conexao
    if not conexao.get("ok"):
        resultado["erro"] = conexao.get("erro", "falha na conexão")
        return resultado

    rows = listar_metricas_campanhas(periodo_dias=periodo_dias, limite=100)
    campanhas = [normalizar_metrica_campanha(r) for r in rows]
    gasto_total = round(sum(c["gasto"] for c in campanhas), 2)
    receita_total = round(sum(c["receita"] for c in campanhas), 2)
    resultado["etapas"]["campanhas"] = {
        "total": len(campanhas),
        "gasto_total": gasto_total,
        "receita_total": receita_total,
        "roas_geral": round(receita_total / gasto_total, 2) if gasto_total > 0 else 0.0,
    }

    rows_plat = listar_metricas_por_plataforma(periodo_dias=periodo_dias, limite=100)
    resultado["etapas"]["plataformas"] = normalizar_por_plataforma(rows_plat)

    resultado["ok"] = True
    return resultado


def _imprimir(resultado: dict) -> None:
    print("=" * 60)
    print("Diagnóstico Meta Ads — Facebook + Instagram")
    print("=" * 60)

    conexao = resultado["etapas"].get("conexao", {})
    if conexao.get("ok"):
        print(f"[{OK}] Conexão — usuário: {conexao.get('usuario')} | "
              f"conta: {conexao.get('conta')} ({conexao.get('moeda')})")
    else:
        print(f"[{ERRO}] Conexão — {conexao.get('erro')}")
        print("\n     Gere/renove o token com: python pegar_token_meta.py --url")
        print("     e configure META_ACCESS_TOKEN e META_AD_ACCOUNT_ID (act_...).")
        return

    camp = resultado["etapas"].get("campanhas", {})
    print(f"[{OK if camp.get('total') else AVISO}] Campanhas — {camp.get('total', 0)} no período | "
          f"gasto R$ {camp.get('gasto_total', 0)} | receita R$ {camp.get('receita_total', 0)} | "
          f"ROAS {camp.get('roas_geral', 0)}x")

    plataformas = resultado["etapas"].get("plataformas", {})
    if plataformas:
        print(f"[{OK}] Split por plataforma:")
        for nome, m in sorted(plataformas.items()):
            print(f"       {nome}: gasto R$ {m['gasto']} | receita R$ {m['receita']} | ROAS {m['roas']}x")
    else:
        print(f"[{AVISO}] Sem dados por plataforma no período.")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    periodo = 7
    if argv:
        try:
            periodo = max(1, int(argv[0]))
        except ValueError:
            pass

    resultado = executar(periodo_dias=periodo)
    _imprimir(resultado)
    return 0 if resultado.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
