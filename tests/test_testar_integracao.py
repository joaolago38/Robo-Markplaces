"""
tests/test_testar_integracao.py
Cobre TESTE 1 de scripts/testar_integracao.py (variáveis de ambiente).
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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


if __name__ == "__main__":
    unittest.main()
