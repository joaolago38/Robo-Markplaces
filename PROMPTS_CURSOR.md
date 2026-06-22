Implemente as 3 melhorias abaixo no Robo-Markplaces, focadas em maximizar o ganho financeiro com a operação no Mercado Livre. São independentes entre si — implemente NA ORDEM e rode `python -m pytest -q` depois de cada item antes de seguir pro próximo.

(Contexto: ACOS no operacao_24h, cron dedicado de ads, endpoint /ml/ads/diagnostico, pausa seletiva por campanha e enriquecimento de concorrência JÁ FORAM implementados em uma rodada anterior — não repita esses itens.)

═══════════════════════════════════════════════════
ITEM 1 — Tornar MAX_ITENS_ANALISE configurável e ampliar a cobertura do catálogo
═══════════════════════════════════════════════════

BUG/LIMITAÇÃO ATUAL:
Em `agentes/ml/agente_monitor_ml.py`, linha ~21:
```python
MAX_ITENS_ANALISE = 15
```
Esse valor está hardcoded no módulo (não vem de `.env`/`core/config.py` como `ACOS_MAXIMO` e `MARGEM_MINIMA`). Isso significa que o monitoramento diário (`_analisar_concorrencia`, usado por `analisar()`) só olha os 15 primeiros itens do catálogo — se a loja tiver mais de 15 anúncios ativos, o restante nunca é analisado nem entra nas recomendações/relatório, mesmo que o resto das melhorias (ACOS, concorrência enriquecida) já estejam funcionando perfeitamente.

TAREFA:
1. Em `core/config.py`, ao lado de `ACOS_MAXIMO`, adicione:
   ```python
   ML_MAX_ITENS_ANALISE = int(os.getenv("ML_MAX_ITENS_ANALISE", "30"))
   ```
   (dobrando o padrão atual de 15 para 30 — valor seguro o suficiente para não estourar limites de rate-limit da API do ML, mas cobrindo bem mais catálogo. Documente no `.env.exemplo` com um comentário explicando o trade-off: valores muito altos aumentam o tempo de execução e o número de chamadas à API do ML por ciclo.)
2. Em `agentes/ml/agente_monitor_ml.py`, remova a constante hardcoded `MAX_ITENS_ANALISE = 15` e importe de `core.config`:
   ```python
   from core.config import ML_MAX_ITENS_ANALISE as MAX_ITENS_ANALISE
   ```
   (mantenha o nome `MAX_ITENS_ANALISE` no módulo para não quebrar nada que já importa esse nome de `agentes.ml.agente_monitor_ml` — ex.: `api/app.py` já importa `MAX_ITENS_ANALISE` de lá.)
3. Confirme que `api/app.py` (endpoint `/ml/ads/diagnostico`) continua funcionando sem alteração, já que ele só usa `MAX_ITENS_ANALISE` como valor default — não precisa mudar nada ali.
4. Atualize/adicione teste em `tests/test_agente_monitor_ml.py` confirmando que `MAX_ITENS_ANALISE` reflete o valor de `cfg.ML_MAX_ITENS_ANALISE` (ex.: usando `monkeypatch`/`patch` para setar um valor diferente via env e confirmar que o módulo respeita).
5. Atualize o `README.md` na seção de variáveis de ambiente, documentando `ML_MAX_ITENS_ANALISE` (default 30).

═══════════════════════════════════════════════════
ITEM 2 — Relatório de impacto financeiro (ROI) do robô
═══════════════════════════════════════════════════

OBJETIVO:
Hoje o robô toma decisões (bloqueia repricing abaixo da margem mínima, pausa campanhas com ACOS alto) mas não existe nenhum lugar que some "quanto dinheiro isso representou" — sem isso, é difícil para o dono do negócio saber se o robô está realmente valendo a pena. Adicione um relatório de impacto financeiro, calculado a partir de dados que o próprio robô já produz.

TAREFA:

1. Em `agentes/repricing/agente_repricing_marketplaces.py`, função `executar()`, no payload de retorno (variável `ajustes`, já tem por item: `preco_atual`, `novo_preco`, `ajustar`, `aplicado`, `motivo`), adicione ao payload final (ao lado de `total_ajustes`) um cálculo de impacto:
   ```python
   economia_estimada = sum(
       round((a["preco_atual"] - a["preco_piso"]) , 2)
       for a in ajustes
       if a.get("motivo", "").endswith("bloqueado")  # bloqueios de faixa de preço
   )
   ```
   Avalie a métrica mais correta dado o código real: o objetivo é estimar quanto o robô EVITOU perder ao não deixar o preço cair abaixo do piso de margem (comparando `preco_atual`/`novo_preco` vs `preco_piso` nos itens onde houve bloqueio ou onde `novo_preco` ficou no piso em vez de mais baixo). Documente a lógica escolhida com um comentário claro, já que é uma estimativa, não um valor exato.
   Adicione esse total ao payload retornado: `"economia_estimada_piso_margem": round(economia_estimada, 2)`.

2. Em `agentes/ml/agente_ads_gatilho.py`, na decisão `"pausar"` (a que já usa `campanhas_acos_acima_limite()` para pausa seletiva), calcule o gasto diário das campanhas pausadas (campo `cost`/período de cada campanha já retornado por `campanhas_acos_acima_limite`) e inclua no retorno de `executar()` um campo `gasto_diario_estimado_evitado` — soma do gasto diário das campanhas pausadas, como proxy de "quanto deixou de ser gasto em ads com ACOS ruim a partir de agora".

3. Crie um agente novo `agentes/relatorio_financeiro.py`, seguindo o estilo de `agentes/relatorio.py` (mesma estrutura: função `executar() -> bool`, usa `core.notificador.alertar`/`alertar_gestor`, loga com `logger`), que:
   a. Chama `agente_repricing_marketplaces.executar(dry_run=True)` (modo simulação, só para coletar os números, sem aplicar nada de novo) e extrai `economia_estimada_piso_margem` e `total_ajustes`.
   b. Chama `agente_monitor_ml.analisar(enviar_alerta=False)` e extrai os dados de `ads` (campanhas com ACOS acima do limite, gasto total).
   c. Monta um resumo consolidado, por exemplo:
      ```
      💰 Relatório financeiro semanal — Robo-Markplaces
      Repricing: R$X protegidos (piso de margem) em Y ajustes
      Ads: R$Z/dia em campanhas com ACOS acima do limite (revisar/pausar)
      ```
   d. Envia esse resumo via `alertar_gestor()` (não `alertar_critico`, pois não é uma falha, é um relatório informativo).
   e. Retorna `True`/`False` conforme sucesso, igual ao padrão de `agentes/relatorio.py`.
4. Crie um workflow novo `.github/workflows/relatorio_financeiro.yml`, no mesmo padrão dos outros (`agente_principal.yml`/`monitor_ml.yml`), rodando 1x por semana (ex.: segunda-feira de manhã, horário BRT) chamando esse novo agente.
5. Adicione testes em `tests/test_agente_relatorio_financeiro.py` (crie esse arquivo), mockando `agente_repricing_marketplaces.executar` e `agente_monitor_ml.analisar`, cobrindo: caso de sucesso com números > 0, caso sem nenhum ajuste/alerta (números zerados, mensagem ainda deve ser enviada sem erro), e caso de exceção interna (deve logar e retornar `False`, nunca propagar exceção).
6. Documente esse novo agente e workflow no `README.md`.

═══════════════════════════════════════════════════
ITEM 3 — Expor os parâmetros financeiros-chave (ACOS_MAXIMO, MARGEM_MINIMA, fases de margem) no relatório do panorama
═══════════════════════════════════════════════════

OBJETIVO:
Hoje, pra revisar se `ACOS_MAXIMO` (0.20 = 20%) e `MARGEM_MINIMA`/`MARGEM_FASE_1/2/3_PCT` estão calibrados certo, é preciso abrir o código (`core/config.py`). Facilite isso expondo esses valores dentro do relatório que já existe, pra quem opera o negócio (não necessariamente quem programa) conseguir revisar e decidir se quer ajustar via `.env`/Secrets, sem precisar olhar código.

TAREFA:
1. Em `agentes/panorama/agente_panorama.py`, localize onde o resumo/JSON operacional é montado (a função que monta o contexto enviado pro Claude e pro Telegram). Adicione uma seção com os parâmetros financeiros atuais, importando de `core.config`:
   ```python
   from core.config import ACOS_MAXIMO, MARGEM_MINIMA, MARGEM_FASE_1_PCT, MARGEM_FASE_2_PCT, MARGEM_FASE_3_PCT
   ```
   E inclua no payload/contexto (não precisa mandar pro Claude reescrever isso, só exibir como dado de referência fixo no final da mensagem Telegram, fora do texto gerado pela IA):
   ```
   ⚙️ Parâmetros atuais: ACOS máx {ACOS_MAXIMO*100:.0f}% | Margem mínima {MARGEM_MINIMA:.0f}% | Fases {MARGEM_FASE_1_PCT:.0f}/{MARGEM_FASE_2_PCT:.0f}/{MARGEM_FASE_3_PCT:.0f}%
   ```
2. Garanta que isso não quebre o formato/teste existente do payload do panorama — adicione como um campo extra no dict (ex.: `"parametros_financeiros": {...}`) e só depois formate na mensagem final de texto.
3. Atualize testes em `tests/test_agente_panorama.py` cobrindo a presença desses novos campos no payload/mensagem.

═══════════════════════════════════════════════════
REGRAS GERAIS
═══════════════════════════════════════════════════
- Não altere comportamento de escrita real (repricing/ads) — os itens 2 e 3 são só leitura/relatório, nunca devem aplicar preço ou pausar campanha por conta própria além do que já acontece hoje.
- Toda nova função deve ter try/except e nunca propagar exceção não tratada (padrão do projeto).
- Rode `ruff check api agentes core integracoes tests` (esse é o escopo real do lint no CI, conforme `.github/workflows/agente_principal.yml`) e `python -m pytest -q` no final de tudo — confirme 0 falhas e cobertura ≥ 80%.
- Atualize o `README.md` para cada novo workflow, variável de ambiente ou agente adicionado.