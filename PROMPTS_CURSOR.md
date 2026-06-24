Em `core/datadog_logger.py`, dentro da função `configurar_logging_datadog()`, adicione UMA linha que está faltando: definir o nível do logger raiz para INFO.

PROVA DO BUG (reproduzi e confirmei):
```python
import logging
logging.getLogger().level            # -> 30 (WARNING), o padrão do Python
logging.getLogger("bling_client").isEnabledFor(logging.INFO)  # -> False
```
Como o logger raiz fica no nível padrão `WARNING` (nenhum lugar do projeto, fora de `api/app.py`, chama `setLevel`/`basicConfig` com `INFO`), toda chamada `logger.info(...)` em `bling_client.py`, `ml_client.py`, `token_manager.py`, etc. é descartada pelo próprio Python ANTES de chegar a qualquer handler — inclusive o `DatadogLogHandler`. Por isso nenhum log chega ao Datadog quando o código roda fora da API Flask (ou seja, na maioria dos workflows do GitHub Actions).

CORREÇÃO EXATA:

Em `core/datadog_logger.py`, função `configurar_logging_datadog()`, adicione a definição do nível do root logger ANTES do `return` antecipado (ou seja, mesmo que o Datadog não esteja configurado, vale a pena ter o nível INFO ativo para qualquer handler futuro/console). Fique assim:

```python
def configurar_logging_datadog() -> None:
    """Anexa DatadogLogHandler ao logger raiz (idempotente)."""
    root = logging.getLogger()
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)

    from core.config import DD_API_KEY, DD_LOGS_ENABLED

    if not DD_LOGS_ENABLED or not DD_API_KEY:
        return

    for handler in root.handlers:
        if isinstance(handler, DatadogLogHandler):
            return

    handler = DatadogLogHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
```

Note que o `root.setLevel(...)` foi movido para ANTES do `if not DD_LOGS_ENABLED or not DD_API_KEY: return` — isso é proposital: o nível INFO deve ficar ativo mesmo que o Datadog não esteja configurado (melhora a visibilidade geral de logs do projeto em qualquer ambiente, não só quando o Datadog está habilitado).

VALIDAÇÃO (faça exatamente este teste manual para confirmar a correção, antes de rodar a suíte completa):
```python
import os, logging
os.environ["DD_API_KEY"] = "fake-key-123"
os.environ["DD_LOGS_ENABLED"] = "true"
import core.config as cfg
root = logging.getLogger()
assert root.level <= logging.INFO, f"Esperado <= INFO, veio {root.level}"
logger = logging.getLogger("bling_client")
assert logger.isEnabledFor(logging.INFO) is True
print("OK — nível de log corrigido")
```
Esse script deve imprimir "OK" sem nenhum AssertionError.

Depois disso, rode `python -m pytest -q` e `ruff check api agentes core integracoes tests`. Confirme 0 falhas e cobertura ≥ 80%.

NÃO altere mais nada nesse arquivo além dessa correção pontual — o resto da implementação (handler, tags por marketplace, payload) já está correto.