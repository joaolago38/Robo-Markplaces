"""
integracoes/ml/acoes_novamix.py
Transforma análise Novamix em plano de ação (guerra / competir / observar)
e opcionalmente aplica pausar/ligar Product Ads após confirmação do gestor.
"""
from __future__ import annotations

import logging
from typing import Any

from core.config import (
    BUDGET_FASE_INICIO,
    ESTRATEGIA_ML_GAP_GUERRA_PCT,
    ESTRATEGIA_ML_MAX_ACOES,
    ML_ANALISE_ANUNCIO_TAXA_PCT,
    NOVAMIX_AUTO_ADS_INVESTIR,
    NOVAMIX_AUTO_ADS_PAUSAR,
    NOVAMIX_GAP_COMPETIR_PCT,
)
from integracoes.ml.estrategia_vendas_ml import (
    _acao_base,
    _custo_produto,
    _f,
    _fmt,
    gerar_acoes_estrategia,
)

logger = logging.getLogger("acoes_novamix")


def _carregar_produtos() -> list[dict[str, Any]]:
    try:
        from core.catalogo_produtos import carregar_produtos_para_operacao

        return carregar_produtos_para_operacao(merge_bling=False)
    except Exception:
        try:
            from core.catalogo_produtos import carregar_produtos_catalogo

            return carregar_produtos_catalogo()
        except Exception:
            return []


def _viavel_competir(
    *,
    meu: float,
    menor: float,
    gap_competir: float,
    custo: float,
    taxa_pct: float,
) -> float | None:
    """Retorna gap% se SKU cabe em 'competir'; senão None."""
    if meu <= 0 or menor <= 0:
        return None
    gap = (meu - menor) / menor * 100.0
    if gap < 0 or gap > gap_competir:
        return None
    liquida = meu * (1.0 - taxa_pct / 100.0)
    if custo > 0 and liquida < custo:
        return None
    return gap


def _enriquecer_competir(
    acoes: list[dict[str, Any]],
    analise_loja: dict[str, Any],
    produtos: list[dict[str, Any]],
    *,
    gap_competir: float,
    taxa_pct: float,
) -> list[dict[str, Any]]:
    """SKUs com gap baixo e margem ok → investir_ads (cria ou promove reposicionar)."""
    por_sku = {str(p.get("sku") or ""): p for p in produtos if p.get("sku")}
    out: list[dict[str, Any]] = []
    promovidos: set[str] = set()

    for a in acoes:
        sku = str(a.get("sku") or "").strip()
        tipo = str(a.get("tipo") or "")
        if sku and tipo in {"reposicionar_preco", "investir_ads"}:
            prod = por_sku.get(sku)
            dados = dict(a.get("dados") or {})
            meu = _f(dados.get("meu_preco") or _meu_preco_fallback(prod))
            menor = _f(dados.get("menor_mercado"))
            gap = _viavel_competir(
                meu=meu,
                menor=menor,
                gap_competir=gap_competir,
                custo=_custo_produto(prod),
                taxa_pct=taxa_pct,
            )
            if gap is not None:
                promovidos.add(sku)
                out.append(
                    _acao_base(
                        tipo="investir_ads",
                        titulo=f"Competir com Ads: {sku}",
                        detalhe=(
                            f"Gap {gap:.1f}% vs Novamix (alvo {_fmt(meu)} vs loja {_fmt(menor)}). "
                            f"Margem no seu preço parece viável — priorize Product Ads neste SKU."
                        ),
                        sku=sku,
                        prioridade="media",
                        score=max(float(a.get("score") or 0), 15 + max(0, gap_competir - gap)),
                        dados={
                            **dados,
                            "gap_pct": round(gap, 1),
                            "meu_preco": meu,
                            "menor_mercado": menor,
                            "origem": dados.get("origem") or "novamix_competir",
                            "caixa": "competir",
                            "ads_acao": "investir",
                        },
                    )
                )
                continue
        out.append(a)

    vistos = {str(a.get("sku") or "") for a in out if a.get("sku")} | promovidos
    for ameaca in analise_loja.get("ameacas_preco") or []:
        sku = str(ameaca.get("sku") or "").strip()
        if not sku or sku in vistos:
            continue
        meu = _f(ameaca.get("meu_preco"))
        menor = _f(ameaca.get("menor_preco_loja"))
        prod = por_sku.get(sku)
        gap = _viavel_competir(
            meu=meu,
            menor=menor,
            gap_competir=gap_competir,
            custo=_custo_produto(prod),
            taxa_pct=taxa_pct,
        )
        if gap is None:
            continue
        out.append(
            _acao_base(
                tipo="investir_ads",
                titulo=f"Competir com Ads: {sku}",
                detalhe=(
                    f"Gap {gap:.1f}% vs Novamix (alvo {_fmt(meu)} vs loja {_fmt(menor)}). "
                    f"Margem no seu preço parece viável — priorize Product Ads neste SKU."
                ),
                sku=sku,
                prioridade="media",
                score=15 + max(0, gap_competir - gap),
                dados={
                    "gap_pct": round(gap, 1),
                    "meu_preco": meu,
                    "menor_mercado": menor,
                    "origem": "novamix_competir",
                    "caixa": "competir",
                    "ads_acao": "investir",
                },
            )
        )
        vistos.add(sku)
    return out


def _meu_preco_fallback(produto: dict[str, Any] | None) -> float:
    if not produto:
        return 0.0
    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    return _f(ml.get("preco") or produto.get("preco"))


def _anotar_ads_acao(
    acoes: list[dict[str, Any]],
    gap_guerra: float,
    gap_competir: float,
) -> list[dict[str, Any]]:
    anotadas: list[dict[str, Any]] = []
    for a in acoes:
        dados = dict(a.get("dados") or {})
        tipo = str(a.get("tipo") or "")
        gap = _f(dados.get("gap_pct"))
        if tipo == "diferenciar_ou_sair" or gap >= gap_guerra:
            dados["caixa"] = "guerra"
            dados["ads_acao"] = "pausar"
        elif tipo == "investir_ads" or (0 <= gap <= gap_competir and tipo != "canal_proprio"):
            dados["caixa"] = dados.get("caixa") or "competir"
            dados["ads_acao"] = "investir"
        elif tipo == "canal_proprio":
            dados["caixa"] = "guerra"
            dados["ads_acao"] = "nenhuma"
        elif tipo == "reposicionar_preco":
            dados["caixa"] = "observar"
            dados["ads_acao"] = "nenhuma"
        else:
            dados["caixa"] = dados.get("caixa") or "observar"
            dados["ads_acao"] = "nenhuma"
        anotadas.append({**a, "dados": dados})
    return anotadas


def gerar_plano_acoes_novamix(
    analise_loja: dict[str, Any],
    *,
    produtos: list[dict[str, Any]] | None = None,
    max_acoes: int | None = None,
) -> dict[str, Any]:
    """Gera plano priorizado a partir da análise da loja Novamix."""
    produtos = produtos if produtos is not None else _carregar_produtos()
    gap_guerra = _f(ESTRATEGIA_ML_GAP_GUERRA_PCT, 25.0)
    gap_competir = _f(NOVAMIX_GAP_COMPETIR_PCT, 10.0)
    taxa = _f(ML_ANALISE_ANUNCIO_TAXA_PCT, 18.0)
    max_n = int(max_acoes if max_acoes is not None else ESTRATEGIA_ML_MAX_ACOES)

    base = gerar_acoes_estrategia(
        analise_loja=analise_loja,
        produtos=produtos,
        gap_guerra_pct=gap_guerra,
        max_acoes=max(8, max_n),
    )
    acoes = list(base.get("acoes") or [])
    acoes = _enriquecer_competir(
        acoes,
        analise_loja,
        produtos,
        gap_competir=gap_competir,
        taxa_pct=taxa,
    )
    acoes = _anotar_ads_acao(acoes, gap_guerra, gap_competir)
    acoes.sort(
        key=lambda x: (
            0 if x.get("prioridade") == "alta" else 1,
            -float(x.get("score") or 0),
        )
    )
    top = acoes[: max(1, max_n)]

    caixas = {"guerra": [], "competir": [], "observar": []}
    for a in acoes:
        caixa = str((a.get("dados") or {}).get("caixa") or "observar")
        if caixa not in caixas:
            caixa = "observar"
        sku = str(a.get("sku") or a.get("titulo") or "")
        if sku and sku not in caixas[caixa]:
            caixas[caixa].append(sku)

    guerra_n = len(caixas["guerra"])
    competir_n = len(caixas["competir"])
    if guerra_n > 0 and competir_n == 0:
        ads_sugerido = "pausar"
    elif competir_n > 0 and guerra_n == 0:
        ads_sugerido = "investir"
    elif guerra_n > competir_n:
        ads_sugerido = "pausar"
    elif competir_n > 0:
        ads_sugerido = "investir"
    else:
        ads_sugerido = "manter"

    return {
        "ok": True,
        "acoes": top,
        "acoes_todas": acoes,
        "caixas": caixas,
        "ads_sugerido": ads_sugerido,
        "contexto": {
            **(base.get("contexto") or {}),
            "gap_competir_pct": gap_competir,
            "gap_guerra_pct": gap_guerra,
            "loja": analise_loja.get("nickname") or "NOVAMIX_COMERCIAL",
        },
    }


def formatar_secao_acoes_telegram(plano: dict[str, Any]) -> str:
    """Bloco Telegram com caixas + ações + próximo passo Ads."""
    if not plano or not plano.get("ok"):
        return ""
    linhas = ["", "*Plano de ação (Novamix → vendas)*"]
    caixas = plano.get("caixas") or {}
    if caixas.get("guerra"):
        linhas.append(f"🔴 Guerra (não baixar/pausar ads): {', '.join(caixas['guerra'][:6])}")
    if caixas.get("competir"):
        linhas.append(f"🟢 Competir (Ads ok): {', '.join(caixas['competir'][:6])}")
    if caixas.get("observar"):
        linhas.append(f"🟡 Observar/ajustar: {', '.join(caixas['observar'][:6])}")

    for i, a in enumerate(plano.get("acoes") or [], 1):
        emoji = "🔴" if a.get("prioridade") == "alta" else "🟡"
        ads = (a.get("dados") or {}).get("ads_acao") or "nenhuma"
        linhas.append(f"{i}. {emoji} *{a.get('titulo')}*")
        linhas.append(f"   {a.get('detalhe')}")
        if ads != "nenhuma":
            linhas.append(f"   _Ads: {ads}_")

    ads = plano.get("ads_sugerido") or "manter"
    if ads == "pausar":
        linhas.append("")
        linhas.append("_Sugestão Ads global: PAUSAR Product Ads (maioria em guerra de preço)._")
    elif ads == "investir":
        linhas.append("")
        linhas.append(
            f"_Sugestão Ads global: LIGAR/manter Product Ads "
            f"(budget ~R$ {BUDGET_FASE_INICIO:.0f}/dia nos SKUs competitivos)._"
        )
    return "\n".join(linhas)


def executar_acoes_ads_novamix(
    plano: dict[str, Any],
    *,
    pedir_confirmacao: bool = True,
) -> dict[str, Any]:
    """
    Aplica pausar/ligar Product Ads conforme plano.
    Preço nunca é alterado automaticamente.
    """
    from core.notificador import alertar_gestor, perguntar_gestor_e_aguardar
    from integracoes.ml.ml_product_ads import aplicar_decisao_campanhas, probe_escrita_product_ads

    ads = str(plano.get("ads_sugerido") or "manter")
    out: dict[str, Any] = {
        "ok": True,
        "ads_sugerido": ads,
        "executado": False,
        "decisao": "manter",
        "confirmado_gestor": None,
        "resultados": [],
        "motivo": "",
    }

    if ads == "manter":
        out["motivo"] = "sem mudança de Ads sugerida"
        return out

    if ads == "pausar" and not NOVAMIX_AUTO_ADS_PAUSAR:
        out["motivo"] = "NOVAMIX_AUTO_ADS_PAUSAR=0 — só recomendação"
        return out
    if ads == "investir" and not NOVAMIX_AUTO_ADS_INVESTIR:
        out["motivo"] = "NOVAMIX_AUTO_ADS_INVESTIR=0 — só recomendação"
        return out

    probe = probe_escrita_product_ads()
    out["probe_escrita"] = probe
    if not probe.get("ok"):
        out["ok"] = False
        out["motivo"] = f"probe escrita falhou: {probe.get('codigo')} {probe.get('erro')}"
        alertar_gestor(
            "⚠️ *Novamix → Ads*: escrita Product Ads indisponível.\n"
            f"`{probe.get('codigo')}` — `{probe.get('erro')}`",
            chave="novamix:ads:probe",
            cooldown_segundos=86400,
        )
        return out

    caixas = plano.get("caixas") or {}
    if ads == "pausar":
        decisao = "pausar"
        budget = 0.0
        skus = ", ".join((caixas.get("guerra") or [])[:8]) or "vários"
        pergunta = (
            "🔴 *Novamix → PAUSAR Product Ads*\n\n"
            f"SKUs em guerra de preço: {skus}\n"
            "Evita pagar clique onde a margem não fecha.\n\n"
            "Confirma PAUSAR as campanhas Product Ads agora?"
        )
    else:
        decisao = "ligar"
        budget = float(BUDGET_FASE_INICIO)
        skus = ", ".join((caixas.get("competir") or [])[:8]) or "vários"
        pergunta = (
            "🟢 *Novamix → LIGAR Product Ads*\n\n"
            f"SKUs competitivos (gap ≤ {NOVAMIX_GAP_COMPETIR_PCT:.0f}%): {skus}\n"
            f"Budget sugerido: R$ {budget:.2f}/dia\n\n"
            "Confirma LIGAR Product Ads agora?"
        )

    confirmado = True
    if pedir_confirmacao:
        confirmado = bool(
            perguntar_gestor_e_aguardar(
                pergunta,
                timeout_segundos=600,
                contexto_decisao={
                    "origem": "novamix_diario",
                    "decisao": decisao,
                    "ads_sugerido": ads,
                    "caixas": caixas,
                    "budget_sugerido_dia": budget,
                },
            )
        )
    out["confirmado_gestor"] = confirmado
    if not confirmado:
        out["motivo"] = "gestor recusou ou não respondeu"
        out["decisao"] = "manter"
        return out

    resultados = aplicar_decisao_campanhas(
        decisao,
        budget=budget,
        dry_run=False,
        confirmar=True,
    )
    out["executado"] = True
    out["decisao"] = decisao
    out["resultados"] = resultados
    ok_n = sum(1 for r in resultados if isinstance(r, dict) and r.get("ok"))
    out["motivo"] = f"aplicado {decisao}: {ok_n}/{len(resultados)} ok"
    alertar_gestor(
        f"✅ *Novamix → Ads {decisao}*\n{out['motivo']}\nSKUs: {skus}",
        chave=f"novamix:ads:{decisao}:ok",
        cooldown_segundos=3600,
    )
    logger.info("Novamix Ads %s — %s", decisao, out["motivo"])
    return out
