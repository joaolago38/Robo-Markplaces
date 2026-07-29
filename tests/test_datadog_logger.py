"""
tests/test_datadog_logger.py — handler Datadog Log Management.
"""
import json
import logging
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.datadog_logger import DatadogLogHandler, LocalErrorBufferHandler, configurar_logging_datadog


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
        mock_post.return_value = MagicMock(status_code=202)
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
    def test_emit_mascara_access_token(self, mock_post, *_):
        mock_post.return_value = MagicMock(status_code=202)
        handler = DatadogLogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(
            _make_record(
                name="shopee_client",
                msg="erro GET https://x.com?access_token=segredo123&shop_id=1",
            )
        )
        payload = json.loads(mock_post.call_args.kwargs["data"])
        self.assertNotIn("segredo123", payload[0]["message"])
        self.assertIn("access_token=***", payload[0]["message"])

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

    @patch("core.datadog_logger.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_LOGS_ENABLED", True)
    @patch("core.datadog_logger.obter_request_id", return_value="req-abc123")
    def test_emit_inclui_request_id(self, mock_rid, mock_post, *_):
        handler = DatadogLogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(_make_record(msg="com correlation id"))

        payload = json.loads(mock_post.call_args.kwargs["data"])
        self.assertIn("request_id:req-abc123", payload[0]["ddtags"])
        self.assertEqual(payload[0]["request_id"], "req-abc123")

    @patch("core.datadog_logger.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_emit_erro_com_extra_e_exc_info(self, mock_post, *_):
        handler = DatadogLogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        try:
            raise ValueError("falha simulada")
        except ValueError:
            record = logging.LogRecord(
                name="bling",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="erro grave",
                args=(),
                exc_info=sys.exc_info(),
            )
        record.error_kind = "ValueError"
        record.error_message = "falha simulada"
        handler.emit(record)

        payload = json.loads(mock_post.call_args.kwargs["data"])
        self.assertEqual(payload[0]["status"], "error")
        self.assertEqual(payload[0]["error"]["kind"], "ValueError")
        self.assertEqual(payload[0]["error"]["message"], "falha simulada")
        self.assertIn("ValueError: falha simulada", payload[0]["error"]["stack"])


class TestLocalErrorBufferHandler(unittest.TestCase):
    @patch("integracoes.datadog.buffer_erros.registrar_erro_local")
    def test_ignora_nivel_abaixo_de_error(self, mock_registrar):
        handler = LocalErrorBufferHandler()
        handler.emit(_make_record(msg="info apenas"))
        mock_registrar.assert_not_called()

    @patch("integracoes.datadog.buffer_erros.registrar_erro_local", side_effect=RuntimeError("buffer off"))
    def test_espelhar_erro_local_nao_propaga_excecao(self, *_):
        handler = LocalErrorBufferHandler()
        record = _make_record(msg="falha")
        record.levelno = logging.ERROR
        record.levelname = "ERROR"
        handler.emit(record)

    @patch("integracoes.datadog.buffer_erros.registrar_erro_local", side_effect=RuntimeError("buffer off"))
    def test_emit_excecao_no_handler_nao_propaga(self, *_):
        handler = LocalErrorBufferHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        record = _make_record(msg="falha")
        record.levelno = logging.ERROR
        record.levelname = "ERROR"
        handler.emit(record)


class TestCoberturaDoMapeamento(unittest.TestCase):
    """Teste-guarda: garante que todo `logging.getLogger("nome")` usado no
    código de produção tenha uma entrada em core.datadog_logger._LOGGER_META.

    Sem isso, é fácil criar um novo módulo/agente, esquecer de mapear o
    logger e ele cair silenciosamente em marketplace:geral no Datadog —
    foi exatamente isso que aconteceu antes (a entrada "bling_client"
    nunca batia com o logger real "bling").
    """

    _IGNORAR_DIRS = {
        "tests",
        ".git",
        ".idea",
        "logs",
        "dados",
        "__pycache__",
        ".venv",
        "venv",
        "site-packages",
    }

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
        buffers = [h for h in self._root.handlers if isinstance(h, LocalErrorBufferHandler)]
        handlers = [h for h in self._root.handlers if isinstance(h, DatadogLogHandler)]
        self.assertEqual(len(buffers), 1)
        self.assertEqual(len(handlers), 1)

    @patch("integracoes.datadog.buffer_erros.registrar_erro_local")
    @patch("core.config.DD_API_KEY", "")
    @patch("core.config.DD_LOGS_ENABLED", False)
    def test_buffer_local_sem_datadog(self, mock_registrar, *_):
        self._root.handlers = [
            h for h in self._root.handlers if not isinstance(h, (LocalErrorBufferHandler, DatadogLogHandler))
        ]
        configurar_logging_datadog()
        logger = logging.getLogger("teste_buffer_local_xyz")
        logger.error("falha grave")
        mock_registrar.assert_called_once()

    @patch("core.config.DD_API_KEY", "")
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_sem_api_key_anexa_buffer_local(self, *_):
        self._root.handlers = [
            h for h in self._root.handlers if not isinstance(h, (LocalErrorBufferHandler, DatadogLogHandler))
        ]
        configurar_logging_datadog()
        buffers = [h for h in self._root.handlers if isinstance(h, LocalErrorBufferHandler)]
        dd_handlers = [h for h in self._root.handlers if isinstance(h, DatadogLogHandler)]
        self.assertEqual(len(buffers), 1)
        self.assertEqual(len(dd_handlers), 0)


if __name__ == "__main__":
    unittest.main()
