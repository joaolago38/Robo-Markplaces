"""
tests/test_testar_integracao.py
Cobre scripts/testar_integracao.py (config e integração Claude+Bling).
"""
import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


def _load_testar_integracao():
    spec = importlib.util.spec_from_file_location(
        "testar_integracao",
        ROOT / "scripts" / "testar_integracao.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestTestarIntegracaoConfig(unittest.TestCase):
    def _run_script(self, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        run_env = os.environ.copy()
        run_env.update(env)
        for key in (
            "ANTHROPIC_API_KEY",
            "BLING_ACCESS_TOKEN",
            "BLING_REFRESH_TOKEN",
            "BLING_CLIENT_ID",
            "BLING_CLIENT_SECRET",
        ):
            run_env.setdefault(key, "")
        run_env.setdefault("PYTHONIOENCODING", "utf-8")
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "testar_integracao.py")],
            cwd=ROOT,
            env=run_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )

    def test_teste1_falha_sem_bling_client_secret(self):
        r = self._run_script(
            {
                "ANTHROPIC_API_KEY": "sk-test-key-12345",
                "BLING_ACCESS_TOKEN": "access-token-abc",
                "BLING_REFRESH_TOKEN": "refresh-token-xyz",
                "BLING_CLIENT_ID": "client-id-ok",
                "BLING_CLIENT_SECRET": "",
            }
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("BLING_CLIENT_SECRET ausente", r.stdout)


class TestIntegracaoClaudeBling(unittest.TestCase):
    @patch("core.claude_client.perguntar", return_value="Recomendo o kit com 12 cores.")
    @patch.object(sys, "exit")
    def test_perguntar_com_contexto_compoe_prompt(self, _mock_exit, mock_perguntar):
        mod = _load_testar_integracao()
        mock_perguntar.reset_mock()
        ctx = "Produtos disponiveis: Kit Impala."
        pergunta = "Qual kit recomenda?"
        out = mod.perguntar_com_contexto(pergunta, ctx)
        self.assertEqual(out, "Recomendo o kit com 12 cores.")
        mock_perguntar.assert_called_once_with(
            f"{ctx}\n\n{pergunta}",
            max_tokens=500,
        )


if __name__ == "__main__":
    unittest.main()
