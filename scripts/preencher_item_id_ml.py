#!/usr/bin/env python3
"""
scripts/preencher_item_id_ml.py

Casa SKUs do catalogo/produtos.json com anúncios reais do Mercado Livre
(via integracoes.ml.ml_client.listar_meus_anuncios) para substituir
item_id="MLB_PREENCHER" pelo ID real.

Match EXATO por seller_sku, ou PROVÁVEL por similaridade de título (difflib, limiar 0.72).
Dry-run por padrão; grava com --aplicar (e --incluir-provaveis para gravar PROVÁVEIS também).

Uso:
    python scripts/preencher_item_id_ml.py
    python scripts/preencher_item_id_ml.py --aplicar
    python scripts/preencher_item_id_ml.py --aplicar --incluir-provaveis
"""
from __future__ import annotations

import argparse
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

CATALOGO_PATH = ROOT / "catalogo" / "produtos.json"
LIMIAR_TITULO = 0.72


def _item_id_pendente(valor: Any) -> bool:
    texto = str(valor or "").strip()
    if not texto:
        return True
    return "PREENCHER" in texto.upper()


def _similaridade(a: str, b: str) -> float:
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def _carregar_catalogo() -> list[dict]:
    try:
        with CATALOGO_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as exc:
        print(f"[FALHA] Erro ao ler catálogo: {exc}")
        return []


def _salvar_catalogo(produtos: list[dict]) -> None:
    tmp = CATALOGO_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(produtos, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(CATALOGO_PATH)


def _encontrar_match(
    produto: dict,
    anuncios: list[dict],
) -> tuple[dict | None, str, float]:
    sku = str(produto.get("sku") or "").strip()
    canais = produto.get("canais") or {}
    ml = canais.get("mercadolivre") if isinstance(canais, dict) else {}
    if not isinstance(ml, dict):
        return None, "", 0.0

    for an in anuncios:
        if str(an.get("sku") or "").strip() == sku and sku:
            return an, "EXATO", 1.0

    titulo_ref = str(ml.get("titulo_anuncio") or produto.get("nome") or "")
    melhor_score = 0.0
    melhor: dict | None = None
    for an in anuncios:
        score = _similaridade(titulo_ref, str(an.get("titulo") or ""))
        if score > melhor_score:
            melhor_score = score
            melhor = an

    if melhor and melhor_score >= LIMIAR_TITULO:
        return melhor, "PROVÁVEL", melhor_score
    return None, "", melhor_score


def executar(aplicar: bool = False, incluir_provaveis: bool = False) -> dict[str, Any]:
    from integracoes.ml import ml_client

    catalogo = _carregar_catalogo()
    if not catalogo:
        return {"ok": False, "erro": "catálogo vazio ou ausente"}

    anuncios = ml_client.listar_meus_anuncios()
    if not anuncios:
        print("[AVISO] Nenhum anúncio retornado do ML — verifique credenciais.")

    resultados: list[dict[str, Any]] = []
    alterados = 0

    for produto in catalogo:
        if not isinstance(produto, dict):
            continue
        canais = produto.get("canais") or {}
        if not isinstance(canais, dict):
            continue
        ml = canais.get("mercadolivre") or {}
        if not isinstance(ml, dict) or not ml.get("ativo"):
            continue
        if not _item_id_pendente(ml.get("item_id")):
            continue

        sku = str(produto.get("sku") or "").strip()
        match, tipo, score = _encontrar_match(produto, anuncios)
        registro: dict[str, Any] = {
            "sku": sku,
            "nome": produto.get("nome"),
            "tipo_match": tipo or "NENHUM",
            "score": round(score, 3),
            "item_id_novo": match.get("item_id") if match else None,
            "titulo_ml": match.get("titulo") if match else None,
            "aplicado": False,
        }

        pode_aplicar = bool(match) and (tipo == "EXATO" or (tipo == "PROVÁVEL" and incluir_provaveis))
        if pode_aplicar and aplicar and match:
            ml["item_id"] = str(match["item_id"])
            registro["aplicado"] = True
            alterados += 1
            print(f"[APLICADO] {sku} → {match['item_id']} ({tipo}, score {score:.2f})")
        elif match:
            print(
                f"[{'APLICARIA' if aplicar else 'DRY-RUN'}] {sku} → {match['item_id']} "
                f"({tipo}, score {score:.2f})"
            )
        else:
            print(f"[SEM MATCH] {sku} (melhor score {score:.2f})")

        resultados.append(registro)

    if aplicar and alterados > 0:
        _salvar_catalogo(catalogo)
        print(f"\n[OK] Catálogo atualizado — {alterados} item_id(s) gravado(s).")
    elif aplicar:
        print("\n[OK] Nada a gravar.")
    else:
        print(f"\n[DRY-RUN] {len(resultados)} pendente(s). Use --aplicar para gravar.")

    return {
        "ok": True,
        "dry_run": not aplicar,
        "total_pendentes": len(resultados),
        "total_aplicados": alterados,
        "resultados": resultados,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preenche item_id ML no catálogo")
    parser.add_argument("--aplicar", action="store_true", help="Grava alterações no catálogo")
    parser.add_argument(
        "--incluir-provaveis",
        action="store_true",
        help="Ao aplicar, inclui matches PROVÁVEIS (não só EXATO por SKU)",
    )
    args = parser.parse_args(argv)

    resultado = executar(aplicar=args.aplicar, incluir_provaveis=args.incluir_provaveis)
    return 0 if resultado.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
