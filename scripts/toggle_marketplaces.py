#!/usr/bin/env python3
"""
scripts/toggle_marketplaces.py

Liga/desliga Shopee, Magalu e Amazon (e ML) sem editar spec.yaml.
Quando o canal está operando, o algoritmo identifica qual CNPJ está conectado.

Uso:
  python scripts/toggle_marketplaces.py status
  python scripts/toggle_marketplaces.py shopee on
  python scripts/toggle_marketplaces.py magalu off --motivo homologacao
  python scripts/toggle_marketplaces.py amazon on --por cli
"""
from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Toggle operação por marketplace")
    parser.add_argument(
        "canal_ou_status",
        help="status | mercadolivre|shopee|magalu|amazon",
    )
    parser.add_argument(
        "acao",
        nargs="?",
        default="",
        help="on/ligar | off/desligar (omitido se o 1º arg for status)",
    )
    parser.add_argument("--motivo", default="", help="Motivo da pausa/religamento")
    parser.add_argument("--por", default="cli", help="Quem alterou")
    args = parser.parse_args()

    from core.marketplace_cnpj import identificar_cnpj_conectado, linha_cnpj_telegram
    from core.marketplace_toggle import CANAIS, canal_em_operacao, definir_canal, estado_canais

    primeiro = (args.canal_ou_status or "").strip().lower()
    if primeiro in ("status", "estado"):
        st = estado_canais()
        print(f"path={st.get('path')}")
        for nome, info in (st.get("canais") or {}).items():
            flag = "ON " if info.get("operando") else "off"
            ident = identificar_cnpj_conectado(nome) if info.get("operando") else {}
            extra = f" · {linha_cnpj_telegram(ident)}" if ident else ""
            print(f"  {nome}: {flag} fonte={info.get('fonte')}{extra}")
        return 0

    canal = primeiro
    if canal in ("ml", "mlb"):
        canal = "mercadolivre"
    if canal not in CANAIS:
        print(f"Canal inválido: {canal}. Use: {', '.join(CANAIS)} ou status")
        return 1

    acao = (args.acao or "").strip().lower()
    if acao in ("on", "ligar", "1"):
        definir_canal(canal, True, motivo=args.motivo or "operacao", atualizado_por=args.por)
    elif acao in ("off", "desligar", "0"):
        definir_canal(canal, False, motivo=args.motivo or "pausa_manual", atualizado_por=args.por)
    else:
        print("Informe on ou off. Ex.: python scripts/toggle_marketplaces.py shopee on")
        return 1

    operando = canal_em_operacao(canal)
    print(f"{canal}: {'OPERANDO' if operando else 'pausado'}")
    if operando:
        print(linha_cnpj_telegram(identificar_cnpj_conectado(canal)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
