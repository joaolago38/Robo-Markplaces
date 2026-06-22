Centralize a sincronização do token Bling com o GitHub Secrets dentro de `core/token_manager.py`, para que QUALQUER caminho que rotacione o `BLING_REFRESH_TOKEN` (não só os scripts `renovar_tokens.py` e `debug_bling_refresh.py`) salve o valor novo no GitHub automaticamente.

CONTEXTO DO BUG:
Hoje existem 3 lugares que podem rotacionar o refresh_token do Bling (ele é de uso único — cada renovação invalida o token antigo):

1. `scripts/renovar_tokens.py` — já sincroniza com `sync_secrets_github()` (core/github_secrets.py). OK.
2. `scripts/debug_bling_refresh.py` — já sincroniza também (corrigido recentemente). OK.
3. `core/token_manager.py::_renovar_token_bling()` — chamada internamente por `get_token_bling(forcar=True)`, que por sua vez é chamada por `integracoes/bling/bling_client.py` (linha ~31) sempre que uma chamada à API do Bling recebe HTTP 401. Esse caminho roda dentro de QUALQUER workflow que use o Bling (`agente_principal.yml`, `cadastrar_ncm.yml`, `testar_integracao.yml`, `panorama.yml`, etc.) — e ele só persiste o token novo em memória e num "cofre" em arquivo local (`_salvar_store_bling`), nunca no GitHub Secrets. Em uma VM efêmera do GitHub Actions, esse arquivo local é destruído ao fim do job, então o token novo se perde — e o próximo run do `renovar_tokens.yml` falha com `Invalid refresh token`, mesmo que a correção dos itens 1 e 2 já esteja aplicada.

OBJETIVO:
Mover a sincronização para dentro de `_renovar_token_bling()`, no ponto único onde o token de fato é rotacionado — assim TODOS os 3 caminhos passam a sincronizar automaticamente, sem precisar lembrar de fazer isso em cada script novo que tocar no Bling no futuro.

TAREFA:

1. Em `core/token_manager.py`, no topo do arquivo, importe a função já existente:
   ```python
   from core.github_secrets import sync_secrets_github
   ```
   (confirme que não há import circular — `core/github_secrets.py` não importa nada de `core/token_manager.py`, então está seguro.)

2. Localize a função `_renovar_token_bling()`. No trecho onde ela já persiste o token localmente:
   ```python
   # Persiste em disco (se o cofre estiver ativo) — resolve a rotação fora do Actions.
   _salvar_store_bling(
       access_token,
       novo_refresh or refresh,
       _token_cache_bling["expires_at"],
   )

   logger.info("Token Bling renovado com sucesso")
   return access_token
   ```
   Adicione, IMEDIATAMENTE DEPOIS de `_salvar_store_bling(...)` e ANTES do `logger.info(...)`, a sincronização condicional com o GitHub:
   ```python
   if os.getenv("GITHUB_ACTIONS") == "true":
       if sync_secrets_github(access_token, novo_refresh or refresh, prefix="BLING"):
           logger.info("Secrets BLING_* sincronizados no GitHub (rotação automática).")
       else:
           logger.warning(
               "Falha ao sincronizar BLING_* no GitHub após rotação — "
               "o próximo refresh pode falhar até o sync funcionar."
           )
   ```
   Confirme que `import os` já existe no topo do arquivo (deve existir, já é usado em outras partes do módulo); se não existir, adicione.

3. NÃO remova a chamada a `_salvar_store_bling(...)` — ela continua útil para processos locais/persistentes fora do GitHub Actions (onde `GITHUB_ACTIONS` não está definido). As duas formas de persistência (disco local + GitHub Secrets) coexistem, cada uma cobrindo um cenário diferente.

4. Em `scripts/renovar_tokens.py` e `scripts/debug_bling_refresh.py`, a chamada a `sync_secrets_github(...)` para o Bling especificamente vai ficar duplicada (uma vez dentro de `_renovar_token_bling()` via passo 2, outra explícita no script). Isso não quebra nada (a segunda chamada só reenviaria o mesmo valor), mas para evitar 2 chamadas de API do GitHub por execução:
   a. Em `scripts/renovar_tokens.py`, no bloco `[Bling]` de `main()`, REMOVA a chamada explícita a `_sync_secrets_github(res_bling["access_token"], novo_refresh, prefix="BLING")` dentro do `if em_actions or quer_sync:` — já que `_renovar_token_bling()` (chamada internamente por `renovar_token_bling_detalhado()`) agora cuida disso sozinha quando `GITHUB_ACTIONS=true`. Mantenha o `else` (impressão dos tokens) para quando NÃO estiver no GitHub Actions, já que nesse caso a sincronização automática do passo 2 não dispara (ela só age quando `GITHUB_ACTIONS == "true"`).
   b. Ajuste a lógica de `exit_code` nesse bloco: como a sincronização do Bling passa a acontecer "dentro" da renovação, se ela falhar o script não saberá diretamente — então capture isso checando o retorno de log ou (mais simples) deixe `renovar_token_bling_detalhado()` devolver no dict também um campo `secrets_sincronizados: bool`, propagado a partir do retorno de `sync_secrets_github` dentro de `_renovar_token_bling()`. Avalie a forma mais simples de implementar isso sem complicar a assinatura de `_renovar_token_bling()` (que hoje só retorna `access_token | None`) — se for complicado demais, é aceitável manter a chamada de sync duplicada nos scripts (não traz bug, só uma chamada de API extra) em vez de mudar a assinatura interna. Documente no código a decisão tomada.
   c. Em `scripts/debug_bling_refresh.py`, mesma avaliação: como o sucesso do refresh ali já passa por `_renovar_token_bling()` (via chamada direta ao endpoint OU indiretamente, confirme qual caminho o script usa hoje), avalie se a chamada própria a `sync_secrets_github` no script ainda é necessária. Se o script faz a chamada HTTP diretamente (sem passar por `_renovar_token_bling()`), MANTENHA a sincronização própria do script como está — ela é o único lugar que sabe que esse refresh aconteceu.

5. Atualize os testes em `tests/test_token_manager_providers.py`:
   - Os testes que já mockam `_renovar_token_bling` diretamente (ex.: `test_renovar_token_bling_detalhado_ok`, `test_renovar_token_bling_detalhado_falha`) não precisam de mudança, pois eles mockam a função inteira e não exercitam o código novo internamente.
   - Adicione um teste novo, por exemplo `test_renovar_token_bling_sincroniza_secrets_no_actions`, que:
     a. Mocka a chamada HTTP (`core.token_manager.request` ou o que for usado internamente) para simular um refresh bem-sucedido do Bling (HTTP 200, com `access_token` e `refresh_token` novos no JSON).
     b. Mocka `core.token_manager.sync_secrets_github` para retornar `True`.
     c. Define a variável de ambiente `GITHUB_ACTIONS=true` (via `monkeypatch.setenv` ou `os.environ`, revertendo no fim do teste).
     d. Chama `tm._renovar_token_bling()` diretamente.
     e. Verifica que `sync_secrets_github` foi chamado com os valores corretos (`access_token`, `refresh_token`, `prefix="BLING"`).
   - Adicione outro teste cobrindo o caso `GITHUB_ACTIONS` não definido (ou `"false"`): mockar `sync_secrets_github` e verificar que ele NÃO foi chamado nesse caso (preserva o comportamento de processos locais, que dependem só do `_salvar_store_bling`).
   - Adicione um teste cobrindo falha do sync (retorna `False`): a função deve continuar retornando o `access_token` normalmente (não falhar a renovação por causa de um problema no sync), só logar o warning.

6. Rode `python -m pytest -q` e `ruff check .` no final. Confirme 0 falhas e cobertura mínima de 80% mantida (`--cov-fail-under=80` em `pyproject.toml`).

7. Atualize o `README.md` (seção sobre renovação de tokens/Bling, se existir) mencionando que a partir de agora a rotação do refresh_token do Bling se auto-sincroniza com os Secrets do GitHub a partir de QUALQUER chamada à API do Bling feita dentro de um workflow do GitHub Actions — não só pelo cron dedicado de renovação.