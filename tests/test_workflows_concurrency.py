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
    "relatorio_manha_ml.yml",
    "relatorio_estrategia_ml.yml",
    "monitor_margem_vendas.yml",
)

_GROUP_ESPERADO = "robo-markplaces-token-renewal"
_GROUP_VIGIA = "robo-markplaces-vigia-datadog"


class TestWorkflowsConcurrency(unittest.TestCase):
    def test_workflows_compartilham_grupo_de_concurrency(self):
        for nome in _WORKFLOWS_COM_CONCURRENCY:
            path = WORKFLOWS_DIR / nome
            self.assertTrue(path.is_file(), f"workflow ausente: {nome}")
            texto = path.read_text(encoding="utf-8")
            self.assertIn("concurrency:", texto, nome)
            self.assertIn(f"group: {_GROUP_ESPERADO}", texto, nome)
            self.assertIn("cancel-in-progress: false", texto, nome)

    def test_vigia_datadog_tem_fila_propria(self):
        path = WORKFLOWS_DIR / "vigia_datadog.yml"
        texto = path.read_text(encoding="utf-8")
        self.assertIn(f"group: {_GROUP_VIGIA}", texto)
        self.assertNotIn(f"group: {_GROUP_ESPERADO}", texto)
        self.assertIn("cancel-in-progress: false", texto)

    def test_vigia_le_heartbeats_compartilhados_sem_regravar(self):
        path = WORKFLOWS_DIR / "vigia_datadog.yml"
        texto = path.read_text(encoding="utf-8")
        self.assertIn("saude-heartbeats-", texto)
        # Não deve regravar heartbeats dos produtores no cache do vigia
        save_bloco = texto.split("Salvar cache vigia")[-1]
        self.assertNotIn("orquestrador_ultimo_ciclo.json", save_bloco)
        self.assertIn("datadog_vigia_history.json", save_bloco)

    def test_produtores_publicam_saude_heartbeats(self):
        for nome in (
            "orquestrador_30min.yml",
            "conectividade_marketplaces.yml",
            "operacao_24h_seguranca.yml",
            "renovar_tokens.yml",
            "relatorio_manha_ml.yml",
            "monitor_mercado_esmaltes.yml",
        ):
            texto = (WORKFLOWS_DIR / nome).read_text(encoding="utf-8")
            self.assertIn("saude-heartbeats-", texto, nome)
            self.assertIn("Restaurar heartbeats de saude", texto, nome)
            self.assertIn("actions/cache/save", texto, nome)
            # Conjunto completo — merge entre produtores
            self.assertIn("orquestrador_ultimo_ciclo.json", texto, nome)
            self.assertIn("renovacao_tokens_ultima.json", texto, nome)
            self.assertIn("esmaltes_mercado_history.json", texto, nome)


if __name__ == "__main__":
    unittest.main()
