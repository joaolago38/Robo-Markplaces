Corrija o teste com falha em `tests/test_token_manager_providers.py::TestTokenManagerProviders::test_renovar_token_meta_detalhado_ok`.

CONTEXTO DO BUG:
O teste falha com `AssertionError: False is not true` porque ele faz mock de `tm.get_token_meta` e `tm._renovar_token_meta`, mas a função testada `renovar_token_meta_detalhado()` (em `core/token_manager.py`) primeiro valida `cfg.META_APP_ID`, `cfg.META_APP_SECRET` e o retorno de `_meta_token_disponivel()` lendo direto das variáveis de config/ambiente — sem nenhum mock. Em qualquer ambiente sem essas variáveis configuradas (ex.: CI limpo, clone novo sem `.env`), esses valores ficam vazios/None, então a função retorna `{"ok": False, "motivo": "credenciais Meta ausentes"}` antes de chegar à lógica que foi mockada — e o teste falha.

Outro teste no mesmo arquivo, `test_renovar_token_bling_detalhado_ok`, já resolve esse mesmo problema corretamente usando:
```python
@patch.multiple(cfg, BLING_CLIENT_ID="c", BLING_CLIENT_SECRET="s", BLING_REFRESH_TOKEN="r")
```

TAREFA:
1. Abra `tests/test_token_manager_providers.py`.
2. Corrija `test_renovar_token_meta_detalhado_ok` adicionando o isolamento das credenciais Meta via `@patch.multiple(cfg, META_APP_ID="id", META_APP_SECRET="sec")`, seguindo o mesmo padrão usado no teste do Bling.
3. Garanta que `_meta_token_disponivel()` também retorne um valor truthy nesse teste — mocke-o com `@patch.object(tm, "_meta_token_disponivel", return_value="token_atual")` (não use o mock de `get_token_meta`, que não é o que `renovar_token_meta_detalhado` consulta).
4. Mantenha o mock existente de `_renovar_token_meta` retornando `"meta_new"`.
5. O teste final deve ficar assim (ajuste apenas se necessário para bater com a assinatura real das funções):

```python
@patch.object(tm, "_meta_token_disponivel", return_value="token_atual")
@patch.multiple(cfg, META_APP_ID="id", META_APP_SECRET="sec")
def test_renovar_token_meta_detalhado_ok(self, *_):
    with patch.object(tm, "_renovar_token_meta", return_value="meta_new"):
        out = tm.renovar_token_meta_detalhado()
    self.assertTrue(out["ok"])
    self.assertEqual(out["access_token"], "meta_new")
```

6. Não altere o código de produção em `core/token_manager.py` — o bug é exclusivamente de isolamento do teste (falta de mock das credenciais), a lógica da função está correta.
7. Rode a suíte completa depois da correção: `python -m pytest -q`. Confirme que esse teste passa e que nenhum outro teste foi afetado (devem continuar 488 passando, 0 falhando, cobertura ≥ 80%).
8. Não remova nem altere o teste `test_renovar_token_meta_detalhado_sem_cred`, que já está correto e cobre o caminho de falha por credencial ausente.