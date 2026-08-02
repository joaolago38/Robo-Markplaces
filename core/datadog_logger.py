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
    "busca_termo_ml": ("mercadolivre", "integracao"),
    "busca_externa_brave": ("mercadolivre", "integracao"),
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
    "claude_roteador": ("infra", "core"),
    "empresa_contexto": ("multi", "core"),
    "empresa_catalogo": ("multi", "core"),
    "vinculo_cnae_cnpj": ("multi", "integracao"),
    "monitor_ml_cnpj": ("mercadolivre", "integracao"),
    "decision_limits": ("multi", "integracao"),
    "contexto_ml_cnae_importacao": ("mercadolivre", "integracao"),
    "operacao_destino": ("multi", "integracao"),
    "portos_brasil": ("multi", "integracao"),
    "comparar_portos_alibaba": ("multi", "integracao"),
    "agente_comparar_portos_alibaba": ("multi", "agente"),
    "agente_monitor_cnpj_cnae": ("multi", "agente"),
    "claude_contexto_ml": ("mercadolivre", "core"),
    "claude_ml_estado": ("mercadolivre", "core"),
    "claude_ml_enriquecedor": ("mercadolivre", "core"),
    "claude_orcamento": ("infra", "core"),
    "claude_toggle": ("infra", "core"),
    "chat_claim": ("mercadolivre", "core"),
    "contexto_fechamento_ml": ("mercadolivre", "core"),
    "produto_lookup": ("mercadolivre", "core"),
    "resumo_ia": ("infra", "core"),
    "alertas_esmaltes": ("infra", "core"),
    "whatsapp": ("infra", "core"),
    "http_client": ("infra", "core"),
    "leilao_busca": ("multi", "integracao"),
    "leilao_comparacao_fipe": ("multi", "integracao"),
    "avaliacao_ia_leilao": ("multi", "integracao"),
    "alibaba_busca": ("multi", "integracao"),
    "avaliacao_ia_alibaba": ("multi", "integracao"),
    "config": ("infra", "core"),
    "state_backend": ("infra", "core"),
    "ssm_secrets": ("infra", "core"),

    # --- Agentes (regras de negócio por marketplace) ---
    "agente_faturamento": ("bling", "agente"),
    "agente_repricing_marketplaces": ("mercadolivre_e_outros", "agente"),
    "agente_repricing_impala": ("mercadolivre_e_outros", "agente"),
    "agente_inteligencia_precos": ("mercadolivre_e_outros", "agente"),
    "catalogo_produtos": ("multi", "core"),
    "sinais_comprador": ("multi", "integracao"),
    "sincronizar_estoque_marketplaces": ("mercadolivre_e_outros", "agente"),
    "agente_monitor_ml": ("mercadolivre", "agente"),
    "agente_relatorio_manha_ml": ("mercadolivre", "agente"),
    "agente_relatorio_estrategia_ml": ("mercadolivre", "agente"),
    "agente_ads_gatilho": ("mercadolivre_ads", "agente"),
    "agente_otimizador_listing": ("mercadolivre", "agente"),
    "agente_monitor_concorrentes": ("mercadolivre", "agente"),
    "agente_resumo_diario_novamix": ("mercadolivre", "agente"),
    "agente_resumo_conta_ml": ("mercadolivre", "agente"),
    "resumo_conta_ml": ("mercadolivre", "integracao"),
    "agente_monitor_sem_venda_ml": ("mercadolivre", "agente"),
    "analise_sem_venda": ("mercadolivre", "integracao"),
    "analise_loja_concorrente": ("mercadolivre", "integracao"),
    "acoes_novamix": ("mercadolivre", "integracao"),
    "analise_anuncio_concorrente": ("mercadolivre", "integracao"),
    "estrategia_vendas_ml": ("mercadolivre", "integracao"),
    "agente_monitor_anita": ("mercadolivre", "agente"),
    "agente_monitor_busca_kit_esmaltes": ("mercadolivre", "agente"),
    "agente_monitor_kits_esmaltes": ("mercadolivre", "agente"),
    "agente_montar_kits_impala": ("mercadolivre", "agente"),
    "agente_ecossistema_esmaltes": ("mercadolivre", "agente"),
    "ecossistema_esmaltes": ("mercadolivre", "integracao"),
    "agente_crescimento_esmaltes": ("mercadolivre", "agente"),
    "crescimento_esmaltes": ("mercadolivre", "integracao"),
    "agente_decisao_dia_esmaltes": ("mercadolivre", "agente"),
    "decisao_dia_esmaltes": ("mercadolivre", "integracao"),
    "agente_esmaltes_operacao": ("mercadolivre", "agente"),
    "agente_alibaba_sourcing": ("multi", "agente"),
    "contrato_impulso_ml": ("mercadolivre", "integracao"),
    "algoritmo_eventos": ("multi", "core"),
    "agente_conversao_manicures": ("social", "agente"),
    "conversao_manicures": ("social", "integracao"),
    "agente_necessidade_manicures": ("social", "agente"),
    "necessidade_manicures": ("social", "integracao"),
    "sustentabilidade_ads_ml": ("social", "integracao"),
    "meta_inbox": ("meta", "integracao"),
    "planilha_impala": ("mercadolivre", "integracao"),
    "agente_monitor_removedores_unha": ("mercadolivre", "agente"),
    "agente_monitor_tendencias_esmaltes": ("multi", "agente"),
    "agente_monitor_mercado_esmaltes": ("mercadolivre", "agente"),
    "agente_comparativo_anita_impala": ("mercadolivre", "agente"),
    "agente_comparativo_ml_shopee": ("multi", "agente"),
    "agente_monitor_filamentos_ml": ("mercadolivre", "agente"),
    "analise_filamentos_ml": ("mercadolivre", "integracao"),
    "filamentos_cruzamento_alibaba": ("multi", "integracao"),
    "sourcing_filamentos": ("multi", "integracao"),
    "agente_monitor_masterprint_petg": ("mercadolivre", "agente"),
    "analise_masterprint_petg": ("mercadolivre", "integracao"),
    "custos_masterprint_petg": ("mercadolivre", "integracao"),
    "agente_monitor_masterprint_escritorio": ("mercadolivre", "agente"),
    "analise_masterprint_escritorio": ("mercadolivre", "integracao"),
    "custos_masterprint_escritorio": ("mercadolivre", "integracao"),
    "avaliacao_ia_masterprint": ("multi", "integracao"),
    "masterprint_ramo": ("mercadolivre", "integracao"),
    "empresa_contexto": ("multi", "core"),
    "empresa_catalogo": ("multi", "core"),
    "vinculo_cnae_cnpj": ("multi", "integracao"),
    "monitor_ml_cnpj": ("mercadolivre", "integracao"),
    "decision_limits": ("multi", "integracao"),
    "contexto_ml_cnae_importacao": ("mercadolivre", "integracao"),
    "operacao_destino": ("multi", "integracao"),
    "portos_brasil": ("multi", "integracao"),
    "comparar_portos_alibaba": ("multi", "integracao"),
    "agente_comparar_portos_alibaba": ("multi", "agente"),
    "agente_monitor_cnpj_cnae": ("multi", "agente"),
    "claude_ml_estado": ("mercadolivre", "core"),
    "claude_ml_enriquecedor": ("mercadolivre", "core"),
    "agente_monitor_acetona_cruzeiro": ("mercadolivre", "agente"),
    "comparativo_anita_impala": ("mercadolivre", "integracao"),
    "ml_shopee_categorias": ("multi", "integracao"),
    "busca_kit_frequencia": ("mercadolivre", "integracao"),
    "analise_kits_esmaltes": ("mercadolivre", "integracao"),
    "analise_removedores": ("mercadolivre", "integracao"),
    "busca_removedores": ("mercadolivre", "integracao"),
    "busca_termo_externa": ("multi", "integracao"),
    "busca_multi_marketplace": ("multi", "integracao"),
    "tendencias_internet": ("multi", "integracao"),
    "cruzamento_tendencias_mercado": ("multi", "integracao"),
    "avaliacao_ia_removedores": ("mercadolivre", "integracao"),
    "analise_acetona_cruzeiro": ("mercadolivre", "integracao"),
    "analise_anita": ("mercadolivre", "integracao"),
    "agente_descoberta_produtos": ("multi", "agente"),
    "descoberta_coletores": ("multi", "integracao"),
    "descoberta_alibaba": ("multi", "integracao"),
    "agente_leilao_veiculo": ("multi", "agente"),
    "agente_monitor_sumare_leiloes": ("multi", "agente"),
    "sumare_leiloes": ("multi", "integracao"),
    "copart_leiloes": ("multi", "integracao"),
    "superbid_leiloes": ("multi", "integracao"),
    "sodre_leiloes": ("multi", "integracao"),
    "leilao_coletores_base": ("multi", "integracao"),
    "agente_monitor_lojas_veiculos": ("multi", "agente"),
    "agente_monitor_carros_batidos": ("multi", "agente"),
    "agente_licitacoes": ("multi", "agente"),
    "licitacao_busca": ("multi", "integracao"),
    "licitacao_pncp": ("multi", "integracao"),
    "agente_alibaba_importacao": ("multi", "agente"),
    "agente_alibaba_importacao_inteligente": ("multi", "agente"),
    "agente_ml_tendencias_importacao": ("multi", "agente"),
    "tendencias_ml_importacao": ("multi", "integracao"),
    "agente_calculo_importacao_aerea": ("multi", "agente"),
    "cotacao_usd": ("infra", "integracao"),
    "custo_landed": ("infra", "integracao"),
    "calculo_importacao_aerea": ("multi", "integracao"),
    "perfil_empresa_importacao": ("multi", "integracao"),
    "analise_margem_importacao": ("multi", "integracao"),
    "agente_orquestrador": ("multi", "orquestrador"),
    "agente_sync_push_main": ("multi", "orquestrador"),
    "agente_push_deploy": ("multi", "orquestrador"),
    "agente_git_branches": ("multi", "orquestrador"),
    "git_deploy": ("infra", "core"),
    "fipe_client": ("infra", "integracao"),
    "veiculos_scrapers": ("multi", "integracao"),
    "veiculos_comparacao": ("multi", "integracao"),
    "ddg_lite": ("multi", "integracao"),
    "telegram_explicacao": ("infra", "core"),
    "telegram_gate": ("infra", "core"),
    "agente_ml": ("mercadolivre", "agente"),
    "painel_item": ("mercadolivre", "agente"),
    "agente_shopee": ("shopee", "agente"),
    "agente_magalu": ("magalu", "agente"),
    "agente_amazon": ("amazon", "agente"),
    "agente_metricas_meta": ("meta", "agente"),
    "agente_trafego_manicures": ("meta", "agente"),
    "agente_promocoes_manicures": ("social", "agente"),
    "promocoes_manicures": ("social", "integracao"),
    "publicador": ("social", "agente"),
    "relatorio": ("bling", "agente"),

    # --- Agentes multi-marketplace (tocam mais de um canal por natureza) ---
    "agente_varredura_marketplaces": ("multi", "agente"),
    "manutencao_marketplaces": ("multi", "agente"),
    "conectividade_marketplaces": ("multi", "agente"),
    "algoritmo_marketplaces": ("multi", "agente"),
    "auto_respostas_visuais": ("multi", "agente"),
    "vendas_notificador": ("multi", "agente"),
    "agente_monitor_margem_vendas": ("multi", "agente"),
    "analise_margem_vendas": ("multi", "integracao"),
    "agente_panorama": ("multi", "agente"),
    "relatorio_financeiro": ("multi", "agente"),
    "operacao_24h": ("infra", "agente"),
    "agente_vigia_datadog": ("infra", "agente"),
    "agente_consumo_claude": ("infra", "agente"),
    "buffer_erros_datadog": ("infra", "core"),
    "consulta_erros_datadog": ("infra", "core"),
    "vigia_saude_datadog": ("infra", "core"),

    # --- Diagnóstico interno deste módulo ---
    "datadog_logger": ("infra", "core"),
    "datadog_metrics": ("infra", "core"),
    "series_historica": ("infra", "core"),
    "graficos": ("infra", "core"),
    "prontidao": ("infra", "core"),

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
_falhas_envio_logs = 0
_ultimo_aviso_falha_log_ts = 0.0


def _avisar_falha_envio_log(motivo: str) -> None:
    global _falhas_envio_logs, _ultimo_aviso_falha_log_ts
    import time

    _falhas_envio_logs += 1
    agora = time.monotonic()
    if agora - _ultimo_aviso_falha_log_ts < 60:
        return
    _ultimo_aviso_falha_log_ts = agora
    # Logger próprio — se o handler DD falhar, o console ainda vê o aviso.
    logging.getLogger("datadog_logger").warning(
        "Datadog logs envio falhou (%s): %s",
        _falhas_envio_logs,
        motivo,
    )


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


def _espelhar_erro_local(record: logging.LogRecord, mensagem: str) -> None:
    if record.levelno < logging.ERROR:
        return
    try:
        from integracoes.datadog.buffer_erros import registrar_erro_local

        registrar_erro_local(
            nome_logger=record.name,
            mensagem=mensagem,
            status=record.levelname.lower(),
            error_kind=getattr(record, "error_kind", None),
            error_message=getattr(record, "error_message", None),
        )
    except Exception:
        pass


class LocalErrorBufferHandler(logging.Handler):
    """Espelha ERROR+ no buffer local — funciona mesmo sem DD_API_KEY."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _espelhar_erro_local(record, self.format(record) if self.formatter else record.getMessage())
        except Exception:
            pass


class DatadogLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        from core.config import DD_SITE

        self._url = f"https://http-intake.logs.{DD_SITE}/api/v2/logs"

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.INFO:
            return
        # Evita recursão se o aviso de falha de envio voltar para este handler
        if record.name in ("datadog_logger", "datadog_metrics"):
            return
        from core.config import DD_API_KEY, DD_ENV, DD_LOGS_ENABLED
        from core.http_errors import mascarar_segredos_http

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

            mensagem_bruta = self.format(record) if self.formatter else record.getMessage()
            mensagem = mascarar_segredos_http(mensagem_bruta)

            payload_entry: dict = {
                "message": mensagem,
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
                    error_attrs["message"] = mascarar_segredos_http(str(error_message))
                if record.exc_info:
                    error_attrs["stack"] = mascarar_segredos_http(
                        logging.Formatter().formatException(record.exc_info)
                    )
                if error_attrs:
                    payload_entry["error"] = error_attrs

            payload = [payload_entry]
            resp = requests.post(
                self._url,
                headers={"DD-API-KEY": DD_API_KEY, "Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=3,
            )
            if getattr(resp, "status_code", None) is not None:
                status = resp.status_code
                if isinstance(status, int) and status >= 300:
                    _avisar_falha_envio_log(f"HTTP {status}")
        except Exception as exc:
            _avisar_falha_envio_log(str(exc)[:160])


def configurar_logging_datadog() -> None:
    """Anexa handlers de log (buffer local + Datadog quando configurado)."""
    root = logging.getLogger()
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)

    formatter = logging.Formatter("%(message)s")

    if not any(isinstance(h, LocalErrorBufferHandler) for h in root.handlers):
        buffer_handler = LocalErrorBufferHandler()
        buffer_handler.setFormatter(formatter)
        root.addHandler(buffer_handler)

    from core.config import DD_API_KEY, DD_LOGS_ENABLED

    if not DD_LOGS_ENABLED or not DD_API_KEY:
        return

    if any(isinstance(h, DatadogLogHandler) for h in root.handlers):
        return

    dd_handler = DatadogLogHandler()
    dd_handler.setFormatter(formatter)
    root.addHandler(dd_handler)
