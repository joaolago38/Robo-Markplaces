Desloque o "início do dia" de todos os workflows agendados do Robo-Markplaces
em -2h, de 08:00 BRT para 06:00 BRT, mantendo o mesmo intervalo relativo
entre eles.

CONTEXTO:
Os cron do GitHub Actions estão em UTC (BRT = UTC-3, sem horário de verão
no Brasil). Hoje o "dia de trabalho" do robô começa às 08:00 BRT. Quero
adiantar 2h o início, sem mudar o espaçamento entre as rotinas.

NÃO ALTERAR (rodam o dia inteiro, não têm "início"):
- .github/workflows/sincronizar_estoque.yml
- .github/workflows/operacao_24h_seguranca.yml
- .github/workflows/renovar_tokens.yml
NÃO ALTERAR também a checagem de saúde a cada 6h dentro de
agente_principal.yml (cron "0 3 * * *", "0 9 * * *", "0 15 * * *",
"0 21 * * *") — é um ritmo fixo independente do dia de trabalho.

ALTERAR exatamente estes, e MAIS NADA além do valor do cron (preserve
comentários, formatação e a lógica dos jobs):

1. .github/workflows/agente_principal.yml
   - cron "0 11 * * *"        → "0 9 * * *"        (relatório diário: 08:00→06:00 BRT)
   - cron "*/30 11-23 * * *"  → "*/30 9-21 * * *"   (chat loop: 08:00–20:30→06:00–18:30 BRT)
   - cron "*/30 0 * * *"      → "*/30 22 * * *"     (continuação chat: 21:00–21:30→19:00–19:30 BRT)
   - Atualize TODAS as condições `github.event.schedule == '...'` (jobs
     "relatorio" e "chat_marketplaces") para os novos valores de cron —
     são strings exatas, se não atualizar o job para de disparar.

2. .github/workflows/monitor_concorrentes_ml.yml
   - cron "0 11 * * *" → "0 9 * * *"   (08:00→06:00 BRT)

3. .github/workflows/monitor_ml.yml
   - cron "0 12 * * *" → "0 10 * * *"  (09:00→07:00 BRT)

4. .github/workflows/panorama.yml
   - cron "30 11 * * *" → "30 9 * * *" (08:30→06:30 BRT)

5. .github/workflows/ads_gatilho_ml.yml
   - cron "0 13 * * *" → "0 11 * * *"  (10:00→08:00 BRT)

6. .github/workflows/otimizar_listing.yml
   - cron "0 11 * * 2" → "0 9 * * 2"   (terça 08:00→06:00 BRT)

7. .github/workflows/relatorio_financeiro.yml
   - cron "0 11 * * 1" → "0 9 * * 1"   (segunda 08:00→06:00 BRT)

AVISO: ao mudar o cron do "relatório diário" em agente_principal.yml para
"0 9 * * *", ele passa a coincidir com um dos horários da checagem de
saúde (também "0 9 * * *" = 06:00 BRT). Isso não quebra nada — os dois
jobs simplesmente disparam juntos nesse horário — mas avise no resumo
final que essa coincidência existe.

VALIDAÇÃO:
1. Valide que todos os .yml em .github/workflows/ continuam sendo YAML
   válido (ex.: python -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]").
2. Rode python -m pytest -q e ruff check . — nenhum desses arquivos afeta
   testes/lint diretamente, mas confirme 0 erros e cobertura >= 80% pra
   garantir que nada mais foi tocado por acidente.
3. Não altere nenhum arquivo .py nesta tarefa — é só configuração de
   agendamento.