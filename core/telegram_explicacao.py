"""
core/telegram_explicacao.py
Descrições detalhadas do que cada agente faz + horário — inseridas nos alertas Telegram.

Ativo com TELEGRAM_EXPLICACAO_AGENTES=1 (padrão ligado).
Horários em Brasília (BRT = UTC−3), conforme crons dos workflows + orquestrador.
"""
from __future__ import annotations

# Descrições para o bloco "_O que este agente faz:_" (Markdown itálico no Telegram).
EXPLICACOES_AGENTES: dict[str, str] = {
    "vigia_datadog": (
        "Monitora erros e silêncio no Datadog. Se aparece erro crítico ou o sistema "
        "fica parado demais tempo (sem heartbeat), avisa no Telegram para você investigar. "
        "Não corrige sozinho — só alerta."
    ),
    "monitor_margem_vendas": (
        "Calcula lucro e margem dos pedidos em ML, Shopee, Magalu e Amazon (custo do "
        "catálogo/Bling). Alerta quando a venda fica abaixo do mínimo configurado e "
        "pode enviar resumo do período — para não vender no prejuízo."
    ),
    "inteligencia_precos": (
        "Analisa sinais de compra (visitas, concorrentes quando há item id válido) e "
        "sugere preço por canal (ML, Shopee etc.) respeitando margem mínima. "
        "Entrega recomendações de preço no Telegram — não altera preço sozinho."
    ),
    "leilao": (
        "Varre leiloeiros, DETRANs e coletores diretos (Sumaré, Copart, Superbid, Sodré) "
        "em busca de veículos com vantagem vs FIPE após taxas. Só leitura — nunca dá "
        "lance. No Telegram: lotes novos com margem e/ou resumo da varredura."
    ),
    "sumare_leiloes": (
        "Abre o site oficial Sumaré Leilões, lista lotes PREFEITURA/DETRAN com documento "
        "(não sucata) e detecta lances novos ou alterados. Telegram: alerta de mudança "
        "de lance e resumo da rodada."
    ),
    "lojas_veiculos": (
        "Varre lojas cadastradas (Lucinei, Leopardo etc.), compara preço anunciado com "
        "FIPE e destaca oportunidades até o teto configurado. Telegram: carros abaixo "
        "da FIPE e resumo da coleta."
    ),
    "carros_batidos": (
        "Monitora lojas de carros batidos/sinistrados (e busca web). Ranqueia Top-N por "
        "margem FIPE com haircut de sinistro. Telegram: anúncio novo detectado e "
        "resumo da varredura."
    ),
    "licitacoes": (
        "Busca licitações públicas no PNCP (27 UFs) e portais alinhadas ao seu perfil "
        "(termo, UF, valor). Somente leitura — não participa do pregão. Telegram: "
        "licitações novas + resumo com checklist de participação."
    ),
    "alibaba": (
        "Busca fornecedores e ofertas no Alibaba para produtos do catálogo (preço, MOQ) "
        "e filtra oportunidades de importação. Telegram: lista de ofertas e resumo "
        "da varredura."
    ),
    "alibaba_inteligencia": (
        "Cruza cotação do dólar, custo landed e preços no ML para dizer se ainda dá "
        "lucro importar. Também alerta queda/alta forte do câmbio. Telegram: "
        "oportunidades com lucro razoável e alerta de variação USD."
    ),
    "ml_tendencias_importacao": (
        "Detecta o que está em alta no Mercado Livre e cruza com preços Alibaba para "
        "indicar se vale importar aquele item agora. Telegram: tendências + veredito "
        "de importação."
    ),
    "monitor_ml": (
        "Acompanha anúncios e saúde da conta no Mercado Livre (preço, status, "
        "concorrência) e resume o que precisa de atenção na rodada. Telegram: "
        "resumo de atenção da conta."
    ),
    "resumo_conta_ml": (
        "Espelha o painel Resumo do vendedor via API: perguntas, anúncios a "
        "melhorar (qualidade), sugestões de preço, envios pendentes, claims e "
        "reputação. Telegram: briefing da conta. Fatura/saldo MP ficam no painel."
    ),
    "relatorio_manha_ml": (
        "Relatório matinal da operação ML: conta, anúncios, concorrentes e propostas "
        "de preço com margem viável para o dia. Telegram: briefing completo da manhã."
    ),
    "relatorio_estrategia_ml": (
        "Monta o plano da semana no ML com base em gaps e margem: o que baixar/"
        "reposicionar, onde investir Ads, o que diferenciar ou empurrar no canal "
        "próprio. Telegram: top ações da semana."
    ),
    "monitor_concorrentes": (
        "Monitora lojas e termos concorrentes no ML (incluindo Novamix). Avisa quando "
        "seu preço alvo fica longe do mercado ou surge ameaça forte. Telegram: "
        "alertas de gap e resumo de concorrência."
    ),
    "resumo_diario_novamix": (
        "Resume desempenho da loja Novamix (preços, giro, perfil), classifica "
        "guerra/competir/observar e pode sugerir Ads (com confirmação). Preço nunca "
        "muda sozinho. Telegram: resumo diário + plano de ação."
    ),
    "monitor_sem_venda_ml": (
        "Lista anúncios ativos sem venda recente e sugere preço, Ads ou republicar "
        "para reativar o giro. Telegram: lista priorizada de reativação."
    ),
    "monitor_anita": (
        "Acompanha esmaltes Anita no ML (cores, kits, ranking de marcas e margem) e "
        "compara com a preferência do seu catálogo Impala. Telegram: painel dos seus "
        "kits vs mercado."
    ),
    "monitor_mercado_esmaltes": (
        "Varre o mercado de esmaltes no ML (não só uma marca): cores, kits, preços e "
        "propostas de como competir mantendo margem. Telegram: visão competitiva "
        "consolidada."
    ),
    "monitor_busca_kit_esmaltes": (
        "Consulta no ML buscas de kits Anita e Impala (por cor), acumula a frequência "
        "do dia e destaca cores nos títulos. Telegram: contagem diária por marca/cor "
        "e última rodada — o que o mercado está procurando agora."
    ),
    "monitor_kits_esmaltes": (
        "Lista kits de esmaltes no ML com vendas e preços, ranqueia marcas e destaca "
        "o que está girando mais. Pode enviar gráfico. Telegram: ranking de kits/"
        "marcas."
    ),
    "monitor_removedores_unha": (
        "Monitora removedores de unha no ML: fabricantes, nomes e ranking por vendas, "
        "para ver líderes e oportunidades. Telegram: ranking (+ gráfico quando houver)."
    ),
    "monitor_tendencias_esmaltes": (
        "Busca tendências de esmaltes na internet (Brave/DDG) e cruza com ML, Magalu, "
        "Shopee e Amazon para antecipar cores e kits em alta. Telegram: tendências + "
        "cruzamento com marketplaces."
    ),
    "comparativo_anita_impala": (
        "Compara Anita vs Impala no ML (demanda, preço, perfil de consumidor) e "
        "sugere como ganhar espaço frente à Impala. Telegram: comparativo + plano."
    ),
    "comparativo_ml_shopee": (
        "Para esmaltes e filamentos 3D, pontua demanda, preço e competição em ML vs "
        "Shopee e fecha um veredito de canal. Telegram: score + recomendação ML ou "
        "Shopee."
    ),
    "monitor_filamentos_ml": (
        "Varre filamentos 3D no Mercado Livre (PLA, PETG, ABS, TPU…): cores mais vendidas, "
        "preços e marcas; cruza com o catálogo Alibaba (FOB/landed × preço ML). "
        "Telegram: ranking de cores + margem de importação."
    ),
    "monitor_acetona_cruzeiro": (
        "Analisa acetona Cruzeiro no ML: vendedores, margem e público manicures, com "
        "ideias de estratégia (Claude + Impala). Telegram: relatório completo da "
        "categoria."
    ),
    "descoberta_produtos": (
        "Descobre produtos com potencial por marketplace (público-alvo + busca ML) e "
        "pode cruzar com Alibaba quando há novidade. Telegram: painel de decisão e/"
        "ou novos fornecedores."
    ),
    "ads_gatilho": (
        "Decide ligar, pausar ou escalar Product Ads no ML com base em regras e "
        "sempre pede sua confirmação no Telegram antes de aplicar. Não executa "
        "sozinho sem o seu OK."
    ),
    "meta_metricas": (
        "Lê métricas das campanhas Meta Ads (gasto, CTR, ROAS) e alerta campanhas "
        "em atenção ou críticas. No orquestrador costuma alertar só o crítico."
    ),
    "trafego_manicures": (
        "Avalia o tráfego pago voltado a manicures e resume se as campanhas estão "
        "saudáveis ou precisam de ajuste. No ciclo 30 min o alerta costuma ficar off."
    ),
    "promocoes_manicures": (
        "Monta promoções de kits Impala a partir do catálogo ML e envia ao grupo de "
        "manicures (WhatsApp + Telegram manicures — não é o chat do gestor). "
        "Tipicamente 2 envios por dia."
    ),
    "panorama": (
        "Consolida panorama de ML, Magalu e Bling (estoque, vendas, alertas) para "
        "visão geral. No orquestrador o alerta próprio fica off — o consolidado vai "
        "no resumo do ciclo; ainda pode alertar crítico se houver falha interna."
    ),
    "orquestrador": (
        "Roda o ciclo de vários agentes a cada ~30 min e manda um resumo do que "
        "passou, falhou ou precisa de atenção. Não reenvia o relatório completo de "
        "cada agente — só o consolidado do ciclo."
    ),
    "operacao_24h": (
        "Gera snapshot da operação 24h (preços, estoque, NFe). No orquestrador roda "
        "em dry-run e sempre manda resumo ao gestor. Escrita real fica no workflow "
        "de segurança (a cada 2h)."
    ),
    "repricing": (
        "Simula ou aplica ajustes de preço nos marketplaces conforme regras. No "
        "orquestrador costuma ser dry-run, mas ainda avisa no Telegram quando detecta "
        "ajustes necessários."
    ),
    "repricing_impala": (
        "Repricing focado em SKUs Impala para manter competitividade com margem. "
        "Dry-run no orquestrador; Telegram quando há kits a ajustar."
    ),
    "sincronizar_estoque": (
        "Compara estoque Bling × marketplaces e aponta (ou aplica) divergências para "
        "não vender sem saldo. Dry-run no orquestrador; Telegram quando há diferenças."
    ),
    "algoritmo": (
        "Checa sinais de saúde do algoritmo/conta nos marketplaces e alerta quando "
        "há risco de queda de exposição. Em geral só Telegram em estado crítico."
    ),
    "manutencao": (
        "Keepalive: renova tokens e confirma que as APIs dos marketplaces continuam "
        "respondendo. Telegram principalmente se algo não estiver ok."
    ),
    "otimizador_listing": (
        "Sugere melhorias de título, descrição e fotos dos anúncios ML com base em "
        "métricas e concorrentes (somente leitura). Telegram: lista de sugestões."
    ),
    "relatorio_financeiro": (
        "Resume economia estimada de repricing e gasto de Ads do período para o "
        "gestor. Telegram: relatório financeiro semanal."
    ),
    "push_deploy": (
        "Roda checks (ruff/pytest) e prepara/push de deploy. Telegram: avisa sucesso "
        "ou falha do pipeline (execução manual)."
    ),
    "auto_respostas": (
        "Responde perguntas frequentes nos chats dos marketplaces com mensagens "
        "padronizadas (visuais quando configurado). Telegram se processou mensagens "
        "na rodada."
    ),
    "chat_ml": (
        "Lê e processa mensagens do chat do Mercado Livre. Telegram sobretudo em "
        "erro ou taxa alta de reclamações — não é resumo rotineiro ao gestor."
    ),
    "chat_shopee": (
        "Lê e processa mensagens do chat da Shopee. Telegram sobretudo em erro/IA — "
        "canal de chat, não resumo rotineiro ao gestor."
    ),
    "chat_magalu": (
        "Lê e processa mensagens do chat do Magalu. Telegram sobretudo em erro/IA — "
        "canal de chat, não resumo rotineiro ao gestor."
    ),
    "chat_amazon": (
        "Lê e processa mensagens do chat da Amazon. Telegram sobretudo em erro/IA — "
        "canal de chat, não resumo rotineiro ao gestor."
    ),
    "conectividade": (
        "Testa se as conexões com os marketplaces estão no ar. Telegram só em falha "
        "real de conectividade (alerta crítico)."
    ),
    "vendas_whatsapp": (
        "Notifica vendas relevantes no WhatsApp do time. Telegram só se a API de "
        "pedidos falhar — o canal principal é WhatsApp."
    ),
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
    "resumo_conta_ml": "Todo dia às 09:00 BRT (Actions); fora do ciclo 30 min",
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
    "monitor_filamentos_ml": "A cada 6h (Actions) e a cada 30 min (orquestrador)",
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
    ("ml:resumo_conta", "resumo_conta_ml"),
    ("resumo_conta", "resumo_conta_ml"),
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
    ("filamentos", "monitor_filamentos_ml"),
    ("filamentos:ml", "monitor_filamentos_ml"),
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


def _escapar_markdown_legado(texto: str) -> str:
    """Escapa _, *, ` e [ para parse_mode=Markdown (legado) do Telegram."""
    out = (texto or "").replace("\\", "\\\\")
    for ch in ("_", "*", "`", "["):
        out = out.replace(ch, "\\" + ch)
    return out


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
    # Itálico Markdown: o corpo precisa escapar _, * etc. (ex.: item_id)
    bloco = f"{titulo}\n\n{_MARCADOR}\n_{_escapar_markdown_legado(texto)}_"
    horario = horario_de(aid)
    if horario and _MARCADOR_HORARIO not in msg:
        bloco = f"{bloco}\n\n{_MARCADOR_HORARIO}\n_{_escapar_markdown_legado(horario)}_"
    if resto.strip():
        return f"{bloco}\n\n{resto.lstrip()}"
    return bloco


def cabecalho_agente(agente_id: str, titulo: str) -> str:
    """Título (+ explicação se TELEGRAM_EXPLICACAO_AGENTES=1)."""
    return inserir_explicacao(titulo.strip(), agente_id)
