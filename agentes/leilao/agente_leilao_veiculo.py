"""
agentes/leilao/agente_leilao_veiculo.py
Monitor 24h de leilões de veículos **recuperados de furto / média monta** em leiloeiros
e portais DETRAN (todos os estados). Modelos prioritários no catálogo padrão:
Fiorino Furgão → Gol → Civic → City → Fit.

Configuração: catalogo/leiloes_veiculos_monitorados.json
Somente leitura + alertas — não participa de leilões.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import LEILAO_PAUSA_ENTRE_FONTES_SEG, LEILAO_VEICULOS_CATALOGO, ROOT
from core.datadog_metrics import gauge, incrementar
from core.ddg_lite import mensagem_circuit_breaker
from core.notificador import alertar_gestor, gestor_telegram_configurado
from integracoes.leilao.busca import buscar_veiculo_em_fontes

logger = logging.getLogger("agente_leilao_veiculo")

HISTORY_PATH = ROOT / "logs" / "leilao_veiculos_history.json"


def _carregar_veiculos() -> list[dict[str, Any]]:
    caminho = ROOT / LEILAO_VEICULOS_CATALOGO
    try:
        if not caminho.is_file():
            logger.warning("Catálogo de leilões não encontrado: %s", caminho)
            return []
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        return [v for v in data if isinstance(v, dict) and v.get("ativo")]
    except Exception as exc:
        logger.error("Erro ao carregar catálogo de leilões: %s", exc)
        return []


def _carregar_historico() -> dict[str, Any]:
    return ler_json(HISTORY_PATH, default={})


def _salvar_historico(historico: dict[str, Any]) -> None:
    try:
        escrever_json_atomico(HISTORY_PATH, historico)
    except Exception as exc:
        logger.error("Erro ao salvar histórico de leilões: %s", exc)


def _monitorar_veiculo(
    veiculo: dict[str, Any],
    historico: dict[str, Any],
) -> dict[str, Any]:
    vid = str(veiculo.get("id") or "").strip()
    nome = f"{veiculo.get('marca', '')} {veiculo.get('modelo', '')}".strip()
    entrada_hist = historico.get(vid) if isinstance(historico.get(vid), dict) else {}
    vistos: dict[str, Any] = dict(entrada_hist.get("vistos") or {})

    achados = buscar_veiculo_em_fontes(
        veiculo,
        pausa_entre_fontes_seg=LEILAO_PAUSA_ENTRE_FONTES_SEG,
    )
    novos: list[dict[str, Any]] = []
    agora = datetime.now(timezone.utc).isoformat()

    for item in achados:
        h = item.get("hash") or ""
        if not h:
            continue
        if h not in vistos:
            registro = {**item, "visto_em": agora}
            vistos[h] = registro
            novos.append(registro)

    historico[vid] = {
        "veiculo": nome,
        "vistos": vistos,
        "ultima_varredura": agora,
        "total_achados_rodada": len(achados),
    }

    gauge("leilao.achados_por_veiculo", len(achados), tags=[f"veiculo:{vid}"])
    incrementar("leilao.novos", len(novos), tags=[f"veiculo:{vid}"])
    _logar_achados(veiculo, achados, novos)

    return {
        "id": vid,
        "veiculo": nome,
        "prioridade": int(veiculo.get("prioridade") or 99),
        "achados_total": len(achados),
        "novos": novos,
        "ok": True,
    }


def _formatar_local_item(item: dict[str, Any]) -> str:
    cidade = str(item.get("cidade") or "").strip()
    uf = str(item.get("uf") or "").strip()
    if item.get("fonte_tipo") == "detran":
        detran = str(item.get("detran_nome") or item.get("fonte_nome") or "").strip()
        if cidade and detran:
            return f"{cidade} — {detran}"
        if cidade and uf:
            return f"{cidade} — DETRAN {uf}"
        return detran or (f"DETRAN {uf}" if uf else str(item.get("fonte_nome") or "?"))
    partes: list[str] = []
    if cidade and uf:
        partes.append(f"{cidade}/{uf}")
    elif cidade:
        partes.append(cidade)
    fonte = str(item.get("fonte_nome") or item.get("fonte_id") or "").strip()
    if fonte:
        partes.append(fonte)
    return " — ".join(partes) if partes else "?"


def _formatar_veiculo_item(item: dict[str, Any]) -> str:
    marca = str(item.get("marca") or "").strip()
    modelo = str(item.get("modelo") or "").strip()
    ano = item.get("ano")
    partes = [p for p in (marca, modelo) if p]
    desc = " ".join(partes)
    if ano:
        desc = f"{desc} {ano}".strip()
    return desc or str(item.get("titulo") or "Veículo")[:60]


def _formatar_valor_item(item: dict[str, Any]) -> str:
    return str(item.get("valor") or "valor n/d")


def _formatar_data_item(item: dict[str, Any]) -> str:
    return str(item.get("data_leilao") or "data n/d")


def _formatar_cadastro_item(item: dict[str, Any]) -> str:
    return str(item.get("url_cadastro") or "cadastro n/d")


def _logar_linha_item(item: dict[str, Any], *, prefix: str) -> None:
    logger.info(
        "%s %s | %s | %s | %s | cadastro: %s | %s",
        prefix,
        _formatar_local_item(item),
        _formatar_veiculo_item(item),
        _formatar_valor_item(item),
        _formatar_data_item(item),
        _formatar_cadastro_item(item),
        item.get("url_anuncio") or item.get("url", ""),
    )


def _logar_achados(
    veiculo: dict[str, Any],
    achados: list[dict[str, Any]],
    novos: list[dict[str, Any]],
) -> None:
    nome = f"{veiculo.get('marca', '')} {veiculo.get('modelo', '')}".strip() or str(
        veiculo.get("id") or "?"
    )

    if not achados:
        logger.info("Leilão %s: nenhum achado nesta rodada", nome)
        ddg = mensagem_circuit_breaker()
        if ddg:
            logger.warning("Leilão %s: %s", nome, ddg)
        return

    logger.info("Leilão %s: %s achado(s) nesta rodada", nome, len(achados))
    for item in achados[:8]:
        _logar_linha_item(item, prefix="  •")
    if len(achados) > 8:
        logger.info("  … e mais %s achado(s) nesta rodada", len(achados) - 8)

    if novos:
        logger.info("Leilão %s: %s achado(s) NOVO(S)", nome, len(novos))
        for item in novos[:5]:
            _logar_linha_item(item, prefix="  ★ NOVO:")
        if len(novos) > 5:
            logger.info("  … e mais %s novo(s)", len(novos) - 5)


def _montar_alerta(resultados: list[dict[str, Any]]) -> str:
    linhas = ["🚗 *Leilões — recuperado furto / média monta*", ""]
    ordenados = sorted(resultados, key=lambda r: int(r.get("prioridade") or 99))
    for r in ordenados:
        novos = r.get("novos") or []
        if not novos:
            continue
        linhas.append(f"*{r.get('veiculo', r.get('id', ''))}* ({len(novos)} novo(s)):")
        for item in novos[:8]:
            linhas.append(f"📍 {_formatar_local_item(item)}")
            linhas.append(f"🚙 {_formatar_veiculo_item(item)}")
            if item.get("data_leilao"):
                linhas.append(f"📅 {item['data_leilao']}")
            if item.get("valor"):
                linhas.append(f"💰 {item['valor']}")
            if item.get("url_cadastro"):
                linhas.append(f"📝 Cadastro: {item['url_cadastro']}")
            titulo = str(item.get("titulo") or "").strip()
            if titulo and titulo != _formatar_veiculo_item(item):
                linhas.append(f"_{titulo[:70]}_")
            linhas.append(f"🔗 {item.get('url_anuncio') or item.get('url', '')}")
            linhas.append("")
        if len(novos) > 8:
            linhas.append(f"… e mais {len(novos) - 8}")
        linhas.append("")
    return "\n".join(linhas).strip()


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    """
    Varre leiloeiros + DETRAN (27 UFs) para cada veículo ativo no catálogo.
    Alerta apenas achados novos (não repetidos). Nunca lança exceção.
    """
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning(
                "Telegram gestor não configurado (TELEGRAM_TOKEN / TELEGRAM_GESTOR_CHAT_ID) — "
                "alertas de leilão não serão entregues"
            )

        veiculos = _carregar_veiculos()
        if not veiculos:
            logger.info("Nenhum veículo ativo em %s", LEILAO_VEICULOS_CATALOGO)
            return {"ok": True, "total_veiculos": 0, "resultados": [], "alerta_enviado": False}

        veiculos = sorted(veiculos, key=lambda v: int(v.get("prioridade") or 99))
        historico = _carregar_historico()
        resultados: list[dict[str, Any]] = []

        for veiculo in veiculos:
            vid = str(veiculo.get("id") or "").strip()
            if not vid:
                continue
            logger.info("Varrendo leilões: %s %s", veiculo.get("marca"), veiculo.get("modelo"))
            resultados.append(_monitorar_veiculo(veiculo, historico))

        _salvar_historico(historico)

        com_novos = [r for r in resultados if r.get("novos")]
        alerta_enviado = False
        if enviar_alerta and com_novos:
            msg = _montar_alerta(com_novos)
            if msg:
                alerta_enviado = bool(
                    alertar_gestor(msg, chave="leilao:veiculos:novos", cooldown_segundos=3600)
                )
                if not alerta_enviado:
                    logger.warning(
                        "%s achado(s) novo(s) mas alerta não enviado (cooldown ou falha Telegram)",
                        sum(len(r.get("novos") or []) for r in com_novos),
                    )

        return {
            "ok": True,
            "total_veiculos": len(resultados),
            "com_novos": len(com_novos),
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Agente leilão veículos erro: %s", exc)
        return {"ok": False, "erro": str(exc), "resultados": []}


def main() -> int:
    logger.info("=== Monitor de leilões de veículos (24h) ===")
    resultado = executar(enviar_alerta=True)
    if not resultado.get("ok"):
        logger.error("Monitor leilões falhou: %s", resultado.get("erro"))
        return 1
    logger.info(
        "Monitor leilões: %s veículo(s), %s com novos achados, alerta=%s",
        resultado.get("total_veiculos"),
        resultado.get("com_novos"),
        resultado.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
