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

from core.request_context import obter_request_id

# Mapa: nome do logger (o argumento passado para logging.getLogger(...))
# -> (marketplace, componente)
#
# IMPORTANTE: a chave aqui é o nome efetivamente passado para getLogger(),
# não o nome do arquivo/módulo. Ex.: integracoes/bling/bling_client.py usa
# logging.getLogger("bling"), então a chave é "bling" — não "bling_client".
#
# `marketplace` alimenta a tag `marketplace:` (facet principal para filtrar
# por canal de venda no Log Explorer / dashboards).
# `componente` alimenta a tag `componente:` (camada: integracao, agente,
# core, script, api) — útil para separar "client de API" de "regra de
# negócio" mesmo dentro do mesmo marketplace.
#
# A cobertura deste dicionário é validada por
# tests/test_datadog_logger.py::test_todos_os_loggers_do_repo_estao_mapeados,
# que varre o código em busca de getLogger(...) e falha se algum nome novo
# não tiver entrada aqui — isso evita que logs voltem a cair em "geral"
# silenciosamente quando um novo módulo for criado.
_LOGGER_META = {
    # --- Integrações (clientes de API por marketplace) ---
    "bling": ("bling", "integracao"),
    "ml_client": ("mercadolivre", "integracao"),
    "ml_product_ads": ("mercadolivre_ads", "integracao"),
    "magalu_client": ("magalu", "integracao"),
    "shopee_client": ("shopee", "integracao"),
    "amazon_client": ("amazon", "integracao"),
    "meta": ("meta", "integracao"),
    "meta_ads_client": ("meta_ads", "integracao"),
    "lojahub": ("lojahub", "integracao"),

    # --- Core (infraestrutura compartilhada, não é um marketplace) ---
    "token_manager": ("bling_e_ml", "core"),
    "notificador": ("infra", "core"),
    "claude": ("infra", "core"),
    "resumo_ia": ("infra", "core"),
    "alertas_esmaltes": ("infra", "core"),
    "whatsapp": ("infra", "core"),
    "http_client": ("infra", "core"),
    "config": ("infra", "core"),

    # --- Agentes (regras de negócio por marketplace) ---
    "agente_faturamento": ("bling", "agente"),
    "agente_repricing_marketplaces": ("mercadolivre_e_outros", "agente"),
    "agente_repricing_impala": ("mercadolivre_e_outros", "agente"),
    "sincronizar_estoque_marketplaces": ("mercadolivre_e_outros", "agente"),
    "agente_monitor_ml": ("mercadolivre", "agente"),
    "agente_ads_gatilho": ("mercadolivre_ads", "agente"),
    "agente_otimizador_listing": ("mercadolivre", "agente"),
    "agente_monitor_concorrentes": ("mercadolivre", "agente"),
    "agente_ml": ("mercadolivre", "agente"),
    "painel_item": ("mercadolivre", "agente"),
    "agente_shopee": ("shopee", "agente"),
    "agente_magalu": ("magalu", "agente"),
    "agente_amazon": ("amazon", "agente"),
    "agente_metricas_meta": ("meta", "agente"),
    "agente_trafego_manicures": ("meta", "agente"),
    "publicador": ("social", "agente"),
    "relatorio": ("bling", "agente"),

    # --- Agentes multi-marketplace (tocam mais de um canal por natureza) ---
    "agente_varredura_marketplaces": ("multi", "agente"),
    "manutencao_marketplaces": ("multi", "agente"),
    "conectividade_marketplaces": ("multi", "agente"),
    "algoritmo_marketplaces": ("multi", "agente"),
    "auto_respostas_visuais": ("multi", "agente"),
    "vendas_notificador": ("multi", "agente"),
    "agente_panorama": ("multi", "agente"),
    "relatorio_financeiro": ("multi", "agente"),
    "operacao_24h": ("infra", "agente"),

    # --- Diagnóstico interno deste módulo ---
    "datadog_logger": ("infra", "core"),

    # --- Scripts / API ---
    "renovar_tokens": ("multi", "script"),
    "renovar_bling_local": ("bling", "script"),
    "scheduler_varredura_marketplaces": ("multi", "script"),
    "api": ("infra", "api"),
}

_DEFAULT_META = ("geral", "outros")

# Evita inundar o Datadog com o mesmo aviso de "logger não mapeado" a cada
# linha de log — avisa uma única vez por nome de logger, por processo.
_avisados_sem_mapeamento: set[str] = set()


def _resolver_meta(nome_logger: str) -> tuple[str, str]:
    meta = _LOGGER_META.get(nome_logger)
    if meta is not None:
        return meta
    if nome_logger not in _avisados_sem_mapeamento:
        _avisados_sem_mapeamento.add(nome_logger)
        logging.getLogger("datadog_logger").warning(
            "Logger '%s' sem marketplace/componente mapeado em "
            "_LOGGER_META — caindo em tags 'geral/outros'. Adicione uma "
            "entrada em core/datadog_logger.py.",
            nome_logger,
        )
    return _DEFAULT_META


class DatadogLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        from core.config import DD_SITE

        self._url = f"https://http-intake.logs.{DD_SITE}/api/v2/logs"

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.INFO:
            return
        from core.config import DD_API_KEY, DD_ENV, DD_LOGS_ENABLED

        if not DD_LOGS_ENABLED or not DD_API_KEY:
            return
        try:
            marketplace, componente = _resolver_meta(record.name)
            ddtags = (
                f"env:{DD_ENV},logger:{record.name},"
                f"marketplace:{marketplace},componente:{componente},"
                f"level:{record.levelname.lower()}"
            )
            request_id = obter_request_id()
            if request_id:
                ddtags += f",request_id:{request_id}"

            payload_entry: dict = {
                "message": self.format(record),
                "ddsource": "python",
                "service": "robo-markplaces",
                # `status` é um standard attribute do Datadog: além de
                # virar tag, alimenta o facet "Status" nativo do Log
                # Explorer (cores/severidade prontas, sem facet custom).
                "status": record.levelname.lower(),
                "ddtags": ddtags,
            }
            if request_id:
                payload_entry["request_id"] = request_id

            # Atributos padrão de erro do Datadog (alimentam a página
            # "Errors"/Error Tracking). `error_kind`/`error_message` são
            # passados via logger.error(..., extra={...}) nos pontos já
            # instrumentados (core/http_client.py, core/claude_client.py).
            # Quando exc_info estiver presente (logger.exception ou
            # exc_info=True), aproveitamos o stack trace real também.
            if record.levelno >= logging.ERROR:
                error_kind = getattr(record, "error_kind", None)
                error_message = getattr(record, "error_message", None)
                error_attrs: dict = {}
                if error_kind:
                    error_attrs["kind"] = error_kind
                if error_message:
                    error_attrs["message"] = error_message
                if record.exc_info:
                    error_attrs["stack"] = logging.Formatter().formatException(record.exc_info)
                if error_attrs:
                    payload_entry["error"] = error_attrs

            payload = [payload_entry]
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
