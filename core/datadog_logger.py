"""
core/datadog_logger.py
Handler de logging que envia registros para o Datadog Log Management
via HTTP Intake API. Nunca lança exceção — falha de rede no envio do
log não pode derrubar a aplicação.
"""
from __future__ import annotations

import json
import logging

import requests

_MARKETPLACE_POR_LOGGER = {
    "bling_client": "bling",
    "token_manager": "bling_e_ml",
    "ml_client": "mercadolivre",
    "ml_product_ads": "mercadolivre_ads",
    "magalu_client": "magalu",
    "shopee_client": "shopee",
    "agente_faturamento": "bling",
    "agente_repricing_marketplaces": "mercadolivre_e_outros",
    "sincronizar_estoque_marketplaces": "mercadolivre_e_outros",
    "agente_monitor_ml": "mercadolivre",
    "agente_ads_gatilho": "mercadolivre_ads",
}


class DatadogLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        from core.config import DD_SITE

        self._url = f"https://http-intake.logs.{DD_SITE}/api/v2/logs"

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.INFO:
            return
        from core.config import DD_API_KEY, DD_LOGS_ENABLED

        if not DD_LOGS_ENABLED or not DD_API_KEY:
            return
        try:
            marketplace = _MARKETPLACE_POR_LOGGER.get(record.name, "geral")
            payload = [
                {
                    "message": self.format(record),
                    "ddsource": "python",
                    "service": "robo-markplaces",
                    "ddtags": (
                        f"env:production,logger:{record.name},"
                        f"marketplace:{marketplace},level:{record.levelname.lower()}"
                    ),
                }
            ]
            requests.post(
                self._url,
                headers={"DD-API-KEY": DD_API_KEY, "Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=3,
            )
        except Exception:
            pass


def configurar_logging_datadog() -> None:
    """Anexa DatadogLogHandler ao logger raiz (idempotente)."""
    root = logging.getLogger()
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)

    from core.config import DD_API_KEY, DD_LOGS_ENABLED

    if not DD_LOGS_ENABLED or not DD_API_KEY:
        return

    for handler in root.handlers:
        if isinstance(handler, DatadogLogHandler):
            return

    handler = DatadogLogHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
