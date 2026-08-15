"""
integracoes/esmaltes/kits_compativeis_manicures.py
Kits Impala compatíveis com a demanda da manicure: condição, índice de
compra, economia vs avulso, padrão Impala (cores/acabamento/qtd).

Não publica anúncio. CNPJ 52.668.583/0001-27.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import MARGEM_MINIMA, ROOT, TAXA_CANAL_PADRAO_PCT
from core.datadog_metrics import gauge, incrementar
from integracoes.esmaltes.analise_anita import _normalizar, detectar_marca
from integracoes.esmaltes.analise_mercado import classificar_anuncio
from integracoes.esmaltes.metricas_batalha_impala import _qtd_nosso_sku
from integracoes.esmaltes.metricas_catalogo_impala import kit_tag, margem_real_pct

logger = logging.getLogger("kits_compativeis_manicures")

SNAPSHOT_PATH = ROOT / "logs" / "kits_compativeis_manicures_ultima.json"
# Avulso típico Impala no ML (a manicure compara kit vs N frascos unitários).
_PRECO_AVULSO_REF = 12.0


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _i(val: Any, default: int = 0) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def perfil_manicure(qtd: int) -> str:
    if qtd >= 10:
        return "salao_estoque"
    if qtd >= 5:
        return "salao_giro"
    if qtd >= 3:
        return "manicure_autonoma"
    return "unitario"


def cores_do_produto(produto: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for c in produto.get("cores") or []:
        if isinstance(c, dict):
            nome = str(c.get("nome") or "").strip()
        elif c:
            nome = str(c).strip()
        else:
            continue
        if nome and nome.lower() not in ("none", "null", "-", "n/d"):
            out.append(nome)
    return out


def economia_kit_vs_unitario(
    qtd: int,
    preco_kit: float,
    preco_unitario_ref: float,
) -> dict[str, float]:
    """Quanto a manicure economiza comprando o kit em vez de N unidades avulsas."""
    qtd = max(0, int(qtd or 0))
    avulso = qtd * max(0.0, float(preco_unitario_ref or 0))
    eco = round(avulso - float(preco_kit or 0), 2)
    pct = round(100.0 * eco / avulso, 1) if avulso > 0 else 0.0
    ppu = round(float(preco_kit or 0) / qtd, 2) if qtd else 0.0
    return {
        "preco_kit": round(float(preco_kit or 0), 2),
        "preco_avulso_ref": round(float(preco_unitario_ref or 0), 2),
        "custo_n_avulsos": round(avulso, 2),
        "economia_brl": eco,
        "economia_pct": pct,
        "preco_por_unidade": ppu,
    }


def indice_compra_impala(
    produto: dict[str, Any],
    compativeis_ml: list[dict[str, Any]] | None = None,
) -> int:
    """vd/dia do catálogo Impala + vendas proxy dos kits ML do mesmo tamanho."""
    vd = _f(produto.get("vd_dia_ml_ref"))
    alav = _f(produto.get("score_alavancagem"))
    vendidos = sum(_i(a.get("quantidade_vendida") or a.get("vendidos")) for a in (compativeis_ml or []))
    return int(vd * 10 + alav / 5.0 + vendidos)


def _preco_unitario_mercado(anuncios: list[dict[str, Any]]) -> float:
    precos = []
    for a in anuncios:
        tipo = str(a.get("tipo_anuncio") or "")
        qtd = _i(a.get("qtd_kit"))
        preco = _f(a.get("preco"))
        if tipo == "unitario" or qtd == 1:
            if preco > 0:
                precos.append(preco)
        elif qtd >= 2 and preco > 0:
            ppu = a.get("preco_por_unidade")
            if ppu:
                precos.append(_f(ppu))
    if not precos:
        return _PRECO_AVULSO_REF
    precos.sort()
    return round(precos[len(precos) // 2], 2)


def _overlap_cores(nossas: list[str], deles: list[str]) -> int:
    nset = {_normalizar(x) for x in nossas if x}
    dset = {_normalizar(x) for x in deles if x}
    nset.discard("")
    dset.discard("")
    return len(nset & dset)


def ranquear_compativeis_ml(
    produto: dict[str, Any],
    anuncios: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Anúncios ML do mesmo tamanho de kit, preferindo Impala e overlap de cor."""
    qtd = _qtd_nosso_sku(produto) or 0
    if qtd < 2:
        return []
    nossas = cores_do_produto(produto)
    ranked: list[dict[str, Any]] = []
    for a in anuncios:
        aq = _i(a.get("qtd_kit"))
        if aq != qtd:
            continue
        marca = str(a.get("marca") or detectar_marca(str(a.get("titulo") or "")))
        cores_ml = [str(c) for c in (a.get("cores_detectadas") or [])]
        overlap = _overlap_cores(nossas, cores_ml)
        impala = _normalizar(marca) == "impala"
        if not impala and overlap == 0 and "impala" not in _normalizar(str(a.get("titulo") or "")):
            # mesmo tamanho ainda é referente de condição para a manicure
            score = 8 + min(20, _i(a.get("quantidade_vendida")) // 20)
        else:
            score = 20 + (30 if impala else 0) + overlap * 12 + min(40, _i(a.get("quantidade_vendida")) // 10)
        ranked.append(
            {
                "titulo": a.get("titulo"),
                "marca": marca,
                "qtd_kit": aq,
                "preco": _f(a.get("preco")),
                "quantidade_vendida": _i(a.get("quantidade_vendida")),
                "cores": cores_ml[:4],
                "impala": impala,
                "overlap_cores": overlap,
                "score_compat": score,
            }
        )
    ranked.sort(key=lambda x: (x["score_compat"], x["quantidade_vendida"]), reverse=True)
    return ranked[:6]


def avaliar_oferta_impala(
    produto: dict[str, Any],
    *,
    anuncios: list[dict[str, Any]] | None = None,
    preco_unitario_ref: float | None = None,
    piso_margem_pct: float | None = None,
) -> dict[str, Any] | None:
    sku = str(produto.get("sku") or "").strip().upper()
    if not sku.startswith("IMP-"):
        return None
    qtd = _qtd_nosso_sku(produto) or 0
    if qtd < 2:
        return None
    piso = float(piso_margem_pct if piso_margem_pct is not None else MARGEM_MINIMA)
    preco = _f((produto.get("canais") or {}).get("mercadolivre", {}).get("preco") or produto.get("preco"))
    uref = float(preco_unitario_ref if preco_unitario_ref is not None else _PRECO_AVULSO_REF)
    eco = economia_kit_vs_unitario(qtd, preco, uref)
    margem = margem_real_pct(produto)
    if margem is None:
        margem = _f(produto.get("margem_trabalho_pct")) or None
    comp = ranquear_compativeis_ml(produto, anuncios or [])
    indice = indice_compra_impala(produto, comp)
    perfil = perfil_manicure(qtd)
    padrao = bool(cores_do_produto(produto)) and qtd >= 3
    entrada_carmed = sku == "IMP-MIMO-003"
    # MIMO perde em R$/frasco (Carmed no custo). Condição da manicure = extra, não economia.
    condicao = (
        qtd >= 3
        and preco > 0
        and (margem is None or float(margem) >= piso)
        and padrao
        and (eco["economia_pct"] > 0 or entrada_carmed)
    )
    return {
        "sku": sku,
        "kit_tag": kit_tag(sku),
        "nome": produto.get("nome"),
        "qtd_kit": qtd,
        "perfil_manicure": perfil,
        "preco": preco,
        "margem_pct": margem,
        "vd_dia_ml_ref": _f(produto.get("vd_dia_ml_ref")),
        "score_alavancagem": _f(produto.get("score_alavancagem")),
        "indice_compra": indice,
        "economia": eco,
        "motivo_condicao": "entrada_carmed" if entrada_carmed and condicao else (
            "economia" if condicao else "sem_condicao"
        ),
        "padrao_impala": padrao,
        "condicao_ok": condicao,
        "atende_clientes": perfil in ("manicure_autonoma", "salao_giro", "salao_estoque"),
        "compativeis_ml": comp,
        "taxa_canal_pct": _f(
            ((produto.get("canais") or {}).get("mercadolivre") or {}).get("taxa_canal_pct"),
            TAXA_CANAL_PADRAO_PCT,
        ),
    }


def emitir_metricas_kits_manicure(ofertas: list[dict[str, Any]]) -> None:
    boas = [o for o in ofertas if o.get("condicao_ok")]
    gauge("esmaltes.kit_manicure.total", float(len(ofertas)))
    gauge("esmaltes.kit_manicure.condicao_ok", float(len(boas)))
    ecos = [float((o.get("economia") or {}).get("economia_pct") or 0) for o in boas]
    gauge("esmaltes.kit_manicure.economia_media_pct", float(sum(ecos) / len(ecos)) if ecos else 0.0)
    entrada = next(
        (o for o in ofertas if str(o.get("sku") or "").upper() == "IMP-MIMO-003"),
        None,
    )
    gauge(
        "esmaltes.kit_manicure.entrada_ok",
        1.0 if entrada and entrada.get("condicao_ok") else 0.0,
    )
    for o in ofertas[:10]:
        tags = [str(o.get("kit_tag") or "kit:x"), f"perfil:{o.get('perfil_manicure') or 'x'}"]
        gauge("esmaltes.kit_manicure.indice_compra", float(o.get("indice_compra") or 0), tags=tags)
        gauge(
            "esmaltes.kit_manicure.economia_pct",
            float((o.get("economia") or {}).get("economia_pct") or 0),
            tags=tags,
        )
    incrementar("esmaltes.kit_manicure.rodadas")
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    try:
        from integracoes.datadog.oscilacao_decisao import registrar_e_avaliar

        registrar_e_avaliar({"kit_condicao_ok": float(len(boas))})
    except Exception as exc:
        logger.info("oscilação kits: %s", exc)


def formatar_secao_manicure(ofertas: list[dict[str, Any]] | None) -> list[str]:
    rows = [o for o in (ofertas or []) if isinstance(o, dict)]
    if not rows:
        return []
    linhas = ["", "*Kits Impala para manicures (economia × padrão)*"]
    for o in rows[:6]:
        eco = o.get("economia") or {}
        flag = "condição" if o.get("condicao_ok") else "montar"
        linhas.append(
            f"• `{o.get('sku')}` kit {o.get('qtd_kit')} ({o.get('perfil_manicure')}) — "
            f"{flag} | índice `{o.get('indice_compra')}` | "
            f"economia `{eco.get('economia_pct')}%` "
            f"(R$ {float(eco.get('economia_brl') or 0):.2f}) | "
            f"R$ {float(o.get('preco') or 0):.2f}"
        )
        top_ml = (o.get("compativeis_ml") or [{}])[0]
        if top_ml.get("titulo"):
            linhas.append(
                f"  referente ML: _{str(top_ml.get('titulo'))[:56]}_ "
                f"({top_ml.get('marca')} · {top_ml.get('quantidade_vendida')} vend.)"
            )
    return linhas


def montar_ofertas_manicure(
    *,
    produtos: list[dict[str, Any]] | None = None,
    anuncios: list[dict[str, Any]] | None = None,
    piso_margem_pct: float | None = None,
) -> dict[str, Any]:
    """Ranking de kits Impala para a manicure atender clientes com economia."""
    try:
        if produtos is None:
            from core.catalogo_produtos import carregar_produtos_catalogo

            produtos = carregar_produtos_catalogo()
        if anuncios is None:
            from integracoes.esmaltes.cruzamento_tendencias_mercado import anuncios_de_snapshots

            anuncios = anuncios_de_snapshots()
        classificados = [classificar_anuncio(a) if "qtd_kit" not in a else a for a in (anuncios or [])]
        uref_ml = _preco_unitario_mercado(classificados)
        # Piso da alternativa da manicure: repor N frascos avulsos Impala (~R$12),
        # não o unitário mais barato dumpado no ML.
        uref = max(uref_ml, _PRECO_AVULSO_REF)
        ofertas: list[dict[str, Any]] = []
        for p in produtos or []:
            if not isinstance(p, dict):
                continue
            row = avaliar_oferta_impala(
                p,
                anuncios=classificados,
                preco_unitario_ref=uref,
                piso_margem_pct=piso_margem_pct,
            )
            if row:
                ofertas.append(row)
        ofertas.sort(
            key=lambda o: (
                bool(o.get("condicao_ok")),
                int(o.get("indice_compra") or 0),
                float((o.get("economia") or {}).get("economia_pct") or 0),
            ),
            reverse=True,
        )
        boas = [o for o in ofertas if o.get("condicao_ok")]
        emitir_metricas_kits_manicure(ofertas)
        out = {
            "ok": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "preco_unitario_ref": uref,
            "preco_unitario_ml": uref_ml,
            "piso_margem_pct": float(piso_margem_pct if piso_margem_pct is not None else MARGEM_MINIMA),
            "ofertas": ofertas[:12],
            "ofertas_condicao": boas[:8],
            "total": len(ofertas),
            "condicao_n": len(boas),
        }
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            try:
                escrever_json_atomico(SNAPSHOT_PATH, out)
            except Exception:
                pass
        return out
    except Exception as exc:
        logger.warning("montar_ofertas_manicure: %s", exc)
        incrementar("esmaltes.kit_manicure.erro")
        return {"ok": False, "erro": str(exc), "ofertas": [], "ofertas_condicao": []}
