"""
tests/test_config_ml_site_id.py
Confirma que ML_SITE_ID nunca fica vazio mesmo quando a variável de
ambiente existe mas está vazia (ex.: GitHub secret ML_SITE_ID
cadastrado sem valor, ou simplesmente ausente — nesses casos
`${{ secrets.ML_SITE_ID }}` interpola para string vazia e o workflow
define env: ML_SITE_ID="" explicitamente, o que é diferente de não
definir a variável).

Isso causava 404 em buscar_concorrentes_por_termo() porque a URL
montada virava ".../sites//search" (barra dupla) em vez de cair no
default "MLB".
"""
import importlib
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestMlSiteIdNuncaFicaVazio(unittest.TestCase):
    def _reimportar_config_com_env(self, valor_env: str | None):
        env = dict(os.environ)
        if valor_env is None:
            env.pop("ML_SITE_ID", None)
        else:
            env["ML_SITE_ID"] = valor_env
        with patch.dict(os.environ, env, clear=True):
            import core.config as config

            importlib.reload(config)
            return config.ML_SITE_ID

    def test_variavel_ausente_usa_default_mlb(self):
        valor = self._reimportar_config_com_env(None)
        self.assertEqual(valor, "MLB")

    def test_variavel_presente_mas_vazia_usa_default_mlb(self):
        """Este é o cenário real do bug: a env existe, só que vazia."""
        valor = self._reimportar_config_com_env("")
        self.assertEqual(valor, "MLB")

    def test_variavel_so_com_espacos_usa_default_mlb(self):
        valor = self._reimportar_config_com_env("   ")
        self.assertEqual(valor, "MLB")

    def test_variavel_configurada_e_respeitada(self):
        valor = self._reimportar_config_com_env("MLA")
        self.assertEqual(valor, "MLA")

    @classmethod
    def tearDownClass(cls):
        # Restaura core.config no estado normal do processo para não
        # vazar para os demais testes da suíte.
        import core.config as config

        importlib.reload(config)


if __name__ == "__main__":
    unittest.main()
