#!/usr/bin/env python3
"""
scripts/toggle_claude.py

Liga/desliga o Claude de forma momentânea (arquivo logs/claude_toggle.json).
Também respeita CLAUDE_ATIVO no .env / GitHub vars (prende tudo se =0).

Uso:
  python scripts/toggle_claude.py status
  python scripts/toggle_claude.py off --motivo fora_de_horario
  python scripts/toggle_claude.py on
  python scripts/toggle_claude.py off --motivo economia

No GitHub Actions: defina a variável CLAUDE_ATIVO=0 (Settings → Variables)
para pausa em todos os jobs sem editar código.
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
    parser = argparse.ArgumentParser(description="Toggle Claude on/off")
    parser.add_argument(
        "acao",
        choices=("on", "off", "status", "ligar", "desligar"),
        help="on/ligar | off/desligar | status",
    )
    parser.add_argument("--motivo", default="", help="Motivo da pausa/religamento")
    parser.add_argument("--por", default="cli", help="Quem alterou")
    args = parser.parse_args()

    from core.claude_toggle import claude_esta_ativo, definir_ativo, estado_toggle

    acao = args.acao
    if acao in ("off", "desligar"):
        st = definir_ativo(
            False,
            motivo=args.motivo or "pausa_manual",
            atualizado_por=args.por,
        )
        print(f"Claude DESLIGADO — {st.get('motivo')} (fonte={st.get('fonte')})")
    elif acao in ("on", "ligar"):
        st = definir_ativo(
            True,
            motivo=args.motivo or "operacao",
            atualizado_por=args.por,
        )
        ok, motivo = claude_esta_ativo()
        if ok:
            print("Claude LIGADO — pronto para operação")
        else:
            print(
                f"Arquivo ligado, mas ainda BLOQUEADO por env: {motivo}\n"
                "Defina CLAUDE_ATIVO=1 no .env / GitHub Variables."
            )
            return 1
    else:
        st = estado_toggle()
        ok, motivo = claude_esta_ativo()
        print(f"ativo={ok}")
        print(f"fonte={st.get('fonte')}")
        print(f"env_ok={st.get('env_ok')} arquivo_ok={st.get('arquivo_ok')}")
        if not ok:
            print(f"motivo={motivo}")
        if st.get("atualizado_em"):
            print(f"arquivo_atualizado_em={st.get('atualizado_em')} por={st.get('atualizado_por')}")
        print(f"path={st.get('path')}")
        return 0 if ok else 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
