"""
agentes/orquestrador/agente_orquestrador.py
Orquestrador que executa todos os agentes de monitoramento a cada 30 minutos,
envia resumo ao Telegram gestor e métricas ao Datadog.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from typing import Any

from agentes.orquestrador.registro_agentes import AgenteRegistrado, executar_registro, listar_agentes
from core.config import (
    ORQUESTRADOR_COOLDOWN_RESUMO_SEG,
    ORQUESTRADOR_PAUSA_ENTRE_AGENTES_SEG,
    ORQUESTRADOR_TIMEOUT_AGENTE_SEG,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, gestor_telegram_configurado
from core.request_context import definir_request_id, novo_request_id

logger = logging.getLogger("agente_orquestrador")


def _interpretar_ok(raw: Any) -> bool:
    if isinstance(raw, dict):
        if "ok" in raw:
            return bool(raw["ok"])
        if raw.get("erro") or raw.get("error"):
            return False
        falhas = raw.get("falhas")
        if isinstance(falhas, (int, float)) and falhas > 0:
            return False
        if raw.get("falha") is True:
            return False
        return True
    if isinstance(raw, bool):
        return raw
    return True


def _extrair_resumo(raw: Any) -> str:
    if isinstance(raw, dict):
        if raw.get("resumo_orquestrador"):
            return str(raw["resumo_orquestrador"])[:120]
        partes: list[str] = []
        for chave, rotulo in (
            ("com_novos", "novos"),
            ("total_veiculos", "veículos"),
            ("total_produtos", "produtos"),
            ("oportunidades_total", "oportunidades"),
            ("achados_total", "achados"),
        ):
            if chave in raw and raw[chave] is not None:
                partes.append(f"{raw[chave]} {rotulo}")
        if raw.get("alerta_enviado") is True:
            partes.append("alerta enviado")
        if raw.get("motivo"):
            partes.append(str(raw["motivo"])[:50])
        elif raw.get("resumo"):
            partes.append(str(raw["resumo"])[:60])
        elif raw.get("resumo_claude"):
            partes.append(str(raw["resumo_claude"])[:60])
        if not partes:
            extras: list[str] = []
            if raw.get("skipped") or raw.get("pulado"):
                extras.append("pulado")
            if raw.get("executou_escrita") is False:
                extras.append("sem escrita")
            if raw.get("ajustes") == 0:
                extras.append("0 ajustes")
            if raw.get("dry_run"):
                extras.append("dry-run")
            if extras:
                return ", ".join(extras)
            if "ok" not in raw:
                return "rodou (sem ok explícito)"
            return "ok"
        return ", ".join(partes)
    if isinstance(raw, bool):
        return "ok" if raw else "falha"
    return "ok"


def _executar_agente_interno(registro: AgenteRegistrado) -> dict[str, Any]:
    inicio = time.monotonic()
    resultado: dict[str, Any] = {
        "id": registro.id,
        "nome": registro.nome,
        "categoria": registro.categoria,
        "ok": False,
    }
    try:
        logger.info("Orquestrador: iniciando %s (%s)", registro.id, registro.nome)
        raw = executar_registro(registro)
        resultado["ok"] = _interpretar_ok(raw)
        resumo = _extrair_resumo(raw)
        if bool((registro.kwargs or {}).get("dry_run")) or bool(
            (registro.kwargs or {}).get("dry_run_repricing")
        ) or bool((registro.kwargs or {}).get("dry_run_nfe")):
            resumo = f"{resumo} (dry-run — sem escrita)"
            resultado["dry_run"] = True
        resultado["resumo"] = resumo
        resultado["payload"] = raw if isinstance(raw, dict) else {"valor": raw}
    except Exception as exc:
        resultado["erro"] = str(exc)
        resultado["resumo"] = str(exc)[:120]
        logger.exception("Orquestrador: falha em %s", registro.id)
        incrementar("orquestrador.agente.erro", tags=[f"agente:{registro.id}"])
    finally:
        duracao_ms = (time.monotonic() - inicio) * 1000
        resultado["duracao_ms"] = round(duracao_ms, 1)
        gauge("orquestrador.agente.latencia_ms", duracao_ms, tags=[f"agente:{registro.id}"])
        incrementar(
            "orquestrador.agente.execucao",
            tags=[f"agente:{registro.id}", f"ok:{str(resultado.get('ok')).lower()}"],
        )
        logger.info(
            "Orquestrador: %s finalizado ok=%s em %.0fms — %s",
            registro.id,
            resultado.get("ok"),
            duracao_ms,
            resultado.get("resumo", ""),
        )
    return resultado


def _executar_agente(registro: AgenteRegistrado) -> dict[str, Any]:
    timeout_seg = float(ORQUESTRADOR_TIMEOUT_AGENTE_SEG or 0)
    if timeout_seg <= 0:
        return _executar_agente_interno(registro)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        fut = pool.submit(_executar_agente_interno, registro)
        try:
            return fut.result(timeout=timeout_seg)
        except FuturesTimeout:
            logger.error(
                "Orquestrador: timeout de %.0fs em %s — segue a fila",
                timeout_seg,
                registro.id,
            )
            incrementar("orquestrador.agente.timeout", tags=[f"agente:{registro.id}"])
            incrementar(
                "orquestrador.agente.execucao",
                tags=[f"agente:{registro.id}", "ok:false", "motivo:timeout"],
            )
            return {
                "id": registro.id,
                "nome": registro.nome,
                "categoria": registro.categoria,
                "ok": False,
                "erro": f"timeout {int(timeout_seg)}s",
                "resumo": f"timeout {int(timeout_seg)}s",
                "duracao_ms": round(timeout_seg * 1000, 1),
            }
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _montar_resumo_telegram(ciclo: dict[str, Any], *, titulo: str) -> str:
    from core.telegram_explicacao import cabecalho_agente

    linhas = [
        cabecalho_agente("orquestrador", titulo),
        "",
        "_Ciclo 30min = monitoramento + chat ML. Sem escrita de preço/estoque/NF-e._",
        (
            f"✅ {ciclo['ok']} ok | ❌ {ciclo['falhas']} falha | "
            f"⏸ {ciclo.get('pulados', 0)} pulado | "
            f"⏱ {ciclo['duracao_seg']:.0f}s | {ciclo['total']} agentes"
        ),
        "",
    ]
    for item in ciclo["agentes"]:
        icone = "✅" if item.get("ok") else "❌"
        nome = item.get("nome") or item.get("id", "?")
        detalhe = item.get("resumo") or item.get("erro") or "—"
        linhas.append(f"{icone} *{nome}*: {str(detalhe)[:90]}")
    return "\n".join(linhas).strip()


def _enviar_metricas_ciclo(ciclo: dict[str, Any], *, prefixo: str) -> None:
    gauge(f"{prefixo}.ciclo.duracao_ms", ciclo["duracao_ms"])
    gauge(f"{prefixo}.ciclo.agentes_ok", ciclo["ok"])
    gauge(f"{prefixo}.ciclo.agentes_falha", ciclo["falhas"])
    gauge(f"{prefixo}.ciclo.agentes_total", ciclo["total"])
    incrementar(f"{prefixo}.ciclo")
    if ciclo["falhas"]:
        incrementar(f"{prefixo}.ciclo.com_falha")


def executar_ciclo(
    *,
    agentes: list[AgenteRegistrado],
    titulo_resumo: str,
    chave_cooldown: str,
    cooldown_segundos: int,
    prefixo_metrica: str = "orquestrador",
    enviar_resumo_telegram: bool = True,
    log_prefix: str = "Orquestrador",
    pausa_entre_agentes_seg: float | None = None,
) -> dict[str, Any]:
    """
    Executa agentes em sequência (isolamento por try/except). Nunca lança exceção.
    """
    pausa = ORQUESTRADOR_PAUSA_ENTRE_AGENTES_SEG if pausa_entre_agentes_seg is None else pausa_entre_agentes_seg
    inicio_ciclo = time.monotonic()
    resultados: list[dict[str, Any]] = []
    run_id = novo_request_id()
    definir_request_id(run_id)

    if enviar_resumo_telegram:
        from core.telegram_gate import verificar_token

        if not gestor_telegram_configurado():
            logger.warning(
                "%s: Telegram gestor não configurado — resumo não será entregue",
                log_prefix,
            )
        elif not verificar_token():
            logger.warning(
                "%s: TELEGRAM_TOKEN inválido — resumo não será entregue (corrija no @BotFather)",
                log_prefix,
            )

    logger.info("%s: iniciando ciclo run_id=%s com %s agente(s)", log_prefix, run_id, len(agentes))

    for registro in agentes:
        resultados.append(_executar_agente(registro))
        if pausa > 0:
            time.sleep(pausa)

    ok_count = sum(1 for r in resultados if r.get("ok"))
    falhas = len(resultados) - ok_count
    pulados = sum(
        1
        for r in resultados
        if isinstance(r.get("payload"), dict)
        and (r["payload"].get("skipped") or r["payload"].get("motivo") == "spec.inativo")
    )
    duracao_ms = (time.monotonic() - inicio_ciclo) * 1000

    ciclo = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "total": len(resultados),
        "ok": ok_count,
        "falhas": falhas,
        "pulados": pulados,
        "duracao_ms": duracao_ms,
        "duracao_seg": duracao_ms / 1000,
        "agentes": resultados,
        "resumo_telegram_enviado": False,
    }

    _enviar_metricas_ciclo(ciclo, prefixo=prefixo_metrica)
    gauge(f"{prefixo_metrica}.ciclo.pulse", 1.0)

    try:
        from core.atomic_io import escrever_json_atomico
        from core.config import ROOT

        escrever_json_atomico(
            ROOT / "logs" / "orquestrador_ultimo_ciclo.json",
            {
                "timestamp": ciclo["timestamp"],
                "ok": ok_count == len(resultados),
                "falhas": falhas,
                "pulados": pulados,
                "total": len(resultados),
                "agentes_falha": [
                    {
                        "id": r.get("id"),
                        "nome": r.get("nome"),
                        "erro": (r.get("erro") or r.get("resumo") or "")[:160],
                    }
                    for r in resultados
                    if not r.get("ok")
                ],
            },
        )
    except Exception as exc:
        logger.warning("Orquestrador: falha ao gravar heartbeat: %s", exc)

    if enviar_resumo_telegram and resultados and falhas > 0:
        msg = _montar_resumo_telegram(ciclo, titulo=titulo_resumo)
        ciclo["resumo_telegram_enviado"] = bool(
            alertar_gestor(
                msg,
                chave=chave_cooldown,
                cooldown_segundos=cooldown_segundos,
                agente_id="orquestrador",
            )
        )

    logger.info(
        "%s: ciclo concluído — %s ok, %s falha(s), %.0fs, telegram=%s",
        log_prefix,
        ok_count,
        falhas,
        duracao_ms / 1000,
        ciclo.get("resumo_telegram_enviado"),
    )
    return {"ok": falhas == 0, **ciclo}


def executar(
    *,
    enviar_resumo_telegram: bool = True,
    agentes: list[AgenteRegistrado] | None = None,
) -> dict[str, Any]:
    """Ciclo padrão de 30 minutos."""
    return executar_ciclo(
        agentes=agentes if agentes is not None else listar_agentes(),
        titulo_resumo="🔄 *Orquestrador 30min — ciclo completo*",
        chave_cooldown="orquestrador:30min:resumo",
        cooldown_segundos=ORQUESTRADOR_COOLDOWN_RESUMO_SEG,
        prefixo_metrica="orquestrador",
        enviar_resumo_telegram=enviar_resumo_telegram,
        log_prefix="Orquestrador",
    )


def main() -> int:
    logger.info("=== Orquestrador 30min — todos os agentes ===")
    resultado = executar(enviar_resumo_telegram=True)
    if resultado.get("falhas"):
        logger.warning("Orquestrador: %s agente(s) com falha", resultado["falhas"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
