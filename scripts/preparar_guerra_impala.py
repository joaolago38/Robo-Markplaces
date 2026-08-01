"""
scripts/preparar_guerra_impala.py
Executa o FAZER possível sem criar anúncio no ML:
  1) tenta vincular MLB existentes (SKU/título)
  2) gera ficha de publicação dos 3 SKUs de guerra
  3) revalida decisão do dia

Uso:
  python scripts/preparar_guerra_impala.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

from core.atomic_io import escrever_json_atomico
from core.catalogo_produtos import CATALOGO_PATH, carregar_produtos_catalogo
from core.config import DECISAO_DIA_ESMALTES_GUERRA_CATALOGO
from core.config import ROOT as CFG_ROOT
from integracoes.esmaltes.crescimento_esmaltes import _mlb_valido
from integracoes.esmaltes.decisao_dia_esmaltes import carregar_skus_guerra, montar_decisao

OUT_PATH = CFG_ROOT / "logs" / "publicacao_guerra_impala.json"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _score_titulo(titulo: str, alvo: str) -> int:
    t = _norm(titulo)
    a = _norm(alvo)
    if not t or not a:
        return 0
    score = 0
    for tok in re.findall(r"[a-z0-9+]{3,}", a):
        if tok in t:
            score += 1
    if "impala" in t:
        score += 2
    if "kit" in t and "kit" in a:
        score += 1
    return score


def tentar_vincular_mlb() -> dict:
    from integracoes.ml import ml_client

    guerra = carregar_skus_guerra(DECISAO_DIA_ESMALTES_GUERRA_CATALOGO)
    produtos = carregar_produtos_catalogo()
    por_sku = {str(p.get("sku") or "").upper(): p for p in produtos}
    anuncios = ml_client.listar_meus_anuncios(statuses=("active", "paused"))

    vinculados = []
    pendentes = []
    mudou = False

    for g in guerra:
        sku = str(g.get("sku") or "").upper()
        p = por_sku.get(sku)
        if not p:
            pendentes.append({"sku": sku, "motivo": "sku_ausente_catalogo"})
            continue
        ml = (p.get("canais") or {}).get("mercadolivre") or {}
        iid = str(ml.get("item_id") or "")
        if _mlb_valido(iid):
            vinculados.append({"sku": sku, "item_id": iid, "origem": "ja_preenchido"})
            continue

        # match por seller_sku exato
        hit = next(
            (a for a in anuncios if str(a.get("sku") or "").upper() == sku and a.get("item_id")),
            None,
        )
        # match por título
        if not hit:
            titulo_alvo = str(ml.get("titulo_anuncio") or p.get("nome") or "")
            ranked = sorted(
                anuncios,
                key=lambda a: _score_titulo(str(a.get("titulo") or ""), titulo_alvo),
                reverse=True,
            )
            if ranked and _score_titulo(str(ranked[0].get("titulo") or ""), titulo_alvo) >= 4:
                hit = ranked[0]

        if hit and hit.get("item_id"):
            ml["item_id"] = str(hit["item_id"])
            if hit.get("preco"):
                ml["preco"] = float(hit["preco"])
                p["preco"] = float(hit["preco"])
            p.setdefault("canais", {})["mercadolivre"] = ml
            mudou = True
            vinculados.append(
                {
                    "sku": sku,
                    "item_id": hit["item_id"],
                    "origem": "ml_seller_sku" if str(hit.get("sku") or "").upper() == sku else "ml_titulo",
                    "titulo_ml": hit.get("titulo"),
                }
            )
        else:
            pendentes.append(
                {
                    "sku": sku,
                    "motivo": "sem_anuncio_na_conta_ml",
                    "titulo_sugerido": ml.get("titulo_anuncio"),
                    "preco": p.get("preco"),
                    "categoria_ml": ml.get("categoria_ml"),
                    "seller_sku": sku,
                }
            )

    if mudou:
        escrever_json_atomico(CATALOGO_PATH, produtos)

    return {
        "anuncios_conta": len(anuncios),
        "vinculados": vinculados,
        "pendentes_publicar": pendentes,
        "catalogo_atualizado": mudou,
    }


def montar_fichas_publicacao(pendentes: list[dict]) -> list[dict]:
    fichas = []
    for p in pendentes:
        fichas.append(
            {
                "acao": "criar_anuncio_ml_manual",
                "seller_sku": p.get("seller_sku") or p.get("sku"),
                "title": p.get("titulo_sugerido"),
                "price": p.get("preco"),
                "category_id": p.get("categoria_ml") or "MLB1430",
                "depois": (
                    f"Colar o MLB gerado em catalogo/produtos.json -> "
                    f"canais.mercadolivre.item_id do SKU {p.get('sku')}"
                ),
            }
        )
    return fichas


def main() -> int:
    vinculo = tentar_vincular_mlb()
    fichas = montar_fichas_publicacao(vinculo.get("pendentes_publicar") or [])
    dec = montar_decisao()
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "vinculo": vinculo,
        "fichas_publicacao": fichas,
        "decisao_apos": {
            "fazer": (dec.get("fazer") or {}).get("codigo"),
            "titulo_fazer": (dec.get("fazer") or {}).get("titulo"),
            "liberados": dec.get("liberados"),
            "bloqueados": dec.get("bloqueados"),
        },
        "instrucao": (
            "Conta ML sem kits Impala: publique os 3 SKUs com seller_sku = SKU do catálogo, "
            "depois rode de novo este script para vincular o MLB automaticamente."
        ),
    }
    escrever_json_atomico(OUT_PATH, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
