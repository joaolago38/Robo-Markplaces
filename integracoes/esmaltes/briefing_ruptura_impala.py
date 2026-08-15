"""
integracoes/esmaltes/briefing_ruptura_impala.py
Prévia do ML + esforço restante + produtos Impala com margem segura.

Claude sintetiza o briefing nos pontos de ruptura (aproximando/liberado).
Não publica anúncio. Não troca de CNPJ.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import MARGEM_MINIMA, ROOT, RUPTURA_CLAUDE_ASSERTIVIDADE_MAXIMA
from core.datadog_metrics import gauge, incrementar
from integracoes.esmaltes.metricas_catalogo_impala import kit_tag, montar_snapshot_catalogo

logger = logging.getLogger("briefing_ruptura_impala")

SNAPSHOT_PATH = ROOT / "logs" / "briefing_ruptura_impala_ultima.json"
SNAPSHOT_RESUMO = ROOT / "logs" / "resumo_conta_ml_ultima.json"
SNAPSHOT_BATALHA = ROOT / "logs" / "impala_batalha_ultima.json"
SNAPSHOT_MARGEM = ROOT / "logs" / "margem_vendas_ultima.json"

_ATITUDES = {
    "avaliacoes": "Publicar kits Impala e pedir avaliação após a entrega (meta 20 reviews / nota 4.8).",
    "nota": "Tratar reclamações e qualidade do anúncio até a nota média ≥ 4.8.",
    "mlb": "Preencher MLB válido de IMP-MIMO-003 e IMP-PERL-004 — kits com margem ≥ piso; SORT-006 fica para fase 2.",
    "estoque": "Abastecer estoque dos kits de validação MIMO-003 e PERL-004 (mínimo do ponto de ruptura).",
    "pedidos": "Concluir 1 pedido próprio com margem registrada (não contar bolsa/legado).",
    "ads_acos": "Manter Ads desligado ou ACOS abaixo do teto — snapshot Ads precisa existir (vazio não é ok).",
    "claims": "Zerar claims abertos antes de escalar anúncio ou Ads.",
    "saude_conta": "Reputação laranja/vermelha ou atraso/cancelamento ≥5% bloqueia a ruptura.",
    "impala_fase1": "Fechar a checklist Impala (reviews / MLB / estoque / pedido) antes de outra marca.",
    "anuncios_foco": "Colocar no ar pelo menos 1 anúncio Impala (kit) no ML.",
    "cnpj_ml": "Confirmar seller_id do CNPJ 52.668.583/0001-27 no ML.",
    "cnae_cosmetico": "Manter CNAE 4772-5/00 neste CNPJ.",
    "radar_ml": "Radar de concorrentes precisa de amostra (≥5 anúncios) — busca 403 deixa o ranking cego.",
    "candidata": "Só ranquear outra marca quando houver anúncios/vendas na amostra.",
}

_ATITUDES_FEITAS = {
    "avaliacoes": "Reviews no caminho da meta.",
    "nota": "Nota média no piso (com reviews reais).",
    "mlb": "Kits de validação MIMO-003 e PERL-004 com MLB.",
    "estoque": "Estoque dos kits de validação no mínimo.",
    "pedidos": "Já existe pedido próprio ou venda completada.",
    "ads_acos": "ACOS dentro do teto (snapshot Ads visível).",
    "claims": "Claims baixos.",
    "anuncios_foco": "Há anúncio Impala ativo no ML.",
    "saude_conta": "Reputação e taxas da conta no piso.",
}


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


def _alinhar_kits_com_sinais(
    kits: list[dict[str, Any]],
    sinais: dict[str, Any],
) -> list[dict[str, Any]]:
    """MLB/estoque da checklist de ruptura prevalece sobre o snapshot do catálogo."""
    por_sku = {
        str(k.get("sku") or "").upper(): k
        for k in (sinais.get("kits") or [])
        if isinstance(k, dict) and k.get("sku")
    }
    if not por_sku:
        return kits
    saida: list[dict[str, Any]] = []
    for kit in kits:
        if not isinstance(kit, dict):
            continue
        sku = str(kit.get("sku") or "").upper()
        ref = por_sku.get(sku)
        if not ref:
            saida.append(kit)
            continue
        row = dict(kit)
        row["mlb_ok"] = bool(ref.get("mlb_ok"))
        row["estoque_zero"] = _i(ref.get("estoque")) <= 0
        saida.append(row)
    return saida


def esforco_da_checklist(checks: list[dict[str, Any]] | None) -> dict[str, Any]:
    """O que falta e o que já foi feito para a ruptura ficar tranquila."""
    faltando: list[dict[str, Any]] = []
    feitos: list[dict[str, Any]] = []
    for c in checks or []:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "")
        row = {
            "id": cid,
            "rotulo": c.get("rotulo"),
            "atual": c.get("atual"),
            "minimo": c.get("minimo"),
            "atitude": _ATITUDES.get(cid) or f"Fechar: {c.get('rotulo')}",
        }
        if c.get("ok"):
            row["atitude"] = _ATITUDES_FEITAS.get(cid) or row["atitude"]
            feitos.append(row)
        else:
            faltando.append(row)
    return {
        "faltando_n": len(faltando),
        "feitos_n": len(feitos),
        "faltando": faltando,
        "feitos": feitos,
    }


def produtos_com_margem_segura(
    kits: list[dict[str, Any]] | None,
    *,
    piso_pct: float,
) -> dict[str, Any]:
    """Kits Impala escolhíveis com margem ≥ piso, MLB e estoque."""
    seguros: list[dict[str, Any]] = []
    risco: list[dict[str, Any]] = []
    for k in kits or []:
        if not isinstance(k, dict):
            continue
        sku = str(k.get("sku") or "").strip().upper()
        if not sku.startswith("IMP-"):
            continue
        margem = k.get("margem_real_pct")
        mlb_ok = bool(k.get("mlb_ok"))
        ez = bool(k.get("estoque_zero"))
        preco = _f(k.get("preco"))
        row = {
            "sku": sku,
            "kit_tag": k.get("kit_tag") or kit_tag(sku),
            "papel": k.get("papel") or "catalogo",
            "preco": preco,
            "margem_real_pct": margem,
            "lucro_ref_ml": _f(k.get("lucro_ref_ml")),
            "mlb_ok": mlb_ok,
            "estoque_zero": ez,
            "guerra": bool(k.get("guerra")),
        }
        if (
            margem is not None
            and float(margem) >= piso_pct
            and mlb_ok
            and not ez
            and preco > 0
        ):
            row["veredito"] = "seguro"
            seguros.append(row)
        else:
            motivos = []
            if not mlb_ok:
                motivos.append("sem_mlb")
            if ez:
                motivos.append("estoque_zero")
            if margem is None:
                motivos.append("sem_margem")
            elif float(margem) < piso_pct:
                motivos.append(f"margem_{margem}%_abaixo_{piso_pct}%")
            if preco <= 0:
                motivos.append("sem_preco")
            row["veredito"] = "risco"
            row["bloqueios"] = motivos
            risco.append(row)
    seguros.sort(
        key=lambda r: (float(r.get("margem_real_pct") or 0), float(r.get("lucro_ref_ml") or 0)),
        reverse=True,
    )
    margens = [float(r["margem_real_pct"]) for r in seguros if r.get("margem_real_pct") is not None]
    return {
        "piso_pct": piso_pct,
        "seguros": seguros[:12],
        "seguros_n": len(seguros),
        "risco_n": len(risco),
        "risco_top": risco[:8],
        "margem_media_segura_pct": round(sum(margens) / len(margens), 1) if margens else 0.0,
        "candidatos_margem": [
            {
                "sku": r["sku"],
                "margem_real_pct": r.get("margem_real_pct"),
                "preco": r.get("preco"),
                "mlb_ok": r.get("mlb_ok"),
                "estoque_zero": r.get("estoque_zero"),
                "bloqueios": r.get("bloqueios") or [],
                "veredito": r.get("veredito"),
            }
            for r in sorted(
                [x for x in (seguros + risco) if x.get("margem_real_pct") is not None and float(x.get("margem_real_pct") or 0) >= piso_pct],
                key=lambda x: float(x.get("margem_real_pct") or 0),
                reverse=True,
            )[:6]
        ],
    }


def previa_ml(
    *,
    resumo: dict[str, Any] | None,
    sinais: dict[str, Any] | None,
    batalha: dict[str, Any] | None,
    margem: dict[str, Any] | None,
) -> dict[str, Any]:
    """Espelho curto do que está acontecendo no ML com foco Impala."""
    resumo = resumo if isinstance(resumo, dict) else {}
    sinais = sinais if isinstance(sinais, dict) else {}
    reputacao = resumo.get("reputacao") if isinstance(resumo.get("reputacao"), dict) else {}
    analise = (margem or {}).get("analise") if isinstance(margem, dict) else {}
    analise = analise if isinstance(analise, dict) else {}
    agir = (batalha or {}).get("agir") if isinstance(batalha, dict) else {}
    top_acoes = []
    if isinstance(agir, dict):
        for a in agir.get("top") or []:
            if isinstance(a, dict):
                top_acoes.append(
                    {
                        "sku": a.get("sku"),
                        "acao": a.get("acao"),
                        "motivo": a.get("motivo"),
                        "critica": bool(a.get("critica")),
                    }
                )
    anuncios_ativos = _i(resumo.get("anuncios_ativos"))
    return {
        "anuncios_ativos_foco": anuncios_ativos,
        "anuncios_pausados_foco": _i(resumo.get("anuncios_pausados")),
        "legado_ignorado": _i(resumo.get("anuncios_ignorados_fora_foco")),
        "foco_vazio": anuncios_ativos <= 0,
        "reputacao_cor": reputacao.get("cor") or "Sem cor ainda",
        "avaliacoes": _i(sinais.get("avaliacoes"), _i(reputacao.get("avaliacoes"))),
        "nota": _f(sinais.get("nota"), _f(reputacao.get("nota"))),
        "vendas_completadas": _i(
            sinais.get("vendas_completadas"), _i(reputacao.get("vendas_completadas"))
        ),
        "claims": _i(sinais.get("claims"), _i(resumo.get("pos_venda_claims"))),
        "claims_fonte_ok": bool(
            sinais["claims_fonte_ok"]
            if "claims_fonte_ok" in sinais
            else resumo.get("pos_venda_ok", True)
        ),
        "receita_bruta_24h": _f(analise.get("receita_bruta"), _f(sinais.get("receita_bruta"))),
        "itens_margem_24h": _i(analise.get("total_itens"), _i(sinais.get("itens_margem"))),
        "acos": _f(sinais.get("acos")),
        "acoes_batalha": top_acoes[:5],
    }


def saude_score(previa: dict[str, Any], esforco: dict[str, Any], checks_ok: int, checks_total: int) -> float:
    """0–100: saúde Impala no ML para decidir com segurança."""
    av_min = 20.0
    nota_min = 4.8
    foco = _i(previa.get("anuncios_ativos_foco")) > 0
    av = min(1.0, _f(previa.get("avaliacoes")) / av_min) * 25.0 if foco else 0.0
    nota = _f(previa.get("nota"))
    nota_pts = (
        min(1.0, nota / nota_min) * 15.0 if foco and _i(previa.get("avaliacoes")) > 0 else 0.0
    )
    anun = 20.0 if foco else 0.0
    pedidos = 15.0 if _i(previa.get("itens_margem_24h")) > 0 or (
        foco and _i(previa.get("vendas_completadas")) > 0
    ) else 0.0
    claims_visivel = previa.get("claims_fonte_ok")
    if claims_visivel is None:
        claims_visivel = True
    claims = 10.0 if bool(claims_visivel) and _i(previa.get("claims")) < 2 else 0.0
    check_pts = (100.0 * checks_ok / max(1, checks_total)) * 0.15
    score = av + nota_pts + anun + pedidos + claims + check_pts
    return round(min(100.0, score), 1)


def _kits_manicure_compacto() -> dict[str, Any]:
    data = ler_json(ROOT / "logs" / "kits_compativeis_manicures_ultima.json", default={})
    if not isinstance(data, dict):
        return {"ok": False, "condicao_n": 0, "ofertas_condicao": []}
    ofertas = []
    for o in (data.get("ofertas_condicao") or data.get("ofertas") or [])[:6]:
        if not isinstance(o, dict):
            continue
        eco = o.get("economia") or {}
        ofertas.append(
            {
                "sku": o.get("sku"),
                "qtd_kit": o.get("qtd_kit"),
                "indice_compra": o.get("indice_compra"),
                "margem_pct": o.get("margem_pct"),
                "condicao_ok": bool(o.get("condicao_ok")),
                "economia_pct": eco.get("economia_pct"),
                "preco": o.get("preco"),
            }
        )
    return {
        "ok": bool(data.get("ok")),
        "condicao_n": _i(data.get("condicao_n")),
        "preco_unitario_ref": _f(data.get("preco_unitario_ref")),
        "preco_unitario_ml": _f(data.get("preco_unitario_ml")),
        "ofertas_condicao": [x for x in ofertas if x.get("condicao_ok")][:4],
        "ofertas_top": ofertas[:4],
    }


def ancora_numerica(
    *,
    veredito: str,
    saude: float,
    previa: dict[str, Any],
    produtos: dict[str, Any],
    esforco: dict[str, Any],
    kits_manicure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Números que o Claude pode citar — com margem de erro explícita."""
    radar_cego = _i(previa.get("anuncios_ativos_foco")) <= 0
    km = kits_manicure if isinstance(kits_manicure, dict) else {}
    return {
        "veredito": veredito,
        "saude_score": saude,
        "saude_erro_pct": 5.0 if radar_cego else 2.0,
        "margem_piso_pct": _f(produtos.get("piso_pct"), 15.0),
        "margem_fonte": "catalogo_custo_mais_taxa_ml",
        "margem_erro_pp": 0.5,
        "vd_dia_fonte": "ref_catalogo_nao_venda_live",
        "radar_ml": "cego" if radar_cego else "amostra",
        "mlb_live": False,
        "reviews": _i(previa.get("avaliacoes")),
        "nota": _f(previa.get("nota")),
        "anuncios_foco": _i(previa.get("anuncios_ativos_foco")),
        "legado_ignorado": _i(previa.get("legado_ignorado")),
        "seguros_n": _i(produtos.get("seguros_n")),
        "faltando_n": _i(esforco.get("faltando_n")),
        "candidatos_margem": produtos.get("candidatos_margem") or [],
        "kits_manicure_condicao_n": _i(km.get("condicao_n")),
        "kits_manicure": (km.get("ofertas_condicao") or km.get("ofertas_top") or [])[:4],
        "preco_avulso_ref": _f(km.get("preco_unitario_ref"), 12.0),
        "cnpj": "52.668.583/0001-27",
        "regra": "cite só estes números; ausente = n/d; não invente venda ao vivo",
    }


def _fingerprint(
    veredito: str,
    saude: float,
    esforco: dict[str, Any],
    produtos: dict[str, Any],
    previa: dict[str, Any],
) -> str:
    return "|".join(
        [
            str(veredito),
            str(saude),
            str(esforco.get("faltando_n")),
            str(produtos.get("seguros_n")),
            str(previa.get("anuncios_ativos_foco")),
            str(previa.get("avaliacoes")),
            str(produtos.get("candidatos_margem") and produtos["candidatos_margem"][0].get("sku") or ""),
        ]
    )


def _resumo_deterministico(
    *,
    veredito: str,
    esforco: dict[str, Any],
    produtos: dict[str, Any],
    previa: dict[str, Any],
    saude: float,
) -> str:
    linhas = [
        f"Veredito *{veredito}* · saúde Impala ML `{saude}/100` · "
        f"anúncios foco `{previa.get('anuncios_ativos_foco')}` · "
        f"reviews `{previa.get('avaliacoes')}` nota `{previa.get('nota')}`."
    ]
    if previa.get("foco_vazio"):
        linhas.append(
            "Prévia ML: catálogo Impala vazio no ar (legado ignorado). "
            "Publicar kit de validação é o esforço nº 1."
        )
    faltando = esforco.get("faltando") or []
    if faltando:
        linhas.append("Esforço para ruptura tranquila:")
        for row in faltando[:4]:
            linhas.append(f"• {row.get('atitude')}")
    feitos = esforco.get("feitos") or []
    if feitos:
        linhas.append(
            "Já encaminhado: " + ", ".join(str(x.get("rotulo")) for x in feitos[:4]) + "."
        )
    seguros = produtos.get("seguros") or []
    piso = produtos.get("piso_pct")
    if seguros:
        top = seguros[0]
        linhas.append(
            f"Produto com margem segura (≥{piso}%): `{top.get('sku')}` "
            f"margem `{top.get('margem_real_pct')}%` preço `R$ {float(top.get('preco') or 0):.2f}`. "
            f"{produtos.get('seguros_n')} kit(s) no piso."
        )
    else:
        linhas.append(
            f"Nenhum kit Impala no piso de margem segura ({piso}%) com MLB e estoque. "
            "Não escale Ads nem volume até haver produto com lucro protegido."
        )
    linhas.append("Não publicar anúncio automático. Não trocar de CNPJ.")
    return "\n".join(linhas)


def _claude_ruptura(
    contexto: dict[str, Any],
    fallback: str,
    *,
    fase: str | None = None,
    momento_lucro: bool = False,
) -> str:
    from core.claude_ml.dosagem import SYSTEM_RUPTURA
    from core.config import (
        CLAUDE_LUCRO_ML_MOMENTOS,
        CLAUDE_MODELO,
        RUPTURA_CLAUDE,
        RUPTURA_CLAUDE_ASSERTIVIDADE_MAXIMA,
        RUPTURA_CLAUDE_IGNORAR_TOGGLE,
    )
    from core.resumo_ia import sintetizar_claude
    from integracoes.esmaltes.claude_ciclo_ruptura import (
        fase_claude_ruptura,
        registrar_pulso_maxima,
    )

    if not RUPTURA_CLAUDE:
        return ""
    fase_atual = (fase or fase_claude_ruptura()).strip().lower()
    maxima = fase_atual == "maxima" and bool(RUPTURA_CLAUDE_ASSERTIVIDADE_MAXIMA)
    if maxima:
        registrar_pulso_maxima()
    lucro = bool(momento_lucro) and bool(CLAUDE_LUCRO_ML_MOMENTOS) and not maxima
    forcar = (maxima and bool(RUPTURA_CLAUDE_IGNORAR_TOGGLE)) or lucro
    prompt = (
        "Analista de ruptura Impala no Mercado Livre. Assertividade máxima. "
        "Em até 8 linhas: (1) esforço que falta, com o número âncora; "
        "(2) o que já está ok; (3) SKU para a manicure com margem e economia "
        "do JSON (não invente); (4) prévia ML. "
        "Use FAZER / NÃO FAZER / OBSERVAR. "
        "Não publicar anúncio automático nem trocar CNPJ "
        "(52.668.583/0001-27 permanece o dono dos esmaltes)."
        if maxima
        else (
            "Analista de lucro Impala no ML. Uso moderado e seguro. "
            "Em até 6 linhas cite SOMENTE números do JSON (âncora). "
            "(1) SKU com margem ≥ piso para MLB+estoque; "
            "(2) NÃO FAZER Ads / SORT-006 se margem < piso / 2º CNPJ; "
            "(3) esforço que falta para ruptura segura; (4) prévia ML. "
            "FAZER / NÃO FAZER / OBSERVAR. Não invente vd/dia nem ranking. "
            "Não publicar anúncio nem trocar CNPJ 52.668.583/0001-27."
        )
    )
    return sintetizar_claude(
        prompt,
        contexto,
        fallback,
        max_tokens=500 if maxima else 220,
        origem="ruptura_impala",
        enriquecer_ml=True,
        proposito="ruptura_impala" if maxima else "ruptura_impala_moderada",
        forcar_profundidade="ampliada" if maxima else "padrao",
        forcar_modelo=maxima,
        modelo=CLAUDE_MODELO if maxima else None,
        forcar_chamada=forcar,
        temperature=0.0 if maxima else None,
        system=SYSTEM_RUPTURA,
        somente_ia=True,
    )


def emitir_metricas_briefing(briefing: dict[str, Any]) -> None:
    previa = briefing.get("previa_ml") or {}
    produtos = briefing.get("produtos") or {}
    esforco = briefing.get("esforco") or {}
    gauge("ruptura.impala.saude_score", float(briefing.get("saude_score") or 0))
    gauge("ruptura.impala.produtos_seguros", float(produtos.get("seguros_n") or 0))
    gauge("ruptura.impala.margem_media_segura_pct", float(produtos.get("margem_media_segura_pct") or 0))
    gauge("ruptura.impala.esforco_faltando", float(esforco.get("faltando_n") or 0))
    gauge("ruptura.impala.anuncios_ativos", float(previa.get("anuncios_ativos_foco") or 0))
    gauge("ruptura.impala.claude_ok", 1.0 if briefing.get("claude_ok") else 0.0)
    gauge(
        "ruptura.impala.claude_assertividade_maxima",
        1.0 if briefing.get("claude_assertividade_maxima") else 0.0,
    )
    momento = briefing.get("momento_lucro") or {}
    gauge("ruptura.impala.claude_lucro_momento", 1.0 if momento.get("momento") else 0.0)
    incrementar("ruptura.impala.briefing_rodadas")
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    try:
        from integracoes.datadog.oscilacao_decisao import registrar_e_avaliar

        kits = briefing.get("kits_manicure") or {}
        amostra: dict[str, float] = {
            "saude_score": float(briefing.get("saude_score") or 0),
            "produtos_seguros": float(produtos.get("seguros_n") or 0),
            "esforco_faltando": float(esforco.get("faltando_n") or 0),
            "claude_ok": 1.0 if briefing.get("claude_ok") else 0.0,
            "anuncios_foco": float(previa.get("anuncios_ativos_foco") or 0),
        }
        if isinstance(kits, dict) and kits:
            amostra["kit_condicao_ok"] = float(kits.get("condicao_n") or 0)
        if briefing.get("progresso_pct") is not None:
            amostra["progresso_pct"] = float(briefing.get("progresso_pct") or 0)
        if briefing.get("veredito") is not None:
            amostra["aproximando"] = 1.0 if str(briefing.get("veredito") or "") == "aproximando" else 0.0
        registrar_e_avaliar(amostra)
    except Exception as exc:
        logger.info("oscilação briefing: %s", exc)


def formatar_secao_briefing(briefing: dict[str, Any] | None) -> list[str]:
    data = briefing if isinstance(briefing, dict) else {}
    if not data or not data.get("ok"):
        return []
    previa = data.get("previa_ml") or {}
    produtos = data.get("produtos") or {}
    esforco = data.get("esforco") or {}
    linhas = [
        "",
        f"*Prévia ML Impala* · saúde `{data.get('saude_score')}/100`",
        f"• Anúncios foco: `{previa.get('anuncios_ativos_foco')}` "
        f"(pausados `{previa.get('anuncios_pausados_foco')}` · legado ignorado `{previa.get('legado_ignorado')}`)",
        f"• Reputação: `{previa.get('reputacao_cor')}` · reviews `{previa.get('avaliacoes')}` "
        f"nota `{previa.get('nota')}` · vendas `{previa.get('vendas_completadas')}`",
        f"• Margem 24h: `{previa.get('itens_margem_24h')}` item(ns) · "
        f"receita `R$ {float(previa.get('receita_bruta_24h') or 0):.2f}`",
    ]
    faltando = esforco.get("faltando") or []
    if faltando:
        linhas.append("")
        linhas.append("*Esforço para ruptura tranquila*")
        for row in faltando[:5]:
            linhas.append(f"• {row.get('atitude')}")
    feitos = esforco.get("feitos") or []
    if feitos:
        linhas.append(
            "*Já feito:* " + ", ".join(f"`{x.get('rotulo')}`" for x in feitos[:5])
        )
    seguros = produtos.get("seguros") or []
    linhas.append("")
    linhas.append(
        f"*Produtos com margem segura* (≥{produtos.get('piso_pct')}% + MLB + estoque)"
    )
    if seguros:
        for p in seguros[:6]:
            linhas.append(
                f"• `{p.get('sku')}` · margem `{p.get('margem_real_pct')}%` · "
                f"R$ {float(p.get('preco') or 0):.2f} · {p.get('papel')}"
            )
    else:
        linhas.append("• nenhum kit no piso — não escolha volume até haver lucro protegido")
    cand = produtos.get("candidatos_margem") or []
    if cand and not seguros:
        linhas.append("_Mais perto do piso (ainda bloqueados):_")
        for p in cand[:3]:
            bloq = ", ".join(str(b) for b in (p.get("bloqueios") or [])[:3]) or "ok"
            linhas.append(
                f"• `{p.get('sku')}` margem `{p.get('margem_real_pct')}%` ±0,5 p.p. — {bloq}"
            )
    ancora = data.get("ancora_numerica") or {}
    if ancora:
        linhas.extend(
            [
                "",
                f"*Números âncora* · margem ±`{ancora.get('margem_erro_pp')}` p.p. · "
                f"saúde ±`{ancora.get('saude_erro_pct')}%` · radar `{ancora.get('radar_ml')}`",
            ]
        )
    texto_ia = str(data.get("resumo_claude") or "").strip()
    if texto_ia and not texto_ia.startswith("⚠️"):
        flag = (
            "assertividade máxima"
            if data.get("claude_assertividade_maxima")
            else "uso moderado"
        )
        linhas.extend(["", f"*Claude ({flag})*", texto_ia])
    elif data.get("resumo_deterministico"):
        linhas.extend(["", "*Leitura para decidir*", str(data.get("resumo_deterministico"))])
    return linhas


def montar_briefing_ruptura(
    ruptura: dict[str, Any] | None,
    *,
    resumo: dict[str, Any] | None = None,
    catalogo: dict[str, Any] | None = None,
    batalha: dict[str, Any] | None = None,
    margem: dict[str, Any] | None = None,
    produtos: list[dict[str, Any]] | None = None,
    guerra: list[dict[str, Any]] | None = None,
    chamar_claude: bool = True,
    piso_pct: float | None = None,
) -> dict[str, Any]:
    """Monta briefing. Nunca lança. Nunca escreve no ML."""
    try:
        rup = ruptura if isinstance(ruptura, dict) else {}
        if resumo is None:
            resumo = ler_json(SNAPSHOT_RESUMO, default={})
        if batalha is None:
            batalha = ler_json(SNAPSHOT_BATALHA, default={})
        if margem is None:
            margem = ler_json(SNAPSHOT_MARGEM, default={})
        if catalogo is None:
            if produtos is None:
                try:
                    from core.catalogo_produtos import carregar_produtos_para_operacao

                    produtos = carregar_produtos_para_operacao(merge_bling=False)
                except Exception:
                    produtos = []
            if guerra is None:
                try:
                    from integracoes.esmaltes.decisao_dia_esmaltes import carregar_skus_guerra

                    guerra = carregar_skus_guerra()
                except Exception:
                    guerra = []
            catalogo = montar_snapshot_catalogo(produtos=produtos or [], guerra=guerra or [])

        piso = float(piso_pct if piso_pct is not None else MARGEM_MINIMA)
        checks = list(rup.get("checks") or [])
        sinais = rup.get("sinais") if isinstance(rup.get("sinais"), dict) else {}
        esforco = esforco_da_checklist(checks)
        kits_cat = list(catalogo.get("kits") or []) if isinstance(catalogo, dict) else []
        kits_cat = _alinhar_kits_com_sinais(kits_cat, sinais)
        prods = produtos_com_margem_segura(kits_cat, piso_pct=piso)
        previa = previa_ml(resumo=resumo, sinais=sinais, batalha=batalha, margem=margem)
        saude = saude_score(
            previa, esforco, _i(rup.get("checks_ok")), _i(rup.get("checks_total"), 8)
        )
        veredito = str(rup.get("veredito") or "ainda_nao")
        kits_m = _kits_manicure_compacto()
        ancora = ancora_numerica(
            veredito=veredito,
            saude=saude,
            previa=previa,
            produtos=prods,
            esforco=esforco,
            kits_manicure=kits_m,
        )
        det = _resumo_deterministico(
            veredito=veredito, esforco=esforco, produtos=prods, previa=previa, saude=saude
        )
        fp = _fingerprint(veredito, saude, esforco, prods, previa)
        from integracoes.esmaltes.claude_lucro_ml import momento_lucro_ml

        momento = momento_lucro_ml(
            produtos=prods,
            kits_manicure=kits_m,
            acoes=(batalha or {}).get("agir") if isinstance(batalha, dict) else None,
            veredito=veredito,
        )
        texto_ia = ""
        claude_ok = False
        claude_reused = False
        from integracoes.esmaltes.claude_ciclo_ruptura import (
            fase_claude_ruptura,
            marcar_exposto_datadog,
        )

        fase = fase_claude_ruptura()
        maxima = fase == "maxima" and bool(RUPTURA_CLAUDE_ASSERTIVIDADE_MAXIMA)
        if chamar_claude and not os.environ.get("PYTEST_CURRENT_TEST"):
            antigo = ler_json(SNAPSHOT_PATH, default={})
            ts_ant = str((antigo or {}).get("timestamp") or "")
            claude_ant = str((antigo or {}).get("resumo_claude") or "")
            fp_ant = str((antigo or {}).get("fingerprint") or "")
            reused = False
            if (
                not maxima
                and claude_ant
                and not claude_ant.startswith("⚠️")
                and ts_ant
                and fp_ant == fp
                and (antigo or {}).get("claude_ok")
            ):
                try:
                    idade_h = (
                        datetime.now(timezone.utc)
                        - datetime.fromisoformat(ts_ant.replace("Z", "+00:00"))
                    ).total_seconds() / 3600.0
                    if idade_h < 6:
                        texto_ia = claude_ant
                        claude_ok = True
                        reused = True
                        claude_reused = True
                except Exception:
                    reused = False
            if not reused:
                try:
                    texto_ia = _claude_ruptura(
                        {
                            "veredito": veredito,
                            "progresso_pct": rup.get("progresso_pct"),
                            "saude_score": saude,
                            "esforco": esforco,
                            "produtos_seguros": prods.get("seguros"),
                            "candidatos_margem": prods.get("candidatos_margem"),
                            "piso_margem_pct": piso,
                            "previa_ml": previa,
                            "ancora_numerica": ancora,
                            "kits_manicure": kits_m,
                            "cnpj": "52.668.583/0001-27",
                            "claude_fase": fase,
                            "momento_lucro": momento,
                        },
                        det,
                        fase=fase,
                        momento_lucro=bool(momento.get("momento")),
                    )
                    claude_ok = bool(texto_ia) and not str(texto_ia).startswith("⚠️")
                except Exception as exc:
                    logger.info("Claude ruptura indisponível: %s", exc)
                    texto_ia = ""

        briefing = {
            "ok": True,
            "veredito": veredito,
            "saude_score": saude,
            "progresso_pct": _f(rup.get("progresso_pct")),
            "esforco": esforco,
            "produtos": prods,
            "previa_ml": previa,
            "ancora_numerica": ancora,
            "kits_manicure": kits_m,
            "resumo_deterministico": det,
            "resumo_claude": texto_ia if claude_ok else "",
            "claude_ok": claude_ok,
            "claude_fase": fase,
            "claude_assertividade_maxima": maxima and claude_ok,
            "claude_reused": claude_reused,
            "momento_lucro": momento,
            "fingerprint": fp,
            "cnpj": "52.668.583/0001-27",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        from core.datadog_metrics import falhas_envio as _falhas_dd

        falhas_antes = _falhas_dd()
        emitir_metricas_briefing(briefing)
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            if _falhas_dd() == falhas_antes:
                marcar_exposto_datadog()
            else:
                logger.warning(
                    "Datadog ingest falhou (%s) — Claude permanece em pulso máximo até os gauges chegarem",
                    _falhas_dd(),
                )
        try:
            escrever_json_atomico(SNAPSHOT_PATH, briefing)
        except Exception:
            pass
        return briefing
    except Exception as exc:
        logger.warning("montar_briefing_ruptura: %s", exc)
        incrementar("ruptura.impala.briefing_erro")
        return {"ok": False, "erro": str(exc), "claude_ok": False}


def anexar_briefing(resultado: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Anexa briefing ao resultado da ruptura. Sempre devolve o dict."""
    out = resultado if isinstance(resultado, dict) else {}
    if "chamar_claude" not in kwargs:
        kwargs["chamar_claude"] = True
    briefing = montar_briefing_ruptura(out, **kwargs)
    out["briefing"] = briefing
    return out
