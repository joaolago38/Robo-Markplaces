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
        {"enviar_alerta": False},
        notas="Datadog a cada ciclo; Telegram fica no workflow de 6h",
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
    # sincronizar_estoque / repricing / repricing_impala:
    # fora do ciclo 30min (pesavam em dry-run). Escrita real = workflows 2h.
    # operacao_24h fica no registro mas em ORQUESTRADOR_EXCLUIR (só workflow 2h).
    AgenteRegistrado(
        "inteligencia_precos",
        "Inteligência de preços",
        "operacao",
        "agentes.precificacao.agente_inteligencia_precos:executar",
        {"enviar_alerta": True},
        notas="Comportamento de compra + sugestão de preço por marketplace",
    ),
    AgenteRegistrado(
        "operacao_24h",
        "Operação 24h (snapshot)",
        "operacao",
        "agentes.operacao_24h:executar",
        {"dry_run_repricing": True, "dry_run_nfe": True},
        notas="Fora do ciclo 30min; escrita real = operacao_24h_seguranca (2h)",
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
        notas="DESLIGADO — SSL do site; só manual. Use LEILAO_INCLUIR_SUMARE_DIRETO=1 para religar na busca.",
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
        "alibaba_sourcing",
        "Alibaba sourcing consolidado",
        "monitor",
        "agentes.importacao.agente_alibaba_sourcing:executar",
        {"enviar_alerta": True},
        notas="Único cron Alibaba: busca catálogo + inteligência margem em 1 run",
    ),
    # alibaba / alibaba_inteligencia NÃO entram no registro — só via alibaba_sourcing.
    # comparar_portos_alibaba = sob demanda (CLI com --fob/--produto-id); sem FOB falha.
    # logistica_china_ml = CLI/manual; toggle LOGISTICA_CHINA_ML_ATIVO=0 (default).
    # hub_paraguai / tributacao_py_br = estrutura futura (CLI/manual, sem cron).
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
        notas="Inclui busca ampla de kits Impala novos no ML (catálogo impala-novos-kits).",
    ),
    AgenteRegistrado(
        "visao_atuacao_impala",
        "Visão atuação Impala (radar diferencial)",
        "monitor",
        "agentes.esmaltes.agente_visao_atuacao_impala:executar",
        {"enviar_alerta": True},
        notas="Se o monitor já rodou o radar nos últimos 25 min, reusa o snapshot (não sobrescreve amostra ao vivo).",
    ),
    AgenteRegistrado(
        "kits_concorrentes_unificado",
        "Kits concorrentes (índice único)",
        "monitor",
        "agentes.esmaltes.agente_kits_concorrentes_unificado:executar",
        {"enviar_alerta": False},
        notas="Lê snapshots já gravados e junta em logs/kits_concorrentes_unificado_ultima.json. Sem Telegram.",
    ),
    AgenteRegistrado(
        "resumo_conta_ml",
        "Resumo conta ML (painel)",
        "monitor",
        "agentes.ml.agente_resumo_conta_ml:executar",
        {"enviar_alerta": True},
        notas="Espelho do Resumo do vendedor: pendências, reputação, envios → Telegram",
    ),
    # resumo_diario_novamix NÃO entra no registro — operação separada / CLI se precisar.
    AgenteRegistrado(
        "monitor_sem_venda_ml",
        "Anúncios ML sem venda 30d",
        "monitor",
        "agentes.ml.agente_monitor_sem_venda_ml:executar",
        {"enviar_alerta": True},
        notas="Sugere preço/ads/republicar para ativos sem pedido no período",
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
    # Sobreposições (anita / kits / tendencias / removedores / acetona) NÃO entram no registro:
    # cobertos por comparativo + busca_kit + mercado; workflows = debug/anexo semanal.
    AgenteRegistrado(
        "montar_kits_impala",
        "Montar kits Impala (planilha × ML)",
        "monitor",
        "agentes.esmaltes.agente_montar_kits_impala:executar",
        {"enviar_alerta": True},
        notas="Cruza cores Impala da planilha com kits mais vendidos no ML e sugere montagem",
    ),
    # crescimento / decisao_dia / ecossistema NÃO entram no registro:
    # só via esmaltes_operacao (1 Telegram). Workflows individuais = debug manual sem alerta.
    AgenteRegistrado(
        "esmaltes_operacao",
        "Operação esmaltes consolidada",
        "monitor",
        "agentes.esmaltes.agente_esmaltes_operacao:executar",
        {"enviar_alerta": True},
        notas="Único cron Impala: crescimento+decisão+ecossistema em 1 Telegram",
    ),
    AgenteRegistrado(
        "comparativo_anita_impala",
        "Comparativo Anita vs Impala",
        "monitor",
        "agentes.esmaltes.agente_comparativo_anita_impala:executar",
        {"enviar_alerta": True},
        notas="Demanda, perfil de consumidor e plano para vencer Impala no ML",
    ),
    # comparativo_ml_shopee NÃO entra no registro — loja foco = ML; canal Shopee = CLI/debug.
    AgenteRegistrado(
        "monitor_filamentos_ml",
        "Monitor filamentos 3D ML",
        "monitor",
        "agentes.filamentos.agente_monitor_filamentos_ml:executar",
        {"enviar_alerta": True},
        notas="PLA/PETG/ABS/TPU no ML: cores + Alibaba + sourcing BR×China",
    ),
    AgenteRegistrado(
        "monitor_masterprint_petg",
        "Monitor Masterprint PETG ML",
        "monitor",
        "agentes.filamentos.agente_monitor_masterprint_petg:executar",
        {"enviar_alerta": True},
        notas="Anúncios Masterprint PETG: total ativos, mais rentáveis e maior ganho",
    ),
    AgenteRegistrado(
        "monitor_masterprint_escritorio",
        "Monitor Masterprint pincéis/apagadores ML",
        "monitor",
        "agentes.escritorio.agente_monitor_masterprint_escritorio:executar",
        {"enviar_alerta": True},
        notas="Pincéis recarregáveis e apagadores Masterprint: margem real vs tabela",
    ),
    AgenteRegistrado(
        "monitor_cnpj_cnae",
        "Monitor CNPJ × CNAE × ML (ciclo 10d)",
        "monitor",
        "agentes.empresa.agente_monitor_cnpj_cnae:executar",
        {"enviar_alerta": True},
        notas="A cada ~10d ou na alteração: inicia ML e Telegram de decisão (AGIR/PANORAMA/PASSOS)",
    ),
    AgenteRegistrado(
        "ponto_ruptura_segundo_cnpj",
        "Ponto de ruptura 2º CNPJ + CNAE",
        "monitor",
        "agentes.empresa.agente_ponto_ruptura_segundo_cnpj:executar",
        {"enviar_alerta": True},
        notas="Impala fase 2? Libera Masterprint. Enquanto isso alerta CNAE/KYC para preparar.",
    ),
    AgenteRegistrado(
        "ponto_ruptura_outra_marca",
        "Ponto de ruptura outra marca de esmalte",
        "monitor",
        "agentes.esmaltes.agente_ponto_ruptura_outra_marca:executar",
        {"enviar_alerta": True},
        notas="Mesmo CNPJ Impala: quando entrar com Anita/Risque/etc. Referente ML.",
    ),
    # descoberta_produtos NÃO entra no registro — amplo demais no foco Impala; CLI/debug.
    AgenteRegistrado("ads_gatilho", "Gatilho Ads ML", "monitor", "agentes.ml.agente_ads_gatilho:executar"),
    AgenteRegistrado(
        "meta_metricas",
        "Métricas Meta Ads",
        "social",
        "agentes.social.agente_metricas_meta:executar",
        {"alertar_quando_atencao": False},
    ),
    # trafego_manicures NÃO entra no registro — alerta off; métricas Meta já cobrem; API/CLI.
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
    Respeita ORQUESTRADOR_EXCLUIR também nos extras (ex.: renovar_tokens).
    """
    from core.config import ORQUESTRADOR_EXCLUIR

    bloqueados = ORQUESTRADOR_EXCLUIR | (excluir or set())
    vistos: set[str] = set()
    resultado: list[AgenteRegistrado] = []
    for registro in (*listar_agentes(excluir=excluir), *_AGENTES_PUSH_MAIN_EXTRA):
        if registro.id in vistos or registro.id in bloqueados:
            continue
        vistos.add(registro.id)
        resultado.append(registro)
    return resultado


def executar_registro(registro: AgenteRegistrado) -> Any:
    fn = _resolver_fn(registro)
    return fn(**registro.kwargs)
