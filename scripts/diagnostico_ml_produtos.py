#!/usr/bin/env python3
"""
scripts/diagnostico_ml_produtos.py

Lista os anúncios da conta Mercado Livre (item_id, preço, status, SKU, título).

Uso:
    .venv\\Scripts\\python.exe scripts\\diagnostico_ml_produtos.py
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

from integracoes.ml.ml_client import listar_meus_anuncios, obter_status_anuncio, pausar_anuncio
from integracoes.ml.ml_product_ads import listar_campanhas, obter_advertiser


def main() -> int:
    token = os.getenv("ML_ACCESS_TOKEN", "").strip()
    seller = os.getenv("ML_SELLER_ID", "").strip()

    if not token or not seller:
        print("Configure ML_ACCESS_TOKEN e ML_SELLER_ID no .env e rode de novo.")
        return 1

    anuncios = listar_meus_anuncios()
    if not anuncios:
        print("Nenhum anúncio retornado (conta vazia ou token inválido).")
        return 1

    print(f"{'item_id':<16} {'preço':>10} {'status':<12} {'SKU':<14} título")
    print("-" * 90)
    for a in anuncios:
        titulo = (a.get("titulo") or "")[:40]
        print(
            f"{a.get('item_id', ''):<16} "
            f"{a.get('preco', 0):>10.2f} "
            f"{a.get('status', ''):<12} "
            f"{(a.get('sku') or ''):<14} "
            f"{titulo}"
        )

    por_status = Counter(a.get("status") or "(sem status)" for a in anuncios)
    sem_sku = sum(1 for a in anuncios if not (a.get("sku") or "").strip())

    print("\n--- Resumo ---")
    print(f"Total: {len(anuncios)} anúncio(s)")
    for status, qtd in sorted(por_status.items()):
        print(f"  {status}: {qtd}")
    print(f"  Sem SKU: {sem_sku}")

    # Valida leitura de status + simulação dry-run (não altera nada no ML)
    primeiro = anuncios[0].get("item_id", "")
    if primeiro:
        st = obter_status_anuncio(primeiro)
        sim = pausar_anuncio(primeiro, dry_run=True)
        print("\n--- Diagnóstico de status (dry-run) ---")
        if st.get("ok"):
            print(f"  Status atual de {primeiro}: {st.get('status')}")
        else:
            print(f"  Não foi possível ler status: {st.get('erro')}")
        print(f"  Simulação pausar: {sim}")

    adv = obter_advertiser()
    print("\n--- Product Ads ---")
    if adv.get("ok"):
        print(f"  Advertiser: {adv.get('advertiser_id')} (site {adv.get('site_id')})")
        camps = listar_campanhas(advertiser_id=adv["advertiser_id"], dias=7)
        print(f"  Campanhas: {len(camps)}")
        for c in camps[:5]:
            print(
                f"    {c.get('id')} | {c.get('nome', '')[:30]} | "
                f"status={c.get('status')} budget={c.get('budget')} acos={c.get('acos')}"
            )
    else:
        print(f"  {adv.get('erro')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
