Corrija a apresentação dos logs no Datadog. Aplique literalmente, na
ordem dos passos. Crie a branch `fix/datadog-tags-marketplace` antes
de começar. Se algo não bater exatamente com o arquivo atual, pare e
mostre o trecho real antes de aplicar.

═══════════════════════════════════════════════════════════════
CONTEXTO — por que isto está quebrado hoje
═══════════════════════════════════════════════════════════════

`core/datadog_logger.py` tagueia cada log enviado ao Datadog com
`marketplace:<nome>`, usando um dicionário que mapeia o nome do
logger (`logging.getLogger("X")`) para o marketplace. Esse dicionário
tem dois problemas:

1. BUG: a chave `"bling_client"` nunca bate com o logger real, que é
   `logging.getLogger("bling")` (definido em
   `integracoes/bling/bling_client.py`). Resultado: nenhum log do
   Bling cai em `marketplace:bling` — tudo vai para
   `marketplace:geral`.
2. COBERTURA INCOMPLETA: de ~40 loggers usados no projeto (Amazon,
   Meta, Meta Ads, Lojahub, todos os `agente_*`, scripts), só 11
   tinham entrada no dicionário. O resto cai silenciosamente em
   `geral`, esvaziando o facet que deveria servir para filtrar e
   montar dashboards por canal de venda.

═══════════════════════════════════════════════════════════════
GARANTIA OBRIGATÓRIA
═══════════════════════════════════════════════════════════════

Isto é só uma correção de tagging/observabilidade — NÃO pode mudar
nenhum comportamento de negócio. Nenhum agente, integração ou regra
de preço/estoque/NF-e é tocado. O único efeito visível é: os logs que
já são enviados ao Datadog passam a chegar com as tags corretas
(`marketplace:`, novo `componente:`, e `status` no payload). Ao
final, confirme que a suíte de testes inteira continua passando
(antes desta mudança eram 640 testes — depois devem ser mais, pelos
novos testes deste arquivo).

═══════════════════════════════════════════════════════════════
PASSO 1 — core/config.py: adicionar DD_ENV configurável
═══════════════════════════════════════════════════════════════

Hoje a tag `env:` no Datadog vem fixa como `"production"`, sem opção
de mudar para staging/dev. Localize o bloco:

```python
# Datadog Log Management (opcional — HTTP Intake, sem Agent)
DD_API_KEY = os.getenv("DD_API_KEY", "").strip()
DD_SITE = os.getenv("DD_SITE", "datadoghq.com").strip() or "datadoghq.com"
DD_LOGS_ENABLED = os.getenv("DD_LOGS_ENABLED", "true").lower() in {"1", "true", "yes"}
```

E substitua por:

```python
# Datadog Log Management (opcional — HTTP Intake, sem Agent)
DD_API_KEY = os.getenv("DD_API_KEY", "").strip()
DD_SITE = os.getenv("DD_SITE", "datadoghq.com").strip() or "datadoghq.com"
DD_LOGS_ENABLED = os.getenv("DD_LOGS_ENABLED", "true").lower() in {"1", "true", "yes"}
# Ambiente exibido na tag `env:` no Datadog (production/staging/dev). Antes era fixo em "production".
DD_ENV = os.getenv("DD_ENV", "production").strip() or "production"
```

═══════════════════════════════════════════════════════════════
PASSO 2 — core/datadog_logger.py: substituir o arquivo inteiro
═══════════════════════════════════════════════════════════════

Antes de sobrescrever, rode no terminal o comando abaixo e confira
se a lista de nomes bate com os do mapeamento do passo 2 (varre o
projeto inteiro por `getLogger("...")`, ignorando `tests/`):

```bash
grep -rhoE 'getLogger\("[^"]+"\)' --include="*.py" . | grep -v "^tests/" | sort -u
```

Se aparecer algum nome de logger que não está no `_LOGGER_META` abaixo,
pare e me avise antes de continuar — significa que o projeto evoluiu
desde este prompt e o mapeamento precisa de mais uma entrada (classifique
seguindo o mesmo padrão: marketplace real ou "infra"/"multi"/"geral", e
componente "integracao"/"agente"/"core"/"script"/"api").

Substitua TODO o conteúdo de `core/datadog_logger.py` por:

```python
"""
core/datadog_logger.py
Handler de logging que envia registros para o Datadog Log Management
via HTTP Intake API. Nunca lança exceção — falha de rede no envio do
log não pode derrubar a aplicação.
"""
from __future__ import annotations

import json
import logging

import requests

# Mapa: nome do logger (o argumento passado para logging.getLogger(...))
# -> (marketplace, componente)
#
# IMPORTANTE: a chave aqui é o nome efetivamente passado para getLogger(),
# não o nome do arquivo/módulo. Ex.: integracoes/bling/bling_client.py usa
# logging.getLogger("bling"), então a chave é "bling" — não "bling_client".
#
# `marketplace` alimenta a tag `marketplace:` (facet principal para filtrar
# por canal de venda no Log Explorer / dashboards).
# `componente` alimenta a tag `componente:` (camada: integracao, agente,
# core, script, api) — útil para separar "client de API" de "regra de
# negócio" mesmo dentro do mesmo marketplace.
#
# A cobertura deste dicionário é validada por
# tests/test_datadog_logger.py::test_todos_os_loggers_do_repo_estao_mapeados,
# que varre o código em busca de getLogger(...) e falha se algum nome novo
# não tiver entrada aqui — isso evita que logs voltem a cair em "geral"
# silenciosamente quando um novo módulo for criado.
_LOGGER_META = {
    # --- Integrações (clientes de API por marketplace) ---
    "bling": ("bling", "integracao"),
    "ml_client": ("mercadolivre", "integracao"),
    "ml_product_ads": ("mercadolivre_ads", "integracao"),
    "magalu_client": ("magalu", "integracao"),
    "shopee_client": ("shopee", "integracao"),
    "amazon_client": ("amazon", "integracao"),
    "meta": ("meta", "integracao"),
    "meta_ads_client": ("meta_ads", "integracao"),
    "lojahub": ("lojahub", "integracao"),

    # --- Core (infraestrutura compartilhada, não é um marketplace) ---
    "token_manager": ("bling_e_ml", "core"),
    "notificador": ("infra", "core"),
    "claude": ("infra", "core"),
    "alertas_esmaltes": ("infra", "core"),
    "whatsapp": ("infra", "core"),
    "http_client": ("infra", "core"),
    "config": ("infra", "core"),

    # --- Agentes (regras de negócio por marketplace) ---
    "agente_faturamento": ("bling", "agente"),
    "agente_repricing_marketplaces": ("mercadolivre_e_outros", "agente"),
    "agente_repricing_impala": ("mercadolivre_e_outros", "agente"),
    "sincronizar_estoque_marketplaces": ("mercadolivre_e_outros", "agente"),
    "agente_monitor_ml": ("mercadolivre", "agente"),
    "agente_ads_gatilho": ("mercadolivre_ads", "agente"),
    "agente_otimizador_listing": ("mercadolivre", "agente"),
    "agente_monitor_concorrentes": ("mercadolivre", "agente"),
    "agente_ml": ("mercadolivre", "agente"),
    "agente_shopee": ("shopee", "agente"),
    "agente_magalu": ("magalu", "agente"),
    "agente_amazon": ("amazon", "agente"),
    "agente_metricas_meta": ("meta", "agente"),
    "agente_trafego_manicures": ("meta", "agente"),
    "publicador": ("social", "agente"),
    "relatorio": ("bling", "agente"),

    # --- Agentes multi-marketplace (tocam mais de um canal por natureza) ---
    "agente_varredura_marketplaces": ("multi", "agente"),
    "manutencao_marketplaces": ("multi", "agente"),
    "algoritmo_marketplaces": ("multi", "agente"),
    "auto_respostas_visuais": ("multi", "agente"),
    "vendas_notificador": ("multi", "agente"),
    "agente_panorama": ("multi", "agente"),
    "relatorio_financeiro": ("multi", "agente"),
    "operacao_24h": ("infra", "agente"),

    # --- Diagnóstico interno deste módulo ---
    "datadog_logger": ("infra", "core"),

    # --- Scripts / API ---
    "renovar_tokens": ("multi", "script"),
    "scheduler_varredura_marketplaces": ("multi", "script"),
    "api": ("infra", "api"),
}

_DEFAULT_META = ("geral", "outros")

# Evita inundar o Datadog com o mesmo aviso de "logger não mapeado" a cada
# linha de log — avisa uma única vez por nome de logger, por processo.
_avisados_sem_mapeamento: set[str] = set()


def _resolver_meta(nome_logger: str) -> tuple[str, str]:
    meta = _LOGGER_META.get(nome_logger)
    if meta is not None:
        return meta
    if nome_logger not in _avisados_sem_mapeamento:
        _avisados_sem_mapeamento.add(nome_logger)
        logging.getLogger("datadog_logger").warning(
            "Logger '%s' sem marketplace/componente mapeado em "
            "_LOGGER_META — caindo em tags 'geral/outros'. Adicione uma "
            "entrada em core/datadog_logger.py.",
            nome_logger,
        )
    return _DEFAULT_META


class DatadogLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        from core.config import DD_SITE

        self._url = f"https://http-intake.logs.{DD_SITE}/api/v2/logs"

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.INFO:
            return
        from core.config import DD_API_KEY, DD_ENV, DD_LOGS_ENABLED

        if not DD_LOGS_ENABLED or not DD_API_KEY:
            return
        try:
            marketplace, componente = _resolver_meta(record.name)
            payload = [
                {
                    "message": self.format(record),
                    "ddsource": "python",
                    "service": "robo-markplaces",
                    # `status` é um standard attribute do Datadog: além de
                    # virar tag, alimenta o facet "Status" nativo do Log
                    # Explorer (cores/severidade prontas, sem facet custom).
                    "status": record.levelname.lower(),
                    "ddtags": (
                        f"env:{DD_ENV},logger:{record.name},"
                        f"marketplace:{marketplace},componente:{componente},"
                        f"level:{record.levelname.lower()}"
                    ),
                }
            ]
            requests.post(
                self._url,
                headers={"DD-API-KEY": DD_API_KEY, "Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=3,
            )
        except Exception:
            pass


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

═══════════════════════════════════════════════════════════════
PASSO 3 — tests/test_datadog_logger.py: substituir o arquivo inteiro
═══════════════════════════════════════════════════════════════

O teste antigo validava o nome de logger errado (`"bling_client"`),
o que mascarava o bug do passo 2. Substitua TODO o conteúdo de
`tests/test_datadog_logger.py` por:

```python
"""
tests/test_datadog_logger.py — handler Datadog Log Management.
"""
import json
import logging
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.datadog_logger import DatadogLogHandler, configurar_logging_datadog


def _make_record(name: str = "bling", msg: str = "evento teste") -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


class TestDatadogLogHandler(unittest.TestCase):
    @patch("core.datadog_logger.requests.post")
    @patch("core.config.DD_API_KEY", "")
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_sem_api_key_nao_chama_http(self, mock_post, *_):
        handler = DatadogLogHandler()
        handler.emit(_make_record())
        mock_post.assert_not_called()

    @patch("core.datadog_logger.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_LOGS_ENABLED", True)
    @patch("core.config.DD_SITE", "datadoghq.com")
    @patch("core.config.DD_ENV", "production")
    def test_emit_bling_tag_marketplace(self, mock_post, *_):
        handler = DatadogLogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(_make_record(name="bling", msg="NF-e ok"))

        mock_post.assert_called_once()
        kwargs = mock_post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["DD-API-KEY"], "dd-key-test")
        self.assertIn("http-intake.logs.datadoghq.com/api/v2/logs", mock_post.call_args.args[0])

        payload = json.loads(kwargs["data"])
        self.assertEqual(payload[0]["service"], "robo-markplaces")
        self.assertEqual(payload[0]["message"], "NF-e ok")
        self.assertEqual(payload[0]["status"], "info")
        self.assertIn("env:production", payload[0]["ddtags"])
        self.assertIn("marketplace:bling", payload[0]["ddtags"])
        self.assertIn("componente:integracao", payload[0]["ddtags"])
        self.assertIn("logger:bling", payload[0]["ddtags"])
        self.assertIn("level:info", payload[0]["ddtags"])

    @patch("core.datadog_logger.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_LOGS_ENABLED", True)
    @patch("core.config.DD_SITE", "datadoghq.com")
    def test_emit_ml_client_tag_mercadolivre(self, mock_post, *_):
        handler = DatadogLogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(_make_record(name="ml_client", msg="estoque ok"))

        payload = json.loads(mock_post.call_args.kwargs["data"])
        self.assertIn("marketplace:mercadolivre", payload[0]["ddtags"])

    @patch("core.datadog_logger.requests.post", side_effect=RuntimeError("rede fora"))
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_emit_excecao_rede_nao_propaga(self, *_):
        handler = DatadogLogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(_make_record())

    @patch("core.datadog_logger.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_emit_ignora_debug(self, mock_post, *_):
        handler = DatadogLogHandler()
        record = _make_record()
        record.levelno = logging.DEBUG
        record.levelname = "DEBUG"
        handler.emit(record)
        mock_post.assert_not_called()

    @patch("core.datadog_logger.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_logger_desconhecido_cai_em_geral(self, mock_post, *_):
        handler = DatadogLogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(_make_record(name="logger_inexistente_xyz", msg="evento"))

        payload = json.loads(mock_post.call_args.kwargs["data"])
        self.assertIn("marketplace:geral", payload[0]["ddtags"])
        self.assertIn("componente:outros", payload[0]["ddtags"])


class TestCoberturaDoMapeamento(unittest.TestCase):
    """Teste-guarda: garante que todo `logging.getLogger("nome")` usado no
    código de produção tenha uma entrada em core.datadog_logger._LOGGER_META.

    Sem isso, é fácil criar um novo módulo/agente, esquecer de mapear o
    logger e ele cair silenciosamente em marketplace:geral no Datadog —
    foi exatamente isso que aconteceu antes (a entrada "bling_client"
    nunca batia com o logger real "bling").
    """

    _IGNORAR_DIRS = {"tests", ".git", ".idea", "logs", "dados", "__pycache__"}

    def test_todos_os_loggers_do_repo_estao_mapeados(self):
        import re
        from pathlib import Path

        from core.datadog_logger import _LOGGER_META

        raiz = Path(__file__).resolve().parent.parent
        padrao = re.compile(r'getLogger\(\s*["\']([^"\']+)["\']\s*\)')
        encontrados: set[str] = set()

        for caminho in raiz.rglob("*.py"):
            if any(parte in self._IGNORAR_DIRS for parte in caminho.parts):
                continue
            texto = caminho.read_text(encoding="utf-8", errors="ignore")
            for nome in padrao.findall(texto):
                encontrados.add(nome)

        sem_mapeamento = sorted(encontrados - set(_LOGGER_META.keys()))
        self.assertEqual(
            sem_mapeamento,
            [],
            f"Loggers sem marketplace/componente mapeado em "
            f"core/datadog_logger.py::_LOGGER_META: {sem_mapeamento}. "
            f"Adicione uma entrada para cada um.",
        )


class TestConfigurarLoggingDatadog(unittest.TestCase):
    def setUp(self):
        self._root = logging.getLogger()
        self._handlers_originais = list(self._root.handlers)

    def tearDown(self):
        self._root.handlers = self._handlers_originais

    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_idempotente_nao_duplica_handler(self, *_):
        configurar_logging_datadog()
        configurar_logging_datadog()
        handlers = [h for h in self._root.handlers if isinstance(h, DatadogLogHandler)]
        self.assertEqual(len(handlers), 1)

    @patch("core.config.DD_API_KEY", "")
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_sem_api_key_nao_anexa_handler(self, *_):
        antes = len(self._root.handlers)
        configurar_logging_datadog()
        self.assertEqual(len(self._root.handlers), antes)


if __name__ == "__main__":
    unittest.main()
```

═══════════════════════════════════════════════════════════════
PASSO 4 — Validar
═══════════════════════════════════════════════════════════════

Rode:

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

Confirme que TODOS os testes passam (inclusive os pré-existentes —
nenhum deles deve precisar de alteração além do arquivo do passo 3).
Se `test_todos_os_loggers_do_repo_estao_mapeados` falhar, é porque
existe no repositório atual um `getLogger("...")` que não veio no
mapeamento deste prompt — me mostre a lista de nomes que faltou
(`sem_mapeamento` na mensagem de erro) antes de inventar uma
classificação, para eu confirmar o marketplace/componente correto de
cada um.

═══════════════════════════════════════════════════════════════
PASSO 5 — Resumo final![img.png](img.png)
═══════════════════════════════════════════════════════════════

Ao terminar, liste em poucas linhas:
- quantos testes passaram antes e depois;
- a lista de loggers que passaram a ter `marketplace:` correto (antes
  caíam em `geral`);
- se alguma variável de ambiente nova precisa ser documentada no
  `.env.exemplo` (`DD_ENV`).