"""
tests/test_protecao_datadog_em_testes.py
Confirma que tests/__init__.py protege a suíte contra o cenário real
que causou o vazamento: DD_API_KEY presente no ambiente onde os
testes rodam (como acontecia antes em .github/workflows/ci.yml, que
herdava o secret de produção para o job inteiro).

Roda um subprocesso novo com DD_API_KEY="chave-real-de-producao" no
ambiente — simulando exatamente o CI antigo — e confirma que nenhuma
chamada de rede ao Datadog é feita mesmo assim, porque
tests/__init__.py já zera a variável antes de qualquer teste importar
core.config.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestProtecaoDatadogEmTestes(unittest.TestCase):
    def test_dd_api_key_no_ambiente_nao_vaza_para_os_testes(self):
        """
        Simula o cenário exato do CSV de erros: um processo de teste
        rodando com DD_API_KEY real no ambiente (como o job de CI
        herdava de secrets.DD_API_KEY). Mesmo assim, core.config.DD_API_KEY
        deve nascer vazia dentro do processo de teste, porque
        tests/__init__.py roda antes de qualquer import de core.config.
        """
        env = dict(os.environ)
        env["DD_API_KEY"] = "chave-fake-simulando-producao"
        env["DD_LOGS_ENABLED"] = "true"

        codigo = (
            "import tests  # noqa: F401 — força a proteção de tests/__init__.py rodar primeiro\n"
            "from core import config\n"
            "assert config.DD_API_KEY == '', f'DD_API_KEY vazou: {config.DD_API_KEY!r}'\n"
            "assert config.DD_LOGS_ENABLED is False, f'DD_LOGS_ENABLED vazou: {config.DD_LOGS_ENABLED!r}'\n"
            "print('OK: protecao funcionando')\n"
        )

        resultado = subprocess.run(
            [sys.executable, "-c", codigo],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(
            resultado.returncode,
            0,
            f"stdout={resultado.stdout!r} stderr={resultado.stderr!r}",
        )
        self.assertIn("OK: protecao funcionando", resultado.stdout)

    def test_init_zera_as_envs_quando_pacote_tests_e_importado(self):
        """
        Checagem direta (sem subprocesso) de que o módulo tests/__init__.py
        de fato contém o efeito colateral esperado.

        NOTA: esta checagem importa o pacote `tests` explicitamente para
        não depender de como o executor de testes foi invocado — `pytest`
        importa `tests/test_xxx.py` como `tests.test_xxx` (executando
        `tests/__init__.py` antes), mas `python -m unittest discover -s
        tests` (sem `-t .`) importa os módulos como top-level soltos,
        pulando o __init__.py do pacote. Importar `tests` aqui de forma
        explícita garante que o teste valida a mesma coisa não importa
        qual dos dois runners foi usado para chegar até aqui.
        """
        import importlib

        import tests as pacote_tests

        importlib.reload(pacote_tests)
        self.assertEqual(os.environ.get("DD_API_KEY"), "")
        self.assertEqual(os.environ.get("DD_LOGS_ENABLED"), "false")


if __name__ == "__main__":
    unittest.main()
