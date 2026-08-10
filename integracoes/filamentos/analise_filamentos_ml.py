"""
integracoes/filamentos/analise_filamentos_ml.py
Varredura de filamentos 3D no Mercado Livre: preços, marcas e ranking por vendas.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

_MARCAS_FILAMENTO: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Masterprint", ("masterprint", "master print", "master-print")),
    ("3D Lab", ("3d lab", "3dlab")),
    ("Printalot", ("printalot",)),
    ("Voolt3D", ("voolt3d", "voolt")),
    ("eSUN", ("esun", "e-sun")),
    ("Creality", ("creality",)),
    ("GTMax", ("gtmax", "gtmax3d")),
    ("Fox Magic", ("fox magic", "foxmagic")),
    ("3DX", ("3dx", "filamento 3dx")),
    ("Polymaker", ("polymaker",)),
    ("Hatchbox", ("hatchbox",)),
    ("SUNLU", ("sunlu",)),
    ("Eryone", ("eryone",)),
    ("Prusa", ("prusa research", "prusa")),
    ("3DFila", ("3dfila",)),
    ("Anycubic", ("anycubic",)),
    ("Bambu Lab", ("bambulab", "bambu lab")),
    ("Geeetech", ("geeetech",)),
    ("Overture", ("overture",)),
)

_MATERIAIS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("PLA Silk", ("pla silk", "silk pla", "pla seda")),
    ("PLA+", ("pla+", "pla plus")),
    ("PETG", ("petg",)),
    ("ABS", ("abs",)),
    ("TPU", ("tpu", "flexivel", "flexible")),
    ("ASA", ("asa",)),
    ("Nylon", ("nylon", "pa6", "pa12")),
    ("PLA", ("pla",)),
)

_RE_PESO_KG = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*kg\b", re.I)

# (nome_exibição, aliases PT/EN) — ordem: mais específicos primeiro
_CORES_FILAMENTO: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Preto", ("preto", "black", "nero")),
    ("Branco", ("branco", "white", "bianco")),
    ("Natural", ("natural", "transparente", "transparent", "clear", "cristal")),
    ("Vermelho", ("vermelho", "red", "vermelho fosco")),
    ("Azul", ("azul", "blue", "navy")),
    ("Verde", ("verde", "green")),
    ("Amarelo", ("amarelo", "yellow")),
    ("Laranja", ("laranja", "orange")),
    ("Rosa", ("rosa", "pink", "magenta")),
    ("Roxo", ("roxo", "purple", "violeta", "violet")),
    ("Cinza", ("cinza", "grey", "gray", "silver grey")),
    ("Prata", ("prata", "silver", "metallic silver")),
    ("Dourado", ("dourado", "gold", "golden")),
    ("Madeira", ("madeira", "wood", "woodfill")),
    ("Neon", ("neon", "fluorescente", "glow", "glow in the dark", "brilha no escuro")),
    ("Marrom", ("marrom", "brown", "chocolate")),
    ("Bege", ("bege", "beige", "ivory", "creme", "cream")),
    ("Cobre", ("cobre", "copper")),
)

_COR_EN: dict[str, str] = {
    "Preto": "black",
    "Branco": "white",
    "Natural": "natural transparent",
    "Vermelho": "red",
    "Azul": "blue",
    "Verde": "green",
    "Amarelo": "yellow",
    "Laranja": "orange",
    "Rosa": "pink",
    "Roxo": "purple",
    "Cinza": "gray",
    "Prata": "silver",
    "Dourado": "gold",
    "Madeira": "wood",
    "Neon": "glow neon",
    "Marrom": "brown",
    "Bege": "beige",
    "Cobre": "copper",
}


def _as_int(valor: Any) -> int:
    try:
        return max(0, int(valor or 0))
    except (TypeError, ValueError):
        return 0


def vendas_api(anuncio: dict[str, Any] | None) -> int:
    """sold_quantity real da API (0 = ausente/zerado para concorrentes)."""
    if not isinstance(anuncio, dict):
        return 0
    return _as_int(anuncio.get("quantidade_vendida") or anuncio.get("sold_quantity"))


def avaliacoes_anuncio(anuncio: dict[str, Any] | None) -> int:
    if not isinstance(anuncio, dict):
        return 0
    metricas = anuncio.get("metricas") if isinstance(anuncio.get("metricas"), dict) else {}
    return _as_int(
        anuncio.get("avaliacoes") or anuncio.get("reviews") or metricas.get("avaliacoes")
    )


def seller_porte(anuncio: dict[str, Any] | None) -> int:
    if not isinstance(anuncio, dict):
        return 0
    seller = anuncio.get("seller") if isinstance(anuncio.get("seller"), dict) else {}
    return _as_int(
        anuncio.get("seller_transactions")
        or anuncio.get("transactions_total")
        or seller.get("transactions_total")
        or seller.get("transactions")
    )


def volume_proxy_anuncio(anuncio: dict[str, Any] | None) -> tuple[int, str]:
    """1) vendas API  2) avaliações  3) porte seller  4) presença (1)."""
    vend = vendas_api(anuncio)
    if vend > 0:
        return vend, "vendas"
    aval = avaliacoes_anuncio(anuncio)
    if aval > 0:
        return aval, "avaliacoes"
    porte = seller_porte(anuncio)
    if porte > 0:
        return porte, "seller"
    return 1, "presenca"


def chave_ranking_anuncio(anuncio: dict[str, Any]) -> tuple[int, int, float]:
    proxy, _ = volume_proxy_anuncio(anuncio)
    return (vendas_api(anuncio), proxy, float(anuncio.get("nota") or 0))


def fmt_vendas_amostra(valor: Any, *, sufixo: str = "vendas") -> str:
    n = _as_int(valor)
    if n <= 0:
        return "n/d"
    return f"{n} {sufixo}"


def cor_para_termo_en(cor: str) -> str:
    return _COR_EN.get(cor, _normalizar(cor))


def detectar_cores(titulo: str) -> list[str]:
    """Cores mencionadas no título (pode haver mais de uma)."""
    norm = _normalizar(titulo)
    achadas: list[str] = []
    for nome, aliases in _CORES_FILAMENTO:
        if any(a in norm for a in aliases):
            achadas.append(nome)
    return achadas


def detectar_cor_principal(titulo: str) -> str:
    cores = detectar_cores(titulo)
    return cores[0] if cores else "Indefinida"


def _normalizar(texto: str) -> str:
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower()).strip()


def detectar_material(titulo: str, fallback: str | None = None) -> str:
    norm = _normalizar(titulo)
    for nome, aliases in _MATERIAIS:
        if any(a in norm for a in aliases):
            return nome
    return (fallback or "Indefinido").strip() or "Indefinido"


def detectar_marca(titulo: str) -> str:
    norm = _normalizar(titulo)
    for display, aliases in _MARCAS_FILAMENTO:
        if any(a in norm for a in aliases):
            return display
    m = re.search(r"^([A-Za-z0-9][\w+.-]{1,20})\s+filamento", titulo or "", re.I)
    if m:
        cand = m.group(1).strip()
        if cand.lower() not in ("kit", "rolo", "bobina", "1kg", "novo"):
            return cand.title()
    return "Genérico/Outros"


def detectar_peso_kg(titulo: str) -> float | None:
    m = _RE_PESO_KG.search(titulo or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def eh_listing_filamento(titulo: str, material_esperado: str | None = None) -> bool:
    """True se o título parece filamento 3D (evita acessórios soltos)."""
    norm = _normalizar(titulo)
    if not norm:
        return False
    if "filamento" not in norm and "filament" not in norm:
        return False
    if any(x in norm for x in ("curso ", "ebook", "suporte impressora")):
        return False
    if not material_esperado:
        return True

    mat_detectado = detectar_material(titulo)
    esp = material_esperado.strip()
    if esp.upper() == "PLA":
        return mat_detectado.startswith("PLA")
    if esp.upper() in ("PLA+", "PLA PLUS"):
        return mat_detectado in ("PLA+", "PLA Silk") or mat_detectado == "PLA+"
    if _normalizar(esp) in ("pla silk",):
        return mat_detectado == "PLA Silk"
    return _normalizar(mat_detectado) == _normalizar(esp)


def classificar_anuncio(
    anuncio: dict[str, Any],
    *,
    material_esperado: str | None = None,
) -> dict[str, Any] | None:
    titulo = str(anuncio.get("titulo") or "")
    if not eh_listing_filamento(titulo):
        return None
    if material_esperado and not eh_listing_filamento(titulo, material_esperado):
        return None

    preco = float(anuncio.get("preco") or anuncio.get("price") or 0)
    vendidos = vendas_api(anuncio)
    seller = anuncio.get("seller") if isinstance(anuncio.get("seller"), dict) else {}
    sid = anuncio.get("seller_id") or seller.get("id")
    if not sid and isinstance(anuncio.get("seller"), (str, int)):
        sid = anuncio.get("seller")
    return {
        "item_id": str(anuncio.get("item_id") or anuncio.get("id") or ""),
        "titulo": titulo[:140],
        "preco": preco,
        "quantidade_vendida": max(0, vendidos),
        "avaliacoes": avaliacoes_anuncio(anuncio),
        "seller_transactions": seller_porte(anuncio),
        "seller_id": str(sid or "").strip(),
        "marca": detectar_marca(titulo),
        "material": detectar_material(titulo, fallback=material_esperado),
        "cor": detectar_cor_principal(titulo),
        "cores": detectar_cores(titulo),
        "peso_kg": detectar_peso_kg(titulo),
        "permalink": anuncio.get("permalink") or anuncio.get("url") or "",
        "marketplace": anuncio.get("marketplace") or "mercadolivre",
    }


def processar_termo(segmento: dict[str, Any], anuncios: list[dict[str, Any]]) -> dict[str, Any]:
    material = str(segmento.get("material") or "").strip() or None
    classificados: list[dict[str, Any]] = []
    for a in anuncios:
        item = classificar_anuncio(a, material_esperado=material)
        if item:
            classificados.append(item)

    precos = [float(p["preco"]) for p in classificados if float(p.get("preco") or 0) > 0]
    return {
        "ok": True,
        "id": segmento.get("id"),
        "nome": segmento.get("nome"),
        "material": material,
        "termo_busca": segmento.get("termo_busca"),
        "prioridade": int(segmento.get("prioridade") or 99),
        "total_bruto": len(anuncios),
        "total_filamentos": len(classificados),
        "preco_min": round(min(precos), 2) if precos else 0.0,
        "preco_max": round(max(precos), 2) if precos else 0.0,
        "preco_medio": round(sum(precos) / len(precos), 2) if precos else 0.0,
        "produtos": classificados,
    }


def _ranking(produtos: list[dict[str, Any]], chave: str, top_n: int = 12) -> list[dict[str, Any]]:
    totais: dict[str, dict[str, Any]] = {}
    for p in produtos:
        nome = str(p.get(chave) or "Indefinido")
        vendidos = vendas_api(p)
        proxy, fonte = volume_proxy_anuncio(p)
        preco = float(p.get("preco") or 0)
        bucket = totais.setdefault(
            nome,
            {
                chave: nome,
                "vendidos": 0,
                "volume_proxy": 0,
                "anuncios": 0,
                "fonte_volume": "presenca",
                "preco_medio": 0.0,
                "_precos": [],
                "_fontes": {},
            },
        )
        bucket["vendidos"] += max(0, vendidos)
        bucket["volume_proxy"] += proxy
        bucket["anuncios"] += 1
        bucket["_fontes"][fonte] = int(bucket["_fontes"].get(fonte) or 0) + 1
        if preco > 0:
            bucket["_precos"].append(preco)

    ranking: list[dict[str, Any]] = []
    for item in totais.values():
        precos = item.pop("_precos", [])
        fontes: dict[str, int] = item.pop("_fontes", {})
        if precos:
            item["preco_medio"] = round(sum(precos) / len(precos), 2)
        if item["vendidos"] > 0:
            item["fonte_volume"] = "vendas"
        elif fontes:
            item["fonte_volume"] = max(fontes.items(), key=lambda kv: kv[1])[0]
        ranking.append(item)
    ranking.sort(
        key=lambda x: (x["vendidos"], x.get("volume_proxy", 0), x["anuncios"]),
        reverse=True,
    )
    for i, item in enumerate(ranking[:top_n], 1):
        item["rank"] = i
    return ranking[:top_n]


def ranking_cores(produtos: list[dict[str, Any]], top_n: int = 10) -> list[dict[str, Any]]:
    """Ranking por vendas API; sem sold_quantity, pondera por avaliações/presença."""
    totais: dict[str, dict[str, Any]] = {}
    for p in produtos:
        cores = list(p.get("cores") or [])
        if not cores:
            cores = [str(p.get("cor") or "Indefinida")]
        vendidos = vendas_api(p)
        proxy, fonte = volume_proxy_anuncio(p)
        preco = float(p.get("preco") or 0)
        peso = proxy if proxy > 0 else 1
        for cor in cores:
            bucket = totais.setdefault(
                cor,
                {
                    "cor": cor,
                    "vendidos": 0,
                    "anuncios": 0,
                    "peso_vendas": 0,
                    "volume_proxy": 0,
                    "fonte_volume": "presenca",
                    "preco_medio": 0.0,
                    "_precos": [],
                    "_fontes": {},
                },
            )
            bucket["vendidos"] += max(0, vendidos)
            bucket["anuncios"] += 1
            bucket["peso_vendas"] += peso
            bucket["volume_proxy"] += proxy
            bucket["_fontes"][fonte] = int(bucket["_fontes"].get(fonte) or 0) + 1
            if preco > 0:
                bucket["_precos"].append(preco)

    ranking: list[dict[str, Any]] = []
    for item in totais.values():
        precos = item.pop("_precos", [])
        fontes: dict[str, int] = item.pop("_fontes", {})
        if precos:
            item["preco_medio"] = round(sum(precos) / len(precos), 2)
        if item["vendidos"] > 0:
            item["fonte_volume"] = "vendas"
        elif fontes:
            item["fonte_volume"] = max(fontes.items(), key=lambda kv: kv[1])[0]
        ranking.append(item)
    ranking.sort(
        key=lambda x: (x["vendidos"], x["peso_vendas"], x["anuncios"]),
        reverse=True,
    )
    for i, item in enumerate(ranking[:top_n], 1):
        item["rank"] = i
    return ranking[:top_n]


def consolidar_varredura(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    por_item: dict[str, dict[str, Any]] = {}
    termos_ok = 0

    for resultado in resultados:
        if not resultado.get("ok"):
            continue
        termos_ok += 1
        for prod in resultado.get("produtos") or []:
            iid = str(prod.get("item_id") or "").strip()
            chave = iid or f"{prod.get('titulo')}|{prod.get('preco')}"
            atual = por_item.get(chave)
            if not atual or chave_ranking_anuncio(prod) > chave_ranking_anuncio(atual):
                por_item[chave] = prod

    unicos = list(por_item.values())
    precos = [float(p.get("preco") or 0) for p in unicos if float(p.get("preco") or 0) > 0]
    com_vendas = [p for p in unicos if vendas_api(p) > 0]
    total_vendas = sum(vendas_api(p) for p in com_vendas)
    top_vendas = sorted(unicos, key=chave_ranking_anuncio, reverse=True)
    top_baratos = sorted(
        [p for p in unicos if float(p.get("preco") or 0) > 0],
        key=lambda x: float(x.get("preco") or 0),
    )[:10]
    cores = ranking_cores(unicos)
    com_aval = sum(1 for p in unicos if avaliacoes_anuncio(p) > 0)

    return {
        "total_filamentos_unicos": len(unicos),
        "total_vendas": total_vendas,
        "vendas_proxy_confiavel": total_vendas > 0,
        "anuncios_com_vendas_api": len(com_vendas),
        "anuncios_com_avaliacoes": com_aval,
        "termos_varridos": termos_ok,
        "preco_medio": round(sum(precos) / len(precos), 2) if precos else 0.0,
        "preco_min": round(min(precos), 2) if precos else 0.0,
        "preco_max": round(max(precos), 2) if precos else 0.0,
        "ranking_marcas": _ranking(unicos, "marca"),
        "ranking_materiais": _ranking(unicos, "material"),
        "ranking_cores": cores,
        "top_vendas": top_vendas[:12],
        "top_baratos": top_baratos,
        "produtos_unicos": unicos,
        "por_termo": [
            {
                "id": r.get("id"),
                "nome": r.get("nome"),
                "material": r.get("material"),
                "total": r.get("total_filamentos"),
                "preco_min": r.get("preco_min"),
                "preco_medio": r.get("preco_medio"),
                "preco_max": r.get("preco_max"),
            }
            for r in resultados
            if r.get("ok")
        ],
    }


def enriquecer_avaliacoes_amostra(
    resultados: list[dict[str, Any]],
    *,
    limite: int = 15,
) -> int:
    """
    Busca /reviews/item nos top anúncios (proxy de demanda quando sold_quantity=0).
    Atualiza produtos in-place; retorna quantos receberam avaliações.
    """
    from integracoes.ml.analise_anuncio_concorrente import buscar_reviews_item

    por_item: dict[str, dict[str, Any]] = {}
    for resultado in resultados:
        if not resultado.get("ok"):
            continue
        for prod in resultado.get("produtos") or []:
            iid = str(prod.get("item_id") or "").strip()
            if not iid:
                continue
            atual = por_item.get(iid)
            if not atual or chave_ranking_anuncio(prod) > chave_ranking_anuncio(atual):
                por_item[iid] = prod

    candidatos = sorted(por_item.values(), key=chave_ranking_anuncio, reverse=True)[: max(0, limite)]
    atualizados = 0
    for prod in candidatos:
        iid = str(prod.get("item_id") or "").strip()
        if not iid or avaliacoes_anuncio(prod) > 0:
            continue
        rev = buscar_reviews_item(iid)
        if not rev.get("ok"):
            continue
        aval = _as_int(rev.get("avaliacoes"))
        if aval <= 0:
            continue
        # propaga para todas as cópias do item nos resultados
        for resultado in resultados:
            for p in resultado.get("produtos") or []:
                if str(p.get("item_id") or "").strip() == iid:
                    p["avaliacoes"] = aval
                    if rev.get("nota") is not None:
                        p["nota"] = rev.get("nota")
        atualizados += 1
    return atualizados


def resumo_decisao_filamentos(
    consolidado: dict[str, Any],
    *,
    custo_1kg_brl: float | None = None,
    taxa_ml_pct: float = 16.0,
    margem_alvo_pct: float = 25.0,
) -> dict[str, Any]:
    """Insights acionáveis (preço/sortimento/cores) — sem fingir volume de vendas."""
    from integracoes.importacao.custo_landed import calcular_margem_revenda

    cores = list(consolidado.get("ranking_cores") or [])
    marcas = list(consolidado.get("ranking_marcas") or [])
    preco_med = float(consolidado.get("preco_medio") or 0)
    preco_min = float(consolidado.get("preco_min") or 0)
    tem_vendas = bool(consolidado.get("vendas_proxy_confiavel"))
    com_aval = int(consolidado.get("anuncios_com_avaliacoes") or 0)

    fonte_cores = "vendas_api" if tem_vendas else ("avaliacoes" if com_aval > 0 else "presenca_anuncios")
    top_cores = [c.get("cor") for c in cores[:5] if c.get("cor")]
    saturadas = [c.get("cor") for c in cores[:3] if int(c.get("anuncios") or 0) >= 10]
    nicho = [
        c.get("cor")
        for c in cores
        if c.get("cor") and c.get("cor") != "Indefinida" and int(c.get("anuncios") or 0) <= 3
    ][:4]

    margem = None
    preco_piso = None
    if custo_1kg_brl and custo_1kg_brl > 0 and preco_med > 0:
        margem = calcular_margem_revenda(
            preco_med, float(custo_1kg_brl), taxa_marketplace_pct=taxa_ml_pct
        )
        # piso aproximado: custo / (1 - taxa - margem_alvo)
        denom = 1 - (taxa_ml_pct / 100.0) - (margem_alvo_pct / 100.0)
        if denom > 0.05:
            preco_piso = round(float(custo_1kg_brl) / denom, 2)

    return {
        "fonte_cores": fonte_cores,
        "confianca_cores_pct": 70 if tem_vendas else (35 if com_aval > 0 else 25),
        "top_cores": top_cores,
        "cores_saturadas": saturadas,
        "cores_nicho": nicho,
        "preco_medio": preco_med,
        "preco_min": preco_min,
        "custo_1kg_brl": custo_1kg_brl,
        "taxa_ml_pct": taxa_ml_pct,
        "margem_no_preco_medio": margem,
        "preco_piso_sugerido": preco_piso,
        "margem_alvo_pct": margem_alvo_pct,
        "marca_mais_presente": (marcas[0].get("marca") if marcas else None),
    }
