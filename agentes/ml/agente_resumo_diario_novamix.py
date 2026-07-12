"""
agentes/ml/agente_resumo_diario_novamix.py
Resumo diário da loja NOVAMIX_COMERCIAL no Telegram:
perfil, desempenho, produtos com giro e plano de ação (Ads/preço/canal).

Opcionalmente pede confirmação e pausa/liga Product Ads conforme o plano.

Uso:
  python -m agentes.ml.agente_resumo_diario_novamix
  python -m agentes.ml.agente_resumo_diario_novamix --sem-alerta
  python -m agentes.ml.agente_resumo_diario_novamix --sem-ads
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    MONITOR_CONCORRENTES_ARQUIVO,
    NOVAMIX_AUTO_ADS_PEDIR_CONFIRMACAO,
    NOVAMIX_RESUMO_DIARIO_ALERTA,
    NOVAMIX_RESUMO_DIARIO_COOLDOWN_SEG,
    NOVAMIX_RESUMO_DIARIO_ENRIQUECER,
    NOVAMIX_RESUMO_DIARIO_NICKNAME,
    NOVAMIX_RESUMO_DIARIO_SELLER_ID,
    NOVAMIX_RESUMO_DIARIO_TOP_N,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.ml.acoes_novamix import (
    executar_acoes_ads_novamix,
    formatar_secao_acoes_telegram,
    gerar_plano_acoes_novamix,
)
from integracoes.ml.analise_loja_concorrente import (
    analisar_desempenho_diario,
    analisar_loja,
    montar_resumo_diario,
)

logger = logging.getLogger("agente_resumo_diario_novamix")

HISTORY_PATH = ROOT / "logs" / "novamix_diario_history.json"
SNAPSHOT_PATH = ROOT / "logs" / "novamix_diario_ultima.json"
ACOES_PATH = ROOT / "logs" / "novamix_acoes_ultima.json"


def _data_brt() -> str:
    brt = timezone(timedelta(hours=-3))
    return datetime.now(brt).strftime("%d/%m/%Y %H:%M")


def _carregar_entrada_catalogo() -> dict[str, Any]:
    data = ler_json(ROOT / MONITOR_CONCORRENTES_ARQUIVO, default=[])
    if not isinstance(data, list):
        return {}
    for row in data:
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "") == "loja-novamix-comercial":
            return row
        if str(row.get("seller_id") or "") == NOVAMIX_RESUMO_DIARIO_SELLER_ID:
            return row
    return {}


def executar(enviar_alerta: bool = True, executar_ads: bool = True) -> dict[str, Any]:
    """Coleta Novamix, plano de ação, Telegram e Ads opcional. Nunca lança."""
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — resumo Novamix sem envio")

        entrada = _carregar_entrada_catalogo()
        seller_id = str(entrada.get("seller_id") or NOVAMIX_RESUMO_DIARIO_SELLER_ID).strip()
        nickname = str(
            entrada.get("nickname") or entrada.get("nome") or NOVAMIX_RESUMO_DIARIO_NICKNAME
        ).strip()
        termos = entrada.get("termos_busca") if isinstance(entrada.get("termos_busca"), list) else None
        limite = int(entrada.get("limite_resultados") or 20)

        logger.info("Resumo diário Novamix: seller=%s nick=%s", seller_id, nickname)
        analise = analisar_loja(
            seller_id,
            nickname=nickname,
            termos=termos,
            limite_por_termo=limite,
            enriquecer_metricas=NOVAMIX_RESUMO_DIARIO_ENRIQUECER,
        )

        historico = ler_json(HISTORY_PATH, default={})
        if not isinstance(historico, dict):
            historico = {}
        anterior = historico.get("ultima_amostra") if isinstance(historico.get("ultima_amostra"), dict) else {}

        desempenho = analisar_desempenho_diario(
            analise,
            historico_anterior=anterior,
            top_n=max(1, NOVAMIX_RESUMO_DIARIO_TOP_N),
        )
        plano = gerar_plano_acoes_novamix(analise)
        msg = montar_resumo_diario(analise, desempenho, data_local=_data_brt())
        secao_acoes = formatar_secao_acoes_telegram(plano)
        if secao_acoes:
            msg = f"{msg}\n{secao_acoes}"

        agora = datetime.now(timezone.utc).isoformat()
        ads_out: dict[str, Any] = {"ok": True, "executado": False, "motivo": "não solicitado"}
        if executar_ads:
            ads_out = executar_acoes_ads_novamix(
                plano,
                pedir_confirmacao=NOVAMIX_AUTO_ADS_PEDIR_CONFIRMACAO,
            )
            if ads_out.get("motivo") and not ads_out.get("executado"):
                msg += f"\n\n_Ads: {ads_out.get('motivo')}_"

        snapshot = {
            "timestamp": agora,
            "ok": bool(analise.get("ok")),
            "analise": {
                "nickname": analise.get("nickname"),
                "seller_id": analise.get("seller_id"),
                "total_anuncios_coletados": analise.get("total_anuncios_coletados"),
                "preco_min": analise.get("preco_min"),
                "preco_med": analise.get("preco_med"),
                "preco_max": analise.get("preco_max"),
                "marcas": analise.get("marcas"),
                "ameacas_preco": analise.get("ameacas_preco"),
                "perfil": analise.get("perfil"),
                "estrategia": analise.get("estrategia"),
            },
            "desempenho": desempenho,
            "plano_acoes": plano,
            "ads": ads_out,
            "mensagem": msg,
        }
        escrever_json_atomico(SNAPSHOT_PATH, snapshot)
        escrever_json_atomico(
            ACOES_PATH,
            {
                "timestamp": agora,
                "ads_sugerido": plano.get("ads_sugerido"),
                "caixas": plano.get("caixas"),
                "acoes": plano.get("acoes"),
                "ads_execucao": ads_out,
            },
        )
        try:
            escrever_json_atomico(
                ROOT / "logs" / "analise_loja_novamix_ultima.json",
                {"timestamp": agora, **analise},
            )
        except Exception as exc:
            logger.warning("snapshot analise_loja_novamix: %s", exc)

        amostra = dict(desempenho.get("atual") or {})
        amostra["timestamp"] = agora
        rodadas = list(historico.get("rodadas") or [])
        rodadas.append(
            {
                "timestamp": agora,
                "amostra": amostra,
                "fonte_giro": desempenho.get("fonte_giro_predominante"),
                "top": (desempenho.get("produtos_saindo") or [])[:3],
                "ads_sugerido": plano.get("ads_sugerido"),
            }
        )
        historico["rodadas"] = rodadas[-60:]
        historico["ultima_amostra"] = amostra
        historico["ultima"] = {
            "timestamp": agora,
            "desempenho": desempenho,
            "nickname": analise.get("nickname"),
            "ads_sugerido": plano.get("ads_sugerido"),
        }
        escrever_json_atomico(HISTORY_PATH, historico)

        gauge("novamix.diario.anuncios", float(amostra.get("anuncios") or 0))
        if amostra.get("preco_min"):
            gauge("novamix.diario.preco_min", float(amostra["preco_min"]))
        incrementar(
            "novamix.diario.rodadas",
            tags=[
                f"fonte_giro:{desempenho.get('fonte_giro_predominante', '?')}",
                f"ads:{plano.get('ads_sugerido', 'manter')}",
            ],
        )

        enviado = False
        if enviar_alerta and NOVAMIX_RESUMO_DIARIO_ALERTA and msg:
            enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave_resumo_periodo("novamix:resumo_diario", horas_por_bucket=20),
                    cooldown_segundos=NOVAMIX_RESUMO_DIARIO_COOLDOWN_SEG,
                )
            )

        return {
            "ok": True,
            "seller_id": seller_id,
            "nickname": analise.get("nickname") or nickname,
            "anuncios": int(analise.get("total_anuncios_coletados") or 0),
            "fonte_giro": desempenho.get("fonte_giro_predominante"),
            "ads_sugerido": plano.get("ads_sugerido"),
            "ads_executado": bool(ads_out.get("executado")),
            "plano_acoes": plano,
            "alerta_enviado": enviado,
            "desempenho": desempenho,
            "mensagem": msg,
        }
    except Exception as exc:
        logger.error("Resumo diário Novamix erro: %s", exc)
        incrementar("novamix.diario.erro")
        return {"ok": False, "erro": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Resumo diário Novamix → ações → Telegram/Ads")
    parser.add_argument("--sem-alerta", action="store_true")
    parser.add_argument("--sem-ads", action="store_true", help="Não tenta pausar/ligar Product Ads")
    args = parser.parse_args()
    logger.info("=== Resumo diário Novamix ===")
    out = executar(enviar_alerta=not args.sem_alerta, executar_ads=not args.sem_ads)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    logger.info(
        "Novamix OK: %s anúncio(s), giro=%s, ads=%s exec=%s, alerta=%s",
        out.get("anuncios"),
        out.get("fonte_giro"),
        out.get("ads_sugerido"),
        out.get("ads_executado"),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
