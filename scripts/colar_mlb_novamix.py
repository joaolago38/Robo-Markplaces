#!/usr/bin/env python3
"""
scripts/colar_mlb_novamix.py

Grava MLB da loja Novamix em catalogo/concorrentes_monitorados.json
(entrada loja-novamix-comercial → item_ids).

Não usa /sites/search. Fontes:
  - IDs passados na linha de comando (colar da URL do anúncio)
  - cache local logs/ml_busca_termo_cache.json filtrado pelo seller_id

Dry-run por padrão. Use --aplicar para gravar.

Uso:
    python scripts/colar_mlb_novamix.py MLB3948390421 MLB5192919860 --aplicar
    python scripts/colar_mlb_novamix.py --do-cache --aplicar
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CATALOGO_PATH = ROOT / "catalogo" / "concorrentes_monitorados.json"
CACHE_PATH = ROOT / "logs" / "ml_busca_termo_cache.json"
LOJA_ID = "loja-novamix-comercial"
SELLER_ID = "1666381510"
_MLB_RE = re.compile(r"MLB-?\d+", re.I)
_PLACEHOLDER = frozenset({"", "MLB_PREENCHER"})


def normalizar_item_ids(brutos: list[Any] | tuple[Any, ...] | None) -> list[str]:
    """Aceita MLB123, MLB-123 ou URL; ignora placeholder. Ordem estável."""
    vistos: set[str] = set()
    out: list[str] = []
    for bruto in brutos or []:
        texto = str(bruto or "").strip()
        if not texto:
            continue
        achados = _MLB_RE.findall(texto) or ([texto] if texto.upper().startswith("MLB") else [])
        for raw in achados:
            iid = raw.upper().replace("-", "")
            if iid in _PLACEHOLDER or iid in vistos:
                continue
            if not iid.startswith("MLB") or not iid[3:].isdigit():
                continue
            vistos.add(iid)
            out.append(iid)
    return out


def extrair_ids_do_cache(
    caminho: Path | str | None = None,
    *,
    seller_id: str = SELLER_ID,
) -> list[str]:
    """MLB do cache cuja seller_id é a da Novamix."""
    path = Path(caminho or CACHE_PATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    sid = str(seller_id or "").strip()
    brutos: list[str] = []
    for bloco in data.values():
        if not isinstance(bloco, dict):
            continue
        for row in bloco.get("resultados") or []:
            if not isinstance(row, dict):
                continue
            if sid and str(row.get("seller_id") or "").strip() != sid:
                continue
            brutos.append(str(row.get("item_id") or ""))
    return normalizar_item_ids(brutos)


def _carregar_catalogo(caminho: Path) -> list[dict[str, Any]]:
    data = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("catálogo de concorrentes inválido")
    return [row for row in data if isinstance(row, dict)]


def _salvar_catalogo(caminho: Path, dados: list[dict[str, Any]]) -> None:
    tmp = caminho.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(caminho)


def gravar_item_ids(
    ids: list[str],
    *,
    caminho: Path | str | None = None,
    loja_id: str = LOJA_ID,
    merge: bool = True,
    aplicar: bool = False,
) -> dict[str, Any]:
    path = Path(caminho or CATALOGO_PATH)
    novos = normalizar_item_ids(ids)
    catalogo = _carregar_catalogo(path)
    entrada = next((row for row in catalogo if str(row.get("id") or "") == loja_id), None)
    if entrada is None:
        return {"ok": False, "erro": f"entrada {loja_id} não encontrada", "item_ids": []}

    atuais = normalizar_item_ids(entrada.get("item_ids") if isinstance(entrada.get("item_ids"), list) else [])
    finais = normalizar_item_ids([*(atuais if merge else []), *novos])
    alterou = finais != atuais

    if aplicar and alterou:
        entrada["item_ids"] = finais
        _salvar_catalogo(path, catalogo)

    return {
        "ok": True,
        "loja_id": loja_id,
        "dry_run": not aplicar,
        "alterou": alterou,
        "item_ids": finais,
        "n_antes": len(atuais),
        "n_depois": len(finais),
        "aplicado": bool(aplicar and alterou),
    }


def executar(
    ids_cli: list[str] | None = None,
    *,
    do_cache: bool = False,
    aplicar: bool = False,
    merge: bool = True,
    caminho: Path | str | None = None,
    cache_path: Path | str | None = None,
) -> dict[str, Any]:
    brutos = list(ids_cli or [])
    if do_cache:
        brutos.extend(extrair_ids_do_cache(cache_path))
    ids = normalizar_item_ids(brutos)
    if not ids and not merge:
        return {"ok": False, "erro": "nenhum MLB válido", "item_ids": []}
    if not ids:
        # merge sem IDs novos: só reporta o que já está no JSON
        path = Path(caminho or CATALOGO_PATH)
        catalogo = _carregar_catalogo(path)
        entrada = next((row for row in catalogo if str(row.get("id") or "") == LOJA_ID), None)
        atuais = normalizar_item_ids(
            (entrada or {}).get("item_ids") if isinstance((entrada or {}).get("item_ids"), list) else []
        )
        print("[AVISO] Nenhum MLB novo. Passe IDs ou --do-cache.")
        return {
            "ok": True,
            "dry_run": not aplicar,
            "alterou": False,
            "item_ids": atuais,
            "n_antes": len(atuais),
            "n_depois": len(atuais),
            "aplicado": False,
        }
    out = gravar_item_ids(ids, caminho=caminho, merge=merge, aplicar=aplicar)
    prefixo = "[APLICADO]" if out.get("aplicado") else "[DRY-RUN]"
    print(f"{prefixo} {out.get('loja_id')} item_ids={out.get('n_depois')} {out.get('item_ids')}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Grava MLB da Novamix em concorrentes_monitorados.json")
    parser.add_argument("ids", nargs="*", help="MLB ou URL de anúncio da loja")
    parser.add_argument("--do-cache", action="store_true", help="Inclui MLB do cache local (seller Novamix)")
    parser.add_argument("--aplicar", action="store_true", help="Grava no JSON")
    parser.add_argument("--substituir", action="store_true", help="Troca a lista em vez de mesclar")
    args = parser.parse_args(argv)
    resultado = executar(
        args.ids,
        do_cache=args.do_cache,
        aplicar=args.aplicar,
        merge=not args.substituir,
    )
    return 0 if resultado.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
