"""
scripts/simular_guerra_impala.py
Roda a doutrina como se MIMO/PERL/JUPAES já estivessem no ML.

Não publica. Não grava MLB em produtos.json.

  python scripts/simular_guerra_impala.py
  python scripts/simular_guerra_impala.py --cenario igual_para_igual
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

from integracoes.esmaltes.simulacao_guerra_impala import formatar_mensagem, rodar_simulacao


def main() -> int:
    parser = argparse.ArgumentParser(description="Simula guerra Impala com anúncios no ar")
    parser.add_argument("--cenario", default="", help="hoje | igual_para_igual | perl_pressionado | dump_abaixo_piso")
    parser.add_argument("--todos", action="store_true", help="Roda os 4 cenários (incluindo hoje sem MLB)")
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cid = str(args.cenario or "").strip() or None
    out = rodar_simulacao(cenario_id=cid, todos=bool(args.todos))
    print(formatar_mensagem(out))
    print()
    print(json.dumps({k: out[k] for k in out if k != "cenarios"}, ensure_ascii=False, indent=2)[:500])
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
