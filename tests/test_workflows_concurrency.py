"""
tests/test_workflows_concurrency.py

Documenta e valida a decisão de serializar renovação OAuth entre workflows:
refresh_tokens de uso único (ML, Magalu, Bling) não podem ser renovados em
paralelo por runners efêmeros sem MAGALU_TOKEN_STORE / ML_TOKEN_STORE.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / ".github" / "workflows"

_WORKFLOWS_COM_CONCURRENCY = (
    "renovar_tokens.yml",
    "agente_principal.yml",
    "operacao_24h_seguranca.yml",
    "sincronizar_estoque.yml",
    "conectividade_marketplaces.yml",
    "orquestrador_30min.yml",
    "push_main_rotinas.yml",
    "leilao_veiculo.yml",
    "alibaba_importacao.yml",
    "licitacoes.yml",
    "lojas_veiculos.yml",
    "push_deploy.yml",
    "branch_cleanup.yml",
)

_GROUP_ESPERADO = "robo-markplaces-token-renewal"


class TestWorkflowsConcurrency(unittest.TestCase):
    def test_workflows_compartilham_grupo_de_concurrency(self):
        for nome in _WORKFLOWS_COM_CONCURRENCY:
            path = WORKFLOWS_DIR / nome
            self.assertTrue(path.is_file(), f"workflow ausente: {nome}")
            texto = path.read_text(encoding="utf-8")
            self.assertIn("concurrency:", texto, nome)
            self.assertIn(f"group: {_GROUP_ESPERADO}", texto, nome)
            self.assertIn("cancel-in-progress: false", texto, nome)


if __name__ == "__main__":
    unittest.main()
