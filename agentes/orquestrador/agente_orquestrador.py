"""
agentes/orquestrador/agente_orquestrador.py
Orquestrador que executa todos os agentes de monitoramento a cada 30 minutos,
envia resumo ao Telegram gestor e métricas ao Datadog.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from agentes.orquestrador.registro_agentes import AgenteRegistrado, executar_registro, listar_agentes
from core.config import ORQUESTRADOR_COOLDOWN_RESUMO_SEG, ORQUESTRADOR_PAUSA_ENTRE_AGENTES_SEG
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, gestor_telegram_configurado

logger = logging.getLogger("agente_orquestrador")


def _interpretar_ok(raw: Any) -> bool:
    if isinstance(raw, dict):
        if raw.get("erro") and raw.get("ok") is not False:
            pass
        if "ok" in raw:
            return bool(raw["ok"])
        if raw.get("erro"):
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
            return "ok"
        return ", ".join(partes)
    if isinstance(raw, bool):
        return "ok" if raw else "falha"
    return "ok"


def _executar_agente(registro: AgenteRegistrado) -> dict[str, Any]:
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
        resultado["resumo"] = _extrair_resumo(raw)
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


def _montar_resumo_telegram(ciclo: dict[str, Any], *, titulo: str) -> str:
    linhas = [
        titulo,
        "",
        (
            f"✅ {ciclo['ok']} ok | ❌ {ciclo['falhas']} falha | "
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
    incrementar(f"{prefixo}.ciclo", tags=[f"falhas:{ciclo['falhas']}"])


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

    logger.info("%s: iniciando ciclo com %s agente(s)", log_prefix, len(agentes))

    for registro in agentes:
        resultados.append(_executar_agente(registro))
        if pausa > 0:
            time.sleep(pausa)

    ok_count = sum(1 for r in resultados if r.get("ok"))
    falhas = len(resultados) - ok_count
    duracao_ms = (time.monotonic() - inicio_ciclo) * 1000

    ciclo = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(resultados),
        "ok": ok_count,
        "falhas": falhas,
        "duracao_ms": duracao_ms,
        "duracao_seg": duracao_ms / 1000,
        "agentes": resultados,
        "resumo_telegram_enviado": False,
    }

    _enviar_metricas_ciclo(ciclo, prefixo=prefixo_metrica)

    try:
        from core.atomic_io import escrever_json_atomico
        from core.config import ROOT

        escrever_json_atomico(
            ROOT / "logs" / "orquestrador_ultimo_ciclo.json",
            {
                "timestamp": ciclo["timestamp"],
                "ok": ok_count == len(resultados),
                "falhas": falhas,
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

    if enviar_resumo_telegram and resultados:
        msg = _montar_resumo_telegram(ciclo, titulo=titulo_resumo)
        ciclo["resumo_telegram_enviado"] = bool(
            alertar_gestor(
                msg,
                chave=chave_cooldown,
                cooldown_segundos=cooldown_segundos,
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
