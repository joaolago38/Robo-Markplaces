"""
integracoes/ml/estrategia_vendas_ml.py
Gera ações de venda no ML a partir de monitor de concorrentes + análise de loja + catálogo.

Prioriza até N ações concretas (preço, ads, diferenciar, canal próprio).
"""
from __future__ import annotations

from typing import Any

from core.config import (
    ML_ANALISE_ANUNCIO_TAXA_PCT,
    MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT,
)
from core.precificacao_comportamento import calcular_lucro_operacao, calcular_preco_piso


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _catalogo_por_sku(produtos: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in produtos or []:
        if not isinstance(p, dict):
            continue
        sku = str(p.get("sku") or "").strip()
        if sku:
            out[sku] = p
    return out


def _meu_preco_produto(produto: dict[str, Any] | None, fallback: float = 0.0) -> float:
    if not produto:
        return fallback
    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    return _f(ml.get("preco") or produto.get("preco") or fallback)


def _custo_produto(produto: dict[str, Any] | None) -> float:
    if not produto:
        return 0.0
    return _f(produto.get("custo") or produto.get("custo_total"))


def _acao_base(
    *,
    tipo: str,
    titulo: str,
    detalhe: str,
    sku: str = "",
    prioridade: str = "media",
    score: float = 0.0,
    dados: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "tipo": tipo,
        "titulo": titulo,
        "detalhe": detalhe,
        "sku": sku,
        "prioridade": prioridade,
        "score": round(score, 2),
        "dados": dados or {},
    }


def _avaliar_sku_vs_mercado(
    *,
    sku: str,
    nome: str,
    meu_preco: float,
    menor_mercado: float,
    produto: dict[str, Any] | None,
    taxa_pct: float,
    gap_alerta_pct: float,
    gap_guerra_pct: float,
    origem: str,
) -> dict[str, Any] | None:
    if meu_preco <= 0 or menor_mercado <= 0:
        return None
    gap = (meu_preco - menor_mercado) / menor_mercado * 100.0
    if gap < gap_alerta_pct:
        # competitivo — sugerir ads só se gap pequeno e positivo ou empatado
        if gap <= 2:
            return _acao_base(
                tipo="investir_ads",
                titulo=f"Investir ads em {sku or nome}",
                detalhe=(
                    f"Preço alinhado ao mercado (preço alvo {_fmt(meu_preco)} vs "
                    f"{_fmt(menor_mercado)}, gap {gap:.1f}%). "
                    f"Priorize Product Ads / exposição neste SKU."
                ),
                sku=sku,
                prioridade="media",
                score=10 + max(0, 5 - abs(gap)),
                dados={"gap_pct": round(gap, 1), "meu_preco": meu_preco, "menor_mercado": menor_mercado, "origem": origem},
            )
        return None

    custo = _custo_produto(produto)
    margem_min = _f((produto or {}).get("margem_minima_pct"), 15.0)
    liquida_mercado = menor_mercado * (1.0 - taxa_pct / 100.0)
    piso = calcular_preco_piso(custo, taxa_pct, margem_min) if custo > 0 else 0.0

    # Guerra de preço inviável
    if gap >= gap_guerra_pct or (custo > 0 and liquida_mercado < custo):
        return _acao_base(
            tipo="diferenciar_ou_sair",
            titulo=f"Não competir só em preço: {sku or nome}",
            detalhe=(
                f"Gap {gap:.1f}% (preço alvo {_fmt(meu_preco)} vs mercado {_fmt(menor_mercado)}). "
                f"Líquida est. no preço do líder: {_fmt(liquida_mercado)}"
                + (f" vs custo {_fmt(custo)}" if custo > 0 else "")
                + ". Diferencie kit/fotos/frete, pause ads agressivos ou empurre no canal próprio."
            ),
            sku=sku,
            prioridade="alta",
            score=50 + gap,
            dados={
                "gap_pct": round(gap, 1),
                "meu_preco": meu_preco,
                "menor_mercado": menor_mercado,
                "receita_liquida_mercado": round(liquida_mercado, 2),
                "custo": custo,
                "origem": origem,
            },
        )

    # Gap moderado: tentar aproximar se margem aguentar
    alvo = round(max(menor_mercado * 1.02, piso), 2) if piso > 0 else round(menor_mercado * 1.02, 2)
    if custo > 0:
        lucro_alvo = calcular_lucro_operacao(alvo, custo, taxa_pct)
        if lucro_alvo["lucro_reais"] < 0 or (piso > 0 and alvo < piso):
            return _acao_base(
                tipo="diferenciar_ou_sair",
                titulo=f"Margem não aguenta igualar: {sku or nome}",
                detalhe=(
                    f"Gap {gap:.1f}%. Piso com margem {margem_min:.0f}%: {_fmt(piso)}; "
                    f"mercado em {_fmt(menor_mercado)}. Melhor bundle/canal próprio do que cortar abaixo do piso."
                ),
                sku=sku,
                prioridade="alta",
                score=40 + gap,
                dados={"gap_pct": round(gap, 1), "piso": piso, "menor_mercado": menor_mercado, "origem": origem},
            )

    return _acao_base(
        tipo="reposicionar_preco",
        titulo=f"Ajustar preço de {sku or nome}",
        detalhe=(
            f"Gap {gap:.1f}% (preço alvo {_fmt(meu_preco)} → sugerido {_fmt(alvo)}). "
            f"Mercado em {_fmt(menor_mercado)}; teste redução controlada sem furar o piso."
        ),
        sku=sku,
        prioridade="alta",
        score=30 + gap,
        dados={
            "gap_pct": round(gap, 1),
            "meu_preco": meu_preco,
            "preco_sugerido": alvo,
            "menor_mercado": menor_mercado,
            "origem": origem,
        },
    )


def _fmt(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def gerar_acoes_estrategia(
    *,
    monitor: dict[str, Any] | None = None,
    analise_loja: dict[str, Any] | None = None,
    produtos: list[dict[str, Any]] | None = None,
    taxa_pct: float | None = None,
    gap_alerta_pct: float | None = None,
    gap_guerra_pct: float = 25.0,
    max_acoes: int = 3,
) -> dict[str, Any]:
    """
    Consolida fontes e devolve até `max_acoes` ações priorizadas + contexto.
    """
    taxa = _f(taxa_pct if taxa_pct is not None else ML_ANALISE_ANUNCIO_TAXA_PCT, 18.0)
    alerta = _f(
        gap_alerta_pct if gap_alerta_pct is not None else MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT,
        5.0,
    )
    por_sku = _catalogo_por_sku(produtos or [])
    candidatas: list[dict[str, Any]] = []
    vistos_sku: set[str] = set()

    monitor = monitor or {}
    for res in monitor.get("resultados") or []:
        if not isinstance(res, dict) or not res.get("ok"):
            continue
        tipo = str(res.get("tipo") or "termo").lower()
        sku = str(res.get("sku") or res.get("id") or "").strip()
        nome = str(res.get("nome") or sku)
        meu = _f(res.get("meu_preco"))
        menor = _f(res.get("menor_preco"))
        if tipo == "loja":
            for ameaca in res.get("ameacas_preco") or []:
                asku = str(ameaca.get("sku") or "").strip()
                if asku in vistos_sku:
                    continue
                ac = _avaliar_sku_vs_mercado(
                    sku=asku,
                    nome=str(ameaca.get("nome") or asku),
                    meu_preco=_f(ameaca.get("meu_preco")),
                    menor_mercado=_f(ameaca.get("menor_preco_loja")),
                    produto=por_sku.get(asku),
                    taxa_pct=taxa,
                    gap_alerta_pct=alerta,
                    gap_guerra_pct=gap_guerra_pct,
                    origem=f"loja:{res.get('nickname') or res.get('id')}",
                )
                if ac:
                    vistos_sku.add(asku)
                    candidatas.append(ac)
            continue

        # termo / sku monitorado
        chave = sku or nome
        if chave in vistos_sku:
            continue
        # tenta sku do catálogo de concorrentes (campo sku na entrada original não vem no resultado)
        # usa id se parecer SKU
        prod = por_sku.get(sku) if sku in por_sku else None
        if not prod:
            for psku, p in por_sku.items():
                if psku.lower() in nome.lower() or nome.lower() in str(p.get("nome") or "").lower():
                    prod = p
                    sku = sku or psku
                    break
        if not meu and prod:
            meu = _meu_preco_produto(prod)
        ac = _avaliar_sku_vs_mercado(
            sku=sku,
            nome=nome,
            meu_preco=meu,
            menor_mercado=menor,
            produto=prod,
            taxa_pct=taxa,
            gap_alerta_pct=alerta,
            gap_guerra_pct=gap_guerra_pct,
            origem="monitor_termo",
        )
        if ac:
            vistos_sku.add(chave)
            candidatas.append(ac)

    analise_loja = analise_loja or {}
    for ameaca in analise_loja.get("ameacas_preco") or []:
        asku = str(ameaca.get("sku") or "").strip()
        if not asku or asku in vistos_sku:
            continue
        ac = _avaliar_sku_vs_mercado(
            sku=asku,
            nome=str(ameaca.get("nome") or asku),
            meu_preco=_f(ameaca.get("meu_preco")),
            menor_mercado=_f(ameaca.get("menor_preco_loja")),
            produto=por_sku.get(asku),
            taxa_pct=taxa,
            gap_alerta_pct=alerta,
            gap_guerra_pct=gap_guerra_pct,
            origem=f"analise_loja:{analise_loja.get('nickname') or ''}",
        )
        if ac:
            vistos_sku.add(asku)
            candidatas.append(ac)

    # Canal próprio se houver pressão de preço
    pressao = [c for c in candidatas if c.get("tipo") in {"diferenciar_ou_sair", "reposicionar_preco"}]
    if pressao:
        candidatas.append(
            _acao_base(
                tipo="canal_proprio",
                titulo="Empurrar kits no canal próprio (WhatsApp/Telegram)",
                detalhe=(
                    f"{len(pressao)} SKU(s) sob pressão de preço no ML. "
                    "Use promoções manicures para vender fora da guerra de catálogo."
                ),
                prioridade="alta",
                score=35 + min(20, len(pressao) * 3),
                dados={"skus_sob_pressao": [c.get("sku") for c in pressao if c.get("sku")][:8]},
            )
        )

    candidatas.sort(
        key=lambda x: (
            0 if x.get("prioridade") == "alta" else 1 if x.get("prioridade") == "media" else 2,
            -_f(x.get("score")),
        )
    )
    # Evita duas ações do mesmo SKU
    finais: list[dict[str, Any]] = []
    skus_finais: set[str] = set()
    tipos_canal = 0
    for ac in candidatas:
        sku = str(ac.get("sku") or "")
        if sku and sku in skus_finais:
            continue
        if ac.get("tipo") == "canal_proprio":
            if tipos_canal:
                continue
            tipos_canal += 1
        if sku:
            skus_finais.add(sku)
        finais.append(ac)
        if len(finais) >= max(1, int(max_acoes)):
            break

    if not finais:
        finais.append(
            _acao_base(
                tipo="manter",
                titulo="Manter estratégia atual",
                detalhe="Sem gaps críticos nos SKUs monitorados nesta rodada. Continue monitorando preços e visitas dos seus anúncios.",
                prioridade="baixa",
                score=1,
            )
        )

    perfil = (analise_loja.get("perfil") or {}) if analise_loja else {}
    return {
        "ok": True,
        "total_candidatas": len(candidatas),
        "acoes": finais,
        "contexto": {
            "taxa_estimada_pct": taxa,
            "gap_alerta_pct": alerta,
            "gap_guerra_pct": gap_guerra_pct,
            "loja_ameaca": analise_loja.get("nickname") or perfil.get("nickname"),
            "loja_porte": (analise_loja.get("estrategia") or {}).get("porte"),
            "monitor_itens": len(monitor.get("resultados") or []),
            "monitor_alertas": len(monitor.get("alertas") or []),
        },
    }


def montar_mensagem_estrategia(payload: dict[str, Any], *, titulo: str | None = None) -> str:
    from datetime import datetime, timedelta, timezone

    agora = datetime.now(timezone(timedelta(hours=-3)))
    ctx = payload.get("contexto") or {}
    linhas = [
        titulo or "🎯 *Estratégia de vendas ML — ações da semana*",
        f"_{agora.strftime('%d/%m/%Y %H:%M')}_",
        "",
        "_Com base em preços de catálogo, gaps vs seus SKUs e margem estimada._",
    ]
    if ctx.get("loja_ameaca"):
        linhas.append(
            f"Concorrente foco: *{ctx['loja_ameaca']}*"
            + (f" ({ctx['loja_porte']})" if ctx.get("loja_porte") else "")
        )
    linhas.append(
        f"Monitor: {ctx.get('monitor_itens', 0)} itens | "
        f"{ctx.get('monitor_alertas', 0)} alertas | taxa est. {ctx.get('taxa_estimada_pct', '?')}%"
    )
    linhas.extend(["", "*Top ações*"])
    for i, ac in enumerate(payload.get("acoes") or [], 1):
        linhas.append(f"{i}. *{ac.get('titulo')}*")
        linhas.append(f"   {ac.get('detalhe')}")
        linhas.append(f"   _tipo: {ac.get('tipo')} | prioridade: {ac.get('prioridade')}_")
    linhas.extend(
        [
            "",
            "_Receita líquida = preço − taxa estimada. Visitas de concorrente não entram (API)._",
        ]
    )
    return "\n".join(linhas)
