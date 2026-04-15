# n8n - Robo-Markplaces

Este diretório contém o pacote pronto para orquestrar a API pelo n8n.

## Arquivos

- `workflows/robo_markplaces_rotinas.json`: rotinas automáticas (cron).
- `workflows/robo_markplaces_chat_webhook.json`: entrada webhook para chat.
- `workflows/robo_markplaces_faturamento_webhook.json`: entrada webhook para emissão de NF-e.
- `workflows/robo_markplaces_meta_metricas.json`: monitoramento de campanhas Meta.
- `workflows/robo_markplaces_repricing_marketplaces.json`: monitoramento e repricing por lucro mínimo.
- `workflows/robo_markplaces_operacao_24h.json`: operação contínua (vendas/lucro + faturamento).
- `workflows/robo_markplaces_trafego_manicures_noite.json`: eficiência noturna de tráfego para manicures.
- `workflows/robo_markplaces_resumo_madrugada.json`: top 3 piores campanhas às 06:00.
- `workflows/robo_markplaces_chat_visual.json`: respostas automáticas com contexto visual dos produtos.
- `env.exemplo`: variáveis esperadas pelos workflows.

## Pré-requisitos

1. API Python rodando em `http://localhost:5000`.
2. n8n em execução.
3. Credencial HTTP no n8n (opcional se API não exigir auth).

## Variáveis no n8n

No n8n, configure as variáveis de ambiente:

- `ROBO_API_BASE_URL` (ex: `http://localhost:5000`)
- `ROBO_KEEPALIVE_DIAS` (ex: `5`)
- `ROBO_ALERTAR_ATENCAO` (`true` ou `false`)
- `ROBO_HORA_FATURAMENTO_DIA_SEGUINTE` (ex: `06:15`)

## Importação

1. n8n -> Workflows -> Import from file.
2. Importe `workflows/robo_markplaces_rotinas.json`.
3. Importe `workflows/robo_markplaces_chat_webhook.json`.
4. Importe `workflows/robo_markplaces_faturamento_webhook.json`.
5. Importe `workflows/robo_markplaces_meta_metricas.json`.
6. Importe `workflows/robo_markplaces_repricing_marketplaces.json`.
7. Importe `workflows/robo_markplaces_operacao_24h.json`.
8. Importe `workflows/robo_markplaces_trafego_manicures_noite.json`.
9. Importe `workflows/robo_markplaces_resumo_madrugada.json`.
10. Importe `workflows/robo_markplaces_chat_visual.json`.
11. Ajuste timezone dos cron nodes para `America/Sao_Paulo`.
12. Ative os workflows.

## Rotinas incluídas

- Keepalive marketplaces: diariamente às 09:00.
- Ajuste de algoritmo/saúde: a cada 1 hora.
- Relatório diário: diariamente às 08:00.
- Estoque crítico: a cada 4 horas.
- Validação Meta Ads: a cada 1 hora.
- Repricing marketplaces: a cada 2 horas.
- Operação 24h (monitoramento + NF): a cada 1 hora.
- Operação 24h (monitoramento sem emissão de NF): a cada 1 hora.
- Faturamento dia seguinte (emissão NF no Bling): horário parametrizado por `ROBO_HORA_FATURAMENTO_DIA_SEGUINTE` (default `06:15`).
- Tráfego manicures (Impala/Anita/Kits): diariamente às 22:00.
- Resumo madrugada (3 piores campanhas): diariamente às 06:00.
- Chat visual marketplaces (respostas automáticas): a cada 1 hora.

## Teste rápido

Após ativar, execute manualmente o node:

- `HTTP Algoritmo` e confirme resposta `ok: true`.
- `HTTP Keepalive` e confirme `resultados`.

Se precisar, altere os horários nos nodes Cron ou via `ROBO_HORA_FATURAMENTO_DIA_SEGUINTE`.
