"""
integracoes/filamentos/cruzamento_alibaba.py
Cruza preços/cores do ML com fornecedores Alibaba do catálogo de importação.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from integracoes.filamentos.analise_filamentos_ml import cor_para_termo_en

logger = logging.getLogger("filamentos_cruzamento_alibaba")


def _eh_produto_filamento(produto: dict[str, Any]) -> bool:
    blob = " ".join(
        str(produto.get(k) or "")
        for k in ("id", "nome", "material", "termo_busca", "termo_busca_pt", "termo_marketplace")
    ).lower()
    return any(
        x in blob
        for x in (
            "filamento",
            "filament",
            "pla",
            "petg",
            "tpu",
            "abs",
            "impressora 3d",
            "3d printer",
        )
    )


def carregar_produtos_filamento_alibaba() -> list[dict[str, Any]]:
    from core.atomic_io import ler_json
    from core.config import ALIBABA_IMPORTACAO_CATALOGO, ROOT

    caminho = ROOT / ALIBABA_IMPORTACAO_CATALOGO
    data = ler_json(caminho, default=[])
    if not isinstance(data, list):
        return []
    return [p for p in data if isinstance(p, dict) and p.get("ativo") and _eh_produto_filamento(p)]


def _material_compatível(mat_ml: str, produto: dict[str, Any]) -> bool:
    mat_p = str(produto.get("material") or "").upper()
    mat_ml_u = (mat_ml or "").upper()
    if not mat_p or not mat_ml_u:
        return True
    if mat_p in mat_ml_u or mat_ml_u.startswith(mat_p) or mat_p.startswith(mat_ml_u.split()[0]):
        return True
    # PLA+ / Silk batem com produto PLA do catálogo
    if mat_p == "PLA" and mat_ml_u.startswith("PLA"):
        return True
    return False


def _precos_ml_do_consolidado(
    consolidado: dict[str, Any],
    resultados: list[dict[str, Any]],
    produto: dict[str, Any],
) -> dict[str, Any]:
    """Usa a varredura ML já feita (não refaz busca) alinhada ao material do catálogo."""
    por_termo = [
        t
        for t in (consolidado.get("por_termo") or [])
        if _material_compatível(str(t.get("material") or ""), produto)
    ]
    if por_termo:
        precos = [float(t.get("preco_medio") or 0) for t in por_termo if float(t.get("preco_medio") or 0) > 0]
        pmins = [float(t.get("preco_min") or 0) for t in por_termo if float(t.get("preco_min") or 0) > 0]
        pmaxs = [float(t.get("preco_max") or 0) for t in por_termo if float(t.get("preco_max") or 0) > 0]
        return {
            "ok": bool(precos),
            "termo": produto.get("termo_marketplace") or "",
            "marketplace": "mercadolivre",
            "fonte": "varredura_filamentos_ml",
            "preco_min_brl": round(min(pmins), 2) if pmins else None,
            "preco_medio_brl": round(sum(precos) / len(precos), 2) if precos else None,
            "preco_max_brl": round(max(pmaxs), 2) if pmaxs else None,
            "total_anuncios": sum(int(t.get("total") or 0) for t in por_termo),
        }
    # fallback: preço global do consolidado
    medio = consolidado.get("preco_medio")
    return {
        "ok": bool(medio),
        "termo": produto.get("termo_marketplace") or "",
        "marketplace": "mercadolivre",
        "fonte": "consolidado_global",
        "preco_min_brl": consolidado.get("preco_min"),
        "preco_medio_brl": medio,
        "preco_max_brl": consolidado.get("preco_max"),
        "total_anuncios": consolidado.get("total_filamentos_unicos") or 0,
    }


def _produto_com_cor(produto: dict[str, Any], cor: str | None) -> dict[str, Any]:
    if not cor or cor == "Indefinida":
        return produto
    en = cor_para_termo_en(cor)
    clone = dict(produto)
    base_en = str(produto.get("termo_busca") or "").strip()
    base_pt = str(produto.get("termo_busca_pt") or "").strip()
    if base_en:
        clone["termo_busca"] = f"{base_en} {en}".strip()
    if base_pt:
        clone["termo_busca_pt"] = f"{base_pt} {cor.lower()}".strip()
    clone["cor_foco"] = cor
    return clone


def cruzar_filamentos_ml_alibaba(
    consolidado: dict[str, Any],
    resultados: list[dict[str, Any]],
    *,
    max_cores: int = 3,
    max_oportunidades: int = 3,
    pausa_seg: float = 1.0,
) -> dict[str, Any]:
    """
    Para cada produto filamento do catálogo Alibaba:
    - usa preços ML já coletados
    - busca ofertas Alibaba (base + top cores do ML)
    - calcula margem landed vs preço médio ML
    """
    from integracoes.alibaba.busca import buscar_oportunidades_detalhado
    from integracoes.cambio.cotacao_usd import cotacao_confiavel_para_margem, obter_cotacao_usd
    from integracoes.importacao.analise_margem import analisar_produto_catalogo

    produtos = carregar_produtos_filamento_alibaba()
    cores_top = [
        c
        for c in (consolidado.get("ranking_cores") or [])
        if str(c.get("cor") or "") not in ("", "Indefinida")
    ][: max(0, max_cores)]

    cotacao = obter_cotacao_usd()
    cambio = float(cotacao.get("usd_brl") or 0)
    confiavel = cotacao_confiavel_para_margem(cotacao)
    motivo_cambio = (
        "ok"
        if confiavel
        else str(cotacao.get("fonte") or cotacao.get("erro") or "cotação inválida/fallback")
    )

    cruzamentos: list[dict[str, Any]] = []
    if not produtos:
        return {
            "ok": True,
            "produtos_catalogo": 0,
            "cruzamentos": [],
            "cores_usadas": [c.get("cor") for c in cores_top],
            "cambio_usd_brl": cambio,
            "cambio_confiavel": confiavel,
            "motivo": "sem produto filamento ativo no catálogo Alibaba",
        }

    if not confiavel or cambio <= 0:
        logger.warning("Cruzamento filamentos: câmbio não confiável (%s)", motivo_cambio)
        return {
            "ok": False,
            "motivo": f"cambio: {motivo_cambio}",
            "produtos_catalogo": len(produtos),
            "cruzamentos": [],
            "cores_usadas": [c.get("cor") for c in cores_top],
            "cambio_usd_brl": cambio,
            "cambio_confiavel": False,
        }

    for i, produto in enumerate(produtos):
        precos_ml = _precos_ml_do_consolidado(consolidado, resultados, produto)
        # Busca base (sem cor) + uma busca por cor top
        variantes = [None] + [str(c.get("cor")) for c in cores_top]
        melhor_analise = None
        todas_ops: list[dict[str, Any]] = []
        por_cor: list[dict[str, Any]] = []
        coleta_agg: dict[str, Any] = {
            "bloqueado": False,
            "motivo": None,
            "direto": 0,
            "ddg": 0,
            "candidatos": 0,
        }

        for cor in variantes:
            prod_q = _produto_com_cor(produto, cor)
            try:
                busca = buscar_oportunidades_detalhado(prod_q, pausa_seg=pausa_seg)
                ops = busca.get("oportunidades") or []
                col = busca.get("coleta") or {}
                coleta_agg["direto"] += int(col.get("direto") or 0)
                coleta_agg["ddg"] += int(col.get("ddg") or 0)
                coleta_agg["candidatos"] += int(col.get("candidatos") or 0)
                if col.get("bloqueado") and not ops:
                    coleta_agg["bloqueado"] = True
                    coleta_agg["motivo"] = coleta_agg.get("motivo") or col.get("motivo")
            except Exception as exc:
                logger.warning("Alibaba filamento falhou produto=%s cor=%s: %s", produto.get("id"), cor, exc)
                ops = []
            todas_ops.extend(ops)
            # Reusa análise com preços ML da varredura (injeta no analisar via override)
            analise = analisar_produto_catalogo(
                produto,
                ops,
                cambio_usd_brl=cambio,
                max_oportunidades=max_oportunidades,
                precos_marketplace=precos_ml,
            )
            por_cor.append(
                {
                    "cor": cor or "geral",
                    "total_oportunidades": len(ops),
                    "lucrativas": analise.get("lucrativas") or 0,
                    "melhor": analise.get("melhor_analise"),
                }
            )
            cand = analise.get("melhor_analise")
            if cand and cand.get("ok"):
                if melhor_analise is None:
                    melhor_analise = {**cand, "cor_foco": cor or "geral"}
                else:
                    m_novo = (cand.get("margem_melhor") or {}).get("margem_brl") or 0
                    m_old = (melhor_analise.get("margem_melhor") or {}).get("margem_brl") or 0
                    if m_novo > m_old:
                        melhor_analise = {**cand, "cor_foco": cor or "geral"}

            if pausa_seg > 0:
                time.sleep(pausa_seg)

        # Dedup oportunidades por url
        vistos: set[str] = set()
        ops_unicas = []
        for op in todas_ops:
            u = str(op.get("url") or op.get("hash") or "")
            if not u or u in vistos:
                continue
            vistos.add(u)
            ops_unicas.append(op)

        if ops_unicas:
            coleta_agg["bloqueado"] = False
            coleta_agg["motivo"] = None

        cruzamentos.append(
            {
                "id": produto.get("id"),
                "produto": produto.get("nome"),
                "material": produto.get("material"),
                "termo_marketplace": produto.get("termo_marketplace"),
                "precos_ml": precos_ml,
                "total_oportunidades_alibaba": len(ops_unicas),
                "coleta_alibaba": coleta_agg,
                "por_cor": por_cor,
                "melhor_analise": melhor_analise,
                "lucrativa": bool(melhor_analise and melhor_analise.get("lucro_razoavel")),
            }
        )
        if i < len(produtos) - 1 and pausa_seg > 0:
            time.sleep(pausa_seg)

    lucrativos = [c for c in cruzamentos if c.get("lucrativa")]
    alibaba_bloqueado = any(
        (c.get("coleta_alibaba") or {}).get("bloqueado") for c in cruzamentos
    )
    return {
        "ok": True,
        "produtos_catalogo": len(produtos),
        "cruzamentos": cruzamentos,
        "lucrativos": len(lucrativos),
        "cores_usadas": [c.get("cor") for c in cores_top],
        "cambio_usd_brl": cambio,
        "cambio_confiavel": True,
        "alibaba_bloqueado": alibaba_bloqueado,
    }


def formatar_secao_cruzamento(cruzamento: dict[str, Any], *, fmt_brl) -> list[str]:
    """Linhas Markdown para o Telegram — comparação ML × Alibaba por material."""
    linhas = ["", "🔗 *Comparativo ML × Alibaba (mesmo tipo)*"]
    if not cruzamento.get("ok"):
        linhas.append(f"_Cruzamento indisponível: {cruzamento.get('motivo') or 'erro'}_")
        return linhas

    if cruzamento.get("alibaba_bloqueado"):
        linhas.append(
            "🚫 _Alibaba coleta bloqueada (captcha/anti-bot) — zeros ≠ sem oferta no mercado._"
        )

    cores = cruzamento.get("cores_usadas") or []
    if cores:
        linhas.append("Cores ML usadas na busca Alibaba: " + ", ".join(str(c) for c in cores))
    cambio = cruzamento.get("cambio_usd_brl")
    if cambio:
        linhas.append(f"Câmbio USD/BRL: {float(cambio):.2f}".replace(".", ","))

    itens = cruzamento.get("cruzamentos") or []
    if not itens:
        linhas.append("_Nenhum produto filamento no catálogo Alibaba para cruzar._")
        return linhas

    # Ordem preferencial TPU / PLA / PETG / ABS
    ordem = {"TPU": 0, "PLA": 1, "PETG": 2, "ABS": 3}
    itens_ord = sorted(
        itens,
        key=lambda x: ordem.get(str(x.get("material") or "").upper(), 99),
    )

    for item in itens_ord:
        ml = item.get("precos_ml") or {}
        mat = str(item.get("material") or "?").upper()
        coleta = item.get("coleta_alibaba") or {}
        linhas.append("")
        linhas.append(f"*{mat}* — {item.get('produto', item.get('id'))}")
        linhas.append(
            f"  ML: {fmt_brl(ml.get('preco_min_brl'))}–{fmt_brl(ml.get('preco_max_brl'))} "
            f"(méd {fmt_brl(ml.get('preco_medio_brl'))}) | "
            f"{ml.get('total_anuncios') or 0} anúncio(s)"
        )
        if coleta.get("bloqueado") and int(item.get("total_oportunidades_alibaba") or 0) == 0:
            linhas.append(
                f"  Alibaba: bloqueado ({coleta.get('motivo') or 'anti-bot'}) — sem cotação nesta rodada"
            )
        else:
            linhas.append(
                f"  Alibaba: {item.get('total_oportunidades_alibaba', 0)} oferta(s) encontradas"
            )
        melhor = item.get("melhor_analise") or {}
        if melhor.get("ok"):
            margem = melhor.get("margem_melhor") or {}
            custo = None
            cen = melhor.get("cenarios_frete") or {}
            modo = melhor.get("melhor_frete")
            if modo and isinstance(cen.get(modo), dict):
                custo = cen[modo].get("custo_landed_brl")
            fob = melhor.get("preco_usd")
            fob_brl = None
            try:
                if fob is not None and cambio:
                    fob_brl = float(fob) * float(cambio)
            except (TypeError, ValueError):
                fob_brl = None
            flag = "✅ margem ok" if item.get("lucrativa") else "⚠️ margem justa/apertada"
            linhas.append(
                f"  → melhor FOB US$ {fob}"
                + (f" (~{fmt_brl(fob_brl)})" if fob_brl else "")
                + f" | landed {fmt_brl(custo)} | "
                f"vs ML méd: margem {fmt_brl(margem.get('margem_brl'))} "
                f"({margem.get('margem_pct') or 'n/d'}%) {flag}"
            )
            if melhor.get("cor_foco"):
                linhas.append(f"  · cor foco: {melhor.get('cor_foco')}")
        elif int(item.get("total_oportunidades_alibaba") or 0) == 0:
            linhas.append("  → _sem oferta Alibaba nesta rodada (ajuste termo/MOQ)_")
        for pc in (item.get("por_cor") or [])[:4]:
            if int(pc.get("total_oportunidades") or 0) <= 0:
                continue
            linhas.append(
                f"  · {pc.get('cor')}: {pc.get('total_oportunidades')} oferta(s), "
                f"{pc.get('lucrativas', 0)} lucrativa(s)"
            )
    return linhas
