# Tarefa: refatorar `testar_magalu.py` para ser testável e cobrir com testes (≥90%)

## Contexto
Existe (ou deve existir) na raiz do projeto um script `testar_magalu.py`: um diagnóstico que tenta renovar o token do Magalu (`POST https://id.magalu.com/oauth/token`, grant `refresh_token`, form-urlencoded) e imprime o **status** e o **corpo** da resposta, para revelar o motivo de um erro 400 (`invalid_grant`, `invalid_client`, etc.). As credenciais vêm do `.env` (`MAGALU_CLIENT_ID`, `MAGALU_CLIENT_SECRET`, `MAGALU_REFRESH_TOKEN`).

O problema para testar: na versão atual o script executa tudo no **nível do módulo** (sem funções, sem `if __name__ == "__main__"`), então importá-lo dispara a chamada HTTP real — impossível de testar e perigoso (consome o refresh token, que é rotativo). Precisamos refatorar para ser testável e então cobrir com testes.

## Parte 1 — Refatorar `testar_magalu.py` (sem mudar o comportamento ao rodar)

Reorganize em funções puras + um `main()` com guarda, **sem efeitos colaterais no import**:

- `carregar_credenciais() -> dict` — lê `MAGALU_CLIENT_ID`, `MAGALU_CLIENT_SECRET`, `MAGALU_REFRESH_TOKEN` do ambiente, com `.strip()`, e retorna um dict.
- `mascarar(valor: str) -> str` — devolve uma versão mascarada para log (ex.: primeiros/últimos chars + tamanho), nunca o valor inteiro.
- `renovar(client_id: str, client_secret: str, refresh_token: str) -> tuple[int, str]` — faz o POST e retorna `(status_code, corpo_texto)`. Toda a chamada HTTP fica aqui (para ser mockada nos testes). Use `requests.post` com `Content-Type: application/x-www-form-urlencoded` e `timeout=25`.
- `main() -> int` — orquestra: carrega credenciais, imprime as mascaradas + tamanhos, valida que as três existem (se faltar alguma, imprime aviso e retorna código diferente de 0 — não use `sys.exit` direto dentro de lógica testável; retorne o código e deixe o `main` retornar), chama `renovar(...)`, imprime status e corpo, e retorna 0 em sucesso (status < 400) ou 1 caso contrário.
- No fim do arquivo: `if __name__ == "__main__": raise SystemExit(main())`.

Mantenha o `load_dotenv()` dentro de try/except, mas chame-o **dentro do `main()`** (ou de `carregar_credenciais()`), não no nível do módulo, para o import não ter efeitos colaterais.

Regra de segurança: NUNCA imprimir o valor completo de client_secret ou tokens — só a versão mascarada e o tamanho.

## Parte 2 — Testes em `tests/test_testar_magalu.py`

Siga o padrão de testes já existente no projeto (pytest). **Nenhum teste pode fazer chamada de rede real** — mocke `requests.post` (via `monkeypatch` ou `unittest.mock.patch`). Use `monkeypatch.setenv` para as variáveis de ambiente. Cubra pelo menos:

1. `carregar_credenciais()` lê e dá `.strip()` corretamente nas três variáveis.
2. `mascarar()` não vaza o valor completo (o resultado não contém o valor inteiro) e indica o tamanho.
3. `renovar()` em **sucesso** (mock de `requests.post` retornando um objeto com `status_code=200` e um `text`/`json` válido) retorna `(200, ...)`.
4. `renovar()` em **erro 400** (mock retornando `status_code=400` e um `text` tipo `{"error":"invalid_grant"}`) retorna `(400, corpo)` e o corpo é propagado.
5. `main()` com as três env vars presentes e mock de sucesso → retorna `0`.
6. `main()` com mock de 400 → retorna `1` e imprime o corpo (capture com `capsys` e verifique que o corpo aparece na saída).
7. `main()` com alguma env var ausente → retorna código != 0 sem fazer a chamada HTTP (verifique que `requests.post` NÃO foi chamado).

Meta de cobertura: **≥ 90%** das linhas de `testar_magalu.py`.

## Validação
- Rode: `pytest tests/test_testar_magalu.py --cov=testar_magalu --cov-report=term-missing -q` e confirme cobertura ≥ 90%.
- Rode `ruff check .` (se o projeto usar ruff) e garanta verde.
- Garanta que a suíte geral (`pytest -q`) continua passando.

## NÃO fazer
- Não fazer chamadas HTTP reais nos testes (mocke tudo).
- Não imprimir/logar credenciais completas em lugar nenhum.
- Não alterar `core/token_manager.py`, `scripts/renovar_tokens.py` nem outros arquivos.
- Não commitar `.env`.

## Entregar
- `testar_magalu.py` refatorado (funções + `main()` + guarda).
- `tests/test_testar_magalu.py` com os casos acima.
- Saída do `pytest --cov` mostrando ≥ 90% para o arquivo.