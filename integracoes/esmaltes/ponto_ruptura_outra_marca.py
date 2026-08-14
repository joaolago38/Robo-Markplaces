"""
integracoes/esmaltes/ponto_ruptura_outra_marca.py
Ponto de ruptura para entrar com outra marca de esmalte no CNPJ Impala
(52.668.583/0001-27). Mercado Livre é o referente de mercado; o mesmo CNPJ
é a identidade em todos os marketplaces.

Não publica anúncio. Não troca de CNPJ (isso é o ponto_ruptura_segundo_cnpj).
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import ler_json
from core.config import ROOT
from core.empresa.cnpj_utils import digitos, formatar_cnpj
from integracoes.empresa.ponto_ruptura_segundo_cnpj import (
    CNAE_IMPALA_COSMETICO,
    _check,
    _f,
    _i,
    avaliar_ponto_ruptura,
    coletar_preparacao_cnae,
)
from integracoes.esmaltes.analise_anita import _normalizar, detectar_marca

logger = logging.getLogger("ponto_ruptura_outra_marca")

CNPJ_IMPALA = "52668583000127"
CATALOGO_PATH = ROOT / "catalogo" / "marcas_esmalte_candidatas.json"
SNAPSHOT_MERCADO = ROOT / "logs" / "esmaltes_mercado_ultima.json"
SNAPSHOT_ANITA = ROOT / "logs" / "anita_esmaltes_ultima.json"
SNAPSHOT_KITS = ROOT / "logs" / "esmaltes_kits_monitor_ultima.json"
SNAPSHOT_RESUMO = ROOT / "logs" / "resumo_conta_ml_ultima.json"

CANAIS = ("mercadolivre", "shopee", "magalu", "amazon")
_IDS_PLACEHOLDER = frozenset({"", "...", "x", "n/a", "na", "preencher", "todo", "tbd", "none", "null"})


def carregar_catalogo_candidatas() -> dict[str, Any]:
    raw = ler_json(CATALOGO_PATH, default={})
    return raw if isinstance(raw, dict) else {}


def slug_marca(marca: str) -> str:
    return _normalizar(marca).replace(" ", "_") or "indefinida"


def _marcas_alvo(catalogo: dict[str, Any] | None = None) -> list[str]:
    cat = catalogo if catalogo is not None else carregar_catalogo_candidatas()
    propria = slug_marca(str(cat.get("marca_propria") or "impala"))
    out: list[str] = []
    vistos: set[str] = set()
    for m in cat.get("marcas_candidatas") or []:
        s = slug_marca(str(m))
        if not s or s == propria or s in vistos:
            continue
        vistos.add(s)
        out.append(s)
    return out


def _extrair_rankings(blob: Any) -> list[dict[str, Any]]:
    if isinstance(blob, list):
        return [x for x in blob if isinstance(x, dict)]
    if not isinstance(blob, dict):
        return []
    for chave in ("ranking_marcas_global", "ranking_marcas", "ranking"):
        raw = blob.get(chave)
        if isinstance(raw, list) and raw:
            return [x for x in raw if isinstance(x, dict)]
    cons = blob.get("consolidado")
    if isinstance(cons, dict):
        raw = cons.get("ranking_marcas_global") or cons.get("ranking_marcas")
        if isinstance(raw, list) and raw:
            return [x for x in raw if isinstance(x, dict)]
    out: list[dict[str, Any]] = []
    for row in blob.get("resultados") or blob.get("segmentos") or []:
        if isinstance(row, dict):
            out.extend(_extrair_rankings(row))
    return out


def consolidar_ranking_ml(
    *,
    mercado: dict[str, Any] | None = None,
    anita: dict[str, Any] | None = None,
    kits: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Junta rankings ML (mercado + Anita + kits). Impala fica de fora."""
    mercado = mercado if mercado is not None else ler_json(SNAPSHOT_MERCADO, default={})
    anita = anita if anita is not None else ler_json(SNAPSHOT_ANITA, default={})
    kits = kits if kits is not None else ler_json(SNAPSHOT_KITS, default={})
    buckets: dict[str, dict[str, Any]] = {}
    for fonte in (mercado, anita, kits):
        for row in _extrair_rankings(fonte):
            nome = str(row.get("marca") or detectar_marca(str(row.get("titulo") or "")))
            slug = slug_marca(nome)
            if slug in ("impala", "indefinida", "outros", ""):
                continue
            b = buckets.setdefault(
                slug,
                {
                    "marca": nome.title() if nome.islower() else nome,
                    "slug": slug,
                    "vendidos": 0,
                    "anuncios": 0,
                    "volume_proxy": 0,
                    "preco_medio": 0.0,
                    "_precos": [],
                },
            )
            b["vendidos"] += _i(row.get("vendidos") or row.get("unidades_vendidas"))
            n_anuncios = _i(row.get("anuncios") or row.get("total_anuncios"))
            if n_anuncios <= 0 and (
                _i(row.get("vendidos") or row.get("unidades_vendidas")) > 0
                or _f(row.get("preco_medio") or row.get("preco")) > 0
            ):
                n_anuncios = 1
            b["anuncios"] += n_anuncios
            b["volume_proxy"] += _i(row.get("volume_proxy"))
            preco = _f(row.get("preco_medio") or row.get("preco"))
            if preco > 0:
                b["_precos"].append(preco)
    ranking: list[dict[str, Any]] = []
    for item in buckets.values():
        precos = item.pop("_precos", [])
        if precos:
            item["preco_medio"] = round(sum(precos) / len(precos), 2)
        item["score"] = int(item["vendidos"] * 10 + item["volume_proxy"] + item["anuncios"] * 2)
        ranking.append(item)
    ranking.sort(key=lambda x: (x["score"], x["vendidos"], x["anuncios"]), reverse=True)
    return ranking


def pontuar_candidatas(
    ranking: list[dict[str, Any]] | None = None,
    *,
    catalogo: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Garante a lista fixa de marcas (score 0 se o radar ML não viu)."""
    cat = catalogo if catalogo is not None else carregar_catalogo_candidatas()
    ranking = ranking if ranking is not None else consolidar_ranking_ml()
    por_slug = {str(r.get("slug")): r for r in ranking}
    saida: list[dict[str, Any]] = []
    for slug in _marcas_alvo(cat):
        base = por_slug.get(slug) or {
            "marca": slug.replace("_", " ").title(),
            "slug": slug,
            "vendidos": 0,
            "anuncios": 0,
            "volume_proxy": 0,
            "preco_medio": 0.0,
            "score": 0,
        }
        anuncios = _i(base.get("anuncios"))
        vendidos = _i(base.get("vendidos"))
        base["elegivel"] = anuncios >= 2 or vendidos > 0
        saida.append(base)
    saida.sort(key=lambda x: (x["score"], x["vendidos"], x["anuncios"]), reverse=True)
    return saida


def _id_canal_ok(valor: Any) -> bool:
    s = str(valor or "").strip()
    return bool(s) and s.lower() not in _IDS_PLACEHOLDER


def coletar_cnpj_canais(*, empresa: dict[str, Any] | None = None) -> dict[str, Any]:
    """O CNPJ Impala é a referência em ML / Shopee / Magalu / Amazon."""
    from core.empresa.catalogo import listar_empresas
    from core.empresa.overrides import aplicar_overrides_env

    if empresa is None:
        empresas = [aplicar_overrides_env(e) for e in listar_empresas(apenas_ativas=True)]
        empresa = next((e for e in empresas if e.get("id") == "esmaltes_impala"), {})
    cnpj = digitos(str(empresa.get("cnpj") or CNPJ_IMPALA)) or CNPJ_IMPALA
    ml = empresa.get("ml") if isinstance(empresa.get("ml"), dict) else {}
    shopee = empresa.get("shopee") if isinstance(empresa.get("shopee"), dict) else {}
    magalu = empresa.get("magalu") if isinstance(empresa.get("magalu"), dict) else {}
    amazon = empresa.get("amazon") if isinstance(empresa.get("amazon"), dict) else {}
    ids = {
        "mercadolivre": str(ml.get("seller_id") or "").strip(),
        "shopee": str(shopee.get("shop_id") or "").strip(),
        "magalu": str(magalu.get("seller_id") or magalu.get("merchant_id") or "").strip(),
        "amazon": str(amazon.get("seller_id") or "").strip(),
    }
    itens = [
        _check(
            f"cnpj_{canal}",
            _id_canal_ok(ids[canal]),
            f"CNPJ {formatar_cnpj(cnpj)} no {canal}",
            ids[canal] if _id_canal_ok(ids[canal]) else "vazio",
            "id preenchido",
        )
        for canal in CANAIS
    ]
    return {
        "cnpj": cnpj,
        "cnpj_formatado": formatar_cnpj(cnpj),
        "ids": ids,
        "itens": itens,
        "ml_ok": _id_canal_ok(ids["mercadolivre"]),
        "canais_ok": sum(1 for c in CANAIS if _id_canal_ok(ids[c])),
        "canais_total": len(CANAIS),
    }


def _radar_cego(candidatas: list[dict[str, Any]], amostra_min: int) -> bool:
    total_anuncios = sum(_i(c.get("anuncios")) for c in candidatas)
    return total_anuncios < amostra_min


def _cnae_cosmetico_ok(cnae: dict[str, Any]) -> bool:
    itens = cnae.get("itens") or []
    if not itens:
        return True
    for item in itens:
        if str(item.get("id") or "") == "impala_cnae_cosmetico":
            return bool(item.get("ok"))
    return True


def avaliar_ruptura_outra_marca(
    *,
    ruptura_impala: dict[str, Any] | None = None,
    candidatas: list[dict[str, Any]] | None = None,
    canais: dict[str, Any] | None = None,
    resumo: dict[str, Any] | None = None,
    catalogo: dict[str, Any] | None = None,
    cnae: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Veredito para entrar com outra marca no mesmo CNPJ. Nunca lança."""
    cat = catalogo if catalogo is not None else carregar_catalogo_candidatas()
    amostra_min = _i(cat.get("amostra_minima_anuncios"), 5)
    ruptura_impala = ruptura_impala if ruptura_impala is not None else avaliar_ponto_ruptura()
    candidatas = candidatas if candidatas is not None else pontuar_candidatas(catalogo=cat)
    canais = canais if canais is not None else coletar_cnpj_canais()
    cnae = cnae if cnae is not None else coletar_preparacao_cnae()
    resumo = resumo if resumo is not None else ler_json(SNAPSHOT_RESUMO, default={})
    if not isinstance(resumo, dict):
        resumo = {}

    ativos_foco = _i(resumo.get("anuncios_ativos"))
    cnae_cosmetico = _cnae_cosmetico_ok(cnae)
    cego = _radar_cego(candidatas, amostra_min)
    top = next((c for c in candidatas if c.get("elegivel")), None)
    impala_ok = bool(ruptura_impala.get("liberado"))
    ml_ok = bool(canais.get("ml_ok"))
    foco_ok = ativos_foco > 0

    checks = [
        _check(
            "impala_fase1",
            impala_ok,
            "Impala passou na checklist (reviews/MLB/estoque/pedido)",
            ruptura_impala.get("veredito"),
            "liberado",
        ),
        _check(
            "anuncios_foco",
            foco_ok,
            "Há anúncio Impala ativo no ML",
            ativos_foco,
            ">=1",
        ),
        _check(
            "cnpj_ml",
            ml_ok,
            f"CNPJ {canais.get('cnpj_formatado')} identificado no ML",
            (canais.get("ids") or {}).get("mercadolivre") or "vazio",
            "seller_id",
        ),
        _check(
            "cnae_cosmetico",
            cnae_cosmetico,
            f"CNAE {CNAE_IMPALA_COSMETICO} (cosméticos) neste CNPJ",
            "ok" if cnae_cosmetico else "falta",
            CNAE_IMPALA_COSMETICO,
        ),
        _check(
            "radar_ml",
            not cego,
            "Amostra ML suficiente para ranquear marcas",
            f"anuncios_outras={sum(_i(c.get('anuncios')) for c in candidatas)}",
            f">={amostra_min}",
        ),
        _check(
            "candidata",
            bool(top),
            "Há marca candidata (não Impala) no referente ML",
            (top or {}).get("marca") or "nenhuma",
            "top1",
        ),
    ]
    ok_n = sum(1 for c in checks if c["ok"])
    total = len(checks)
    liberado = ok_n == total
    aproximando = (not liberado) and (
        bool(ruptura_impala.get("aproximando") or ruptura_impala.get("liberado")) or ok_n >= 3
    )
    if liberado:
        veredito = "liberado"
    elif aproximando:
        veredito = "aproximando"
    else:
        veredito = "ainda_nao"

    return {
        "veredito": veredito,
        "liberado": liberado,
        "aproximando": aproximando,
        "progresso_pct": round(100.0 * ok_n / total, 1) if total else 0.0,
        "checks_ok": ok_n,
        "checks_total": total,
        "checks": checks,
        "cnpj": canais.get("cnpj") or CNPJ_IMPALA,
        "cnpj_formatado": canais.get("cnpj_formatado") or formatar_cnpj(CNPJ_IMPALA),
        "marca_propria": "impala",
        "marketplace_referente": "mercadolivre",
        "radar_cego": cego,
        "anuncios_foco": ativos_foco,
        "canais": canais,
        "impala": {
            "veredito": ruptura_impala.get("veredito"),
            "progresso_pct": ruptura_impala.get("progresso_pct"),
            "checks_ok": ruptura_impala.get("checks_ok"),
            "checks_total": ruptura_impala.get("checks_total"),
        },
        "top_marca": (top or {}).get("marca") or "",
        "top_slug": (top or {}).get("slug") or "",
        "top_score": _i((top or {}).get("score")),
        "candidatas": candidatas[:12],
    }
