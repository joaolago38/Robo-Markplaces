# Tarefa: corrigir o erro de lint E402 do ruff nos testes

## Erro
O `ruff check` está falhando no CI com:

```
E402 Module level import not at top of file
  --> tests/test_pegar_token_magalu.py:16:1
   |
14 | sys.path.insert(0, str(ROOT))
15 |
16 | import pegar_token_magalu as ptm
```

## Causa
O teste precisa importar um script que fica na **raiz** do projeto (`pegar_token_magalu.py`), e para isso faz `sys.path.insert(0, str(ROOT))` ANTES do import. O ruff (regra `E402`) exige imports no topo do arquivo e acusa esse import como "fora de lugar". Mas o `sys.path.insert` é proposital e necessário — não é erro de verdade. A correção é dizer ao ruff para ignorar `E402` nesse caso.

Importante: vários outros testes da pasta `tests/` que importam scripts da raiz (`pegar_token_bling.py`, `pegar_token_ml.py`, `testar_magalu.py`, etc.) têm ou terão o mesmo padrão e cairiam no mesmo `E402`. Por isso, a correção preferida é por pasta, não linha a linha.

## Correção preferida: per-file-ignores para a pasta de testes
No config do ruff do projeto, ignore a regra `E402` apenas para a pasta `tests/`. 

- Primeiro **verifique onde e como o ruff está configurado**: pode estar em `pyproject.toml` (sob `[tool.ruff]` ou `[tool.ruff.lint]`) ou em um `ruff.toml`/`.ruff.toml` separado. Siga o formato que já existe no projeto.
- Adicione (ajustando a seção conforme a versão de config já usada):

  Se o projeto usa a seção nova `[tool.ruff.lint]`:
  ```toml
  [tool.ruff.lint.per-file-ignores]
  "tests/**" = ["E402"]
  ```

  Se usa a seção antiga `[tool.ruff]` (sem `.lint`):
  ```toml
  [tool.ruff.per-file-ignores]
  "tests/**" = ["E402"]
  ```
- Se já existir um bloco `per-file-ignores`, **adicione** a entrada de `tests/**` em vez de sobrescrever as existentes.

## Alternativa (se não quiser mexer no config)
Adicionar `# noqa: E402` apenas na(s) linha(s) de import afetada(s):
```python
import pegar_token_magalu as ptm  # noqa: E402
```

## NÃO fazer
- Não remover o `sys.path.insert` nem alterar a lógica dos testes.
- Não desativar a regra `E402` globalmente (só para a pasta `tests/`).
- Não tocar em código de produção (`api`, `agentes`, `core`, `integracoes`) — só no config do ruff e/ou nos arquivos de teste.

## Validar
- Rode exatamente o comando do CI e confirme que passa:
  ```
  ruff check api agentes core integracoes tests
  ```
- Garanta que `pytest -q` continua verde.

## Entregar
A alteração no config do ruff (ou os `# noqa: E402`), e a saída do `ruff check ...` sem erros.