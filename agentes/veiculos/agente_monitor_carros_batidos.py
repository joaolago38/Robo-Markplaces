"""
agentes/veiculos/agente_monitor_carros_batidos.py
Monitora lojas de carros batidos/salvados e envia novos anúncios ao Telegram.

Catálogo: catalogo/carros_batidos_fontes.json

Uso:
  python -m agentes.veiculos.agente_monitor_carros_batidos
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    CARROS_BATIDOS_ALERTA_COOLDOWN_SEG,
    CARROS_BATIDOS_ALERTA_RESUMO,
    CARROS_BATIDOS_ALERTA_RESUMO_COOLDOWN_SEG,
    CARROS_BATIDOS_BUSCA_WEB,
    CARROS_BATIDOS_BUSCA_WEB_MAX_UFS,
    CARROS_BATIDOS_BUSCA_WEB_PAUSA_SEG,
    CARROS_BATIDOS_BUSCA_WEB_RESULTADOS,
    CARROS_BATIDOS_INCLUIR_FIPE,
    CARROS_BATIDOS_PAUSA_ENTRE_LOJAS_SEG,
    CARROS_BATIDOS_PRECO_MAX,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_itens_novos, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.veiculos.carros_batidos_fontes import carregar_fontes
from integracoes.veiculos.comparacao import calcular_margem_fipe
from integracoes.veiculos.fipe_client import consultar_preco_fipe
from integracoes.veiculos.scrapers import coletar_busca_web_brasil, coletar_fonte

logger = logging.getLogger("agente_monitor_carros_batidos")

HISTORY_PATH = ROOT / "logs" / "carros_batidos_history.json"
SNAPSHOT_PATH = ROOT / "logs" / "carros_batidos_ultima.json"


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def _enriquecer_fipe(item: dict[str, Any]) -> dict[str, Any]:
    if not CARROS_BATIDOS_INCLUIR_FIPE:
        return item
    fipe = consultar_preco_fipe(
        marca=str(item.get("marca") or ""),
        titulo=str(item.get("titulo") or ""),
        ano_texto=str(item.get("ano") or ""),
    )
    if not fipe:
        return item
    preco = float(item.get("preco") or 0)
    margem = calcular_margem_fipe(preco_anunciado=preco, valor_fipe=float(fipe["valor_fipe"]))
    return {**item, **fipe, **margem}


def _filtrar_preco(anuncios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    limite = CARROS_BATIDOS_PRECO_MAX
    if limite <= 0:
        return anuncios
    return [a for a in anuncios if 0 < float(a.get("preco") or 0) <= limite]


def _montar_linha_anuncio(item: dict[str, Any]) -> list[str]:
    linhas = [
        f"🚙 *{item.get('titulo', '?')}*",
        f"🏪 {item.get('loja_nome', '?')}",
        f"💰 {_fmt_brl(item.get('preco'))}",
    ]
    if item.get("ano"):
        linhas.append(f"📅 Ano: {item['ano']}")
    if item.get("condicao"):
        linhas.append(f"🔧 {item['condicao']}")
    if item.get("valor_fipe"):
        linhas.append(f"📊 FIPE: {_fmt_brl(item['valor_fipe'])} ({item.get('modelo_fipe', '')})")
        linhas.append(
            f"📉 {_fmt_brl(item.get('margem_reais'))} abaixo da FIPE ({item.get('desconto_pct', 0):.1f}%)"
        )
    linhas.append(f"🔗 {item.get('url', '')}")
    return linhas


def _montar_alerta_novos(itens: list[dict[str, Any]]) -> str:
    linhas = [
        "🚗 *Carros batidos — novos anúncios*",
        "",
        f"_{len(itens)} veículo(s) novo(s) em lojas de salvados/sinistrados._",
        "",
    ]
    for item in itens[:15]:
        linhas.extend(_montar_linha_anuncio(item))
        linhas.append("")
    if len(itens) > 15:
        linhas.append(f"… e mais {len(itens) - 15} anúncio(s)")
    return "\n".join(linhas).strip()


def _montar_resumo(por_loja: list[dict[str, Any]], novos: list[dict[str, Any]]) -> str:
    total = sum(int(x.get("total") or 0) for x in por_loja)
    linhas = [
        "🚗 *Carros batidos — resumo da varredura*",
        "",
        f"Lojas monitoradas: {len(por_loja)}",
        f"Anúncios coletados: {total}",
        f"Novos nesta rodada: {len(novos)}",
        "",
    ]
    for loja in por_loja:
        linhas.append(
            f"• {loja.get('loja_nome', loja.get('loja_id'))}: "
            f"{loja.get('total', 0)} anúncio(s), {len(loja.get('novos') or [])} novo(s)"
        )
    if not total:
        linhas.extend(["", "_Nenhum anúncio coletado nesta rodada._"])
    return "\n".join(linhas).strip()


def _processar_anuncios(
    loja_id: str,
    loja_nome: str,
    anuncios: list[dict[str, Any]],
    historico: dict[str, Any],
    *,
    enriquecer_fipe: bool = True,
) -> dict[str, Any]:
    entrada = historico.get(loja_id) if isinstance(historico.get(loja_id), dict) else {}
    vistos: dict[str, Any] = dict(entrada.get("vistos") or {})
    novos: list[dict[str, Any]] = []
    agora = datetime.now(timezone.utc).isoformat()

    for item in anuncios:
        h = str(item.get("hash") or "")
        if not h:
            continue
        if h not in vistos:
            registro = {**item, "visto_em": agora}
            if enriquecer_fipe:
                registro = _enriquecer_fipe(registro)
            vistos[h] = registro
            novos.append(registro)

    historico[loja_id] = {
        "loja_nome": loja_nome,
        "vistos": vistos,
        "ultima_varredura": agora,
        "total_anuncios": len(anuncios),
    }

    gauge("carros_batidos.anuncios", len(anuncios), tags=[f"loja:{loja_id}"])
    incrementar("carros_batidos.novos", len(novos), tags=[f"loja:{loja_id}"])

    return {
        "loja_id": loja_id,
        "loja_nome": loja_nome,
        "total": len(anuncios),
        "novos": novos,
        "ok": True,
    }


def _monitorar_loja(fonte: dict[str, Any], historico: dict[str, Any]) -> dict[str, Any]:
    loja_id = str(fonte.get("id") or "")
    anuncios = _filtrar_preco(coletar_fonte(fonte))
    return _processar_anuncios(loja_id, str(fonte.get("nome") or loja_id), anuncios, historico)


def _monitorar_busca_web(historico: dict[str, Any]) -> dict[str, Any]:
    anuncios = coletar_busca_web_brasil(
        max_ufs=CARROS_BATIDOS_BUSCA_WEB_MAX_UFS,
        max_resultados=CARROS_BATIDOS_BUSCA_WEB_RESULTADOS,
        pausa_seg=CARROS_BATIDOS_BUSCA_WEB_PAUSA_SEG,
    )
    return _processar_anuncios(
        "busca_web",
        "Busca web nacional",
        anuncios,
        historico,
        enriquecer_fipe=False,
    )


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    """Varre todas as lojas ativas do catálogo e alerta novos anúncios no Telegram."""
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — alertas de carros batidos não serão entregues")

        fontes = carregar_fontes()
        if not fontes and not CARROS_BATIDOS_BUSCA_WEB:
            logger.info("Nenhuma loja ativa no catálogo de carros batidos")
            return {"ok": True, "lojas": 0, "novos": 0, "alerta_enviado": False, "resultados": []}

        historico = ler_json(HISTORY_PATH, default={})
        por_loja: list[dict[str, Any]] = []

        for i, fonte in enumerate(fontes):
            logger.info("Monitorando loja batidos: %s", fonte.get("nome"))
            por_loja.append(_monitorar_loja(fonte, historico))
            if i < len(fontes) - 1 and CARROS_BATIDOS_PAUSA_ENTRE_LOJAS_SEG > 0:
                time.sleep(CARROS_BATIDOS_PAUSA_ENTRE_LOJAS_SEG)

        if CARROS_BATIDOS_BUSCA_WEB:
            logger.info("Busca web nacional de carros batidos (todo o Brasil)")
            por_loja.append(_monitorar_busca_web(historico))

        escrever_json_atomico(HISTORY_PATH, historico)

        todos_novos: list[dict[str, Any]] = []
        for loja in por_loja:
            todos_novos.extend(loja.get("novos") or [])

        agora = datetime.now(timezone.utc).isoformat()
        escrever_json_atomico(
            SNAPSHOT_PATH,
            {"timestamp": agora, "lojas": len(por_loja), "novos": len(todos_novos), "resultados": por_loja},
        )

        alerta_novos = False
        alerta_resumo = False

        if enviar_alerta and todos_novos:
            msg = _montar_alerta_novos(todos_novos)
            alerta_novos = bool(
                alertar_gestor(
                    msg,
                    chave=chave_itens_novos("carros_batidos:novos", todos_novos),
                    cooldown_segundos=CARROS_BATIDOS_ALERTA_COOLDOWN_SEG,
                )
            )

        if enviar_alerta and CARROS_BATIDOS_ALERTA_RESUMO:
            msg_resumo = _montar_resumo(por_loja, todos_novos)
            alerta_resumo = bool(
                alertar_gestor(
                    msg_resumo,
                    chave=chave_resumo_periodo("carros_batidos", horas_por_bucket=4),
                    cooldown_segundos=CARROS_BATIDOS_ALERTA_RESUMO_COOLDOWN_SEG,
                )
            )

        incrementar("carros_batidos.rodadas", tags=[f"novos:{len(todos_novos)}"])

        return {
            "ok": True,
            "lojas": len(por_loja),
            "novos": len(todos_novos),
            "alerta_enviado": alerta_novos or alerta_resumo,
            "alerta_novos_enviado": alerta_novos,
            "alerta_resumo_enviado": alerta_resumo,
            "resultados": por_loja,
        }
    except Exception as exc:
        logger.error("Agente carros batidos erro: %s", exc)
        incrementar("carros_batidos.erro")
        return {"ok": False, "erro": str(exc), "resultados": []}


def main() -> int:
    logger.info("=== Monitor carros batidos ===")
    out = executar(enviar_alerta=True)
    if not out.get("ok"):
        logger.error("Monitor carros batidos falhou: %s", out.get("erro"))
        return 1
    logger.info(
        "Monitor carros batidos: %s loja(s), %s novo(s), alerta=%s",
        out.get("lojas"),
        out.get("novos"),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
