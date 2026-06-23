Corrija o erro de lint `F401` (import não utilizado) em `tests/test_magalu_client.py`, linha 7:
```
from datetime import datetime, timedelta, timezone
```

CONTEXTO:
Esse import foi adicionado numa correção anterior, que pedia para o teste `test_listar_pedidos_ok` parar de usar uma data fixa (`"created_at": "2026-06-16T10:00:00+00:00"`) e passar a calcular uma data relativa ao momento da execução, usando algo como:
```python
created_recente = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
```
O lint está acusando que `datetime`, `timedelta` e `timezone` foram importados mas não são usados em nenhum lugar do arquivo — ou seja, essa parte da correção anterior não foi aplicada de fato no corpo do teste (só o import foi adicionado).

TAREFA:

1. Abra `tests/test_magalu_client.py` e localize o teste `test_listar_pedidos_ok`.
2. Verifique se o mock de `created_at` ainda está com uma data fixa (string literal tipo `"2026-06-16T10:00:00+00:00"`) em vez de calculada com `datetime.now(timezone.utc)`.
3. Se ainda estiver com data fixa: corrija para usar uma data relativa dentro da janela de `dias=7` usada por `mag.listar_pedidos(dias=7)`, por exemplo:
   ```python
   created_recente = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
   ```
   E use essa variável no campo `"created_at"` do mock, em vez da string fixa.
4. Confirme se existe algum outro teste no mesmo arquivo que também deveria ter sido corrigido na rodada anterior (mock de pedido "recente" para testar filtro por `dias`) e que também ficou com import não utilizado — aplique a mesma correção se encontrar.
5. Só remova o import de `datetime`/`timedelta`/`timezone` se, depois de revisar tudo, ficar claro que nenhum teste do arquivo realmente precisa dele — o que não deveria ser o caso aqui.
6. NÃO altere nenhum código de produção (`integracoes/magalu/magalu_client.py`) — a correção é só no teste.
7. Rode `ruff check api agentes core integracoes tests` — confirme 0 erros de lint (nem o `F401` nem nenhum outro).
8. Rode `python -m pytest -q` — confirme 0 falhas e cobertura ≥ 80% (`--cov-fail-under=80` em `pyproject.toml`).