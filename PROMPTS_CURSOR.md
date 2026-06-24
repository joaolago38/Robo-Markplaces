Inclua scripts/ e o nível raiz no escopo de lint do CI, hoje o ci.yml só verifica
api/agentes/core/integracoes/tests e isso deixou passar 12 erros de ruff em
scripts/*.py e setup_projeto.py sem ningúem notar.

CONTEXTO:
ruff.toml já tem per-file-ignores para tests/** (E402) e acabei de adicionar
scripts/** também (E402, por causa do padrão sys.path.insert(...) antes de
importar módulos locais nesses scripts). Mas o .github/workflows/ci.yml roda
"ruff check api agentes core integracoes tests" — não inclui scripts/ nem os
arquivos .py da raiz (setup_projeto.py, pegar_token_*.py, testar_*.py). Quero
que o CI passe a cobrir 100% do código Python do repositório.

TAREFA:

1. Em .github/workflows/ci.yml, localize o passo que roda `ruff check` e
   amplie o escopo para cobrir todo o projeto, por exemplo:
   ruff check .
   (em vez de listar pastas manualmente) — assim qualquer novo
   arquivo/pasta criado no futuro já entra automaticamente no lint, sem
   precisar editar o workflow de novo.

2. Confirme que ruff.toml já ignora corretamente os casos intencionais:
   - E402 em tests/** e scripts/** (padrão sys.path.insert antes de
     imports locais).
   Se ao rodar `ruff check .` localmente aparecer algum erro novo fora
   desses casos já conhecidos, corrija o código (não silencie com ignore
   genérico).

3. Rode `ruff check .` e `python -m pytest -q` localmente antes de
   finalizar. Confirme 0 erros de lint e cobertura de teste >= 80%
   (limite já configurado no projeto).

4. Não altere a lógica de nenhum agente/integração — esta tarefa é
   apenas de configuração de CI e limpeza de lint.