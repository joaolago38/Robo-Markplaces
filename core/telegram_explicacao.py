"""
core/telegram_explicacao.py
Descrições detalhadas do que cada agente faz + horário — inseridas nos alertas Telegram.

Ativo com TELEGRAM_EXPLICACAO_AGENTES=1 (padrão ligado).
Horários em Brasília (BRT = UTC−3), conforme crons dos workflows + orquestrador.
"""
from __future__ import annotations

import re

# Descrições para o bloco "_O que este agente faz:_" (Markdown itálico no Telegram).
EXPLICACOES_AGENTES: dict[str, str] = {
    "vigia_datadog": (
        "Monitora erros e silêncio no Datadog. Se aparece erro crítico ou o sistema "
        "fica parado demais tempo (sem heartbeat), avisa no Telegram para você investigar. "
        "Não corrige sozinho — só alerta."
    ),
    "consumo_claude": (
        "Mostra orçamento Claude (US$ usado/restante) e a assertividade por agente "
        "(ok vs falha/fallback/vazio). Alerta limiares e hard stop. Estimativa local por tokens."
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
        "Busca catálogo Alibaba. Em produção roda só dentro de alibaba_sourcing — "
        "não manda Telegram sozinho."
    ),
    "alibaba_inteligencia": (
        "Câmbio + landed + margem. Em produção roda só dentro de alibaba_sourcing — "
        "não manda Telegram sozinho."
    ),
    "alibaba_sourcing": (
        "Único run Alibaba: busca catálogo + inteligência de margem/câmbio. "
        "Preferir este no cron."
    ),
    "comparar_portos_alibaba": (
        "Compara importação com referência Alibaba (FOB) em qualquer porto ou "
        "aeroporto do Brasil — aéreo e marítimo — sob demanda (sem cron)."
    ),
    "hub_paraguai_marketplace": (
        "Estrutura futura (hub PY × marketplaces). Sem cron — só CLI/manual quando ativar."
    ),
    "tributacao_py_br": (
        "Cenário futuro Mercosul (II=0). Sem cron — só CLI/manual quando ativar."
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
        "Debug: resumo Novamix. Só se a loja for operação separada ainda "
        "gerenciada — sem cron/Telegram no ciclo Impala."
    ),
    "monitor_sem_venda_ml": (
        "Lista anúncios ativos sem venda recente e sugere preço, Ads ou republicar "
        "para reativar o giro. Telegram: lista priorizada de reativação."
    ),
    "monitor_anita": (
        "Debug: Anita no ML. Em produção use comparativo_anita_impala — "
        "este monitor não manda Telegram no cron."
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
        "Debug: ranking de kits. Em produção use monitor_mercado_esmaltes — "
        "sem Telegram no cron."
    ),
    "montar_kits_impala": (
        "Lê a planilha Impala (cores/SKU), cruza com os kits mais vendidos no Mercado Livre "
        "e sugere quais cores montar em kits 3/5/6/10. Telegram: top cores + kits sugeridos."
    ),
    "ecossistema_esmaltes": (
        "Plano de ecossistema (cor → kit → anexos → B2B). Em produção roda só "
        "dentro de esmaltes_operacao — não manda Telegram sozinho."
    ),
    "crescimento_esmaltes": (
        "KPI kits% + checklist MLB. Em produção roda só dentro de "
        "esmaltes_operacao — não manda Telegram sozinho."
    ),
    "decisao_dia_esmaltes": (
        "Veredito FAZER / NÃO FAZER / CUSTO. Em produção roda só dentro de "
        "esmaltes_operacao — não manda Telegram sozinho."
    ),
    "esmaltes_operacao": (
        "Único card Impala do dia: roda crescimento + decisão + ecossistema "
        "e envia um Telegram consolidado."
    ),
    "golpe_guerra_impala": (
        "Classifica o golpe da frente Impala (ignorar, diferenciar, igualar na faixa "
        "ou nao perseguir). Telegram só no disparo. Nao altera preco sozinho."
    ),
    "simulacao_guerra_impala": (
        "Sala de guerra operacional: trata MIMO/PERL/JUPAES como no ar "
        "(estoque 60, rivais ao vivo). Overlay em memória — não grava item id. "
        "Quando existir MLB real, o overlay desliga sozinho."
    ),
    "radar_diferencial_impala": (
        "Lê títulos Impala no ML: o que o rival oferece a mais (Carmed, brinde, "
        "tratamento, francesinha) vs o nosso combo, se a margem operacional está "
        "acima de 15%, se há MLB publicado e se a amostra é ao vivo ou cache velho. "
        "Telegram com o FAZER e o link do Datadog."
    ),
    "kits_concorrentes_unificado": (
        "Junta num JSON só os snapshots de kits já gravados (radar Impala, marca×kit, "
        "Anita, nossos kits, PETG com kit no título). Não busca ML e não publica. "
        "Arquivo: logs/kits_concorrentes_unificado_ultima.json."
    ),
    "monitor_removedores_unha": (
        "Anexo: ranking de removedores no ML. Digest semanal (quarta) — "
        "fora do foco diário de kits."
    ),
    "monitor_tendencias_esmaltes": (
        "Debug: tendências web. Em produção use monitor_busca_kit_esmaltes — "
        "sem Telegram no cron."
    ),
    "comparativo_anita_impala": (
        "Compara Anita vs Impala no ML (demanda, preço, perfil de consumidor) e "
        "sugere como ganhar espaço frente à Impala. Telegram: comparativo + plano."
    ),
    "comparativo_ml_shopee": (
        "Debug: score ML × Shopee. Loja foco = ML — use só ao escolher canal; "
        "sem cron/Telegram no ciclo atual."
    ),
    "monitor_filamentos_ml": (
        "Varre no Mercado Livre anúncios de filamento TPU, PLA, PETG e ABS: "
        "preços, cores, marcas e ranking de vendas; compara com Alibaba "
        "(FOB/landed × preço ML) e decide sourcing COMPRAR_BR vs IMPORTAR_CHINA "
        "vs NAO_COMPENSA com o catálogo de fornecedor nacional."
    ),
    "monitor_masterprint_petg": (
        "Monitora PETG Masterprint no ML (margem real + Δ). Claude 1×/dia: análise "
        "concisa do ecossistema ML. Pode usar CNPJ/conta/Telegram próprios (≠ esmaltes)."
    ),
    "monitor_masterprint_escritorio": (
        "Monitora pincéis recarregáveis e apagadores Masterprint (margem real). "
        "Claude 1×/dia no ecossistema ML. Ramo/conta separados dos esmaltes quando configurado."
    ),
    "monitor_cnpj_cnae": (
        "A cada ~10 dias (dias 1/11/21): pelo CNAE resolve o CNPJ, lista produtos e, "
        "se houver alteração (ou ciclo vencido), inicia monitoramento Mercado Livre "
        "com card de decisão no Telegram (AGIR / PANORAMA ML / PRÓXIMOS PASSOS). "
        "Limites Datadog (Alibaba + USD + vendas + saúde do produto) evitam o "
        "ecossistema repetir o mesmo tema. Demais marketplaces ficam abertos no perfil."
    ),
    "ponto_ruptura_segundo_cnpj": (
        "Cruza reputação, MLB, estoque, pedido e ACOS do Impala e, quando a ruptura "
        "está perto ou liberada, o Claude resume esforço, atitudes já tomadas e "
        "quais kits Impala têm margem segura no ML. Também alerta CNAE/KYC do "
        "segundo CNPJ (Masterprint). Não publica anúncio nem liga a flag de dono."
    ),
    "ponto_ruptura_outra_marca": (
        "Diz se o CNPJ Impala (52.668.583/0001-27) já pode entrar com outra marca "
        "de esmalte. Inclui prévia da saúde Impala no ML, esforço restante e "
        "produtos com margem segura (Claude no veredito aproximando/liberado). "
        "Não publica anúncio e não troca de CNPJ."
    ),
    "monitor_acetona_cruzeiro": (
        "Anexo: acetona Cruzeiro no ML. Digest semanal (sexta) — "
        "fora do foco diário de kits."
    ),
    "descoberta_produtos": (
        "Debug: descoberta ampla por marketplace. Fora do foco Impala — "
        "sem cron/Telegram; CLI/manual."
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
        "Debug/API: tráfego pago manicures. Alerta costuma ficar off — "
        "métricas Meta já cobrem; fora do orquestrador."
    ),
    "promocoes_manicures": (
        "Monta promoções de kits Impala a partir do catálogo ML e envia ao grupo de "
        "manicures (WhatsApp + Telegram manicures — não é o chat do gestor). "
        "Tipicamente 2 envios por dia."
    ),
    "conversao_manicures": (
        "Converte manicures (WA/IG/FB) para o ML: Haiku oferta + inbox Meta/WA. "
        "Chat ML de fechamento fica com agentes.ml (evita resposta duplicada). "
        "Bloqueia boost se link MLB_PREENCHER ou ROAS Ads×ML crítico."
    ),
    "necessidade_manicures": (
        "Lê necessidade das manicures (tendências, busca kit, Anita, leads), "
        "valida o que temos no catálogo/ML e oferece condições no WA/Telegram "
        "somente após SIM do gestor. Não publica FB/IG nem altera Ads."
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
        "Único dry-run do ciclo 30min: snapshot preços/estoque/NFe → Telegram. "
        "Escrita real a cada 2h em operacao_24h_seguranca."
    ),
    "repricing": (
        "Ajustes de preço nos marketplaces. Fora do orquestrador — "
        "roda via operacao_24h_seguranca (escrita real)."
    ),
    "repricing_impala": (
        "Repricing Impala. Fora do orquestrador — via operacao_24h / CLI."
    ),
    "sincronizar_estoque": (
        "Estoque Bling × marketplaces. Fora do orquestrador — "
        "workflow sincronizar_estoque.yml a cada 2h (escrita real)."
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
        "Sugere título e descrição ML via Claude: concorrentes + estrutura de copy "
        "das bolsas/legado desta conta que já vendem (não copia o produto bolsa). "
        "Kits Impala sem MLB entram como pré-publicação. Telegram: lista de sugestões."
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
# relatorio_estrategia_ml, ads_gatilho, resumo_conta_ml.
HORARIOS_AGENTES: dict[str, str] = {
    "vigia_datadog": "A cada 30 min (workflow próprio; fora do orquestrador)",
    "consumo_claude": "A cada 6h (Actions) + alerta a cada uso Claude",
    "monitor_margem_vendas": "3x/dia às 08:05, 14:05 e 21:05 BRT (Actions) e a cada 30 min (orquestrador)",
    "inteligencia_precos": "A cada 30 min (orquestrador)",
    "leilao": "A cada hora (Actions); fora do orquestrador 30 min",
    "sumare_leiloes": "DESLIGADO (SSL site); só workflow_dispatch manual",
    "lojas_veiculos": "1x/dia às 09:30 BRT (Actions); fora do orquestrador 30 min",
    "carros_batidos": "1x/dia às 10:15 BRT (Actions); fora do orquestrador 30 min",
    "licitacoes": "A cada 4h (Actions); fora do orquestrador 30 min",
    "alibaba": "Debug/CLI — produção via alibaba_sourcing",
    "alibaba_inteligencia": "Debug/CLI — produção via alibaba_sourcing",
    "alibaba_sourcing": "2x/dia às 08:00 e 20:00 BRT (Actions); fora do orquestrador 30 min",
    "comparar_portos_alibaba": "Sob demanda / CLI; fora do orquestrador 30 min",
    "hub_paraguai_marketplace": "Planejado — sem cron",
    "tributacao_py_br": "Futuro Mercosul — sem cron",
    "ml_tendencias_importacao": "Junto com alibaba_sourcing (2x/dia Actions)",
    "monitor_ml": "A cada 30 min (orquestrador); workflow dedicado só manual",
    "resumo_conta_ml": "Todo dia às 09:00 BRT (Actions); fora do ciclo 30 min",
    "relatorio_manha_ml": "Todo dia às 07:30 BRT (Actions); fora do orquestrador 30 min",
    "relatorio_estrategia_ml": "Segundas às 08:00 BRT (fora do orquestrador)",
    "monitor_concorrentes": "A cada 30 min (orquestrador); workflow dedicado só manual",
    "resumo_diario_novamix": "Debug manual (sem Telegram) — Novamix fora do ciclo Impala",
    "monitor_sem_venda_ml": "A cada 30 min (orquestrador)",
    "monitor_anita": "Debug manual (sem Telegram) — produção via comparativo_anita_impala",
    "monitor_mercado_esmaltes": "A cada 30 min (orquestrador); workflow dedicado só manual",
    "monitor_busca_kit_esmaltes": "3x/dia às 08:10, 14:10 e 21:10 BRT (Actions); fora do orquestrador",
    "monitor_kits_esmaltes": "Debug manual (sem Telegram) — produção via monitor_mercado_esmaltes",
    "montar_kits_impala": "3x/dia às 08:00, 14:00 e 21:00 BRT (Actions); fora do ciclo 30 min",
    "ecossistema_esmaltes": "Debug manual (sem Telegram) — produção via esmaltes_operacao",
    "crescimento_esmaltes": "Debug manual (sem Telegram) — produção via esmaltes_operacao",
    "decisao_dia_esmaltes": "Debug manual (sem Telegram) — produção via esmaltes_operacao",
    "esmaltes_operacao": "3x/dia às 08:00, 14:00 e 21:00 BRT — único Telegram Impala",
    "golpe_guerra_impala": "No golpe (monitor concorrentes 30 min); cooldown 6h por SKU+classe",
    "simulacao_guerra_impala": "Sob demanda / CLI — nao entra no cron",
    "radar_diferencial_impala": "No monitor concorrentes (30 min) + orquestrador visao atuacao; cooldown 6h no Telegram",
    "kits_concorrentes_unificado": "A cada 30 min (orquestrador), depois do radar; sem Telegram — só o JSON",
    "monitor_removedores_unha": "1x/semana quarta 09:00 BRT (anexo)",
    "monitor_tendencias_esmaltes": "Debug manual (sem Telegram) — produção via busca_kit",
    "comparativo_anita_impala": "Segundas e quintas às 08:00 BRT (Actions); fora do orquestrador 30 min",
    "comparativo_ml_shopee": "Debug manual (sem Telegram) — canal Shopee sob demanda",
    "monitor_filamentos_ml": "1x/dia às 08:30 BRT (Actions); fora do orquestrador 30 min",
    "monitor_masterprint_petg": (
        "1x/dia às 08:15 BRT (Actions); Claude 1×/noite; fora do orquestrador"
    ),
    "monitor_masterprint_escritorio": (
        "1x/dia às 08:45 BRT (Actions); Claude 1×/noite; fora do orquestrador"
    ),
    "monitor_cnpj_cnae": (
        "A cada ~10 dias (1, 11 e 21 do mês, 09:00 BRT via Actions); "
        "alteração de CNPJ dispara ML + Telegram de decisão; fora do orquestrador 30 min"
    ),
    "ponto_ruptura_segundo_cnpj": (
        "Todo dia às 08:05 BRT (Actions); fora do orquestrador 30 min. "
        "Telegram no veredito (CNAE semanal / aproximando 24h / liberado) com briefing Impala."
    ),
    "ponto_ruptura_outra_marca": (
        "Todo dia às 08:05 BRT (mesmo workflow do 2º CNPJ); fora do orquestrador 30 min. "
        "Telegram no veredito (aproximando 24h / radar cego / liberado) com briefing Impala."
    ),
    "monitor_acetona_cruzeiro": "1x/semana sexta 09:00 BRT (anexo)",
    "descoberta_produtos": "Debug manual (sem Telegram) — fora do foco Impala",
    "ads_gatilho": "Todo dia às 08:00 BRT (fora do orquestrador)",
    "meta_metricas": "A cada 30 min (orquestrador)",
    "trafego_manicures": "Debug/API (fora do orquestrador) — cobrir com meta_metricas",
    "promocoes_manicures": "Todo dia às 10:00 e 18:00 BRT (fora do orquestrador)",
    "conversao_manicures": "3x/dia às 08:25, 14:25 e 21:25 BRT (Actions); fora do ciclo 30 min",
    "necessidade_manicures": "3x/dia às 08:35, 14:35 e 21:35 BRT (Actions); fora do ciclo 30 min",
    "panorama": "Todo dia às 06:30 BRT (Actions) e a cada 30 min (orquestrador)",
    "orquestrador": "A cada 30 min (GitHub Actions)",
    "operacao_24h": "A cada 2h (operacao_24h_seguranca); fora do orquestrador 30 min",
    "repricing": "Via operacao_24h_seguranca (2h) — fora do orquestrador",
    "repricing_impala": "Via operacao_24h / CLI — fora do orquestrador",
    "sincronizar_estoque": "A cada 2h (Actions, escrita real); fora do orquestrador",
    "algoritmo": (
        "4x ao dia às 00:00, 06:00, 12:00 e 18:00 BRT (agente principal) e a cada "
        "30 min (orquestrador)"
    ),
    "manutencao": "A cada 30 min (orquestrador / renovação de tokens)",
    "otimizador_listing": "Terças às 06:00 BRT (Actions; fora do ciclo 30 min)",
    "relatorio_financeiro": "Segundas às 06:00 BRT (Actions; fora do ciclo 30 min)",
    "push_deploy": "Somente manual (workflow_dispatch)",
    "auto_respostas": "Agente principal (chat); fora do orquestrador 30 min",
    "chat_ml": (
        "A cada 30 min no horário comercial via agente principal (~06h–19h BRT) e "
        "no orquestrador"
    ),
    "chat_shopee": "Agente principal (chat); fora do orquestrador 30 min",
    "chat_magalu": "Agente principal (chat); fora do orquestrador 30 min",
    "chat_amazon": "Agente principal (chat); fora do orquestrador 30 min",
    "conectividade": "A cada hora (Actions) e a cada 30 min (orquestrador)",
    "vendas_whatsapp": "A cada 30 min (orquestrador / agente principal)",
}

# Prefixo da chave de cooldown → id do agente (fallback automático)
_CHAVE_PARA_AGENTE: tuple[tuple[str, str], ...] = (
    ("vigia_datadog", "vigia_datadog"),
    ("vigia:", "vigia_datadog"),
    ("consumo_claude", "consumo_claude"),
    ("claude_orcamento", "consumo_claude"),
    ("orcamento_claude", "consumo_claude"),
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
    ("alibaba_sourcing", "alibaba_sourcing"),
    ("alibaba:sourcing", "alibaba_sourcing"),
    ("portos_alibaba", "comparar_portos_alibaba"),
    ("portos_br", "comparar_portos_alibaba"),
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
    ("montar_kits_impala", "montar_kits_impala"),
    ("montar_kits", "montar_kits_impala"),
    ("ecossistema_esmaltes", "ecossistema_esmaltes"),
    ("ecossistema", "ecossistema_esmaltes"),
    ("crescimento_esmaltes", "crescimento_esmaltes"),
    ("crescimento", "crescimento_esmaltes"),
    ("decisao_dia_esmaltes", "decisao_dia_esmaltes"),
    ("decisao_dia", "decisao_dia_esmaltes"),
    ("esmaltes_operacao", "esmaltes_operacao"),
    ("operacao_esmaltes", "esmaltes_operacao"),
    ("golpe_guerra_impala", "golpe_guerra_impala"),
    ("golpe_guerra", "golpe_guerra_impala"),
    ("simulacao_guerra_impala", "simulacao_guerra_impala"),
    ("simulacao_guerra", "simulacao_guerra_impala"),
    ("radar_diferencial_impala", "radar_diferencial_impala"),
    ("visao_atuacao_impala", "radar_diferencial_impala"),
    ("kits_concorrentes_unificado", "kits_concorrentes_unificado"),
    ("kits_concorrentes", "kits_concorrentes_unificado"),
    ("removedores", "monitor_removedores_unha"),
    ("tendencias_esmaltes", "monitor_tendencias_esmaltes"),
    ("esmaltes:tendencias", "monitor_tendencias_esmaltes"),
    ("anita_impala", "comparativo_anita_impala"),
    ("comparativo:ml_shopee", "comparativo_ml_shopee"),
    ("ml_shopee", "comparativo_ml_shopee"),
    ("filamentos", "monitor_filamentos_ml"),
    ("filamentos:ml", "monitor_filamentos_ml"),
    ("masterprint", "monitor_masterprint_petg"),
    ("masterprint_petg", "monitor_masterprint_petg"),
    ("petg_masterprint", "monitor_masterprint_petg"),
    ("masterprint_escritorio", "monitor_masterprint_escritorio"),
    ("pinceis_masterprint", "monitor_masterprint_escritorio"),
    ("apagador_masterprint", "monitor_masterprint_escritorio"),
    ("cnpj_cnae", "monitor_cnpj_cnae"),
    ("monitor_cnpj", "monitor_cnpj_cnae"),
    ("vinculo_cnae", "monitor_cnpj_cnae"),
    ("outra_marca", "ponto_ruptura_outra_marca"),
    ("marca_esmalte", "ponto_ruptura_outra_marca"),
    ("ruptura_marca", "ponto_ruptura_outra_marca"),
    ("ponto_ruptura", "ponto_ruptura_segundo_cnpj"),
    ("segundo_cnpj", "ponto_ruptura_segundo_cnpj"),
    ("cnae_prep", "ponto_ruptura_segundo_cnpj"),
    ("acetona", "monitor_acetona_cruzeiro"),
    ("descoberta", "descoberta_produtos"),
    ("ads_ml", "ads_gatilho"),
    ("ads:", "ads_gatilho"),
    ("meta:", "meta_metricas"),
    ("meta_ads", "meta_metricas"),
    ("trafego_manicures", "trafego_manicures"),
    ("promocoes_manicures", "promocoes_manicures"),
    ("conversao_manicures", "conversao_manicures"),
    ("conversao", "conversao_manicures"),
    ("necessidade_manicures", "necessidade_manicures"),
    ("necessidade", "necessidade_manicures"),
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


def corpo_sem_cabecalho(mensagem: str) -> str:
    """
    Remove título + blocos 'O que este agente faz' / 'Quando roda'.

    Usado ao embutir mensagens de agentes-filho num consolidado (ex.: esmaltes_operacao),
    evitando 3–4 cabeçalhos/explicações iguais na mesma mensagem do Telegram.
    """
    msg = (mensagem or "").strip()
    if not msg:
        return ""
    lines = msg.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return ""
    # Descarta a 1ª linha (título do agente-filho)
    i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith(_MARCADOR):
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith(
                _MARCADOR_HORARIO
            ):
                i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            continue
        if s.startswith(_MARCADOR_HORARIO):
            i += 1
            while i < len(lines) and lines[i].strip():
                i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            continue
        break
    corpo = "\n".join(lines[i:]).strip()
    return corpo if corpo else msg


_URL_RE = re.compile(r"https?://[^\s<>\]]+", re.IGNORECASE)


def escapar_markdown_legado(texto: str) -> str:
    """Escapa _, *, ` e [ para literal em parse_mode=Markdown (legado)."""
    out = (texto or "").replace("\\", "\\\\")
    for ch in ("_", "*", "`", "["):
        out = out.replace(ch, "\\" + ch)
    return out


def _escapar_markdown_legado(texto: str) -> str:
    """Alias interno (compatível com testes/uso legado)."""
    return escapar_markdown_legado(texto)


def sanitizar_markdown_legado(texto: str) -> str:
    """
    Torna o texto seguro para parse_mode=Markdown (legado) do Telegram.

    Preserva *negrito*, _itálico_, `código` e [texto](url) quando fechados;
    escapa marcadores soltos e especiais no interior das entidades.
    URLs plain-text têm _, * etc. escapados (evitam 'can't parse entities').
    """
    s = texto or ""
    if not s:
        return ""

    placeholders: list[str] = []

    def _guardar_url(m: re.Match) -> str:
        url = m.group(0)
        trail = ""
        while url and url[-1] in ".,;:!?)":
            trail = url[-1] + trail
            url = url[:-1]
        placeholders.append(escapar_markdown_legado(url))
        return f"\x00URL{len(placeholders) - 1}\x00{trail}"

    s = _URL_RE.sub(_guardar_url, s)
    s = _sanitizar_corpo_markdown(s)
    for idx, esc in enumerate(placeholders):
        s = s.replace(f"\x00URL{idx}\x00", esc)
    return s


def _sanitizar_corpo_markdown(s: str) -> str:
    out: list[str] = []
    i = 0
    n = len(s)

    def _achar_fecho(inicio: int, marcador: str) -> int:
        j = inicio
        while j < n:
            if s[j] == "\\" and j + 1 < n:
                j += 2
                continue
            if s[j] == marcador:
                return j
            j += 1
        return -1

    while i < n:
        if s[i] == "\\" and i + 1 < n:
            out.append(s[i : i + 2])
            i += 2
            continue

        ch = s[i]

        if ch == "`":
            fecha = _achar_fecho(i + 1, "`")
            if fecha != -1:
                out.append(s[i : fecha + 1])
                i = fecha + 1
            else:
                out.append("\\`")
                i += 1
            continue

        if ch == "[":
            m = re.match(r"\[([^\]]*)\]\(([^)]*)\)", s[i:])
            if m:
                label = m.group(1)
                label_esc: list[str] = []
                k = 0
                while k < len(label):
                    if label[k] == "\\" and k + 1 < len(label):
                        label_esc.append(label[k : k + 2])
                        k += 2
                        continue
                    if label[k] in "_*`[":
                        label_esc.append("\\" + label[k])
                    else:
                        label_esc.append(label[k])
                    k += 1
                out.append(f"[{''.join(label_esc)}]({m.group(2)})")
                i += m.end()
            else:
                out.append("\\[")
                i += 1
            continue

        if ch in "*_":
            fecha = _achar_fecho(i + 1, ch)
            if fecha > i + 1:
                mid = s[i + 1 : fecha]
                outros = {"*": "_`[", "_": "*`["}[ch]
                mid_esc: list[str] = []
                k = 0
                while k < len(mid):
                    if mid[k] == "\\" and k + 1 < len(mid):
                        mid_esc.append(mid[k : k + 2])
                        k += 2
                        continue
                    if mid[k] in outros:
                        mid_esc.append("\\" + mid[k])
                    else:
                        mid_esc.append(mid[k])
                    k += 1
                out.append(ch + "".join(mid_esc) + ch)
                i = fecha + 1
            else:
                out.append("\\" + ch)
                i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


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
