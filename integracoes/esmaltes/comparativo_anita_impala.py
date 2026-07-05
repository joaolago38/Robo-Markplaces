"""
integracoes/esmaltes/comparativo_anita_impala.py
Comparativo Anita vs Impala no ML: demanda (vendas), perfil de consumidor e plano para vencer.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from integracoes.esmaltes.analise_anita import _normalizar
from integracoes.esmaltes.analise_mercado import classificar_anuncio, tendencia_cores

MARCAS_ALVO: tuple[str, ...] = ("Anita", "Impala")

_CHAVES_SALAO = ("atacado", "salao", "salão", "revenda", "cabine", "profissional", "salon")
_CHAVES_PRESENTE = ("presente", "lembrancinha", "mimo", "brinde")
_CHAVES_TENDENCIA = ("tendencia", "tendência", "moda", "novidade", "lançamento", "lancamento")


def _marca_norm(marca: str) -> str:
    return _normalizar(str(marca or ""))


def _filtrar_marcas(anuncios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    classificados = [classificar_anuncio(an) for an in anuncios]
    return [a for a in classificados if _marca_norm(a.get("marca") or "") in ("anita", "impala")]


def inferir_perfil_consumidor(anuncio: dict[str, Any]) -> dict[str, Any]:
    """
    Infere o tipo de comprador a partir do anúncio (título, formato, preço, frete).
    `quantidade_vendida` do ML é proxy de unidades vendidas (≈ volume de compradores).
    """
    titulo = str(anuncio.get("titulo") or "")
    norm = _normalizar(titulo)
    qtd = anuncio.get("qtd_kit")
    tipo = anuncio.get("tipo_anuncio") or "outro"
    preco = float(anuncio.get("preco") or 0)
    ppu = anuncio.get("preco_por_unidade")
    frete = bool(anuncio.get("frete_gratis"))

    perfis: list[str] = []
    if any(c in norm for c in _CHAVES_SALAO) or (qtd and int(qtd) >= 10):
        perfis.append("salao_atacado")
    elif tipo == "unitario" or (qtd == 1):
        perfis.append("consumidor_final")
    elif qtd and 3 <= int(qtd) <= 6:
        perfis.append("manicure_autonoma")
    else:
        perfis.append("consumidor_misto")

    if any(c in norm for c in _CHAVES_PRESENTE):
        perfis.append("presente")
    if any(c in norm for c in _CHAVES_TENDENCIA):
        perfis.append("busca_tendencia")

    if preco > 0 and ppu and float(ppu) <= 4.5:
        perfis.append("price_sensitive")
    elif frete and ppu and float(ppu) >= 7.0:
        perfis.append("premium")

    if frete:
        perfis.append("valoriza_frete_gratis")

    # Perfil principal = primeiro da lista (prioridade de negócio)
    principal = perfis[0] if perfis else "indefinido"
    labels = {
        "salao_atacado": "Salão / atacado (kits grandes, revenda)",
        "consumidor_final": "Consumidor final (unitário ou cor avulsa)",
        "manicure_autonoma": "Manicure autônoma / MEI (kits 3–6)",
        "consumidor_misto": "Comprador misto (kit médio sem perfil claro)",
        "presente": "Presente / mimo",
        "busca_tendencia": "Busca tendência / novidade",
        "price_sensitive": "Sensível a preço",
        "premium": "Disposto a pagar mais (premium)",
        "valoriza_frete_gratis": "Valoriza frete grátis",
        "indefinido": "Indefinido",
    }
    return {
        "perfil_principal": principal,
        "perfil_label": labels.get(principal, principal),
        "perfis_secundarios": perfis[1:],
        "perfis_labels": [labels.get(p, p) for p in perfis],
    }


def _metricas_marca(anuncios: list[dict[str, Any]], marca: str) -> dict[str, Any]:
    alvo = _marca_norm(marca)
    subset = [a for a in anuncios if _marca_norm(a.get("marca") or "") == alvo]
    if not subset:
        return {
            "marca": marca,
            "anuncios": 0,
            "unidades_vendidas": 0,
            "compradores_estimados": 0,
            "share_vendas_pct": 0.0,
            "preco_medio": None,
            "preco_por_unidade_medio": None,
            "frete_gratis_pct": 0.0,
            "perfis_consumidor": [],
            "cores_top": [],
            "kits_top": [],
        }

    vendidos = sum(int(a.get("quantidade_vendida") or 0) for a in subset)
    precos = [float(a.get("preco") or 0) for a in subset if float(a.get("preco") or 0) > 0]
    ppus = [float(a.get("preco_por_unidade") or 0) for a in subset if a.get("preco_por_unidade")]
    frete_pct = round(
        100.0 * sum(1 for a in subset if a.get("frete_gratis")) / len(subset),
        1,
    )

    peso_perfis: Counter[str] = Counter()
    peso_kits: Counter[int] = Counter()
    for an in subset:
        peso = max(1, int(an.get("quantidade_vendida") or 0))
        perfil = inferir_perfil_consumidor(an)
        peso_perfis[perfil["perfil_principal"]] += peso
        if an.get("qtd_kit"):
            peso_kits[int(an["qtd_kit"])] += peso

    cores = tendencia_cores(subset, top_n=5)

    return {
        "marca": marca,
        "anuncios": len(subset),
        "unidades_vendidas": vendidos,
        "compradores_estimados": vendidos,
        "share_vendas_pct": 0.0,
        "preco_medio": round(sum(precos) / len(precos), 2) if precos else None,
        "preco_por_unidade_medio": round(sum(ppus) / len(ppus), 2) if ppus else None,
        "frete_gratis_pct": frete_pct,
        "perfis_consumidor": [
            {"perfil": p, "peso_vendas": w} for p, w in peso_perfis.most_common(5)
        ],
        "cores_top": cores,
        "kits_top": [{"qtd": q, "peso_vendas": w} for q, w in peso_kits.most_common(4)],
        "destaques": sorted(
            subset,
            key=lambda x: int(x.get("quantidade_vendida") or 0),
            reverse=True,
        )[:3],
    }


def _calcular_shares(anita: dict[str, Any], impala: dict[str, Any]) -> None:
    total = int(anita.get("unidades_vendidas") or 0) + int(impala.get("unidades_vendidas") or 0)
    if total <= 0:
        return
    anita["share_vendas_pct"] = round(100.0 * int(anita["unidades_vendidas"]) / total, 1)
    impala["share_vendas_pct"] = round(100.0 * int(impala["unidades_vendidas"]) / total, 1)


def comparar_segmento(
    segmento: dict[str, Any],
    anuncios: list[dict[str, Any]],
) -> dict[str, Any]:
    filtrados = _filtrar_marcas(anuncios)
    anita = _metricas_marca(filtrados, "Anita")
    impala = _metricas_marca(filtrados, "Impala")
    _calcular_shares(anita, impala)

    diff_vendas = int(anita["unidades_vendidas"]) - int(impala["unidades_vendidas"])
    vencedor = "empate"
    if diff_vendas > 0:
        vencedor = "Anita"
    elif diff_vendas < 0:
        vencedor = "Impala"

    diff_share = round(anita["share_vendas_pct"] - impala["share_vendas_pct"], 1)

    preco_anita = anita.get("preco_por_unidade_medio") or anita.get("preco_medio")
    preco_impala = impala.get("preco_por_unidade_medio") or impala.get("preco_medio")
    diff_preco_pct = None
    if preco_anita and preco_impala and preco_impala > 0:
        diff_preco_pct = round((float(preco_anita) - float(preco_impala)) / float(preco_impala) * 100, 1)

    return {
        "id": segmento.get("id"),
        "nome": segmento.get("nome"),
        "termo_busca": segmento.get("termo_busca"),
        "total_anuncios_busca": len(anuncios),
        "total_anita_impala": len(filtrados),
        "anita": anita,
        "impala": impala,
        "vencedor_vendas": vencedor,
        "diferenca_unidades": diff_vendas,
        "diferenca_share_pct": diff_share,
        "diferenca_preco_pct": diff_preco_pct,
        "ok": len(filtrados) > 0,
    }


def consolidar_comparativo(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in resultados if r.get("ok")]
    anita_total = sum(int(r["anita"]["unidades_vendidas"]) for r in ok)
    impala_total = sum(int(r["impala"]["unidades_vendidas"]) for r in ok)
    total_vendas = anita_total + impala_total

    peso_perfis_anita: Counter[str] = Counter()
    peso_perfis_impala: Counter[str] = Counter()
    for r in ok:
        for item in r["anita"].get("perfis_consumidor") or []:
            peso_perfis_anita[item["perfil"]] += int(item["peso_vendas"])
        for item in r["impala"].get("perfis_consumidor") or []:
            peso_perfis_impala[item["perfil"]] += int(item["peso_vendas"])

    share_anita = round(100.0 * anita_total / total_vendas, 1) if total_vendas else 0.0
    share_impala = round(100.0 * impala_total / total_vendas, 1) if total_vendas else 0.0

    vencedor_global = "empate"
    if anita_total > impala_total:
        vencedor_global = "Anita"
    elif impala_total > anita_total:
        vencedor_global = "Impala"

    segmentos_anita = [r for r in ok if r.get("vencedor_vendas") == "Anita"]
    segmentos_impala = [r for r in ok if r.get("vencedor_vendas") == "Impala"]

    return {
        "total_segmentos": len(resultados),
        "segmentos_com_dados": len(ok),
        "anita_unidades_vendidas": anita_total,
        "impala_unidades_vendidas": impala_total,
        "anita_share_pct": share_anita,
        "impala_share_pct": share_impala,
        "vencedor_global": vencedor_global,
        "diferenca_unidades": anita_total - impala_total,
        "segmentos_anita_lider": len(segmentos_anita),
        "segmentos_impala_lider": len(segmentos_impala),
        "perfis_anita_global": [
            {"perfil": p, "peso_vendas": w} for p, w in peso_perfis_anita.most_common(5)
        ],
        "perfis_impala_global": [
            {"perfil": p, "peso_vendas": w} for p, w in peso_perfis_impala.most_common(5)
        ],
        "resultados": ok,
    }


def label_perfil(perfil: str) -> str:
    labels = {
        "salao_atacado": "Salão / atacado",
        "consumidor_final": "Consumidor final",
        "manicure_autonoma": "Manicure autônoma",
        "consumidor_misto": "Comprador misto",
        "price_sensitive": "Sensível a preço",
        "premium": "Premium",
    }
    return labels.get(perfil, perfil)


def gerar_estrategias_vencer(consolidado: dict[str, Any]) -> list[dict[str, Any]]:
    """Plano acionável para reduzir a diferença Anita vs Impala."""
    estrategias: list[dict[str, Any]] = []
    share_anita = float(consolidado.get("anita_share_pct") or 0)
    share_impala = float(consolidado.get("impala_share_pct") or 0)
    diff = int(consolidado.get("diferenca_unidades") or 0)

    if share_impala > share_anita:
        estrategias.append(
            {
                "prioridade": "alta",
                "titulo": "Recuperar share de vendas",
                "texto": (
                    f"Impala lidera com {share_impala:.0f}% vs Anita {share_anita:.0f}% "
                    f"({abs(diff)} unidades de diferença nos segmentos analisados). "
                    "Priorize kits nos formatos onde Impala vence e ajuste preço por unidade."
                ),
            }
        )
    elif share_anita > share_impala:
        estrategias.append(
            {
                "prioridade": "media",
                "titulo": "Consolidar liderança Anita",
                "texto": (
                    f"Anita lidera {share_anita:.0f}% vs Impala {share_impala:.0f}%. "
                    "Mantenha estoque nos kits vencedores e teste aumento gradual de preço onde a margem permitir."
                ),
            }
        )

    perfis_impala = consolidado.get("perfis_impala_global") or []
    perfis_anita = consolidado.get("perfis_anita_global") or []
    if perfis_impala:
        top_impala = perfis_impala[0]["perfil"]
        top_anita = perfis_anita[0]["perfil"] if perfis_anita else None
        if top_impala != top_anita:
            estrategias.append(
                {
                    "prioridade": "alta",
                    "titulo": "Alinhar oferta ao comprador que mais compra Impala",
                    "texto": (
                        f"Impala concentra demanda em *{label_perfil(top_impala)}*. "
                        f"Anita hoje puxa mais *{label_perfil(top_anita or 'outro perfil')}*. "
                        "Crie/destaque kits no formato e título que falam com o perfil líder da concorrência."
                    ),
                }
            )

    for r in consolidado.get("resultados") or []:
        if r.get("vencedor_vendas") != "Impala":
            continue
        seg = r.get("nome") or r.get("id")
        impala = r.get("impala") or {}
        anita = r.get("anita") or {}
        kits = impala.get("kits_top") or []
        kit_txt = f"kit {kits[0]['qtd']}" if kits else "formato líder"
        preco_imp = impala.get("preco_por_unidade_medio") or impala.get("preco_medio")
        preco_ani = anita.get("preco_por_unidade_medio") or anita.get("preco_medio")
        if preco_imp and preco_ani and float(preco_ani) > float(preco_imp):
            estrategias.append(
                {
                    "prioridade": "alta",
                    "titulo": f"Preço por unidade — {seg}",
                    "texto": (
                        f"Impala vence em *{seg}* ({kit_txt}). "
                        f"Preço/un Anita {_fmt_preco(preco_ani)} vs Impala {_fmt_preco(preco_imp)}. "
                        "Teste preço 2–5% abaixo do líder com frete grátis ou destaque de cores do kit."
                    ),
                }
            )
            break

    cores_impala: Counter[str] = Counter()
    for r in consolidado.get("resultados") or []:
        for c in (r.get("impala") or {}).get("cores_top") or []:
            cores_impala[c["cor"]] += int(c["peso_vendas"])
    if cores_impala:
        top_cores = ", ".join(c for c, _ in cores_impala.most_common(3))
        estrategias.append(
            {
                "prioridade": "media",
                "titulo": "Cores que puxam demanda Impala",
                "texto": (
                    f"Incluir ou destacar no título/fotos: *{top_cores}*. "
                    "Monte kits sortidos espelhando a combinação mais vendida no mercado."
                ),
            }
        )

    if consolidado.get("resultados"):
        estrategias.append(
            {
                "prioridade": "media",
                "titulo": "Conversão nos seus anúncios",
                "texto": (
                    "Com item_id real no ML, o agente cruza visitas × vendas 7d (sinais_comprador). "
                    "Enquanto isso, `quantidade_vendida` da busca indica volume de compra no segmento."
                ),
            }
        )

    if not estrategias:
        estrategias.append(
            {
                "prioridade": "baixa",
                "titulo": "Dados insuficientes",
                "texto": "Poucos anúncios Anita/Impala nos termos buscados — revise termos ou credenciais ML.",
            }
        )

    return estrategias[:8]


def _fmt_preco(valor: Any) -> str:
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def enriquecer_com_sinais_proprios(
    consolidado: dict[str, Any],
    *,
    sinais_anita: list[dict[str, Any]] | None = None,
    sinais_impala: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Cruza busca pública com sinais dos seus anúncios (visitas/vendas 7d quando disponível)."""
    out: dict[str, Any] = {"anita": [], "impala": []}
    for marca, lista in (("anita", sinais_anita or []), ("impala", sinais_impala or [])):
        for s in lista:
            visitas = int(s.get("visitas_7d") or 0)
            vendas = int(s.get("unidades_vendidas_7d") or 0)
            conv = round(vendas / visitas * 100, 2) if visitas > 0 else None
            out[marca].append(
                {
                    "sku": s.get("sku"),
                    "termo": s.get("termo_busca"),
                    "visitas_7d": visitas,
                    "unidades_vendidas_7d": vendas,
                    "conversao_pct": conv,
                    "preco_listado": s.get("preco_listado"),
                    "preco_concorrente_vivo": s.get("preco_concorrente_vivo"),
                }
            )
    consolidado["sinais_proprios"] = out
    return consolidado
