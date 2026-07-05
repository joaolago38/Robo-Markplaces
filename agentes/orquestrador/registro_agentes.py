"""
agentes/orquestrador/registro_agentes.py
Catálogo de agentes executáveis pelo orquestrador de 30 minutos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, Callable


@dataclass(frozen=True)
class AgenteRegistrado:
    id: str
    nome: str
    categoria: str
    importar: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    notas: str = ""


def _resolver_fn(registro: AgenteRegistrado) -> Callable[..., Any]:
    modulo_path, attr = registro.importar.split(":", 1)
    modulo = import_module(modulo_path)
    return getattr(modulo, attr)


# Agentes excluídos de propósito (não são monitoramento contínuo ou são destrutivos):
# - publicador: publicaria posts a cada 30 min
# - relatorio / relatorio_financeiro / otimizador_listing: rotinas diárias/semanais
_AGENTES_PADRAO: tuple[AgenteRegistrado, ...] = (
    AgenteRegistrado("conectividade", "Conectividade marketplaces", "infra", "agentes.conectividade_marketplaces:executar"),
    AgenteRegistrado(
        "vigia_datadog",
        "Vigia Datadog",
        "infra",
        "agentes.infra.agente_vigia_datadog:executar",
        {"enviar_alerta": True},
        notas="Erros DD + inatividade 2h — alerta crítico se não verificado",
    ),
    AgenteRegistrado("vendas_whatsapp", "Vendas WhatsApp", "vendas", "agentes.vendas_notificador:executar"),
    AgenteRegistrado("chat_ml", "Chat Mercado Livre", "chat", "agentes.ml.agente_ml:executar"),
    AgenteRegistrado("chat_shopee", "Chat Shopee", "chat", "agentes.shopee.agente_shopee:executar"),
    AgenteRegistrado("chat_magalu", "Chat Magalu", "chat", "agentes.magalu.agente_magalu:executar"),
    AgenteRegistrado("chat_amazon", "Chat Amazon", "chat", "agentes.amazon.agente_amazon:executar"),
    AgenteRegistrado("auto_respostas", "Auto-respostas visuais", "chat", "agentes.auto_respostas_visuais:executar"),
    AgenteRegistrado("manutencao", "Keepalive marketplaces", "infra", "agentes.manutencao_marketplaces:executar"),
    AgenteRegistrado(
        "algoritmo",
        "Algoritmo marketplaces",
        "infra",
        "agentes.algoritmo_marketplaces:executar",
        {"alertar_quando_atencao": False},
    ),
    AgenteRegistrado(
        "sincronizar_estoque",
        "Sincronizar estoque",
        "operacao",
        "agentes.sincronizar_estoque_marketplaces:executar",
        {"dry_run": True},
    ),
    AgenteRegistrado(
        "repricing",
        "Repricing marketplaces",
        "operacao",
        "agentes.repricing.agente_repricing_marketplaces:executar",
        {"dry_run": True},
    ),
    AgenteRegistrado(
        "inteligencia_precos",
        "Inteligência de preços",
        "operacao",
        "agentes.precificacao.agente_inteligencia_precos:executar",
        {"enviar_alerta": True},
        notas="Comportamento de compra + sugestão de preço por marketplace",
    ),
    AgenteRegistrado(
        "repricing_impala",
        "Repricing Impala",
        "operacao",
        "agentes.repricing.agente_repricing_impala:executar",
        {"dry_run": True},
    ),
    AgenteRegistrado(
        "operacao_24h",
        "Operação 24h (snapshot)",
        "operacao",
        "agentes.operacao_24h:executar",
        {"dry_run_repricing": True, "dry_run_nfe": True},
        notas="Somente leitura no orquestrador; escrita real fica no workflow operacao_24h_seguranca",
    ),
    AgenteRegistrado(
        "leilao",
        "Leilões veículos",
        "monitor",
        "agentes.leilao.agente_leilao_veiculo:executar",
        {"enviar_alerta": True},
    ),
    AgenteRegistrado(
        "lojas_veiculos",
        "Lojas veículos FIPE",
        "monitor",
        "agentes.veiculos.agente_monitor_lojas_veiculos:executar",
        {"enviar_alerta": True},
        notas="Lucinei + Leopardo — carros até R$20k com margem FIPE",
    ),
    AgenteRegistrado(
        "licitacoes",
        "Licitações públicas",
        "monitor",
        "agentes.licitacao.agente_licitacoes:executar",
        {"enviar_alerta": True},
        notas="PNCP todos os estados + portais estaduais; somente leitura",
    ),
    AgenteRegistrado(
        "alibaba",
        "Alibaba importação",
        "monitor",
        "agentes.importacao.agente_alibaba_importacao:executar",
        {"enviar_alerta": True},
    ),
    AgenteRegistrado(
        "alibaba_inteligencia",
        "Alibaba câmbio + margem",
        "monitor",
        "agentes.importacao.agente_alibaba_importacao_inteligente:executar",
        {"enviar_alerta": True},
        notas="Dólar + custo landed + preços ML + alerta de lucro",
    ),
    AgenteRegistrado(
        "monitor_ml",
        "Monitor ML",
        "monitor",
        "agentes.ml.agente_monitor_ml:analisar",
        {"enviar_alerta": True},
    ),
    AgenteRegistrado(
        "relatorio_manha_ml",
        "Relatório manhã ML",
        "monitor",
        "agentes.ml.agente_relatorio_manha_ml:executar",
        {"enviar_alerta": True},
        notas="Visão matinal + propostas de preço com margem viável",
    ),
    AgenteRegistrado(
        "monitor_concorrentes",
        "Monitor concorrentes ML",
        "monitor",
        "agentes.ml.agente_monitor_concorrentes:executar",
        {"enviar_alerta": True},
    ),
    AgenteRegistrado(
        "monitor_anita",
        "Monitor esmaltes Anita",
        "monitor",
        "agentes.esmaltes.agente_monitor_anita:executar",
        {"enviar_alerta": True},
        notas="Cores/kits vs preferência + ranking marcas + margem",
    ),
    AgenteRegistrado(
        "monitor_mercado_esmaltes",
        "Monitor mercado esmaltes ML",
        "monitor",
        "agentes.esmaltes.agente_monitor_mercado_esmaltes:executar",
        {"enviar_alerta": True},
        notas="Todos esmaltes ML: cores, kits, margem viável e propostas de competição",
    ),
    AgenteRegistrado(
        "descoberta_produtos",
        "Descoberta produtos marketplace",
        "monitor",
        "agentes.descoberta.agente_descoberta_produtos:executar",
        {"enviar_alerta": True},
        notas="Público-alvo e oportunidades por marketplace (Claude + busca ML)",
    ),
    AgenteRegistrado("ads_gatilho", "Gatilho Ads ML", "monitor", "agentes.ml.agente_ads_gatilho:executar"),
    AgenteRegistrado(
        "meta_metricas",
        "Métricas Meta Ads",
        "social",
        "agentes.social.agente_metricas_meta:executar",
        {"alertar_quando_atencao": False},
    ),
    AgenteRegistrado(
        "trafego_manicures",
        "Tráfego manicures",
        "social",
        "agentes.social.agente_trafego_manicures:executar",
        {"alertar_todo_relatorio": False},
    ),
    AgenteRegistrado(
        "panorama",
        "Panorama ML/Magalu/Bling",
        "monitor",
        "agentes.panorama.agente_panorama:gerar_panorama",
        {"enviar_alerta": False, "emitir_nfe": False},
        notas="Resumo consolidado vai no alerta do orquestrador",
    ),
)


def listar_agentes(*, excluir: set[str] | None = None) -> list[AgenteRegistrado]:
    from core.config import ORQUESTRADOR_EXCLUIR

    bloqueados = ORQUESTRADOR_EXCLUIR | (excluir or set())
    return [a for a in _AGENTES_PADRAO if a.id not in bloqueados]


_AGENTES_PUSH_MAIN_EXTRA: tuple[AgenteRegistrado, ...] = (
    AgenteRegistrado(
        "renovar_tokens",
        "Renovar tokens OAuth",
        "infra",
        "agentes.orquestrador.runners:executar_renovar_tokens",
    ),
    AgenteRegistrado("relatorio", "Relatório GitHub", "relatorio", "agentes.relatorio:executar"),
    AgenteRegistrado(
        "relatorio_financeiro",
        "Relatório financeiro",
        "relatorio",
        "agentes.relatorio_financeiro:executar",
    ),
    AgenteRegistrado(
        "otimizador_listing",
        "Otimizador listing ML",
        "monitor",
        "agentes.ml.agente_otimizador_listing:executar",
        {"limite_itens": 5},
    ),
)


def listar_agentes_push_main(*, excluir: set[str] | None = None) -> list[AgenteRegistrado]:
    """
    Todos os agentes do ciclo 30min + rotinas extras de deploy (push main).
    Os crons dos workflows individuais permanecem inalterados.
    """
    vistos: set[str] = set()
    resultado: list[AgenteRegistrado] = []
    for registro in (*listar_agentes(excluir=excluir), *_AGENTES_PUSH_MAIN_EXTRA):
        if registro.id in vistos:
            continue
        vistos.add(registro.id)
        resultado.append(registro)
    return resultado


def executar_registro(registro: AgenteRegistrado) -> Any:
    fn = _resolver_fn(registro)
    return fn(**registro.kwargs)
