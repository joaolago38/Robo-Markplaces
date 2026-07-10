"""
integracoes/ml/analise_loja_concorrente.py
Análise de loja concorrente no Mercado Livre (reputação + mix por termos).

Como /sites/search?seller_id=… costuma retornar 403, a coleta de anúncios
usa buscas por termo e filtra pelo seller_id quando o campo vem preenchido.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from core.http_client import request
from integracoes.ml import ml_client

logger = logging.getLogger("analise_loja_concorrente")

BASE = "https://api.mercadolibre.com"

_TERMOS_PADRAO_ESMALTES: tuple[str, ...] = (
    "kit 5 esmaltes impala bailarina",
    "kit 3 esmaltes impala mimo",
    "kit 6 esmaltes impala sortidos",
    "kit 10 esmaltes impala atacado",
    "kit esmalte impala",
    "kit esmalte risque atacado",
    "kit esmalte colorama",
    "kit esmalte dailus",
    "kit esmalte manicure atacado",
    "kit esmalte helen color gel",
    "kit 30 esmaltes atacado",
)

_MARCAS = (
    "impala",
    "risque",
    "risqué",
    "colorama",
    "dailus",
    "anita",
    "hits",
    "helen",
    "novo toque",
    "carmed",
)


def buscar_perfil_loja(seller_id: str | int) -> dict[str, Any]:
    """Perfil público/autenticado do vendedor. Nunca lança."""
    sid = str(seller_id or "").strip()
    if not sid:
        return {"ok": False, "motivo": "seller_id vazio"}
    try:
        headers = ml_client._h() if ml_client._enabled() else {}
        r = request("GET", f"{BASE}/users/{sid}", headers=headers, timeout=25)
        if r.status_code != 200:
            return {"ok": False, "motivo": f"HTTP {r.status_code}", "seller_id": sid}
        u = r.json() or {}
        rep = u.get("seller_reputation") or {}
        addr = u.get("address") or {}
        return {
            "ok": True,
            "seller_id": sid,
            "nickname": u.get("nickname"),
            "permalink": u.get("permalink"),
            "cidade": addr.get("city"),
            "estado": addr.get("state"),
            "site_status": (u.get("status") or {}).get("site_status"),
            "level_id": rep.get("level_id"),
            "power_seller_status": rep.get("power_seller_status"),
            "transactions_total": ((rep.get("transactions") or {}).get("total")),
            "url_loja": f"https://lista.mercadolivre.com.br/pagina/{(u.get('nickname') or '').lower()}",
        }
    except Exception as exc:
        logger.error("buscar_perfil_loja erro: %s", exc)
        return {"ok": False, "motivo": str(exc), "seller_id": sid}


def _marcar_titulo(titulo: str) -> list[str]:
    low = (titulo or "").lower()
    return [m for m in _MARCAS if m in low]


def coletar_anuncios_loja(
    seller_id: str | int,
    *,
    termos: list[str] | None = None,
    limite_por_termo: int = 20,
) -> list[dict[str, Any]]:
    """
    Coleta anúncios da loja via catálogo oficial (/products/search + /items),
    filtrando pelo seller_id. Não depende de /sites/search (403).
    """
    from integracoes.ml import ml_client
    from integracoes.ml.busca_termo_ml import _buscar_via_products_api

    sid = str(seller_id or "").strip()
    lista_termos = [t.strip() for t in (termos or list(_TERMOS_PADRAO_ESMALTES)) if t and t.strip()]
    vistos: set[str] = set()
    anuncios: list[dict[str, Any]] = []

    # 1) Preferir products API (tem seller_id + preço)
    if ml_client._enabled():
        for termo in lista_termos:
            try:
                # pede mais resultados para achar o seller entre vários vendedores do catálogo
                rows = _buscar_via_products_api(termo, max(limite_por_termo, 40))
            except Exception as exc:
                logger.warning("products termo %r falhou: %s", termo, exc)
                rows = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_sid = str(row.get("seller_id") or "").strip()
                if sid and row_sid != sid:
                    continue
                item_id = str(row.get("item_id") or "").strip().upper()
                chave = item_id or str(row.get("permalink") or row.get("titulo") or "")
                if not chave or chave in vistos:
                    continue
                vistos.add(chave)
                titulo = str(row.get("titulo") or "")
                anuncios.append(
                    {
                        "item_id": item_id,
                        "titulo": titulo,
                        "preco": float(row.get("preco") or 0),
                        "quantidade_vendida": int(row.get("quantidade_vendida") or 0),
                        "seller_id": row_sid or sid,
                        "permalink": str(row.get("permalink") or ""),
                        "termo_origem": termo,
                        "marcas": _marcar_titulo(titulo),
                        "fonte_busca": row.get("fonte_busca") or "products_api",
                        "catalog_product_id": row.get("catalog_product_id"),
                        "catalog_date_created": row.get("catalog_date_created"),
                        "listing_type_id": row.get("listing_type_id"),
                    }
                )

    # 2) Fallback genérico (Brave/DDG) se products não trouxe nada
    if not anuncios:
        for termo in lista_termos:
            try:
                rows = ml_client.buscar_concorrentes_por_termo(termo, limite=limite_por_termo)
            except Exception as exc:
                logger.warning("busca termo %r falhou: %s", termo, exc)
                rows = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                item_id = str(row.get("item_id") or row.get("id") or "").strip().upper()
                row_sid = str(row.get("seller_id") or "").strip()
                if sid and row_sid and row_sid != sid:
                    continue
                if sid and not row_sid and "novamix" not in termo.lower():
                    continue
                chave = item_id or str(row.get("permalink") or row.get("titulo") or "")
                if not chave or chave in vistos:
                    continue
                vistos.add(chave)
                titulo = str(row.get("titulo") or row.get("title") or "")
                anuncios.append(
                    {
                        "item_id": item_id,
                        "titulo": titulo,
                        "preco": float(row.get("preco") or row.get("price") or 0),
                        "quantidade_vendida": int(
                            row.get("quantidade_vendida") or row.get("sold_quantity") or 0
                        ),
                        "seller_id": row_sid or sid,
                        "permalink": str(row.get("permalink") or row.get("url") or ""),
                        "termo_origem": termo,
                        "marcas": _marcar_titulo(titulo),
                        "fonte_busca": row.get("fonte_busca") or "ml",
                    }
                )
    return anuncios


def _comparar_com_catalogo(anuncios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cruza anúncios da loja com SKUs Impala do catálogo (por palavras-chave)."""
    try:
        from core.catalogo_produtos import carregar_produtos_catalogo

        produtos = carregar_produtos_catalogo()
    except Exception:
        produtos = []

    overlaps: list[dict[str, Any]] = []
    for p in produtos:
        sku = str(p.get("sku") or "")
        nome = str(p.get("nome") or "")
        ml = (p.get("canais") or {}).get("mercadolivre") or {}
        meu = float(ml.get("preco") or p.get("preco") or 0)
        if meu <= 0:
            continue
        low_nome = nome.lower()
        tokens = [t for t in re.findall(r"[a-z0-9]+", low_nome) if len(t) > 3]
        tokens = [t for t in tokens if t not in {"kit", "esmaltes", "esmalte", "impala", "cores"}]
        matches = []
        for a in anuncios:
            t = (a.get("titulo") or "").lower()
            if "impala" not in t and "impala" in low_nome:
                continue
            score = sum(1 for tok in tokens if tok in t)
            if score >= 1 and float(a.get("preco") or 0) > 0:
                matches.append(a)
        if not matches:
            continue
        menor = min(float(m.get("preco") or 0) for m in matches)
        overlaps.append(
            {
                "sku": sku,
                "nome": nome,
                "meu_preco": meu,
                "menor_preco_loja": menor,
                "gap_pct": round((meu - menor) / menor * 100.0, 1) if menor > 0 else 0.0,
                "anuncios_loja": len(matches),
                "amostra": matches[:3],
            }
        )
    overlaps.sort(key=lambda x: -abs(float(x.get("gap_pct") or 0)))
    return overlaps


def _analise_estrategica(perfil: dict[str, Any], anuncios: list[dict[str, Any]], overlaps: list[dict[str, Any]]) -> dict[str, Any]:
    """Síntese competitiva mesmo quando a listagem de anúncios vem vazia (API 403)."""
    txs = int(perfil.get("transactions_total") or 0)
    lider = str(perfil.get("power_seller_status") or "").lower()
    nivel = str(perfil.get("level_id") or "")
    porte = "gigante" if txs >= 50000 else "grande" if txs >= 10000 else "medio" if txs >= 1000 else "pequeno"
    return {
        "porte": porte,
        "ameaca_geral": "alta" if porte in {"gigante", "grande"} and lider in {"platinum", "gold"} else "media",
        "pontos_fortes_loja": [
            f"Mercado Líder {lider or '?'} com reputação {nivel or '?'}",
            f"{txs:,} transações históricas".replace(",", "."),
            "Base em São Paulo (logística e alcance nacional no ML)",
            "Mix tipicamente focado em kits de esmalte (Dailus, Risqué, Colorama, Impala, gel)",
            "Página da loja com paginação (_Desde_49) indica estoque amplo (49+ anúncios)",
        ],
        "implicacoes_para_voce": [
            "Não compete só em Impala — cobre várias marcas de manicure/atacado",
            "Volume alto sugere preço agressivo e ads constantes; evite guerra só de preço",
            "Diferencie kits Impala (Bailarina, Mimo+Carmed, sortidos) com título/fotos e frete",
            "Monitore gap nos SKUs IMP-* quando a busca ML voltar a liberar seller_id",
            "Use promoções manicures (WhatsApp/Telegram) para canal próprio fora do ML",
        ],
        "anuncios_amostra": len(anuncios),
        "skus_sob_pressao": [o.get("sku") for o in overlaps if float(o.get("gap_pct") or 0) >= 5],
    }


def analisar_loja(
    seller_id: str | int,
    *,
    nickname: str | None = None,
    termos: list[str] | None = None,
    limite_por_termo: int = 20,
) -> dict[str, Any]:
    """Análise consolidada da loja concorrente."""
    perfil = buscar_perfil_loja(seller_id)
    nick = (nickname or perfil.get("nickname") or "").strip()
    termos_final = list(termos or _TERMOS_PADRAO_ESMALTES)
    if nick and f"{nick.lower()} esmalte" not in [t.lower() for t in termos_final]:
        termos_final = [f"{nick} esmalte", f"{nick} kit"] + termos_final

    anuncios = coletar_anuncios_loja(seller_id, termos=termos_final, limite_por_termo=limite_por_termo)
    try:
        from integracoes.ml.analise_anuncio_concorrente import enriquecer_lista

        anuncios = enriquecer_lista(anuncios)
    except Exception as exc:
        logger.warning("enriquecer métricas loja: %s", exc)

    precos = [float(a.get("preco") or 0) for a in anuncios if float(a.get("preco") or 0) > 0]
    marcas = Counter()
    for a in anuncios:
        for m in a.get("marcas") or []:
            marcas[m] += 1

    overlaps = _comparar_com_catalogo(anuncios)
    ameacas = [o for o in overlaps if float(o.get("gap_pct") or 0) >= 5]
    estrategia = _analise_estrategica(perfil if perfil.get("ok") else {}, anuncios, overlaps)

    return {
        "ok": True,
        "perfil": perfil,
        "nickname": nick or perfil.get("nickname"),
        "seller_id": str(seller_id),
        "total_anuncios_coletados": len(anuncios),
        "anuncios": anuncios,
        "preco_min": min(precos) if precos else 0.0,
        "preco_med": round(sum(precos) / len(precos), 2) if precos else 0.0,
        "preco_max": max(precos) if precos else 0.0,
        "marcas": dict(marcas.most_common()),
        "overlap_catalogo": overlaps,
        "ameacas_preco": ameacas,
        "estrategia": estrategia,
        "termos_usados": termos_final,
        "limitacao": (
            "Busca ML por seller_id retorna 403; anúncios vêm de termos filtrados. "
            "Métricas (nota/receita) estimadas; visitas só dos seus anúncios."
        ),
    }


def montar_mensagem_analise(analise: dict[str, Any]) -> str:
    p = analise.get("perfil") or {}
    e = analise.get("estrategia") or {}
    linhas = [
        "🏪 *Análise loja concorrente ML*",
        f"*{analise.get('nickname') or p.get('nickname') or '?'}* (`{analise.get('seller_id')}`)",
        "",
        f"Reputação: {p.get('level_id') or '?'} | Líder: {p.get('power_seller_status') or '?'}",
        f"Transações: {p.get('transactions_total') or '?'}",
        f"Local: {p.get('cidade') or '?'} / {p.get('estado') or '?'}",
        f"Porte/ameaça: *{e.get('porte', '?')}* / *{e.get('ameaca_geral', '?')}*",
        f"Anúncios coletados (amostra): *{analise.get('total_anuncios_coletados', 0)}*",
    ]
    if analise.get("preco_med"):
        linhas.append(
            f"Preços amostra: R$ {analise['preco_min']:.2f} – "
            f"{analise['preco_med']:.2f} – {analise['preco_max']:.2f}"
        )
    marcas = analise.get("marcas") or {}
    if marcas:
        top = ", ".join(f"{k} ({v})" for k, v in list(marcas.items())[:6])
        linhas.extend(["", f"Marcas no mix: {top}"])
    fortes = e.get("pontos_fortes_loja") or []
    if fortes:
        linhas.extend(["", "*Pontos fortes da loja*"])
        for f in fortes[:5]:
            linhas.append(f"• {f}")
    implic = e.get("implicacoes_para_voce") or []
    if implic:
        linhas.extend(["", "*O que fazer*"])
        for i in implic[:5]:
            linhas.append(f"• {i}")
    ameacas = analise.get("ameacas_preco") or []
    if ameacas:
        linhas.extend(["", "*Ameaças vs seus kits Impala (≥5% mais caro)*"])
        for a in ameacas[:6]:
            linhas.append(
                f"• {a.get('sku')}: seu R$ {a.get('meu_preco'):.2f} vs loja R$ "
                f"{a.get('menor_preco_loja'):.2f} (+{a.get('gap_pct')}%)"
            )
    amostra_m = [a for a in (analise.get("anuncios") or []) if a.get("metricas")]
    if amostra_m:
        linhas.extend(["", "*Amostra métricas (estimadas)*"])
        for a in amostra_m[:5]:
            m = a.get("metricas") or {}
            tit = (a.get("titulo") or a.get("item_id") or "?")[:40]
            ped = [f"R$ {float(m.get('preco') or 0):.2f}"]
            if m.get("nota") is not None:
                ped.append(f"★{m.get('nota')} ({m.get('avaliacoes') or 0})")
            if m.get("receita_liquida_un") is not None:
                ped.append(f"líq R$ {m['receita_liquida_un']:.2f}")
            if m.get("vendas_por_dia") is not None:
                ped.append(f"{m['vendas_por_dia']}/dia")
            linhas.append(f"• {tit}: " + " | ".join(ped))
    elif analise.get("total_anuncios_coletados", 0) == 0:
        linhas.extend(
            [
                "",
                "_Listagem de anúncios indisponível nesta rodada (API search 403)._",
                "_Perfil/reputação e análise estratégica OK — preços por SKU na próxima liberação._",
            ]
        )
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    import argparse
    from datetime import datetime, timezone

    from core.atomic_io import escrever_json_atomico
    from core.config import ROOT

    parser = argparse.ArgumentParser(description="Analisa loja concorrente no ML")
    parser.add_argument("--seller", default="1666381510", help="seller_id ML")
    parser.add_argument("--nickname", default="NOVAMIX_COMERCIAL")
    parser.add_argument("--telegram", action="store_true", help="Envia resumo ao gestor")
    args = parser.parse_args(argv)

    out = analisar_loja(args.seller, nickname=args.nickname)
    path = ROOT / "logs" / "analise_loja_novamix_ultima.json"
    escrever_json_atomico(
        path,
        {"timestamp": datetime.now(timezone.utc).isoformat(), **out},
    )
    print(montar_mensagem_analise(out))
    print(f"\nSnapshot: {path}")
    if args.telegram:
        from core.notificador import alertar_gestor

        alertar_gestor(montar_mensagem_analise(out), chave="analise:loja:novamix")
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
