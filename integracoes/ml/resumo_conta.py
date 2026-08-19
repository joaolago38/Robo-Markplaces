"""
integracoes/ml/resumo_conta.py
Coleta o espelho do Resumo do vendedor ML (pendências, reputação, envios, preços)
via API — não abre o painel web.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from core.config import ML_ACCESS_TOKEN, ML_SELLER_ID
from integracoes.ml import ml_client
from integracoes.ml.filtro_anuncios_conta import filtrar_anuncios_foco, ultimo_filtro_anuncios

logger = logging.getLogger("resumo_conta_ml")

_NIVEL_COR = {
    "5_green": "Verde",
    "4_light_green": "Verde claro",
    "3_yellow": "Amarelo",
    "2_orange": "Laranja",
    "1_red": "Vermelho",
    "null": "Sem cor",
    "none": "Sem cor",
}
_NIVEL_NUM = {
    "5_green": 5,
    "4_light_green": 4,
    "3_yellow": 3,
    "2_orange": 2,
    "1_red": 1,
}
_POWER_NUM = {"platinum": 3, "gold": 2, "silver": 1}


def _fmt_brl(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _linha_integridade(integ: Any) -> str:
    if not isinstance(integ, dict):
        return "*Integridade ML:* `_sem auditoria_`"
    pct = float(integ.get("pct") or 0)
    meta = float(integ.get("meta_pct") or 99.99)
    if integ.get("atinge_meta"):
        extra = f" · {int(integ.get('corrigidos') or 0)} campo(s) alinhados ao vivo" if integ.get("corrigidos") else ""
        return f"*Integridade ML:* *{pct:.2f}%* (meta {meta:.2f}%){extra}"
    return (
        f"*Integridade ML:* *{pct:.2f}%* — abaixo da meta {meta:.2f}% "
        f"(espelho não confiável)"
    )


def _data_brt() -> str:
    brt = timezone(timedelta(hours=-3))
    return datetime.now(brt).strftime("%d/%m/%Y %H:%M")


def _texto_reputacao(rep: dict[str, Any]) -> dict[str, Any]:
    level_id = rep.get("level_id")
    if level_id is None or str(level_id).lower() in ("", "null", "none"):
        cor = "Sem cor ainda"
        nivel = ""
    else:
        key = str(level_id)
        cor = _NIVEL_COR.get(key, key)
        nivel = key
    transactions = rep.get("transactions") if isinstance(rep.get("transactions"), dict) else {}
    completed = int(transactions.get("completed") or 0)
    metrics = rep.get("metrics") if isinstance(rep.get("metrics"), dict) else {}
    claims = metrics.get("claims") if isinstance(metrics.get("claims"), dict) else {}
    claims_rate = float(claims.get("rate") or 0)
    sales = metrics.get("sales") if isinstance(metrics.get("sales"), dict) else {}
    delayed = (
        metrics.get("delayed_handling_time")
        if isinstance(metrics.get("delayed_handling_time"), dict)
        else {}
    )
    cancel = metrics.get("cancellations") if isinstance(metrics.get("cancellations"), dict) else {}
    power = str(rep.get("power_seller_status") or "") or "—"
    avaliacoes = int(metrics.get("total_ratings") or 0)
    nota = float(metrics.get("average_rating") or 0)
    return {
        "cor": cor,
        "level_id": nivel,
        "nivel_num": int(_NIVEL_NUM.get(str(level_id or ""), 0)),
        "vendas_completadas": completed,
        "vendas_60d": int(sales.get("completed") or 0),
        "avaliacoes": avaliacoes,
        "nota": nota,
        "claims_rate": claims_rate,
        "atraso_rate": float(delayed.get("rate") or 0),
        "cancelamentos_rate": float(cancel.get("rate") or 0),
        "power_seller": power,
        "power_num": int(_POWER_NUM.get(power.lower(), 0)),
        "sem_cor": completed < 10 or cor.startswith("Sem cor"),
    }


def coletar_resumo_conta(*, max_anuncios_performance: int = 80) -> dict[str, Any]:
    """
    Monta o resumo da conta do seller autenticado.
    Nunca lança exceção.
    """
    try:
        if not (ML_ACCESS_TOKEN and ML_SELLER_ID):
            return {"ok": False, "erro": "ml_nao_configurado"}

        perfil = ml_client.buscar_perfil_vendedor()
        rep = perfil.get("seller_reputation") if isinstance(perfil.get("seller_reputation"), dict) else {}
        if not rep:
            rep = ml_client.buscar_reputacao_vendedor()
        reputacao = _texto_reputacao(rep)

        perguntas = ml_client.listar_perguntas_nao_respondidas()
        anuncios_todos = ml_client.listar_meus_anuncios(
            statuses=("active", "paused"),
            aplicar_foco=False,
        )
        try:
            from integracoes.ml.integridade_dados_ml import executar as auditar_ml

            integridade = auditar_ml(anuncios=anuncios_todos)
        except Exception as exc:
            logger.info("integridade ML: %s", exc)
            integridade = {"pct": 0.0, "atinge_meta": False, "espelho_confiavel": False}
        anuncios, _ = filtrar_anuncios_foco(anuncios_todos)
        filtro = ultimo_filtro_anuncios()
        ignorados_fora_foco = int(filtro.get("ignorados") or 0)
        ativos = sum(1 for a in anuncios if str(a.get("status") or "").lower() == "active")
        pausados = sum(1 for a in anuncios if str(a.get("status") or "").lower() == "paused")
        ativos_conta = sum(1 for a in anuncios_todos if str(a.get("status") or "").lower() == "active")
        pausados_conta = sum(1 for a in anuncios_todos if str(a.get("status") or "").lower() == "paused")
        from integracoes.ml.tipo_anuncio_ml import contar_prateleiras

        prateleiras = contar_prateleiras(anuncios)
        sugestoes_preco_ids = ml_client.listar_itens_com_sugestao_preco()
        envios = ml_client.contar_envios_pendentes()
        claims = ml_client.contar_claims_abertos()

        a_melhorar: list[dict[str, Any]] = []
        vistos_up: set[str] = set()
        amostra = anuncios[: max(1, int(max_anuncios_performance))]
        for anuncio in amostra:
            item_id = str(anuncio.get("item_id") or "").strip()
            if not item_id:
                continue
            status_an = str(anuncio.get("status") or "").lower()
            # Performance API não calcula suspenso/fechado/under review
            if status_an in ("closed", "inactive", "under_review", "forbidden"):
                continue
            up_id = str(anuncio.get("user_product_id") or "").strip()
            if up_id and up_id in vistos_up:
                continue
            if up_id:
                vistos_up.add(up_id)
            perf = ml_client.buscar_performance_item(item_id, user_product_id=up_id)
            if perf and perf.get("a_melhorar"):
                pend = perf.get("regras_pendentes") or []
                a_melhorar.append(
                    {
                        "item_id": item_id,
                        "titulo": str(anuncio.get("titulo") or anuncio.get("family_name") or "")[:60],
                        "preco": float(anuncio.get("preco") or 0),
                        "score": float(perf.get("score") or 0),
                        "level_wording": str(perf.get("level_wording") or ""),
                        "acoes": [str(p.get("titulo") or p.get("key") or "") for p in pend[:3]],
                    }
                )
            elif str(anuncio.get("status") or "").lower() == "paused":
                # Performance UP/item frequentemente indisponível p/ pausados;
                # painel ainda lista como "a melhorar" / atenção.
                a_melhorar.append(
                    {
                        "item_id": item_id,
                        "titulo": str(anuncio.get("titulo") or "")[:60],
                        "preco": float(anuncio.get("preco") or 0),
                        "score": 0,
                        "level_wording": "pausado",
                        "acoes": ["Reativar anúncio"],
                    }
                )

        preco_com_sugestao: list[dict[str, Any]] = []
        anuncios_por_id = {str(a.get("item_id")): a for a in anuncios}
        for item_id in sugestoes_preco_ids:
            item_id = str(item_id).strip()
            if not item_id or item_id not in anuncios_por_id:
                continue
            sug = ml_client.buscar_sugestao_preco(item_id)
            if not sug or not (sug.get("preco_sugerido") or sug.get("aplicavel")):
                continue
            base = anuncios_por_id.get(item_id) or {}
            preco_com_sugestao.append(
                {
                    "item_id": item_id,
                    "titulo": str(base.get("titulo") or sug.get("item_id") or "")[:50],
                    "preco_atual": float(sug.get("preco_atual") or base.get("preco") or 0),
                    "preco_sugerido": float(sug.get("preco_sugerido") or 0),
                    "percent_difference": float(sug.get("percent_difference") or 0),
                    "aplicavel": bool(sug.get("aplicavel")),
                }
            )

        ads_recomendacoes = 0
        try:
            from integracoes.ml import ml_product_ads

            camps = ml_product_ads.listar_campanhas(limit=20) or []
            for c in camps:
                if not isinstance(c, dict):
                    continue
                status = str(c.get("status") or "").upper()
                if status in ("IDLE", "HOLD", "PAUSED", ""):
                    ads_recomendacoes += 1
        except Exception as exc:
            logger.warning("resumo_conta ads: %s", exc)

        return {
            "ok": True,
            "coletado_em": datetime.now(timezone.utc).isoformat(),
            "seller_id": str(perfil.get("id") or ""),
            "nickname": str(perfil.get("nickname") or ""),
            "permalink": str(perfil.get("permalink") or ""),
            "perguntas_pendentes": len(perguntas),
            "anuncios_ativos": ativos,
            "anuncios_pausados": pausados,
            "anuncios_ativos_conta": ativos_conta,
            "anuncios_pausados_conta": pausados_conta,
            "anuncios_total": len(anuncios),
            "anuncios_premium": int(prateleiras.get("premium") or 0),
            "anuncios_classico": int(prateleiras.get("classico") or 0),
            "anuncios_ignorados_fora_foco": ignorados_fora_foco,
            "anuncios_a_melhorar": a_melhorar,
            "anuncios_a_melhorar_total": len(a_melhorar),
            "precos_pendencias": preco_com_sugestao,
            "precos_pendencias_total": len(preco_com_sugestao),
            "publicidade_recomendacoes": ads_recomendacoes,
            "envios_pendentes": int(envios.get("total") or 0),
            "envios_ok": bool(envios.get("ok")),
            "pos_venda_claims": int(claims.get("total") or 0),
            "pos_venda_ok": bool(claims.get("ok")),
            "pos_venda_motivo": str(claims.get("motivo") or ""),
            "reputacao": reputacao,
            "integridade": integridade,
            "faturamento_nota": (
                "Fatura/saldo Mercado Pago não disponíveis só com token ML — "
                "confira no painel ou configure token MP."
            ),
            "anuncios_amostra": [
                {
                    "item_id": a.get("item_id"),
                    "titulo": str(a.get("titulo") or "")[:50],
                    "preco": float(a.get("preco") or 0),
                    "vendidos": int(a.get("sold_quantity") or 0),
                    "status": str(a.get("status") or ""),
                    "listing_type_id": str(a.get("listing_type_id") or ""),
                }
                for a in anuncios[:8]
            ],
        }
    except Exception as exc:
        logger.error("coletar_resumo_conta erro: %s", exc)
        return {"ok": False, "erro": str(exc)}


def emitir_metricas_saude_conta(resumo: dict[str, Any]) -> None:
    """Gauges Datadog da saúde da conta ML (reputação + anúncios + pós-venda)."""
    from core.datadog_metrics import gauge

    if not resumo.get("ok"):
        gauge("ml.saude.ok", 0.0)
        gauge("ml.saude.conta_ok", 0.0)
        return
    from integracoes.empresa.ponto_ruptura_segundo_cnpj import _f, _saude_conta_ok

    rep = resumo.get("reputacao") if isinstance(resumo.get("reputacao"), dict) else {}
    conta_ok, _atual = _saude_conta_ok(
        cor=str(rep.get("cor") or rep.get("level_id") or ""),
        atraso_rate=_f(rep.get("atraso_rate")),
        cancelamentos_rate=_f(rep.get("cancelamentos_rate")),
        claims_rate=_f(rep.get("claims_rate")),
    )
    gauge("ml.saude.ok", 1.0)
    gauge("ml.saude.conta_ok", 1.0 if conta_ok else 0.0)
    gauge("ml.saude.vendas_completadas", float(rep.get("vendas_completadas") or 0))
    gauge("ml.saude.vendas_60d", float(rep.get("vendas_60d") or 0))
    gauge("ml.saude.avaliacoes", float(rep.get("avaliacoes") or 0))
    gauge("ml.saude.nota", float(rep.get("nota") or 0))
    gauge("ml.saude.claims_rate_pct", float(rep.get("claims_rate") or 0) * 100.0)
    gauge("ml.saude.atraso_rate_pct", float(rep.get("atraso_rate") or 0) * 100.0)
    gauge("ml.saude.cancelamentos_rate_pct", float(rep.get("cancelamentos_rate") or 0) * 100.0)
    gauge("ml.saude.nivel", float(rep.get("nivel_num") or 0))
    gauge("ml.saude.power_seller", float(rep.get("power_num") or 0))
    gauge("ml.saude.sem_cor", 1.0 if rep.get("sem_cor") else 0.0)
    gauge("ml.saude.anuncios_ativos", float(resumo.get("anuncios_ativos") or 0))
    gauge("ml.saude.anuncios_pausados", float(resumo.get("anuncios_pausados") or 0))
    gauge("ml.saude.anuncios_ativos_conta", float(resumo.get("anuncios_ativos_conta") or 0))
    gauge("ml.saude.anuncios_pausados_conta", float(resumo.get("anuncios_pausados_conta") or 0))
    gauge("ml.saude.anuncios_premium", float(resumo.get("anuncios_premium") or 0))
    gauge("ml.saude.anuncios_classico", float(resumo.get("anuncios_classico") or 0))
    gauge(
        "ml.saude.anuncios_ignorados_fora_foco",
        float(resumo.get("anuncios_ignorados_fora_foco") or 0),
    )
    gauge(
        "ml.saude.catalogo_foco_vazio",
        1.0
        if (
            int(resumo.get("anuncios_total") or 0) == 0
            and int(resumo.get("anuncios_ignorados_fora_foco") or 0) > 0
        )
        else 0.0,
    )
    gauge("ml.saude.anuncios_a_melhorar", float(resumo.get("anuncios_a_melhorar_total") or 0))
    gauge("ml.saude.perguntas_pendentes", float(resumo.get("perguntas_pendentes") or 0))
    gauge("ml.saude.envios_pendentes", float(resumo.get("envios_pendentes") or 0))
    gauge("ml.saude.claims_abertos", float(resumo.get("pos_venda_claims") or 0))
    gauge("ml.saude.precos_pendencias", float(resumo.get("precos_pendencias_total") or 0))
    gauge("ml.saude.todos_pausados", 1.0 if (
        int(resumo.get("anuncios_pausados") or 0) > 0
        and int(resumo.get("anuncios_ativos") or 0) == 0
    ) else 0.0)


def montar_mensagem_telegram(resumo: dict[str, Any]) -> str:
    """Formata o resumo no estilo do painel Resumo do vendedor."""
    from core.telegram_explicacao import cabecalho_agente

    if not resumo.get("ok"):
        return (
            cabecalho_agente("resumo_conta_ml", "📋 *Resumo conta ML*")
            + f"\n\n❌ Falha na coleta: `{resumo.get('erro', 'desconhecido')}`"
        )

    rep = resumo.get("reputacao") if isinstance(resumo.get("reputacao"), dict) else {}
    nick = resumo.get("nickname") or "—"
    linhas = [
        cabecalho_agente("resumo_conta_ml", "📋 *Resumo da conta — Mercado Livre*"),
        "",
        f"_Espelho do painel Resumo · {_data_brt()} BRT_",
        f"*Loja:* `{nick}` (seller `{resumo.get('seller_id') or '—'}`)",
        _linha_integridade(resumo.get("integridade")),
        "",
        "*Pendências nos anúncios*",
        f"  • Perguntas: *{int(resumo.get('perguntas_pendentes') or 0)}*",
        f"  • Anúncios a melhorar: *{int(resumo.get('anuncios_a_melhorar_total') or 0)}* "
        f"(de {int(resumo.get('anuncios_total') or resumo.get('anuncios_ativos') or 0)} listados)",
        f"  • Ativos (foco): *{int(resumo.get('anuncios_ativos') or 0)}* · "
        f"Pausados (foco): *{int(resumo.get('anuncios_pausados') or 0)}*",
        f"  • Exposição: *{int(resumo.get('anuncios_premium') or 0)}* Premium · "
        f"*{int(resumo.get('anuncios_classico') or 0)}* Clássico",
        f"  • Preços c/ sugestão ML: *{int(resumo.get('precos_pendencias_total') or 0)}*",
        f"  • Publicidade (campanhas idle/pausadas): *{int(resumo.get('publicidade_recomendacoes') or 0)}*",
        "",
        "*Pendências em vendas*",
        f"  • Envios pendentes: *{int(resumo.get('envios_pendentes') or 0)}*"
        + ("" if resumo.get("envios_ok") else " _(API parcial)_"),
        f"  • Pós-venda (claims abertos): *{int(resumo.get('pos_venda_claims') or 0)}*"
        + (
            ""
            if resumo.get("pos_venda_ok")
            else " _(API claims indisponivel p/ este app)_"
        ),
        "",
        "*Reputação*",
        f"  • Cor: *{rep.get('cor', '—')}*",
        f"  • Vendas completadas: *{int(rep.get('vendas_completadas') or 0)}*",
        f"  • Avaliações: *{int(rep.get('avaliacoes') or 0)}* · nota *{float(rep.get('nota') or 0):.1f}*",
        f"  • Claims rate: *{float(rep.get('claims_rate') or 0) * 100:.2f}%*",
        f"  • Mercado Líder: *{rep.get('power_seller', '—')}*",
    ]
    if rep.get("sem_cor"):
        linhas.append("  _Ao alcançar 10 vendas você terá cor de reputação._")
    ignorados = int(resumo.get("anuncios_ignorados_fora_foco") or 0)
    if ignorados > 0:
        linhas.append(
            f"  _{ignorados} anúncio(s) de bolsas/legado ignorados. "
            "Radar só vê Impala/Masterprint. Reputação da conta continua valendo._"
        )
    if int(resumo.get("anuncios_total") or 0) == 0 and ignorados > 0:
        linhas.append("  _Nenhum anúncio do foco no ar. Publique os kits Impala quando estiver pronto._")
    elif int(resumo.get("anuncios_pausados") or 0) > 0 and int(resumo.get("anuncios_ativos") or 0) == 0:
        linhas.append(
            "  ⚠️ *Todos os anúncios do foco estão pausados* — reative para voltar a vender."
        )

    linhas.extend(
        [
            "",
            "*Faturamento / saldo*",
            f"  _{resumo.get('faturamento_nota')}_",
        ]
    )

    melhorar = resumo.get("anuncios_a_melhorar") or []
    if melhorar:
        linhas.append("")
        linhas.append("*Top anúncios a melhorar*")
        for row in melhorar[:6]:
            acoes = ", ".join(a for a in (row.get("acoes") or []) if a) or "ações pendentes"
            linhas.append(
                f"  • `{row.get('item_id')}` score {row.get('score', 0):.0f} — "
                f"{row.get('titulo', '')}\n    _{acoes}_"
            )

    precos = resumo.get("precos_pendencias") or []
    aplicaveis = [p for p in precos if p.get("aplicavel") and p.get("preco_sugerido")]
    if aplicaveis:
        linhas.append("")
        linhas.append("*Sugestões de preço*")
        for p in aplicaveis[:5]:
            linhas.append(
                f"  • `{p.get('item_id')}` {_fmt_brl(float(p.get('preco_atual') or 0))} → "
                f"*{_fmt_brl(float(p.get('preco_sugerido') or 0))}* "
                f"({float(p.get('percent_difference') or 0):+.1f}%)"
            )

    amostra = resumo.get("anuncios_amostra") or []
    if amostra:
        linhas.append("")
        linhas.append("*Seus anúncios (amostra)*")
        for a in amostra[:5]:
            linhas.append(
                f"  • `{a.get('item_id')}` [{a.get('status') or '?'}] "
                f"{_fmt_brl(float(a.get('preco') or 0))} · "
                f"{int(a.get('vendidos') or 0)} vend. — {a.get('titulo', '')}"
            )

    linhas.extend(
        [
            "",
            "*Ação:* abra mercadolivre.com.br/resumo para fatura/saldo; "
            "corrija anúncios a melhorar e responda perguntas.",
        ]
    )
    return "\n".join(linhas).strip()
