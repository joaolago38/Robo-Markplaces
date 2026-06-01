"""
scripts/scheduler_varredura_marketplaces.py
Scheduler diário (7 dias por semana) para varredura de marketplaces.

Uso:
    py scripts/scheduler_varredura_marketplaces.py

Variáveis opcionais:
    MARKETPLACE_SCHEDULE_HOUR=6
    MARKETPLACE_SCHEDULE_MINUTE=0
    MARKETPLACE_RUN_ON_START=true
    MARKETPLACE_SLEEP_SECONDS=30
    MARKETPLACE_DRY_RUN_REPRICING=true
    MARKETPLACE_ALERTAR_ATENCAO=false
    MARKETPLACE_KEEPALIVE_LIMITE_DIAS=5
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentes.agente_varredura_marketplaces import executar_varredura  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("scheduler_varredura_marketplaces")


def _to_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "sim"}


def _to_int(value: str | None, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(str(value))
        return max(min_value, min(max_value, parsed))
    except (TypeError, ValueError):
        return default


def _proxima_execucao(hour: int, minute: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _salvar_ultimo_resultado(payload: dict) -> None:
    out = ROOT / "logs" / "scheduler_varredura_marketplaces.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    hour = _to_int(os.getenv("MARKETPLACE_SCHEDULE_HOUR"), default=6, min_value=0, max_value=23)
    minute = _to_int(os.getenv("MARKETPLACE_SCHEDULE_MINUTE"), default=0, min_value=0, max_value=59)
    sleep_seconds = _to_int(os.getenv("MARKETPLACE_SLEEP_SECONDS"), default=30, min_value=5, max_value=300)
    run_on_start = _to_bool(os.getenv("MARKETPLACE_RUN_ON_START"), default=True)
    dry_run_repricing = _to_bool(os.getenv("MARKETPLACE_DRY_RUN_REPRICING"), default=True)
    alertar_atencao = _to_bool(os.getenv("MARKETPLACE_ALERTAR_ATENCAO"), default=False)
    limite_dias_sem_acesso = _to_int(os.getenv("MARKETPLACE_KEEPALIVE_LIMITE_DIAS"), default=5, min_value=1, max_value=30)

    logger.info(
        "Scheduler diário ativo: todos os dias às %02d:%02d (7x por semana).",
        hour,
        minute,
    )

    if run_on_start:
        logger.info("Executando varredura inicial ao iniciar o processo.")
        payload = executar_varredura(
            limite_dias_sem_acesso=limite_dias_sem_acesso,
            alertar_quando_atencao=alertar_atencao,
            dry_run_repricing=dry_run_repricing,
        )
        _salvar_ultimo_resultado(payload)

    proxima = _proxima_execucao(hour, minute)
    logger.info("Próxima execução agendada para: %s", proxima.isoformat(timespec="seconds"))

    while True:
        agora = datetime.now()
        if agora >= proxima:
            logger.info("Disparando varredura agendada.")
            payload = executar_varredura(
                limite_dias_sem_acesso=limite_dias_sem_acesso,
                alertar_quando_atencao=alertar_atencao,
                dry_run_repricing=dry_run_repricing,
            )
            _salvar_ultimo_resultado(payload)
            proxima = _proxima_execucao(hour, minute, now=agora + timedelta(seconds=1))
            logger.info("Próxima execução agendada para: %s", proxima.isoformat(timespec="seconds"))
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
