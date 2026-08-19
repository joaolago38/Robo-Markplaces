"""
agentes/ml/agente_monitor_ml.py
Varredura de leitura do Mercado Livre: conta, Product Ads e concorrência.
Somente diagnóstico e recomendação — NÃO altera preço, campanha ou orçamento.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from core.config import (
    ACOS_MAXIMO,
    ML_ADS_ORCAMENTO_MAXIMO,
)
from core.config import (
    ML_MAX_ITENS_ANALISE as MAX_ITENS_ANALISE,
)
from core.notificador import alertar_gestor
from integracoes.ml import ml_client, ml_product_ads

logger = logging.getLogger("agente_monitor_ml")

PAUSA_ENTRE_CHAMADAS_S = 0.15
LIMIAR_PRECO_CONCORRENTE = 0.05
CLAIMS_RATE_ALTO = 0.05
DIAS_SEM_ACESSO_ALTO = 7
ROAS_BAIXO = 1.0
CLICKS_ALTOS = 20


def _pct_diff(maior: float, menor: float) -> float:
    if menor <= 0:
        return 0.0
    return round((maior - menor) / menor * 100, 1)


def _analisar_conta() -> tuple[dict[str, Any], list[str]]:
    recomendacoes: list[str] = []
    conta: dict[str, Any] = {}

    try:
        saude = ml_client.obter_saude_conta()
        conta["saude"] = saude
    except Exception as exc:
        logger.error("monitor_ml obter_saude_conta: %s", exc)
        saude = {}
        conta["erro_saude"] = str(exc)

    try:
        perguntas = ml_client.listar_perguntas_nao_respondidas()
        conta["perguntas_pendentes"] = len(perguntas)
        conta["perguntas_amostra"] = perguntas[:3]
    except Exception as exc:
        logger.error("monitor_ml listar_perguntas: %s", exc)
        perguntas = []
        conta["perguntas_pendentes"] = 0

    try:
        reputacao = ml_client.buscar_reputacao_vendedor()
        conta["reputacao"] = reputacao
    except Exception as exc:
        logger.error("monitor_ml buscar_reputacao: %s", exc)
        reputacao = {}

    qtd = conta.get("perguntas_pendentes", 0)
    if qtd:
        recomendacoes.append(
            f"Responder {qtd} pergunta(s) não respondida(s) no Mercado Livre (prioridade alta)."
        )

    claims = float(saude.get("claims_rate") or 0)
    if claims > CLAIMS_RATE_ALTO:
        recomendacoes.append(
            f"Claims rate elevado ({claims*100:.1f}%) — revisar pós-venda e prazos de envio."
        )

    dias = int(saude.get("dias_sem_acesso") or 0)
    if dias > DIAS_SEM_ACESSO_ALTO:
        recomendacoes.append(
            f"Conta sem acesso há {dias} dia(s) — risco de perda de relevância no algoritmo."
        )

    nivel = (reputacao or {}).get("level_id", "")
    if nivel and str(nivel).lower() in {"red", "orange"}:
        recomendacoes.append(
            f"Reputação em nível de atenção ({nivel}) — focar em qualidade e entregas."
        )

    return conta, recomendacoes


def _analisar_ads(dias: int = 14) -> tuple[dict[str, Any], list[str]]:
    recomendacoes: list[str] = []
    ads: dict[str, Any] = {"configurado": False}

    try:
        adv = ml_product_ads.obter_advertiser()
        ads["advertiser"] = adv
    except Exception as exc:
        logger.error("monitor_ml obter_advertiser: %s", exc)
        ads["erro"] = str(exc)
        recomendacoes.append(f"Não foi possível consultar Product Ads: {exc}")
        return ads, recomendacoes

    if not adv.get("ok"):
        codigo = adv.get("codigo", "")
        msg = adv.get("erro", "Product Ads indisponível")
        if codigo == "sem_permissao":
            ads["pendencia"] = "Publicidade não habilitada"
            recomendacoes.append(
                "Habilitar Publicidade em Mercado Livre > Mi perfil > Publicidad."
            )
        else:
            ads["pendencia"] = msg
            recomendacoes.append(f"Product Ads: {msg}")
        return ads, recomendacoes

    ads["configurado"] = True
    advertiser_id = adv.get("advertiser_id", "")

    try:
        campanhas = ml_product_ads.listar_campanhas(advertiser_id, dias=dias)
        ads["campanhas"] = campanhas
        ads["total_campanhas"] = len(campanhas)
        ads["campanhas_ativas"] = sum(
            1 for c in campanhas if str(c.get("status", "")).lower() == "active"
        )
    except Exception as exc:
        logger.error("monitor_ml listar_campanhas: %s", exc)
        campanhas = []
        ads["erro_campanhas"] = str(exc)

    try:
        acima = ml_product_ads.campanhas_acos_acima_limite(dias=dias)
        ads["campanhas_acos_alto"] = acima
        for c in acima[:5]:
            recomendacoes.append(
                f"Revisar campanha '{c.get('nome', '?')[:40]}' — ACOS "
                f"{float(c.get('acos', 0))*100:.0f}% (limite {ACOS_MAXIMO*100:.0f}%). "
                "Considere baixar lance ou pausar."
            )
    except Exception as exc:
        logger.error("monitor_ml campanhas_acos_acima_limite: %s", exc)

    gasto_total = sum(float(c.get("cost") or 0) for c in campanhas)
    ads["gasto_total"] = round(gasto_total, 2)
    if gasto_total > ML_ADS_ORCAMENTO_MAXIMO:
        recomendacoes.append(
            f"Gasto de ads R$ {gasto_total:.2f} acima do teto "
            f"R$ {ML_ADS_ORCAMENTO_MAXIMO:.2f} — revisar orçamento."
        )

    for c in campanhas:
        if str(c.get("status", "")).lower() != "active":
            continue
        clicks = int(c.get("clicks") or 0)
        roas = float(c.get("roas") or 0)
        if clicks >= CLICKS_ALTOS and 0 < roas < ROAS_BAIXO:
            recomendacoes.append(
                f"Campanha '{c.get('nome', '?')[:40]}' com {clicks} cliques e ROAS "
                f"{roas:.2f} — ajustar criativo, lance ou landing."
            )

    if ads.get("campanhas_ativas", 0) == 0 and campanhas:
        recomendacoes.append(
            "Nenhuma campanha ativa — avaliar se faz sentido ligar Product Ads "
            "(após revisar margem e reputação)."
        )

    return ads, recomendacoes


def _analisar_concorrencia(limite_itens: int = MAX_ITENS_ANALISE) -> tuple[list[dict], list[str]]:
    recomendacoes: list[str] = []
    itens: list[dict] = []

    try:
        from integracoes.ml.filtro_anuncios_conta import filtrar_anuncios_foco

        anuncios_todos = ml_client.listar_meus_anuncios(
            statuses=("active", "paused"),
            aplicar_foco=False,
        )
        try:
            from integracoes.ml.integridade_dados_ml import executar as auditar_ml

            auditar_ml(anuncios=anuncios_todos)
        except Exception as exc:
            logger.info("integridade ML: %s", exc)
        anuncios, _ = filtrar_anuncios_foco(anuncios_todos)
        anuncios = anuncios[:limite_itens]
    except Exception as exc:
        logger.error("monitor_ml listar_meus_anuncios: %s", exc)
        return [], [f"Não foi possível listar anúncios: {exc}"]

    for anuncio in anuncios:
        item_id = str(anuncio.get("item_id") or "").strip()
        if not item_id:
            continue

        try:
            metricas = ml_client.buscar_metricas_item(item_id) or {}
        except Exception as exc:
            logger.error("monitor_ml metricas %s: %s", item_id, exc)
            metricas = {}

        try:
            menor_concorrente = ml_client.buscar_menor_preco_concorrente(item_id)
        except Exception as exc:
            logger.error("monitor_ml menor_preco %s: %s", item_id, exc)
            menor_concorrente = 0.0
        try:
            menor_qualquer = ml_client.buscar_menor_preco_concorrente(
                item_id, mesma_prateleira=False
            )
        except Exception as exc:
            logger.error("monitor_ml menor_preco_qualquer %s: %s", item_id, exc)
            menor_qualquer = menor_concorrente

        try:
            concorrentes = ml_client.buscar_detalhes_concorrentes(item_id, limite=5)
        except Exception as exc:
            logger.error("monitor_ml detalhes_concorrentes %s: %s", item_id, exc)
            concorrentes = []

        try:
            sugestao = ml_client.buscar_sugestao_preco(item_id)
        except Exception as exc:
            logger.error("monitor_ml sugestao_preco %s: %s", item_id, exc)
            sugestao = {}

        try:
            acos_item = ml_client.buscar_acos_ads(item_id, dias=14)
        except Exception as exc:
            logger.error("monitor_ml acos_item %s: %s", item_id, exc)
            acos_item = 0.0

        meu_preco = float(metricas.get("preco") or anuncio.get("preco") or 0)
        visitas_7 = int(metricas.get("visitas_7d") or 0)
        visitas_30 = int(metricas.get("visitas_30d") or 0)
        estoque = metricas.get("estoque")
        prioridade = 0.0
        meu_tipo = str(
            metricas.get("listing_type_id") or anuncio.get("listing_type_id") or ""
        )

        analise: dict[str, Any] = {
            "item_id": item_id,
            "titulo": metricas.get("titulo") or anuncio.get("titulo", ""),
            "sku": anuncio.get("sku", ""),
            "listing_type_id": meu_tipo,
            "meu_preco": meu_preco,
            "menor_concorrente": menor_concorrente,
            "concorrentes": concorrentes,
            "sugestao_preco": sugestao,
            "visitas_7d": visitas_7,
            "visitas_30d": visitas_30,
            "estoque": estoque,
            "acos_ads": acos_item,
            "alertas": [],
        }

        if sugestao.get("aplicavel") and sugestao.get("preco_sugerido", 0) > 0:
            preco_sugerido = sugestao["preco_sugerido"]
            diff_sugestao = sugestao.get("percent_difference", 0)
            if abs(diff_sugestao) >= LIMIAR_PRECO_CONCORRENTE * 100:
                msg = (
                    f"Item {item_id}: ML sugere R$ {preco_sugerido:.2f} "
                    f"(seu preço R$ {meu_preco:.2f}, diferença {diff_sugestao:.1f}%) "
                    "com base em produtos similares dentro/fora da ML."
                )
                analise["alertas"].append(msg)
                recomendacoes.append(msg)
                prioridade = max(prioridade, abs(diff_sugestao))

        if menor_concorrente > 0 and meu_preco > menor_concorrente:
            diff = _pct_diff(meu_preco, menor_concorrente)
            analise["diff_preco_pct"] = diff
            if diff > LIMIAR_PRECO_CONCORRENTE * 100:
                msg = (
                    f"Item {item_id}: preço R$ {meu_preco:.2f} está {diff:.1f}% acima do "
                    f"concorrente na mesma exposição (R$ {menor_concorrente:.2f}) — revisar preço."
                )
                analise["alertas"].append(msg)
                recomendacoes.append(msg)
                prioridade = max(prioridade, diff)

        if (
            menor_qualquer > 0
            and (menor_concorrente <= 0 or menor_qualquer + 0.005 < menor_concorrente)
        ):
            from integracoes.ml.tipo_anuncio_ml import rotulo_prateleira

            msg = (
                f"Item {item_id}: menor do catálogo R$ {menor_qualquer:.2f} é outra "
                f"exposição (seu anúncio: {rotulo_prateleira(meu_tipo)}) — não igualar preço."
            )
            analise["alertas"].append(msg)
            recomendacoes.append(msg)

        if (
            menor_concorrente > 0
            and meu_preco <= menor_concorrente
            and visitas_7 >= 20
            and isinstance(estoque, int)
            and estoque > 10
        ):
            msg = (
                f"Item {item_id}: menor preço e visitas altas ({visitas_7}/7d) com estoque "
                f"— revisar título/fotos para melhorar conversão."
            )
            analise["alertas"].append(msg)
            recomendacoes.append(msg)
            prioridade = max(prioridade, visitas_7 / 10)

        media_semanal_30 = visitas_30 / 4.0 if visitas_30 else 0
        if media_semanal_30 > 0 and visitas_7 < media_semanal_30 * 0.5:
            msg = (
                f"Item {item_id}: queda de tráfego — {visitas_7} visitas/7d vs "
                f"~{media_semanal_30:.0f}/semana (base 30d)."
            )
            analise["alertas"].append(msg)
            recomendacoes.append(msg)
            prioridade = max(prioridade, media_semanal_30 - visitas_7)

        analise["prioridade"] = prioridade
        itens.append(analise)
        time.sleep(PAUSA_ENTRE_CHAMADAS_S)

    itens.sort(key=lambda x: x.get("prioridade", 0), reverse=True)
    return itens, recomendacoes


def _montar_resumo(
    conta: dict,
    ads: dict,
    concorrencia: list[dict],
    recomendacoes: list[str],
) -> str:
    linhas = [
        "📊 *Conta*",
        f"• Perguntas pendentes: {conta.get('perguntas_pendentes', '?')}",
    ]
    saude = conta.get("saude") or {}
    if saude:
        linhas.append(
            f"• Claims rate: {float(saude.get('claims_rate', 0))*100:.1f}% | "
            f"Dias sem acesso: {saude.get('dias_sem_acesso', '?')}"
        )

    linhas.append("")
    linhas.append("📣 *Ads*")
    if ads.get("configurado"):
        linhas.append(
            f"• Campanhas: {ads.get('total_campanhas', 0)} "
            f"({ads.get('campanhas_ativas', 0)} ativas) | "
            f"Gasto período: R$ {ads.get('gasto_total', 0):.2f}"
        )
        acima = ads.get("campanhas_acos_alto") or []
        if acima:
            linhas.append(f"• {len(acima)} campanha(s) com ACOS acima do limite")
    else:
        linhas.append(f"• {ads.get('pendencia', 'Product Ads não consultado')}")

    linhas.append("")
    linhas.append("🔎 *Concorrência*")
    if concorrencia:
        for item in concorrencia[:5]:
            titulo = str(item.get("titulo", "?"))[:35]
            linhas.append(
                f"• {titulo} | R$ {item.get('meu_preco', 0):.2f} vs "
                f"conc. R$ {item.get('menor_concorrente', 0):.2f}"
            )
    else:
        linhas.append("• Nenhum anúncio analisado")

    linhas.append("")
    linhas.append("✅ *Ajustes recomendados*")
    unicas = list(dict.fromkeys(recomendacoes))
    if unicas:
        for i, rec in enumerate(unicas[:12], start=1):
            linhas.append(f"{i}. {rec}")
    else:
        linhas.append("1. Nenhum ajuste urgente — manter monitoramento.")

    return "\n".join(linhas)


def analisar(*, limite_itens: int = MAX_ITENS_ANALISE, enviar_alerta: bool = True) -> dict:
    """
    Varredura completa ML (somente leitura). Retorna dict estruturado e envia resumo ao gestor.
    """
    if not ml_client._enabled():
        motivo = "ML não configurado"
        msg = (
            "Mercado Livre não configurado — defina ML_ACCESS_TOKEN e ML_SELLER_ID "
            "(e credenciais OAuth para renovação)."
        )
        enviado = False
        if enviar_alerta:
            try:
                enviado = bool(alertar_gestor(msg))
            except Exception as exc:
                logger.error("monitor_ml alerta credenciais: %s", exc)
        return {"ok": False, "motivo": motivo, "enviado": enviado, "resumo": msg}

    dias_ads = 14

    conta, rec_conta = _analisar_conta()
    ads, rec_ads = _analisar_ads(dias=dias_ads)
    concorrencia, rec_conc = _analisar_concorrencia(limite_itens=limite_itens)

    todas_recs = rec_conta + rec_ads + rec_conc
    resumo = _montar_resumo(conta, ads, concorrencia, todas_recs)

    enviado = False
    enviado_p0 = False
    if enviar_alerta:
        try:
            from integracoes.ml.alerta_pendencias_loja import emitir_alerta_p0_do_ciclo

            enviado_p0 = bool(
                emitir_alerta_p0_do_ciclo(
                    perguntas_pendentes=int(conta.get("perguntas_pendentes") or 0),
                    reputacao=conta.get("reputacao") if isinstance(conta.get("reputacao"), dict) else {},
                ).get("enviado")
            )
        except Exception as exc:
            logger.warning("monitor_ml P0: %s", exc)
        try:
            enviado = bool(
                alertar_gestor(
                    resumo,
                    chave="ml:monitor_ml:resumo",
                    cooldown_segundos=7200,
                    agente_id="monitor_ml",
                )
            )
        except Exception as exc:
            logger.error("monitor_ml alertar_gestor: %s", exc)

    return {
        "ok": True,
        "conta": conta,
        "ads": ads,
        "concorrencia": concorrencia,
        "recomendacoes": list(dict.fromkeys(todas_recs)),
        "resumo": resumo,
        "enviado": enviado,
        "enviado_p0": enviado_p0,
    }


def main() -> int:
    resultado = analisar()
    print(resultado.get("resumo") or resultado.get("motivo", "Sem resultado"))
    if not resultado.get("ok"):
        return 0
    print()
    print(f"[INFO] Recomendações: {len(resultado.get('recomendacoes', []))}")
    print(f"[INFO] Alerta gestor enviado: {resultado.get('enviado')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
