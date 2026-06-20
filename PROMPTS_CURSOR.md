Aqui está um prompt que você pode colar em outra sessão de IA (ou usar você mesmo) para fazer a correção:

---

**Prompt:**

> No projeto Robo-Markplaces, o teste `scripts/testar_integracao.py` está passando no TESTE 1 (Configuração de variáveis) mesmo quando `BLING_CLIENT_SECRET` está ausente ou incorreto, porque esse teste só confere `ANTHROPIC_API_KEY`, `BLING_ACCESS_TOKEN`, `BLING_REFRESH_TOKEN` e `BLING_CLIENT_ID` — nunca o `BLING_CLIENT_SECRET`. Isso esconde a causa real de falhas de renovação de token do Bling (erro 400 no `/Api/v3/oauth/token`), que só aparece depois, no TESTE 2.
>
> Faça o seguinte:
>
> 1. Em `scripts/testar_integracao.py`, dentro do TESTE 1, adicione uma checagem para `BLING_CLIENT_SECRET` (variável de ambiente), seguindo o mesmo padrão das checagens existentes (usar a função `checar()`, mostrar só os primeiros caracteres do valor por segurança, msg de erro clara se ausente).
> 2. Confirme que `core/config.py` já expõe `BLING_CLIENT_SECRET` corretamente (já expõe, em `core/config.py` linha ~39) — não precisa duplicar, só usar `os.getenv` no próprio script de teste, igual aos outros.
> 3. Em `core/token_manager.py`, na função `_renovar_token_bling`, garanta que a mensagem de erro logada no bloco `if r.status_code != 200` (que já existe, chamando `_dica_erro_refresh_bling`) é a que realmente aparece nos logs — ou seja, confirme que não há nenhum outro lugar (ex: em `core/http_client.py` ou em outra camada) que poderia estar chamando `raise_for_status()` antes desse bloco e mascarando a mensagem detalhada com o erro genérico do `requests` ("400 Client Error: Bad Request for url..."). Se encontrar, ajuste para que a mensagem detalhada com a dica (`invalid_grant`, `invalid_client`, etc.) seja sempre a que é logada.
> 4. Rode os testes existentes em `tests/test_diagnostico_bling.py` e `tests/test_bling_client.py` para garantir que nada quebrou, e adicione um teste novo cobrindo o caso de `BLING_CLIENT_SECRET` ausente.
> 5. Não altere nenhuma credencial real, apenas a lógica de diagnóstico/teste.

