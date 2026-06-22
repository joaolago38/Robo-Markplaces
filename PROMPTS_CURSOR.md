Corrija `scripts/debug_bling_refresh.py` para que ele NÃO descarte o novo token quando o refresh do Bling der certo.

CONTEXTO DO BUG:
Hoje, quando `debug_bling_refresh.py` chama `POST /oauth/token` (grant_type=refresh_token) e a resposta é HTTP 200, o script faz:
```python
if r.status_code == 200:
    print("  SUCESSO — o refresh funcionou! (NÃO vou imprimir os tokens no log)")
    print("  Pegue os novos tokens rodando a renovação normal e atualize os Secrets.")
    sys.exit(0)
```
O Bling usa refresh_token rotativo de uso único: ao chamar o refresh com sucesso, o token antigo (`BLING_REFRESH_TOKEN` atual no Secret/`.env`) é invalidado e um novo é emitido — mas esse script joga esse novo token fora sem salvar nem mostrar. Resultado: a PRÓXIMA execução do workflow `renovar_tokens.yml` (que roda a cada 30 min) usa o Secret antigo (agora inválido) e falha com `HTTP 400 Invalid refresh token`. Isso é a causa principal do padrão "renova uma hora, falha na outra" nos runs do GitHub Actions.

OBJETIVO:
Quando o refresh der sucesso dentro do `debug_bling_refresh.py`, o script deve:
1. Sincronizar automaticamente os novos tokens nos Secrets do GitHub, quando possível (mesmo mecanismo já usado em `scripts/renovar_tokens.py`).
2. Quando não for possível sincronizar automaticamente (sem `gh` CLI, sem `GH_TOKEN`, ou rodando localmente fora do GitHub Actions), imprimir os novos tokens de forma BEM destacada no terminal, para que o usuário copie e atualize os Secrets manualmente — sem deixar o token se perder silenciosamente.

TAREFA:

1. Abra `scripts/renovar_tokens.py` e localize a função `_sync_secrets_github(access_token: str, refresh_token: str | None, prefix: str = "BLING") -> bool` (usa `gh secret set` via subprocess, requer `gh` CLI instalado e `GH_TOKEN`/`GH_REPO` no ambiente). Não duplique essa lógica — extraia/reaproveite.

2. Para evitar duplicação de código entre os dois scripts, faça UMA das duas opções (escolha a mais simples de implementar sem quebrar nada):
   - OPÇÃO A (preferida): mova `_sync_secrets_github` para um módulo compartilhado, ex. `core/github_secrets.py`, exportando a função `sync_secrets_github(access_token: str, refresh_token: str | None, prefix: str = "BLING") -> bool`. Atualize `scripts/renovar_tokens.py` para importar de lá em vez de definir localmente (mantenha exatamente o mesmo comportamento/assinatura, só mudando a localização). Importe essa mesma função em `scripts/debug_bling_refresh.py`.
   - OPÇÃO B (mais rápida, se preferir não criar módulo novo): em `scripts/debug_bling_refresh.py`, importe diretamente a função já existente:
     ```python
     from scripts.renovar_tokens import _sync_secrets_github
     ```
     (ajuste o `sys.path`/imports conforme o padrão já usado no início do arquivo, que já garante a raiz do projeto no `sys.path`).

3. No bloco de sucesso do refresh em `scripts/debug_bling_refresh.py`, substitua:
   ```python
   if r.status_code == 200:
       print("  SUCESSO — o refresh funcionou! (NÃO vou imprimir os tokens no log)")
       print("  Pegue os novos tokens rodando a renovação normal e atualize os Secrets.")
       sys.exit(0)
   ```
   por uma lógica que:
   a. Extraia `access_token` e `refresh_token` da resposta JSON (`dados = r.json()`).
   b. Se `GITHUB_ACTIONS` estiver definido como `"true"` no ambiente (igual ao padrão já usado em `renovar_tokens.py` com `em_actions = os.getenv("GITHUB_ACTIONS") == "true"`) E o `gh` CLI estiver disponível, chame a função de sync (do passo 2) para atualizar `BLING_ACCESS_TOKEN` e `BLING_REFRESH_TOKEN` diretamente nos Secrets do GitHub. Imprima o resultado (sucesso/falha) sem nunca expor o valor dos tokens no log.
   c. Caso a sincronização automática não seja possível (não está no GitHub Actions, ou `gh` ausente, ou sync falhou), imprima os tokens de forma BEM visível, com um aviso claro, por exemplo:
      ```python
      print("=" * 60)
      print("SUCESSO! O refresh funcionou e o token foi ROTACIONADO.")
      print("Copie AGORA estes valores para os Secrets do GitHub, ou a")
      print("proxima renovacao automatica vai falhar (token antigo invalidado):")
      print("=" * 60)
      print(f"BLING_ACCESS_TOKEN:  {access_token}")
      print(f"BLING_REFRESH_TOKEN: {refresh_token}")
      print("=" * 60)
      ```
   d. Em ambos os casos, finalize com `sys.exit(0)`.

4. Garanta que, se a chamada de sync (passo 3b) falhar, o script caia automaticamente no fallback do passo 3c (nunca deixe o token se perder sem mostrar nem salvar).

5. Não altere o comportamento do script em caso de ERRO no refresh (HTTP != 200) — essa parte (diagnóstico de `invalid_grant`/`invalid_client`) já está correta e não deve vazar tokens, mantenha como está.

6. Atualize o comentário/docstring no topo de `scripts/debug_bling_refresh.py` para refletir o novo comportamento (não é mais "só diagnóstico" — agora ele também salva/exibe o token novo em caso de sucesso).

7. Se criar testes novos, siga o padrão dos testes existentes (`tests/test_diagnostico_bling.py` ou crie `tests/test_debug_bling_refresh.py`), mockando a chamada HTTP (`requests.post`) e o `subprocess.run` usado pelo `gh secret set`, cobrindo os 3 cenários:
   - sucesso + sync automático funciona (em GitHub Actions, `gh` disponível) → não imprime tokens, só confirma secrets atualizados.
   - sucesso + sync indisponível (local, sem `gh` ou fora do Actions) → imprime os tokens destacados.
   - sucesso + sync falha (gh existe mas o `subprocess.run` retorna erro) → cai no fallback e imprime os tokens destacados.

8. Rode `python -m pytest -q` e `ruff check .` no final e confirme que nada quebrou (cobertura mínima de 80% continua passando).