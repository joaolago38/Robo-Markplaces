"""
core/horario.py
Horário de exibição alinhado ao fuso do Brasil (UTC-3 / Brasília).
Usado em cabeçalhos Telegram/WhatsApp — evita UTC no CI (GitHub Actions).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Brasil sem horário de verão desde 2019 — offset fixo -3h (igual ml_client).
TZ_BRASIL = timezone(timedelta(hours=-3))


def agora_brasil() -> datetime:
    """Datetime atual no fuso de Brasília (UTC-3)."""
    return datetime.now(TZ_BRASIL)


def formatar_data_hora_br(fmt: str = "%d/%m %H:%M") -> str:
    """Formata data/hora local BR para mensagens ao usuário."""
    return agora_brasil().strftime(fmt)
