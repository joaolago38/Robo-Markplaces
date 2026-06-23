Corrija o teste `tests/test_magalu_client.py::TestMagaluClient::test_listar_pedidos_ok`.

CONTEXTO DO BUG:
O teste usa uma data fixa no mock:
```python
"created_at": "2026-06-16T10:00:00+00:00",
```
A função real `integracoes/magalu/magalu_client.py::listar_pedidos()` filtra pedidos mais antigos que `dias=7` comparando `created_at` com `datetime.now(timezone.utc)` — ou seja, com a data REAL de quando o código roda, não com uma data fixa.

Como já passou mais de 7 dias desde 16/06/2026 10:00 UTC, o próprio código de produção, corretamente, descarta esse pedido por estar fora da janela de 7 dias — e o teste, que espera 1 pedido no retorno, passa a falhar:
```
AssertionError: 0 != 1
```
Isso é um bug de teste (data "chumbada" no código), não um bug de produção — a lógica de filtro por `dias` em `listar_pedidos()` está correta e não deve ser alterada.

TAREFA:

1. Abra `tests/test_magalu_client.py`.
2. No topo do arquivo, garanta que `datetime`, `timedelta` e `timezone` estão importados de `datetime` (adicione o import se não existir).
3. Em `test_listar_pedidos_ok`, substitua a data fixa por uma data calculada relativa ao momento do teste, dentro da janela de `dias=7` usada na chamada (`mag.listar_pedidos(dias=7)`), por exemplo:
   ```python
   created_recente = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
   ```
   E use essa variável no mock:
   ```python
   "created_at": created_recente,
   ```
4. Procure em TODO o projeto por outros testes que usem datas absolutas fixas (strings como `"2026-06-..."`, `"2025-..."`, etc.) para simular "pedido/evento recente" em conjunto com um filtro por `dias`/janela de tempo — verifique especialmente:
   - `tests/test_ml_client.py` (função `listar_pedidos`)
   - `tests/test_shopee_client.py` (função `listar_pedidos`)
   - `tests/test_amazon_client.py` (função `listar_pedidos`)
   - qualquer outro teste que mocke `listar_pedidos`, `buscar_metricas_item`, ou funções com parâmetro `dias`
   Esses clientes seguem o mesmo padrão de filtro por `dias` que o Magalu, então podem ter o mesmo problema, mesmo que ainda não tenham "vencido" (vão quebrar sozinhos no futuro se não forem corrigidos agora). Aplique a mesma correção (data relativa a `datetime.now(timezone.utc)`) em todos que encontrar.
5. NÃO altere nenhum código de produção (`integracoes/*/*.py`) — a correção é só nos testes.
6. Rode `python -m pytest -q` no final e confirme 0 falhas e cobertura ≥ 80% (`--cov-fail-under=80` em `pyproject.toml`).
7. Rode também `ruff check api agentes core integracoes tests` para confirmar que os imports novos (`timedelta`, `timezone`) não geram nenhum aviso de lint.