Corrija os workflows do n8n em `n8n/workflows/*.json` para não usarem mais `$env` nas expressões, trocando por `$vars`.

CONTEXTO DO BUG:
Todos os nodes HTTP nos workflows do n8n (`n8n/workflows/robo_markplaces_rotinas.json`, `robo_markplaces_meta_metricas.json`, `robo_markplaces_chat_visual.json`, e possivelmente outros) usam expressões como:
```
{{$env.ROBO_API_BASE_URL || 'http://localhost:5000'}}/marketplaces/algoritmo/ajustar
```
O n8n bloqueia o acesso a `$env` (variáveis de ambiente do sistema) dentro da interface — ao testar qualquer node manualmente ("Execute step"), o n8n lança o erro `access to env vars denied`, independente do fallback `||` configurado na expressão (o bloqueio acontece antes de avaliar o fallback). Isso afeta TODOS os nodes que leem `$env`, em todos os workflows.

A solução correta é usar as **Variables nativas do n8n** (`$vars`), que não têm essa restrição, em vez de variáveis de ambiente do sistema operacional (`$env`).

TAREFA:

1. Abra a pasta `n8n/workflows/` e, em cada arquivo `.json`, substitua TODAS as ocorrências de `$env.` por `$vars.`. As variáveis usadas no projeto, pelo que já mapeei, são:
   - `$env.ROBO_API_BASE_URL` → `$vars.ROBO_API_BASE_URL`
   - `$env.ROBO_KEEPALIVE_DIAS` → `$vars.ROBO_KEEPALIVE_DIAS`
   - `$env.ROBO_ALERTAR_ATENCAO` → `$vars.ROBO_ALERTAR_ATENCAO`
   - `$env.ROBO_HORA_FATURAMENTO_DIA_SEGUINTE` → `$vars.ROBO_HORA_FATURAMENTO_DIA_SEGUINTE`
   Faça uma busca por `$env.` em TODOS os arquivos `.json` dentro de `n8n/workflows/` (não só nos 3 que já identifiquei) para garantir que nenhuma ocorrência fique de fora — pode haver outras variáveis em workflows que eu não listei aqui (ex.: `robo_markplaces_repricing_marketplaces.json`, `robo_markplaces_operacao_24h.json`, `robo_markplaces_trafego_manicures_noite.json`, `robo_markplaces_resumo_madrugada.json`, `robo_markplaces_faturamento_webhook.json`, `robo_markplaces_chat_webhook.json`).
2. NÃO altere o restante da expressão (mantenha os fallbacks `|| 'valor_padrao'` como estão, só troque `$env` por `$vars` — o fallback continua útil caso a variável não esteja cadastrada nas Variables do n8n).
3. Atualize `n8n/README.md`:
   - Troque a seção "Variáveis no n8n" para deixar claro que essas variáveis devem ser cadastradas em **Settings → Variables** do n8n (não como variável de ambiente do sistema/Docker), já que `$env` é bloqueado pela interface do n8n para testes manuais.
   - Mantenha a lista de variáveis e seus exemplos de valor (`ROBO_API_BASE_URL`, `ROBO_KEEPALIVE_DIAS`, `ROBO_ALERTAR_ATENCAO`, `ROBO_HORA_FATURAMENTO_DIA_SEGUINTE`), só mudando onde/como configurá-las.
   - Adicione um aviso curto explicando o erro `access to env vars denied` e por que a solução é usar `$vars` em vez de `$env`, para quem importar os workflows no futuro não precisar descobrir isso de novo.
4. Se existir `n8n/env.exemplo`, mantenha esse arquivo como está (ele continua útil como referência de quais variáveis existem e seus valores padrão — só não documente mais que elas devem ser variáveis de ambiente do n8n/Docker; ajuste o comentário/cabeçalho do arquivo se ele disser isso explicitamente).
5. Não há testes Python para arquivos `.json` do n8n no projeto — não é necessário criar testes automatizados para essa correção, mas confirme ao final, listando (via `grep -ro '\$env\.' n8n/workflows/*.json` ou equivalente) que não restou nenhuma ocorrência de `$env.` em nenhum arquivo de workflow.
6. Essa correção é só nos arquivos `.json`/`.md` do n8n — não altere nenhum código Python (`api/app.py`, `agentes/`, `core/`, etc.), já que o problema é só do lado do n8n.