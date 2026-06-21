# Prompt — Agente de monitoramento do Mercado Livre (conta + ads + concorrência + recomendações)

Crie um novo arquivo **`agentes/ml/agente_monitor_ml.py`** no projeto
Robo-Markplaces. Ele deve fazer uma varredura de leitura (somente análise,
SEM alterar nada na conta) e me comunicar a situação e quais ajustes fazer.

REGRA DE OURO: este agente é SÓ DIAGNÓSTICO E RECOMENDAÇÃO. Ele NÃO pausa
campanha, NÃO muda preço, NÃO muda orçamento. Toda ação de escrita continua
sendo decidida por mim (o agente apenas alerta e sugere). Nunca lance exceção
não tratada.

## Reutilize as funções que JÁ existem (não reescreva):
De `integracoes.ml.ml_client`:
- `_enabled()` — saber se ML está configurado
- `obter_saude_conta()` -> {configurado, pendencias, claims_rate, dias_sem_acesso}
- `buscar_reputacao_vendedor()` -> dict de reputação
- `listar_perguntas_nao_respondidas()` -> list
- `listar_meus_anuncios()` -> list de anúncios (cada um com item_id)
- `buscar_metricas_item(item_id)` -> {titulo, status, preco, estoque, visitas_7d, visitas_30d}
- `buscar_menor_preco_concorrente(item_id)` -> float (0.0 se não houver catálogo)
- `buscar_acos_ads(item_id, dias=14)` -> float

De `integracoes.ml.ml_product_ads`:
- `obter_advertiser()` -> {ok, advertiser_id, site_id, ...}
- `listar_campanhas(advertiser_id, dias=14)` -> list de {id,nome,status,budget,acos,roas,cost,clicks}
- `campanhas_acos_acima_limite(campanhas)` -> list

De `core.notificador`:
- `alertar_gestor(msg)` — para me enviar o resumo/alertas (Telegram/WhatsApp)

De `core.config` (limites já existentes; use com getattr e defaults seguros):
- `ML_ADS_ORCAMENTO_MAXIMO`, `ML_ADS_ACOS_DIAS_LIMITE`, e o ACOS máximo usado no
  projeto (procure por `ACOS_MAXIMO` em `agentes/ml/agente_ads_gatilho.py` e use o
  mesmo valor/origem; se não achar, use 0.30 como default).

## O que o agente deve produzir — função `analisar() -> dict`

1. **Situação da conta**
   - Se `_enabled()` for False: retorne {ok: False, motivo: "ML não configurado"}
     e mande UM alerta dizendo que faltam credenciais. Não quebre.
   - Chame `obter_saude_conta()` e `listar_perguntas_nao_respondidas()`.
   - Gere recomendações: se houver perguntas não respondidas -> recomendar
     responder (cite a quantidade); se `claims_rate` alto ou `dias_sem_acesso`
     elevado -> alertar risco de reputação.

2. **Situação dos Ads**
   - `obter_advertiser()`. Se `ok=False`: registre como pendência ("Publicidade
     não habilitada" quando `codigo == sem_permissao`) e siga.
   - Se ok: `listar_campanhas(advertiser_id, dias=14)`.
   - Recomendações de ads:
     - campanhas com ACOS acima do limite -> recomendar REVISAR/baixar lance ou
       pausar (use `campanhas_acos_acima_limite`).
     - gasto (`cost`) somado acima de `ML_ADS_ORCAMENTO_MAXIMO` -> alertar.
     - campanhas `active` com `clicks` altos e `roas` baixo -> recomendar ajuste.
     - se NÃO houver nenhuma campanha ativa e a conta vende -> sugerir avaliar
       ligar ads.

3. **Pesquisa de concorrência e desempenho**
   - Pegue meus anúncios via `listar_meus_anuncios()` (limite a, por ex., os 15
     primeiros para não estourar rate limit).
   - Para cada item: `buscar_metricas_item(item_id)` e
     `buscar_menor_preco_concorrente(item_id)`.
   - Compare meu preço com o menor preço do concorrente:
     - se meu preço > concorrente em mais de X% (ex.: 5%) -> recomendar revisar
       preço para baixo (mostre meu preço, o do concorrente e a diferença %).
     - se eu já sou o menor e tenho boa visita/baixa conversão aparente
       (visitas altas, mas estoque parado) -> recomendar revisar título/fotos.
     - se visitas_7d caíram muito vs média de visitas_30d -> alertar queda de
       tráfego.
   - Produza uma lista ordenada por prioridade (maior diferença de preço ou
     maior gasto de ads primeiro).

4. **Comunicação dos ajustes (o que fazer)**
   - Monte um texto de resumo claro, em português, com seções:
     "📊 Conta", "📣 Ads", "🔎 Concorrência", e "✅ Ajustes recomendados"
     (lista numerada e priorizada do que devo fazer).
   - Envie esse resumo via `alertar_gestor(resumo)`.
   - Retorne também um dict estruturado:
     {ok: True, conta: {...}, ads: {...}, concorrencia: [...],
      recomendacoes: ["...", "..."], enviado: True}

## Função `main()` / execução direta
- Permita rodar com `python -m agentes.ml.agente_monitor_ml` ou
  `python agentes/ml/agente_monitor_ml.py`, chamando `analisar()` e imprimindo o
  resumo no console (com os helpers de log que o projeto já usa, se houver).

## Boas práticas obrigatórias
- Cada chamada de API protegida por try/except; nunca propague exceção.
- Respeite rate limit: não chame métricas para centenas de itens — limite a
  quantidade e, se possível, durma alguns ms entre chamadas.
- Não escreva NADA na conta (sem pausar/alterar preço/orçamento). Apenas leitura
  + alerta + recomendação.
- Ao terminar, confirme que o arquivo compila
  (`python -m py_compile agentes/ml/agente_monitor_ml.py`) e me diga como rodar.

## Opcional
Crie também `.github/workflows/monitor_ml.yml` (workflow_dispatch + schedule
diário, ex.: 09:00 BRT) que roda este agente, nos moldes dos workflows já
existentes no projeto.

> Lembrete: o agente roda no GitHub Actions a partir do que está commitado.
> Depois de gerar, faça commit e push na branch `main` para valer.