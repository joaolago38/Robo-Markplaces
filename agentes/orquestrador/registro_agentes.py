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
    AgenteRegistrado(
        "consumo_claude",
        "Consumo Claude (orçamento US$)",
        "infra",
        "agentes.infra.agente_consumo_claude:executar",
        notas="Painel usado/resta no Telegram; hard stop no claude_client",
    ),
    AgenteRegistrado("vendas_whatsapp", "Vendas WhatsApp", "vendas", "agentes.vendas_notificador:executar"),
    AgenteRegistrado(
        "monitor_margem_vendas",
        "Margem das vendas (Telegram)",
        "vendas",
        "agentes.vendas.agente_monitor_margem_vendas:executar",
        {"enviar_alerta": True},
        notas="Lucro/margem de pedidos ML/Shopee/Magalu/Amazon — alerta se abaixo do mínimo",
    ),
    AgenteRegistrado(
        "chat_ml",
        "Chat Mercado Livre",
        "chat",
        "agentes.ml.agente_ml:executar",
        notas="Dono único das respostas ML; usa snapshot conversão + MLB→SKU",
    ),
    AgenteRegistrado("chat_shopee", "Chat Shopee", "chat", "agentes.shopee.agente_shopee:executar"),
    AgenteRegistrado("chat_magalu", "Chat Magalu", "chat", "agentes.magalu.agente_magalu:executar"),
    AgenteRegistrado("chat_amazon", "Chat Amazon", "chat", "agentes.amazon.agente_amazon:executar"),
    AgenteRegistrado(
        "auto_respostas",
        "Auto-respostas visuais",
        "chat",
        "agentes.auto_respostas_visuais:executar",
        notas="Shopee/Magalu/Amazon; ML só se AUTO_RESPOSTAS_ML=1",
    ),
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
        "sumare_leiloes",
        "Sumaré Leilões PREFEITURA/DETRAN",
        "monitor",
        "agentes.leilao.agente_monitor_sumare_leiloes:executar",
        {"enviar_alerta": True},
        notas="Veículos com documento no site oficial — alerta de lances",
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
        "carros_batidos",
        "Carros batidos — todas as lojas",
        "monitor",
        "agentes.veiculos.agente_monitor_carros_batidos:executar",
        {"enviar_alerta": True},
        notas="Lucinei, Leopardo, Motorjan, Velozes — alerta Telegram de novos anúncios",
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
        "ml_tendencias_importacao",
        "ML tendências × Alibaba",
        "monitor",
        "agentes.importacao.agente_ml_tendencias_importacao:executar",
        {"enviar_alerta": True},
        notas="Demanda ML + cotação Alibaba + veredito se vale importar",
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
        "relatorio_estrategia_ml",
        "Relatório estratégia vendas ML",
        "monitor",
        "agentes.ml.agente_relatorio_estrategia_ml:executar",
        {"enviar_alerta": True, "coletar_fresco": True},
        notas="Top ações da semana: preço, ads, diferenciar, canal próprio",
    ),
    AgenteRegistrado(
        "monitor_concorrentes",
        "Monitor concorrentes ML",
        "monitor",
        "agentes.ml.agente_monitor_concorrentes:executar",
        {"enviar_alerta": True},
    ),
    AgenteRegistrado(
        "resumo_conta_ml",
        "Resumo conta ML (painel)",
        "monitor",
        "agentes.ml.agente_resumo_conta_ml:executar",
        {"enviar_alerta": True},
        notas="Espelho do Resumo do vendedor: pendências, reputação, envios → Telegram",
    ),
    AgenteRegistrado(
        "resumo_diario_novamix",
        "Resumo diário Novamix",
        "monitor",
        "agentes.ml.agente_resumo_diario_novamix:executar",
        {"enviar_alerta": True},
        notas="Desempenho + plano guerra/competir + Ads (pausar com confirmação) Novamix",
    ),
    AgenteRegistrado(
        "monitor_sem_venda_ml",
        "Anúncios ML sem venda 30d",
        "monitor",
        "agentes.ml.agente_monitor_sem_venda_ml:executar",
        {"enviar_alerta": True},
        notas="Sugere preço/ads/republicar para ativos sem pedido no período",
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
        "monitor_busca_kit_esmaltes",
        "Busca kit esmaltes Anita/Impala (frequência)",
        "monitor",
        "agentes.esmaltes.agente_monitor_busca_kit_esmaltes:executar",
        {"enviar_alerta": True},
        notas="Conta buscas diárias por kit/cor Anita e Impala no ML + Telegram",
    ),
    AgenteRegistrado(
        "monitor_kits_esmaltes",
        "Monitor kits esmaltes — vendas e marcas",
        "monitor",
        "agentes.esmaltes.agente_monitor_kits_esmaltes:executar",
        {"enviar_alerta": True},
        notas="Varre todos os kits de esmaltes no ML: vendas, preços e ranking de marcas",
    ),
    AgenteRegistrado(
        "montar_kits_impala",
        "Montar kits Impala (planilha × ML)",
        "monitor",
        "agentes.esmaltes.agente_montar_kits_impala:executar",
        {"enviar_alerta": True},
        notas="Cruza cores Impala da planilha com kits mais vendidos no ML e sugere montagem",
    ),
    AgenteRegistrado(
        "ecossistema_esmaltes",
        "Ecossistema esmaltes (plano consolidado)",
        "monitor",
        "agentes.esmaltes.agente_ecossistema_esmaltes:executar",
        {"enviar_alerta": True},
        notas="Cor atrai → kit+anexos+B2B pagam. Lê snapshots e monta plano 7/30/90d. Fora do ciclo 30min",
    ),
    AgenteRegistrado(
        "monitor_removedores_unha",
        "Monitor removedores de unha — ranking",
        "monitor",
        "agentes.esmaltes.agente_monitor_removedores_unha:executar",
        {"enviar_alerta": True},
        notas="Removedores de unha no ML: nomes, fabricnking por vendas",
    ),
    antes e ra    AgenteRegistrado(
        "monitor_tendencias_esmaltes",
        "Tendências esmaltes — web × marketplaces",
        "monitor",
        "agentes.esmaltes.agente_monitor_tendencias_esmaltes:executar",
        {"enviar_alerta": True},
        notas="Varre internet (Brave/DDG) e cruza com ML/Magalu/Shopee/Amazon para tendências",
    ),
    AgenteRegistrado(
        "comparativo_anita_impala",
        "Comparativo Anita vs Impala",
        "monitor",
        "agentes.esmaltes.agente_comparativo_anita_impala:executar",
        {"enviar_alerta": True},
        notas="Demanda, perfil de consumidor e plano para vencer Impala no ML",
    ),
    AgenteRegistrado(
        "comparativo_ml_shopee",
        "Comparativo ML × Shopee",
        "monitor",
        "agentes.comparativo.agente_comparativo_ml_shopee:executar",
        {"enviar_alerta": True},
        notas="Esmaltes e filamentos 3D: score e veredito de canal (ML vs Shopee)",
    ),
    AgenteRegistrado(
        "monitor_filamentos_ml",
        "Monitor filamentos 3D ML",
        "monitor",
        "agentes.filamentos.agente_monitor_filamentos_ml:executar",
        {"enviar_alerta": True},
        notas="PLA/PETG/ABS/TPU no ML: cores mais vendidas + cruzamento Alibaba (FOB×ML)",
    ),
    AgenteRegistrado(
        "monitor_acetona_cruzeiro",
        "Monitor Acetona Cruzeiro ML",
        "monitor",
        "agentes.esmaltes.agente_monitor_acetona_cruzeiro:executar",
        {"enviar_alerta": True},
        notas="Vendedores, margem, manicures BR e estratégias Claude + Impala",
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
        "promocoes_manicures",
        "Promoções manicures ML",
        "social",
        "agentes.social.agente_promocoes_manicures:executar",
        notas="WhatsApp grupo + Telegram — kits esmaltes Impala no ML; roda no workflow promocoes_manicures",
    ),
    AgenteRegistrado(
        "conversao_manicures",
        "Conversão manicures WA/IG/FB/ML",
        "social",
        "agentes.social.agente_conversao_manicures:executar",
        notas="Haiku: oferta + inbox Meta/WA; chat ML ficou com agentes.ml (CONVERSAO_MANICURES_CHAT_ML=0). Workflow 4h, fora do ciclo 30min",
    ),
    AgenteRegistrado(
        "necessidade_manicures",
        "Necessidade manicures × ML × canais",
        "social",
        "agentes.social.agente_necessidade_manicures:executar",
        notas="Sinais (tendências/busca/Anita/leads) → match catálogo ML → SIM gestor → WA/TG. Fora do ciclo 30min",
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
