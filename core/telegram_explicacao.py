"""
core/telegram_explicacao.py
Textos curtos do que cada agente faz + horário — prontos para os alertas Telegram.

DESATIVADO por padrão (mensagens saem sem estes blocos).
Para religar no futuro: TELEGRAM_EXPLICACAO_AGENTES=1 no .env / secrets do Actions.
Horários em Brasília (BRT = UTC−3), conforme crons dos workflows + orquestrador.
"""
from __future__ import annotations

# Explicações em 1–2 frases (Markdown itálico no Telegram).
EXPLICACOES_AGENTES: dict[str, str] = {
    "vigia_datadog": (
        "Monitora erros e silêncio no Datadog. Se algo crítico aparece ou o sistema "
        "fica parado demais tempo, avisa para você investigar."
    ),
    "monitor_margem_vendas": (
        "Calcula lucro e margem dos pedidos nos marketplaces. Alerta quando a venda "
        "fica abaixo do mínimo configurado — para não vender no prejuízo."
    ),
    "inteligencia_precos": (
        "Analisa comportamento de compra e sugere preço por canal (ML, Shopee, etc.), "
        "ajudando a precificar com margem e competitividade."
    ),
    "leilao": (
        "Varre leiloeiros e DETRANs (e coletores diretos Sumaré/Copart/Superbid/Sodré) "
        "em busca de veículos com vantagem vs FIPE (após taxas). Só leitura — não dá lance."
    ),
    "sumare_leiloes": (
        "Abre o site oficial Sumaré Leilões, lista lotes de PREFEITURA/DETRAN e avisa "
        "lances novos ou alterados. Foco em veículos (não sucata)."
    ),
    "lojas_veiculos": (
        "Varre lojas de carros (ex.: Lucinei, Leopardo) e compara preço com FIPE, "
        "destacando oportunidades até o teto configurado."
    ),
    "carros_batidos": (
        "Monitora anúncios de carros batidos/sinistrados nas lojas cadastradas e "
        "avisa quando surge carro novo (Top-N por margem FIPE com haircut de sinistro)."
    ),
    "licitacoes": (
        "Busca licitações públicas (PNCP e portais estaduais) alinhadas ao seu perfil. "
        "Somente leitura — não participa do pregão."
    ),
    "alibaba": (
        "Busca fornecedores e ofertas no Alibaba para produtos do catálogo e resume "
        "oportunidades de importação no Telegram."
    ),
    "alibaba_inteligencia": (
        "Cruza cotação do dólar, custo landed e preços no ML para dizer se o produto "
        "ainda dá lucro importando — e alerta queda/alta forte do câmbio."
    ),
    "ml_tendencias_importacao": (
        "Vê o que está em alta no Mercado Livre e cruza com preços Alibaba para "
        "indicar se vale importar aquele item agora."
    ),
    "monitor_ml": (
        "Acompanha anúncios e saúde da conta no Mercado Livre e resume o que precisa "
        "de atenção (preço, status, concorrência)."
    ),
    "relatorio_manha_ml": (
        "Relatório matinal da operação ML: conta, anúncios, concorrentes e propostas "
        "de preço com margem viável para o dia."
    ),
    "relatorio_estrategia_ml": (
        "Monta o plano da semana no ML: o que baixar/reposicionar, onde investir Ads, "
        "o que diferenciar ou empurrar no canal próprio — com base em gaps e margem."
    ),
    "monitor_concorrentes": (
        "Monitora lojas e termos concorrentes no ML (incluindo Novamix). Avisa quando "
        "seu preço alvo fica longe do mercado ou surge ameaça forte."
    ),
    "resumo_diario_novamix": (
        "Resume o desempenho da loja Novamix no ML (preços, giro, perfil) e sugere "
        "ações de guerra/competir/Ads — preço nunca muda sozinho."
    ),
    "monitor_sem_venda_ml": (
        "Lista anúncios ativos sem venda recente e sugere preço, Ads ou republicar "
        "para reativar o giro."
    ),
    "monitor_anita": (
        "Acompanha esmaltes Anita no ML: cores, kits, ranking de marcas e margem, "
        "para comparar com a preferência do seu catálogo."
    ),
    "monitor_mercado_esmaltes": (
        "Varre o mercado de esmaltes no ML (não só uma marca): cores, kits, preços "
        "e propostas de como competir com margem."
    ),
    "monitor_busca_kit_esmaltes": (
        "Simula/consulta no ML as buscas de kits Anita e Impala (por cor) e conta a "
        "frequência do dia — mostra o que o mercado está procurando agora."
    ),
    "monitor_kits_esmaltes": (
        "Lista kits de esmaltes no ML com vendas e preços, ranqueia marcas e destaca "
        "o que está girando mais."
    ),
    "monitor_removedores_unha": (
        "Monitora removedores de unha no ML: fabricantes, nomes e ranking por vendas, "
        "para ver líderes e oportunidades."
    ),
    "monitor_tendencias_esmaltes": (
        "Busca tendências de esmaltes na internet e cruza com ML/Magalu/Shopee/Amazon "
        "para antecipar cores e kits em alta."
    ),
    "comparativo_anita_impala": (
        "Compara Anita vs Impala no ML (demanda, preço, perfil) e sugere como ganhar "
        "espaço frente à Impala."
    ),
    "comparativo_ml_shopee": (
        "Para esmaltes e filamentos 3D, pontua se o canal ideal é ML ou Shopee "
        "(demanda, preço, competição) e dá um veredito."
    ),
    "monitor_acetona_cruzeiro": (
        "Analisa acetona Cruzeiro no ML: vendedores, margem e público manicures, "
        "com ideias de estratégia (Claude + Impala)."
    ),
    "descoberta_produtos": (
        "Descobre produtos com potencial por marketplace (público-alvo + busca ML) "
        "e pode cruzar com Alibaba quando há novidade."
    ),
    "ads_gatilho": (
        "Decide ligar, pausar ou escalar Product Ads no ML com base em regras e "
        "sempre pede sua confirmação no Telegram antes de aplicar."
    ),
    "meta_metricas": (
        "Lê métricas das campanhas Meta Ads (gasto, CTR, ROAS) e alerta campanhas "
        "em atenção ou críticas."
    ),
    "trafego_manicures": (
        "Avalia o tráfego pago voltado a manicures e resume se as campanhas estão "
        "saudáveis ou precisam de ajuste."
    ),
    "promocoes_manicures": (
        "Monta e envia promoções de kits Impala para o grupo de manicures "
        "(WhatsApp/Telegram), com base no catálogo ML."
    ),
    "panorama": (
        "Consolida um panorama de ML, Magalu e Bling (estoque, vendas, alertas) "
        "para visão geral da operação."
    ),
    "orquestrador": (
        "Roda o ciclo de vários agentes a cada ~30 min e manda um resumo do que "
        "passou, falhou ou precisa de atenção."
    ),
    "operacao_24h": (
        "Snapshot da operação 24h (preços, estoque, NFe em dry-run no orquestrador). "
        "Escrita real fica no workflow de segurança."
    ),
    "repricing": (
        "Simula ou aplica ajustes de preço nos marketplaces conforme regras "
        "(no orquestrador costuma rodar em dry-run)."
    ),
    "repricing_impala": (
        "Repricing focado em SKUs Impala — ajusta ou simula preços para manter "
        "competitividade com margem."
    ),
    "sincronizar_estoque": (
        "Compara estoque Bling × marketplaces e aponta (ou aplica) divergências "
        "para não vender sem saldo."
    ),
    "algoritmo": (
        "Checa sinais de saúde do algoritmo/conta nos marketplaces e alerta quando "
        "há risco de queda de exposição."
    ),
    "manutencao": (
        "Keepalive: renova tokens e confirma que as APIs dos marketplaces continuam "
        "respondendo."
    ),
    "otimizador_listing": (
        "Sugere melhorias de título/descrição/fotos dos anúncios ML com base em "
        "métricas e concorrentes."
    ),
    "relatorio_financeiro": (
        "Resume economia de repricing e gasto de Ads do período para o gestor."
    ),
    "push_deploy": (
        "Roda checks (ruff/pytest) e prepara/push de deploy — avisa sucesso ou falha."
    ),
    "auto_respostas": (
        "Responde perguntas frequentes nos chats dos marketplaces com mensagens "
        "padronizadas (visuais quando configurado)."
    ),
    "chat_ml": "Lê e processa mensagens do chat do Mercado Livre.",
    "chat_shopee": "Lê e processa mensagens do chat da Shopee.",
    "chat_magalu": "Lê e processa mensagens do chat do Magalu.",
    "chat_amazon": "Lê e processa mensagens do chat da Amazon.",
    "conectividade": "Testa se as conexões com os marketplaces estão no ar.",
    "vendas_whatsapp": "Notifica vendas relevantes no WhatsApp do time.",
}

# Quando cada agente roda (BRT). Inclui workflow dedicado e/ou orquestrador 30 min.
# Excluídos do orquestrador por padrão: vigia_datadog, promocoes_manicures,
# relatorio_estrategia_ml, ads_gatilho, resumo_diario_novamix.
HORARIOS_AGENTES: dict[str, str] = {
    "vigia_datadog": "A cada 30 min (workflow próprio; fora do orquestrador)",
    "monitor_margem_vendas": "A cada 3h (Actions) e a cada 30 min (orquestrador)",
    "inteligencia_precos": "A cada 30 min (orquestrador)",
    "leilao": "A cada hora (Actions) e a cada 30 min (orquestrador)",
    "sumare_leiloes": "A cada 2h (Actions) e a cada 30 min (orquestrador)",
    "lojas_veiculos": "A cada 2h (Actions) e a cada 30 min (orquestrador)",
    "carros_batidos": "A cada 4h (Actions) e a cada 30 min (orquestrador)",
    "licitacoes": "A cada 4h (Actions) e a cada 30 min (orquestrador)",
    "alibaba": "A cada 2h (Actions) e a cada 30 min (orquestrador)",
    "alibaba_inteligencia": "A cada 2h (Actions Alibaba) e a cada 30 min (orquestrador)",
    "ml_tendencias_importacao": "A cada 2h (Actions Alibaba) e a cada 30 min (orquestrador)",
    "monitor_ml": "A cada 30 min (orquestrador); workflow dedicado só manual",
    "relatorio_manha_ml": "Todo dia às 07:30 BRT (Actions) e a cada 30 min (orquestrador)",
    "relatorio_estrategia_ml": "Segundas às 08:00 BRT (fora do orquestrador)",
    "monitor_concorrentes": "A cada 30 min (orquestrador); workflow dedicado só manual",
    "resumo_diario_novamix": "Todo dia às 08:00 BRT (fora do orquestrador)",
    "monitor_sem_venda_ml": "A cada 30 min (orquestrador)",
    "monitor_anita": "A cada 30 min (orquestrador); workflow dedicado só manual",
    "monitor_mercado_esmaltes": "A cada 30 min (orquestrador); workflow dedicado só manual",
    "monitor_busca_kit_esmaltes": "A cada 4h (Actions) e a cada 30 min (orquestrador)",
    "monitor_kits_esmaltes": "A cada 6h (Actions) e a cada 30 min (orquestrador)",
    "monitor_removedores_unha": "A cada 6h (Actions) e a cada 30 min (orquestrador)",
    "monitor_tendencias_esmaltes": (
        "2x ao dia às 05:15 e 17:15 BRT (Actions) e a cada 30 min (orquestrador)"
    ),
    "comparativo_anita_impala": (
        "Segundas e quintas às 08:00 BRT (Actions) e a cada 30 min (orquestrador)"
    ),
    "comparativo_ml_shopee": (
        "Segundas e quintas às 09:00 BRT (Actions) e a cada 30 min (orquestrador)"
    ),
    "monitor_acetona_cruzeiro": (
        "Terças e sextas às 09:00 BRT (Actions) e a cada 30 min (orquestrador)"
    ),
    "descoberta_produtos": "Quartas às 08:00 BRT (Actions) e a cada 30 min (orquestrador)",
    "ads_gatilho": "Todo dia às 08:00 BRT (fora do orquestrador)",
    "meta_metricas": "A cada 30 min (orquestrador)",
    "trafego_manicures": "A cada 30 min (orquestrador)",
    "promocoes_manicures": "Todo dia às 10:00 e 18:00 BRT (fora do orquestrador)",
    "panorama": "Todo dia às 06:30 BRT (Actions) e a cada 30 min (orquestrador)",
    "orquestrador": "A cada 30 min (GitHub Actions)",
    "operacao_24h": (
        "Snapshot a cada 30 min (orquestrador, dry-run); escrita real a cada 2h "
        "(workflow de segurança)"
    ),
    "repricing": "A cada 30 min (orquestrador, dry-run)",
    "repricing_impala": "A cada 30 min (orquestrador, dry-run)",
    "sincronizar_estoque": "A cada 2h (Actions) e a cada 30 min (orquestrador, dry-run)",
    "algoritmo": (
        "4x ao dia às 00:00, 06:00, 12:00 e 18:00 BRT (agente principal) e a cada "
        "30 min (orquestrador)"
    ),
    "manutencao": "A cada 30 min (orquestrador / renovação de tokens)",
    "otimizador_listing": "Terças às 06:00 BRT (Actions; fora do ciclo 30 min)",
    "relatorio_financeiro": "Segundas às 06:00 BRT (Actions; fora do ciclo 30 min)",
    "push_deploy": "Somente manual (workflow_dispatch)",
    "auto_respostas": "A cada 30 min (orquestrador)",
    "chat_ml": (
        "A cada 30 min no horário comercial via agente principal (~06h–19h BRT) e "
        "no orquestrador"
    ),
    "chat_shopee": (
        "A cada 30 min no horário comercial via agente principal (~06h–19h BRT) e "
        "no orquestrador"
    ),
    "chat_magalu": (
        "A cada 30 min no horário comercial via agente principal (~06h–19h BRT) e "
        "no orquestrador"
    ),
    "chat_amazon": (
        "A cada 30 min no horário comercial via agente principal (~06h–19h BRT) e "
        "no orquestrador"
    ),
    "conectividade": "A cada hora (Actions) e a cada 30 min (orquestrador)",
    "vendas_whatsapp": "A cada 30 min (orquestrador / agente principal)",
}

# Prefixo da chave de cooldown → id do agente (fallback automático)
_CHAVE_PARA_AGENTE: tuple[tuple[str, str], ...] = (
    ("vigia_datadog", "vigia_datadog"),
    ("vigia:", "vigia_datadog"),
    ("margem_vendas", "monitor_margem_vendas"),
    ("margem_baixa", "monitor_margem_vendas"),
    ("precificacao:", "inteligencia_precos"),
    ("inteligencia_precos", "inteligencia_precos"),
    ("leilao:", "leilao"),
    ("leilao", "leilao"),
    ("sumare:", "sumare_leiloes"),
    ("lojas_veiculos", "lojas_veiculos"),
    ("carros_batidos", "carros_batidos"),
    ("licitacao", "licitacoes"),
    ("cambio:usd", "alibaba_inteligencia"),
    ("alibaba:inteligencia", "alibaba_inteligencia"),
    ("alibaba_intel", "alibaba_inteligencia"),
    ("alibaba:", "alibaba"),
    ("importacao:ml_tendencias", "ml_tendencias_importacao"),
    ("ml_tendencias", "ml_tendencias_importacao"),
    ("ml:relatorio:manha", "relatorio_manha_ml"),
    ("relatorio_manha", "relatorio_manha_ml"),
    ("estrategia_ml", "relatorio_estrategia_ml"),
    ("estrategia:", "relatorio_estrategia_ml"),
    ("novamix:", "resumo_diario_novamix"),
    ("sem_venda", "monitor_sem_venda_ml"),
    ("monitor_concorrentes", "monitor_concorrentes"),
    ("concorrentes", "monitor_concorrentes"),
    ("anita:esmaltes", "monitor_anita"),
    ("anita:", "monitor_anita"),
    ("esmaltes:mercado", "monitor_mercado_esmaltes"),
    ("mercado_esmaltes", "monitor_mercado_esmaltes"),
    ("busca_kit", "monitor_busca_kit_esmaltes"),
    ("kits_esmaltes", "monitor_kits_esmaltes"),
    ("esmaltes:kits", "monitor_kits_esmaltes"),
    ("removedores", "monitor_removedores_unha"),
    ("tendencias_esmaltes", "monitor_tendencias_esmaltes"),
    ("esmaltes:tendencias", "monitor_tendencias_esmaltes"),
    ("anita_impala", "comparativo_anita_impala"),
    ("comparativo:ml_shopee", "comparativo_ml_shopee"),
    ("ml_shopee", "comparativo_ml_shopee"),
    ("acetona", "monitor_acetona_cruzeiro"),
    ("descoberta", "descoberta_produtos"),
    ("ads_ml", "ads_gatilho"),
    ("ads:", "ads_gatilho"),
    ("meta:", "meta_metricas"),
    ("meta_ads", "meta_metricas"),
    ("trafego_manicures", "trafego_manicures"),
    ("promocoes_manicures", "promocoes_manicures"),
    ("panorama", "panorama"),
    ("orquestrador", "orquestrador"),
    ("operacao_24h", "operacao_24h"),
    ("repricing_impala", "repricing_impala"),
    ("repricing", "repricing"),
    ("estoque", "sincronizar_estoque"),
    ("algoritmo", "algoritmo"),
    ("saude:", "algoritmo"),
    ("otimizador", "otimizador_listing"),
    ("financeiro", "relatorio_financeiro"),
    ("push_deploy", "push_deploy"),
    ("conectividade", "conectividade"),
)

_MARCADOR = "_O que este agente faz:_"
_MARCADOR_HORARIO = "_Quando roda:_"


def explicacao_ativa() -> bool:
    """True só com TELEGRAM_EXPLICACAO_AGENTES=1 (ver core/config.py)."""
    from core.config import TELEGRAM_EXPLICACAO_AGENTES

    return bool(TELEGRAM_EXPLICACAO_AGENTES)


def explicacao_de(agente_id: str | None) -> str:
    if not agente_id:
        return ""
    return (EXPLICACOES_AGENTES.get(str(agente_id).strip()) or "").strip()


def horario_de(agente_id: str | None) -> str:
    if not agente_id:
        return ""
    return (HORARIOS_AGENTES.get(str(agente_id).strip()) or "").strip()


def agente_id_da_chave(chave: str | None) -> str | None:
    if not chave:
        return None
    c = str(chave).lower()
    for prefixo, agente_id in _CHAVE_PARA_AGENTE:
        if prefixo.lower() in c:
            return agente_id
    return None


def inserir_explicacao(mensagem: str, agente_id: str | None = None, *, chave: str | None = None) -> str:
    """
    Insere bloco 'O que este agente faz' (+ horário) após a 1ª linha (título).
    Sem efeito se TELEGRAM_EXPLICACAO_AGENTES estiver desligado.
    Não duplica se o marcador já existir.
    """
    if not explicacao_ativa():
        return mensagem
    msg = (mensagem or "").strip()
    if not msg or _MARCADOR in msg:
        return mensagem
    aid = (agente_id or "").strip() or (agente_id_da_chave(chave) or "")
    texto = explicacao_de(aid)
    if not texto:
        return mensagem

    partes = msg.split("\n", 1)
    titulo = partes[0]
    resto = partes[1] if len(partes) > 1 else ""
    bloco = f"{titulo}\n\n{_MARCADOR}\n_{texto}_"
    horario = horario_de(aid)
    if horario and _MARCADOR_HORARIO not in msg:
        bloco = f"{bloco}\n\n{_MARCADOR_HORARIO}\n_{horario}_"
    if resto.strip():
        return f"{bloco}\n\n{resto.lstrip()}"
    return bloco


def cabecalho_agente(agente_id: str, titulo: str) -> str:
    """Título (+ explicação se TELEGRAM_EXPLICACAO_AGENTES=1)."""
    return inserir_explicacao(titulo.strip(), agente_id)
