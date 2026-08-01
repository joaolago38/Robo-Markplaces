"""
agentes/ml/agente_ads_gatilho.py
Decide automaticamente quando ligar, escalar ou pausar Product Ads no ML.
Baseado em avaliações reais, nota média e ACOS atual.
"""
from __future__ import annotations

import logging
from datetime import datetime

from core.config import (
    ACOS_MAXIMO,
    AVALIACOES_PARA_ADS,
    AVALIACOES_PARA_ESCALAR,
    BUDGET_FASE_CRESCIMENTO,
    BUDGET_FASE_ESCALA,
    BUDGET_FASE_INICIO,
    ML_ADS_ACOS_DIAS_LIMITE,
    NOTA_MINIMA_PARA_ADS,
)
from core.notificador import alertar_gestor, perguntar_gestor_e_aguardar
from integracoes.ml.ml_client import buscar_acos_ads, buscar_reputacao_vendedor
from integracoes.ml.ml_product_ads import (
    aplicar_decisao_campanhas,
    campanhas_acos_acima_limite,
    listar_campanhas,
    probe_escrita_product_ads,
)

logger = logging.getLogger("agente_ads_gatilho")


def _contexto_decisao_ads(
    decisao: str,
    avaliacoes: int,
    nota_media: float,
    acos_atual: float,
    full_ativo: bool,
    budget_sugerido: float,
    motivos: list[str],
) -> dict:
    """Contexto para justificativa Claude em perguntar_gestor_e_aguardar (item notificador)."""
    ctx = {
        "decisao": decisao,
        "avaliacoes": avaliacoes,
        "nota_media": nota_media,
        "acos_atual": acos_atual,
        "full_ativo": full_ativo,
        "budget_sugerido_dia": budget_sugerido,
        "motivos": motivos,
        "mes_atual": datetime.now().month,
    }
    if datetime.now().month in (10, 11, 12) and any(
        "sazonal" in m.lower() or "out-dez" in m.lower() for m in motivos
    ):
        ctx["sazonalidade_out_dez"] = True
    return ctx


def avaliar_momento_ads(
    avaliacoes: int,
    nota_media: float,
    acos_atual: float = 0.0,
    full_ativo: bool = False,
) -> dict:
    decisao = "aguardar"
    budget_sugerido = 0.0
    motivos = []
    gasto_diario_estimado_evitado = 0.0

    if avaliacoes < AVALIACOES_PARA_ADS:
        motivos.append(f"Avaliações insuficientes: {avaliacoes}/{AVALIACOES_PARA_ADS}")
        motivos.append("Focar em orgânico + Programa Decola")

    elif nota_media < NOTA_MINIMA_PARA_ADS:
        motivos.append(f"Nota abaixo do mínimo: {nota_media:.1f}/{NOTA_MINIMA_PARA_ADS}")
        motivos.append("Melhorar atendimento antes de investir em ads")

    elif acos_atual > ACOS_MAXIMO and acos_atual > 0:
        decisao = "pausar"
        budget_sugerido = 0.0
        motivos.append(f"ACOS alto: {acos_atual*100:.0f}% (máx {ACOS_MAXIMO*100:.0f}%)")
        motivos.append("Revisar título e preço antes de religar")
        try:
            campanhas_ruins = campanhas_acos_acima_limite()
            gasto_periodo = sum(float(c.get("cost") or 0) for c in campanhas_ruins)
            gasto_diario_estimado_evitado = round(
                gasto_periodo / max(1, ML_ADS_ACOS_DIAS_LIMITE),
                2,
            )
        except Exception as exc:
            logger.warning("Não foi possível estimar gasto diário das campanhas: %s", exc)

    elif datetime.now().month in (10, 11, 12) and avaliacoes >= AVALIACOES_PARA_ADS and nota_media >= NOTA_MINIMA_PARA_ADS:
        decisao = "escalar"
        budget_sugerido = BUDGET_FASE_ESCALA
        motivos.append("Pico sazonal (Out-Dez) — escalar agressivo")
        motivos.append(f"Budget sugerido: R$ {BUDGET_FASE_ESCALA}/dia")

    elif full_ativo and avaliacoes >= AVALIACOES_PARA_ESCALAR:
        decisao = "escalar"
        budget_sugerido = BUDGET_FASE_CRESCIMENTO
        motivos.append("Full ativo + volume sólido — escalar budget")
        motivos.append(f"Budget sugerido: R$ {BUDGET_FASE_CRESCIMENTO}/dia")

    elif avaliacoes >= AVALIACOES_PARA_ADS:
        decisao = "ligar"
        budget_sugerido = BUDGET_FASE_INICIO
        motivos.append("Avaliações suficientes para iniciar Product Ads")
        motivos.append(f"Budget: R$ {BUDGET_FASE_INICIO}/dia — campanha automática por 2 semanas")

    # Contrato impulso: sem SKU guerra+MLB liberado, não liga/escala
    if decisao in ("ligar", "escalar"):
        try:
            from integracoes.ml.contrato_impulso_ml import ads_pode_ligar, montar_contrato

            montar_contrato()
            pode_ads, motivo_contrato = ads_pode_ligar()
            if not pode_ads:
                motivos.append(f"Contrato impulso ML: {motivo_contrato}")
                motivos.append("Publique/preencha MLB dos SKUs de guerra antes de ads")
                decisao = "aguardar"
                budget_sugerido = 0.0
        except Exception as exc:
            logger.warning("Contrato impulso ads: %s", exc)

    resultado = {
        "decisao": decisao,
        "budget_sugerido_dia": budget_sugerido,
        "avaliacoes": avaliacoes,
        "nota_media": nota_media,
        "acos_atual": acos_atual,
        "full_ativo": full_ativo,
        "motivos": motivos,
        "confirmado_gestor": None,
        "gasto_diario_estimado_evitado": 0.0,
    }

    if decisao == "pausar":
        resultado["gasto_diario_estimado_evitado"] = gasto_diario_estimado_evitado

    # Antes de pedir aprovação para ações de escrita, valida scopes Product Ads
    if decisao in ("ligar", "pausar", "escalar"):
        probe = probe_escrita_product_ads()
        resultado["probe_escrita"] = probe
        if not probe.get("ok"):
            msg_probe = (
                "⚠️ *ADS ML — escrita Product Ads indisponível*\n\n"
                f"Decisão sugerida: *{decisao}*, mas a API recusou escrita.\n"
                f"Código: `{probe.get('codigo')}`\n"
                f"Erro: `{probe.get('erro')}`\n\n"
                "Libere Product Ads no DevCenter / regenerar token com scopes de advertising "
                "antes de aprovar ligar/pausar/escalar."
            )
            alertar_gestor(msg_probe, chave="ads_ml:probe_escrita_falhou", cooldown_segundos=86400)
            resultado["confirmado_gestor"] = False
            resultado["decisao"] = "aguardar" if decisao == "ligar" else "manter"
            resultado["motivos"] = list(motivos) + [
                f"Probe escrita falhou: {probe.get('codigo')} — {probe.get('erro')}"
            ]
            logger.warning("Ads gatilho: probe escrita falhou — %s", probe)
            return resultado

    if decisao == "ligar":
        pergunta = (
            f"🟢 *ADS ML — LIGAR Product Ads*\n\n"
            f"📊 Avaliações: {avaliacoes} | Nota: {nota_media:.1f}\n"
            f"💰 Budget sugerido: R$ {budget_sugerido:.2f}/dia\n"
            f"📋 Motivo: {motivos[0] if motivos else 'critérios atingidos'}\n\n"
            f"Deseja LIGAR o Product Ads agora?"
        )
        ctx = _contexto_decisao_ads(decisao, avaliacoes, nota_media, acos_atual, full_ativo, budget_sugerido, motivos)
        confirmado = perguntar_gestor_e_aguardar(pergunta, timeout_segundos=600, contexto_decisao=ctx)
        resultado["confirmado_gestor"] = confirmado
        if confirmado:
            alertar_gestor(
                f"✅ ADS ML: LIGANDO Product Ads — aprovado pelo gestor\n"
                f"Budget: R$ {budget_sugerido}/dia\n"
                + "\n".join(motivos)
            )
            logger.info("Gestor APROVOU ligar ads — budget R$ %.2f/dia", budget_sugerido)
        else:
            alertar_gestor("⏸ ADS ML: ação de LIGAR cancelada ou sem resposta do gestor.")
            logger.info("Gestor RECUSOU ou não respondeu — ads não ligado")
            resultado["decisao"] = "aguardar"

    elif decisao == "pausar":
        pergunta = (
            f"🔴 *ADS ML — PAUSAR Product Ads*\n\n"
            f"📈 ACOS atual: {acos_atual*100:.0f}% (limite: {ACOS_MAXIMO*100:.0f}%)\n"
            f"📋 Motivo: {motivos[0] if motivos else 'ACOS acima do limite'}\n\n"
            f"Deseja PAUSAR o Product Ads agora?"
        )
        confirmado = perguntar_gestor_e_aguardar(
            pergunta, timeout_segundos=600,
            contexto_decisao=_contexto_decisao_ads(
                decisao, avaliacoes, nota_media, acos_atual, full_ativo, budget_sugerido, motivos
            ),
        )
        resultado["confirmado_gestor"] = confirmado
        if confirmado:
            alertar_gestor(
                f"✅ ADS ML: PAUSANDO — aprovado pelo gestor\n"
                f"ACOS: {acos_atual*100:.0f}%\n"
                + "\n".join(motivos)
            )
            logger.info("Gestor APROVOU pausar ads — ACOS %.0f%%", acos_atual * 100)
        else:
            alertar_gestor("⏸ ADS ML: ação de PAUSAR cancelada ou sem resposta do gestor.")
            logger.info("Gestor RECUSOU ou não respondeu — ads não pausado")
            resultado["decisao"] = "manter"

    elif decisao == "escalar":
        pergunta = (
            f"🚀 *ADS ML — ESCALAR Budget*\n\n"
            f"📊 Avaliações: {avaliacoes} | Full ativo: {'Sim' if full_ativo else 'Não'}\n"
            f"💰 Novo budget sugerido: R$ {budget_sugerido:.2f}/dia\n"
            f"📋 Motivo: {motivos[0] if motivos else 'critérios de escala atingidos'}\n\n"
            f"Deseja ESCALAR o budget de ads agora?"
        )
        ctx = _contexto_decisao_ads(decisao, avaliacoes, nota_media, acos_atual, full_ativo, budget_sugerido, motivos)
        confirmado = perguntar_gestor_e_aguardar(pergunta, timeout_segundos=600, contexto_decisao=ctx)
        resultado["confirmado_gestor"] = confirmado
        if confirmado:
            alertar_gestor(
                f"✅ ADS ML: ESCALANDO budget — aprovado pelo gestor\n"
                f"Novo budget: R$ {budget_sugerido}/dia\n"
                + "\n".join(motivos)
            )
            logger.info("Gestor APROVOU escalar ads — budget R$ %.2f/dia", budget_sugerido)
        else:
            alertar_gestor("⏸ ADS ML: ação de ESCALAR cancelada ou sem resposta do gestor.")
            logger.info("Gestor RECUSOU ou não respondeu — budget não escalado")
            resultado["decisao"] = "manter"

    logger.info("Gatilho ads: %s", resultado)
    return _executar_api_se_aprovado(resultado)


def _calcular_acos_agregado(dias: int = 14) -> float:
    """ACOS ponderado por gasto das campanhas com cost > 0."""
    try:
        campanhas = listar_campanhas(dias=dias)
        com_gasto = [c for c in campanhas if c.get("cost", 0) > 0]
        if not com_gasto:
            return 0.0
        gasto_total = sum(c["cost"] for c in com_gasto)
        return sum(c["acos"] * c["cost"] for c in com_gasto) / gasto_total
    except Exception as exc:
        logger.warning("Não foi possível calcular ACOS agregado: %s", exc)
        return 0.0


def _executar_api_se_aprovado(resultado: dict) -> dict:
    """Após confirmação do gestor, aplica a decisão nas campanhas Product Ads via API."""
    if not resultado.get("confirmado_gestor"):
        return resultado

    decisao = resultado.get("decisao")
    mapa = {"ligar": "ativar", "pausar": "pausar", "escalar": "escalar"}
    api_decisao = mapa.get(decisao)
    if not api_decisao:
        return resultado

    kwargs: dict = {
        "budget": float(resultado.get("budget_sugerido_dia") or 0),
        "dry_run": False,
        "confirmar": True,
    }
    # Pausa seletiva: só campanhas com ACOS acima do limite (ligar/escalar mantém todas).
    if api_decisao == "pausar":
        campanhas_acima = campanhas_acos_acima_limite()
        ids_acima = [c["id"] for c in campanhas_acima if c.get("id")]
        if ids_acima:
            kwargs["campaign_ids"] = ids_acima

    aplicacoes = aplicar_decisao_campanhas(api_decisao, **kwargs)
    resultado["aplicacoes_api"] = aplicacoes
    ok = sum(1 for a in aplicacoes if a.get("ok"))
    alertar_gestor(
        f"ML Product Ads API ({decisao}): {ok}/{len(aplicacoes)} campanha(s) processada(s)."
    )
    return resultado


def executar(item_id: str = "", acos_atual: float = 0.0, full_ativo: bool = False) -> dict:
    rep = buscar_reputacao_vendedor()
    if item_id and acos_atual == 0.0:
        acos_atual = buscar_acos_ads(item_id)
    elif acos_atual == 0.0:
        acos_atual = _calcular_acos_agregado()
    metrics = rep.get("metrics", {})
    avaliacoes = int(metrics.get("total_ratings", 0))
    nota = float(metrics.get("average_rating", 0.0))
    if not full_ativo:
        full_ativo = bool(metrics.get("power_seller_status") in ("gold", "platinum"))
    return avaliar_momento_ads(avaliacoes, nota, acos_atual, full_ativo)


if __name__ == "__main__":
    import pprint
    pprint.pprint(executar())
