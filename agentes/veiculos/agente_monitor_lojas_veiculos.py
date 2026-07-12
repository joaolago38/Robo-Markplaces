"""
agentes/veiculos/agente_monitor_lojas_veiculos.py
Monitora Lucinei e Leopardo: carros até R$ 20k com grande desconto vs FIPE.

Uso:
  python -m agentes.veiculos.agente_monitor_lojas_veiculos
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    LOJAS_VEICULOS_ALERTA_RESUMO,
    LOJAS_VEICULOS_ALERTA_RESUMO_COOLDOWN_SEG,
    LOJAS_VEICULOS_MARGEM_FIPE_MIN_PCT,
    LOJAS_VEICULOS_MARGEM_FIPE_MIN_REAIS,
    LOJAS_VEICULOS_PAUSA_ENTRE_LOJAS_SEG,
    LOJAS_VEICULOS_PRECO_MAX,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_itens_novos, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.veiculos.comparacao import filtrar_oportunidades
from integracoes.veiculos.fontes import FONTES_PADRAO
from integracoes.veiculos.scrapers import coletar_fonte

logger = logging.getLogger("agente_monitor_lojas_veiculos")

HISTORY_PATH = ROOT / "logs" / "lojas_veiculos_history.json"


def _carregar_historico() -> dict[str, Any]:
    return ler_json(HISTORY_PATH, default={})


def _salvar_historico(historico: dict[str, Any]) -> None:
    try:
        escrever_json_atomico(HISTORY_PATH, historico)
    except Exception as exc:
        logger.error("Erro ao salvar histórico lojas veículos: %s", exc)


def _formatar_moeda(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _montar_alerta_oportunidades(itens: list[dict[str, Any]]) -> str:
    from core.telegram_explicacao import cabecalho_agente

    linhas = [
        cabecalho_agente("lojas_veiculos", "🚗 *Oportunidade — carros abaixo da FIPE*"),
        f"Preço máx. anúncio: {_formatar_moeda(LOJAS_VEICULOS_PRECO_MAX)}",
        f"Margem mínima vs FIPE: {LOJAS_VEICULOS_MARGEM_FIPE_MIN_PCT:.0f}%",
        "",
    ]
    for item in itens[:10]:
        linhas.append(f"*{item.get('titulo', '?')}* ({item.get('loja_nome', '?')})")
        linhas.append(f"💰 Anunciado: {_formatar_moeda(float(item.get('preco') or 0))}")
        linhas.append(f"📊 FIPE: {_formatar_moeda(float(item.get('valor_fipe') or 0))}")
        linhas.append(
            f"📉 Desconto: {item.get('desconto_pct', 0):.1f}% "
            f"({_formatar_moeda(float(item.get('margem_reais') or 0))} abaixo)"
        )
        if item.get("modelo_fipe"):
            linhas.append(f"🔎 FIPE ref.: {item.get('marca_fipe')} {item.get('modelo_fipe')} ({item.get('ano_fipe')})")
        if item.get("ano"):
            linhas.append(f"📅 Ano anúncio: {item.get('ano')}")
        if item.get("condicao"):
            linhas.append(f"🔧 {item.get('condicao')}")
        linhas.append(f"🔗 {item.get('url', '')}")
        linhas.append("")
    if len(itens) > 10:
        linhas.append(f"… e mais {len(itens) - 10} oportunidade(s)")
    return "\n".join(linhas).strip()


def _montar_resumo(
    por_loja: list[dict[str, Any]],
    oportunidades: list[dict[str, Any]],
    novos: list[dict[str, Any]],
) -> str:
    from core.telegram_explicacao import cabecalho_agente

    linhas = [
        cabecalho_agente("lojas_veiculos", "🚗 *Lojas veículos — resumo*"),
        "",
        f"Preço máx.: {_formatar_moeda(LOJAS_VEICULOS_PRECO_MAX)} | Margem FIPE mín.: {LOJAS_VEICULOS_MARGEM_FIPE_MIN_PCT:.0f}%",
        f"Anúncios coletados: {sum(int(x.get('total') or 0) for x in por_loja)}",
        f"Oportunidades (FIPE): {len(oportunidades)}",
        f"Novas oportunidades: {len(novos)}",
        "",
    ]
    for loja in por_loja:
        linhas.append(
            f"• {loja.get('loja_nome', loja.get('loja_id'))}: "
            f"{loja.get('total', 0)} anúncio(s), {loja.get('oportunidades', 0)} oportunidade(s)"
        )
    if not oportunidades:
        linhas.extend(["", "_Nenhuma oportunidade acima da margem FIPE nesta rodada._"])
    return "\n".join(linhas).strip()


def _monitorar_loja(fonte: dict[str, Any], historico: dict[str, Any]) -> dict[str, Any]:
    loja_id = str(fonte.get("id") or "")
    anuncios = coletar_fonte(fonte)
    oportunidades = filtrar_oportunidades(
        anuncios,
        preco_max=LOJAS_VEICULOS_PRECO_MAX,
        margem_min_pct=LOJAS_VEICULOS_MARGEM_FIPE_MIN_PCT,
        margem_min_reais=LOJAS_VEICULOS_MARGEM_FIPE_MIN_REAIS,
    )

    entrada = historico.get(loja_id) if isinstance(historico.get(loja_id), dict) else {}
    vistos: dict[str, Any] = dict(entrada.get("vistos") or {})
    novos: list[dict[str, Any]] = []
    agora = datetime.now(timezone.utc).isoformat()

    for item in oportunidades:
        h = str(item.get("hash") or "")
        if not h:
            continue
        if h not in vistos:
            registro = {**item, "visto_em": agora}
            vistos[h] = registro
            novos.append(registro)

    historico[loja_id] = {
        "loja_nome": fonte.get("nome"),
        "vistos": vistos,
        "ultima_varredura": agora,
        "total_anuncios": len(anuncios),
        "total_oportunidades": len(oportunidades),
    }

    gauge("lojas_veiculos.anuncios", len(anuncios), tags=[f"loja:{loja_id}"])
    gauge("lojas_veiculos.oportunidades", len(oportunidades), tags=[f"loja:{loja_id}"])
    incrementar("lojas_veiculos.novos", len(novos), tags=[f"loja:{loja_id}"])

    return {
        "loja_id": loja_id,
        "loja_nome": fonte.get("nome"),
        "total": len(anuncios),
        "oportunidades": len(oportunidades),
        "novos": novos,
        "ok": True,
    }


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning(
                "Telegram gestor não configurado — alertas de lojas veículos não serão entregues"
            )

        historico = _carregar_historico()
        por_loja: list[dict[str, Any]] = []
        fontes = list(FONTES_PADRAO)

        for i, fonte in enumerate(fontes):
            logger.info("Monitorando loja: %s", fonte.get("nome"))
            por_loja.append(_monitorar_loja(fonte, historico))
            if i < len(fontes) - 1 and LOJAS_VEICULOS_PAUSA_ENTRE_LOJAS_SEG > 0:
                time.sleep(LOJAS_VEICULOS_PAUSA_ENTRE_LOJAS_SEG)

        _salvar_historico(historico)

        todas_oportunidades: list[dict[str, Any]] = []
        todos_novos: list[dict[str, Any]] = []
        for loja in por_loja:
            todos_novos.extend(loja.get("novos") or [])

        for loja_id, entrada in historico.items():
            if not isinstance(entrada, dict):
                continue
            for item in (entrada.get("vistos") or {}).values():
                if isinstance(item, dict) and item.get("oportunidade"):
                    todas_oportunidades.append(item)

        alerta_novos = False
        alerta_resumo = False

        if enviar_alerta and todos_novos:
            msg = _montar_alerta_oportunidades(todos_novos)
            alerta_novos = bool(
                alertar_gestor(
                    msg,
                    chave=chave_itens_novos("lojas_veiculos:novos", todos_novos),
                    cooldown_segundos=86400,
                    agente_id="lojas_veiculos",
                )
            )

        if enviar_alerta and LOJAS_VEICULOS_ALERTA_RESUMO:
            msg_resumo = _montar_resumo(por_loja, todas_oportunidades, todos_novos)
            alerta_resumo = bool(
                alertar_gestor(
                    msg_resumo,
                    chave=chave_resumo_periodo("lojas_veiculos", horas_por_bucket=2),
                    cooldown_segundos=LOJAS_VEICULOS_ALERTA_RESUMO_COOLDOWN_SEG,
                    agente_id="lojas_veiculos",
                )
            )

        return {
            "ok": True,
            "lojas": len(por_loja),
            "oportunidades": len(todas_oportunidades),
            "novos": len(todos_novos),
            "alerta_enviado": alerta_novos or alerta_resumo,
            "resultados": por_loja,
        }
    except Exception as exc:
        logger.error("Agente lojas veículos erro: %s", exc)
        return {"ok": False, "erro": str(exc), "resultados": []}


def main() -> int:
    logger.info("=== Monitor lojas veículos (FIPE) ===")
    out = executar(enviar_alerta=True)
    if not out.get("ok"):
        logger.error("Monitor falhou: %s", out.get("erro"))
        return 1
    logger.info(
        "Monitor lojas: %s loja(s), %s oportunidade(s), %s nova(s), alerta=%s",
        out.get("lojas"),
        out.get("oportunidades"),
        out.get("novos"),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
