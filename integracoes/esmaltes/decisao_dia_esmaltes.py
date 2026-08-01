"""
integracoes/esmaltes/decisao_dia_esmaltes.py
Um veredito por dia: FAZER · NÃO FAZER · CUSTO DE NÃO FAZER.

Junta crescimento, ecossistema, comparativo Anita e SKUs de guerra.
Menos opções = decisão melhor.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.atomic_io import ler_json
from core.catalogo_produtos import carregar_produtos_catalogo
from core.config import ROOT, TAXA_CANAL_PADRAO_PCT
from integracoes.esmaltes.crescimento_esmaltes import (
    _mlb_valido,
    eh_kit_catalogo,
    montar_relatorio,
)

GUERRA_PATH_DEFAULT = "catalogo/skus_guerra_impala.json"
ECOSSISTEMA_PATH = ROOT / "logs" / "ecossistema_esmaltes_ultima.json"
COMPARATIVO_PATH = ROOT / "logs" / "anita_impala_comparativo_ultima.json"
ESTRATEGIA_PATH = ROOT / "logs" / "relatorio_estrategia_ml_ultima.json"
HISTORICO_KPI_PATH = ROOT / "logs" / "decisao_dia_esmaltes_kpis.json"


def carregar_skus_guerra(caminho: str | None = None) -> list[dict[str, Any]]:
    path = ROOT / (caminho or GUERRA_PATH_DEFAULT)
    data = ler_json(path, default=[])
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict) and str(x.get("sku") or "").strip()]


def _produto_por_sku(produtos: list[dict[str, Any]], sku: str) -> dict[str, Any] | None:
    alvo = sku.strip().upper()
    for p in produtos:
        if str(p.get("sku") or "").strip().upper() == alvo:
            return p
    return None


def _item_id(produto: dict[str, Any] | None) -> str:
    if not produto:
        return ""
    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    return str(ml.get("item_id") or "").strip().upper().replace("-", "")


def avaliar_skus_guerra(
    *,
    guerra: list[dict[str, Any]],
    produtos: list[dict[str, Any]],
    margem_piso_pct: float,
) -> list[dict[str, Any]]:
    """Status de cada SKU de guerra: MLB, margem estimada, pode impulsionar."""
    out: list[dict[str, Any]] = []
    for g in guerra:
        sku = str(g.get("sku") or "").strip()
        p = _produto_por_sku(produtos, sku)
        ml = ((p or {}).get("canais") or {}).get("mercadolivre") or {}
        iid = _item_id(p)
        mlb_ok = _mlb_valido(iid)
        preco = float(ml.get("preco") or (p or {}).get("preco") or 0)
        custo = float((p or {}).get("custo_total") or (p or {}).get("custo") or 0)
        taxa = float(ml.get("taxa_canal_pct") or TAXA_CANAL_PADRAO_PCT)
        margem = None
        if preco > 0 and custo > 0:
            liquida = preco * (1 - taxa / 100.0)
            margem = round(100.0 * (liquida - custo) / preco, 1)
        margem_ok = margem is not None and margem >= margem_piso_pct
        diferencial = str(g.get("diferencial_obrigatorio") or "").strip()
        pode_impulsionar = bool(mlb_ok and margem_ok and diferencial)
        bloqueios: list[str] = []
        if not mlb_ok:
            bloqueios.append("sem_mlb")
        if margem is None:
            bloqueios.append("sem_custo_ou_preco")
        elif not margem_ok:
            bloqueios.append(f"margem_{margem}%_abaixo_piso_{margem_piso_pct}%")
        if not diferencial:
            bloqueios.append("sem_diferencial")
        if (p or {}).get("estoque_total") == 0 and ml.get("estoque") == 0:
            bloqueios.append("estoque_zero")

        out.append(
            {
                "sku": sku,
                "papel": g.get("papel"),
                "nome": g.get("nome") or (p or {}).get("nome"),
                "diferencial": diferencial,
                "item_id": iid or "MLB_PREENCHER",
                "mlb_ok": mlb_ok,
                "preco": preco,
                "custo": custo,
                "margem_estimada_pct": margem,
                "margem_ok": margem_ok,
                "pode_impulsionar": pode_impulsionar,
                "bloqueios": bloqueios,
            }
        )
    return out


def _acao_fazer(
    *,
    guerra_status: list[dict[str, Any]],
    crescimento: dict[str, Any],
    eco_top: list[dict[str, Any]],
) -> dict[str, Any]:
    """Escolhe UMA ação do dia (prioridade fixa)."""
    # 1) Desbloquear SKU de guerra sem MLB
    for s in guerra_status:
        if not s.get("mlb_ok"):
            return {
                "veredito": "fazer",
                "codigo": "preencher_mlb_guerra",
                "titulo": f"Publicar/preencher MLB de `{s.get('sku')}` ({s.get('papel')})",
                "detalhe": (
                    f"{s.get('nome')} — diferencial: {s.get('diferencial')}. "
                    "Sem MLB não há ads nem promoção."
                ),
                "sku": s.get("sku"),
            }
    # 2) WhatsApp
    canais = crescimento.get("canais") or {}
    if not canais.get("whatsapp_ok"):
        return {
            "veredito": "fazer",
            "codigo": "ligar_whatsapp_manicures",
            "titulo": "Ligar WhatsApp grupo manicures",
            "detalhe": "WHATSAPP_* + GRUPO — canal de recompra B2B.",
            "sku": "",
        }
    # 3) Impulsionar primeiro SKU guerra liberado
    for s in guerra_status:
        if s.get("pode_impulsionar"):
            return {
                "veredito": "fazer",
                "codigo": "impulsionar_sku_guerra",
                "titulo": f"Impulsionar só `{s.get('sku')}` com combo anexo",
                "detalhe": (
                    f"{s.get('nome')} | margem ~{s.get('margem_estimada_pct')}% | "
                    f"diferencial: {s.get('diferencial')}"
                ),
                "sku": s.get("sku"),
            }
    # 4) Top 7d ecossistema
    if eco_top:
        a = eco_top[0]
        return {
            "veredito": "fazer",
            "codigo": "acao_ecossistema",
            "titulo": str(a.get("titulo") or "Ação ecossistema 7d"),
            "detalhe": str(a.get("detalhe") or ""),
            "sku": "",
        }
    # 5) Checklist crescimento
    check = crescimento.get("checklist") or []
    if check:
        c = check[0]
        return {
            "veredito": "fazer",
            "codigo": str(c.get("id") or "checklist"),
            "titulo": str(c.get("titulo") or "Resolver checklist"),
            "detalhe": str(c.get("detalhe") or ""),
            "sku": "",
        }
    return {
        "veredito": "fazer",
        "codigo": "manter_curso",
        "titulo": "Manter foco nos 3 SKUs de guerra + combo anexo",
        "detalhe": "Sem gap crítico — reforçar promoção do kit com melhor margem.",
        "sku": "",
    }


def _acao_nao_fazer(
    *,
    guerra_status: list[dict[str, Any]],
    guerra_skus: set[str],
    produtos: list[dict[str, Any]],
) -> dict[str, Any]:
    bloqueados = [s for s in guerra_status if not s.get("pode_impulsionar")]
    if bloqueados:
        s = bloqueados[0]
        return {
            "veredito": "nao_fazer",
            "codigo": "nao_impulsionar_sem_condicao",
            "titulo": f"Não impulsionar `{s.get('sku')}` hoje",
            "detalhe": "Bloqueios: " + ", ".join(s.get("bloqueios") or ["condição"]),
            "sku": s.get("sku"),
        }
    # Outros kits fora da guerra
    extras = [
        p
        for p in produtos
        if eh_kit_catalogo(p)
        and str(p.get("sku") or "").upper() not in guerra_skus
    ]
    if extras:
        return {
            "veredito": "nao_fazer",
            "codigo": "nao_abrir_sku_fora_guerra",
            "titulo": "Não abrir ads/promo em kits fora dos 3 de guerra",
            "detalhe": f"{len(extras)} kit(s) no catálogo fora da lista — dilui decisão e estoque.",
            "sku": "",
        }
    return {
        "veredito": "nao_fazer",
        "codigo": "nao_guerra_preco_unitario",
        "titulo": "Não entrar em guerra de preço no esmalte unitário",
        "detalhe": "Diferença = kit + anexo + B2B, não unitário mais barato.",
        "sku": "",
    }


def _custo_nao_fazer(*, fazer: dict[str, Any], crescimento: dict[str, Any]) -> dict[str, Any]:
    codigo = fazer.get("codigo")
    if codigo == "preencher_mlb_guerra":
        return {
            "veredito": "custo",
            "titulo": "Sem MLB: zero promoção válida e share parado vs Anita",
            "detalhe": "Cada dia sem anúncio = manicure compra kit da concorrência.",
        }
    if codigo == "ligar_whatsapp_manicures":
        return {
            "veredito": "custo",
            "titulo": "Sem WA: perde recompra B2B (o que paga o ecossistema)",
            "detalhe": "ML sozinho vira leilão de preço; canal próprio fecha margem.",
        }
    if codigo == "impulsionar_sku_guerra":
        return {
            "veredito": "custo",
            "titulo": "Sem impulso no SKU liberado: receita de kits não sobe à meta 40%",
            "detalhe": f"Kits hoje: {((crescimento.get('kpis') or {}).get('kits_pct_receita'))}% da receita.",
        }
    return {
        "veredito": "custo",
        "titulo": "Não executar = checklist cresce e margem dilui em SKUs errados",
        "detalhe": "Decisão espalhada mata o diferencial Impala.",
    }


def _sinal_comparativo() -> dict[str, Any]:
    data = ler_json(COMPARATIVO_PATH, default={})
    if not isinstance(data, dict) or not data:
        return {"disponivel": False}
    cons = data.get("consolidado") or data.get("resumo") or {}
    return {
        "disponivel": True,
        "resumo": cons.get("mensagem_curta")
        or cons.get("veredito")
        or data.get("veredito")
        or "comparativo disponível no snapshot",
        "timestamp": data.get("timestamp"),
    }


def _sinal_estrategia() -> dict[str, Any]:
    data = ler_json(ESTRATEGIA_PATH, default={})
    if not isinstance(data, dict) or not data:
        return {"disponivel": False, "top": None}
    acoes = data.get("acoes") or (data.get("resultado") or {}).get("acoes") or []
    top = acoes[0] if acoes and isinstance(acoes[0], dict) else None
    return {
        "disponivel": bool(top),
        "top": top,
        "timestamp": data.get("timestamp"),
    }


def _evolucao_semanal(kpis: dict[str, Any]) -> dict[str, Any]:
    hist = ler_json(HISTORICO_KPI_PATH, default={"pontos": []})
    if not isinstance(hist, dict):
        hist = {"pontos": []}
    pontos = list(hist.get("pontos") or [])
    atual = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kits_pct": kpis.get("kits_pct_receita"),
        "margem_pct": kpis.get("margem_media_pct"),
        "receita": kpis.get("receita_bruta"),
    }
    # comparação com ~7 dias atrás se houver pontos
    anterior = pontos[0] if pontos else None
    if len(pontos) >= 2:
        anterior = pontos[-min(7, len(pontos))]
    delta = {}
    if anterior and atual.get("kits_pct") is not None and anterior.get("kits_pct") is not None:
        try:
            delta["kits_pct"] = round(float(atual["kits_pct"]) - float(anterior["kits_pct"]), 1)
        except (TypeError, ValueError):
            pass
    if anterior and atual.get("margem_pct") is not None and anterior.get("margem_pct") is not None:
        try:
            delta["margem_pct"] = round(float(atual["margem_pct"]) - float(anterior["margem_pct"]), 1)
        except (TypeError, ValueError):
            pass
    return {"atual": atual, "anterior": anterior, "delta": delta, "pontos_para_gravar": pontos + [atual]}


def montar_decisao(
    *,
    margem_piso_pct: float = 15.0,
    meta_kits_pct: float = 40.0,
    caminho_guerra: str | None = None,
) -> dict[str, Any]:
    produtos = carregar_produtos_catalogo()
    guerra = carregar_skus_guerra(caminho_guerra)
    guerra_status = avaliar_skus_guerra(
        guerra=guerra, produtos=produtos, margem_piso_pct=margem_piso_pct
    )
    crescimento = montar_relatorio(meta_kits_pct=meta_kits_pct, meta_margem_pct=margem_piso_pct)
    eco = ler_json(ECOSSISTEMA_PATH, default={})
    eco_top = (eco or {}).get("top_7d") if isinstance(eco, dict) else []
    if not isinstance(eco_top, list):
        eco_top = []

    fazer = _acao_fazer(
        guerra_status=guerra_status, crescimento=crescimento, eco_top=eco_top
    )
    guerra_skus = {str(g.get("sku") or "").upper() for g in guerra}
    nao_fazer = _acao_nao_fazer(
        guerra_status=guerra_status, guerra_skus=guerra_skus, produtos=produtos
    )
    custo = _custo_nao_fazer(fazer=fazer, crescimento=crescimento)
    evolucao = _evolucao_semanal(crescimento.get("kpis") or {})
    comparativo = _sinal_comparativo()
    estrategia = _sinal_estrategia()

    liberados = [s for s in guerra_status if s.get("pode_impulsionar")]
    bloqueados = [s for s in guerra_status if not s.get("pode_impulsionar")]

    regras = [
        "Só 3 SKUs de guerra recebem ads/promo",
        f"Margem estimada ≥ {margem_piso_pct}% senão não impulsiona",
        "Sem MLB real → não promove",
        "Todo impulso leva combo anexo (removedor/base+top)",
        "Diferença = kit/anexo/B2B, não unitário mais barato",
    ]

    return {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fazer": fazer,
        "nao_fazer": nao_fazer,
        "custo_nao_fazer": custo,
        "skus_guerra": guerra_status,
        "liberados": len(liberados),
        "bloqueados": len(bloqueados),
        "regras": regras,
        "kpis": crescimento.get("kpis"),
        "evolucao": {
            "atual": evolucao.get("atual"),
            "anterior": evolucao.get("anterior"),
            "delta": evolucao.get("delta"),
        },
        "_pontos_kpi": evolucao.get("pontos_para_gravar"),
        "comparativo": comparativo,
        "estrategia_top": estrategia.get("top"),
        "canais": crescimento.get("canais"),
        "score_ecossistema": (eco or {}).get("score_ecossistema") if isinstance(eco, dict) else None,
        "margem_piso_pct": margem_piso_pct,
        "meta_kits_pct": meta_kits_pct,
    }


def montar_mensagem_telegram(dec: dict[str, Any]) -> str:
    from core.telegram_explicacao import cabecalho_agente

    fazer = dec.get("fazer") or {}
    nao = dec.get("nao_fazer") or {}
    custo = dec.get("custo_nao_fazer") or {}
    kpis = dec.get("kpis") or {}
    delta = (dec.get("evolucao") or {}).get("delta") or {}

    linhas = [
        cabecalho_agente(
            "decisao_dia_esmaltes",
            "🎯 *Decisão do dia — Impala ML*",
        ),
        "",
        f"✅ *FAZER:* {fazer.get('titulo')}",
        f"   _{fazer.get('detalhe')}_",
        "",
        f"🛑 *NÃO FAZER:* {nao.get('titulo')}",
        f"   _{nao.get('detalhe')}_",
        "",
        f"💸 *CUSTO DE NÃO FAZER:* {custo.get('titulo')}",
        f"   _{custo.get('detalhe')}_",
        "",
        (
            f"SKUs guerra: *{dec.get('liberados')}* liberado(s) / "
            f"*{dec.get('bloqueados')}* bloqueado(s) | "
            f"piso margem *{dec.get('margem_piso_pct')}%*"
        ),
    ]

    # status curto dos 3
    for s in (dec.get("skus_guerra") or [])[:3]:
        emoji = "🟢" if s.get("pode_impulsionar") else "🔴"
        linhas.append(
            f"{emoji} `{s.get('sku')}` ({s.get('papel')}) "
            f"{'OK' if s.get('pode_impulsionar') else '/'.join(s.get('bloqueios') or ['bloqueado'])}"
        )

    if not kpis.get("sem_vendas_periodo"):
        d_kits = delta.get("kits_pct")
        d_m = delta.get("margem_pct")
        evol = ""
        if d_kits is not None:
            evol += f" kits {d_kits:+}pp"
        if d_m is not None:
            evol += f" margem {d_m:+}pp"
        linhas.extend(
            [
                "",
                (
                    f"KPI: kits *{kpis.get('kits_pct_receita')}%* receita | "
                    f"margem *{kpis.get('margem_media_pct')}%*"
                    + (f" | Δ{evol}" if evol else "")
                ),
            ]
        )

    top_est = dec.get("estrategia_top")
    if isinstance(top_est, dict) and top_est.get("titulo"):
        linhas.extend(
            [
                "",
                f"_Estratégia ML:_ {top_est.get('titulo')}",
            ]
        )

    linhas.extend(
        [
            "",
            "*Regras:* " + " · ".join((dec.get("regras") or [])[:3]),
            "",
            "_Uma decisão. Execute só o FAZER de hoje._",
        ]
    )
    return "\n".join(linhas).strip()
