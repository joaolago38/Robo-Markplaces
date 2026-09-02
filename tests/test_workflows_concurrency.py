"""
tests/test_workflows_concurrency.py

Núcleo OAuth (tokens/estoque/orquestrador) compartilha `robo-markplaces-token-renewal`.
Workflows secundários usam fila própria `robo-markplaces-${{ github.workflow }}`
(ou grupos dedicados) para não disputar o cadeado de refresh.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / ".github" / "workflows"

_GROUP_TOKEN = "robo-markplaces-token-renewal"
_GROUP_VIGIA = "robo-markplaces-vigia-datadog"
_GROUP_PUSH_MAIN = "robo-markplaces-push-main-sync"
_GROUP_SECUNDARIO = "robo-markplaces-monitor-secundario"
_GROUP_POR_WORKFLOW = "robo-markplaces-${{ github.workflow }}"

# Núcleo que renova/usa refresh OAuth — permanece no cadeado compartilhado.
_WORKFLOWS_TOKEN_RENEWAL = (
    "renovar_tokens.yml",
    "operacao_24h_seguranca.yml",
    "sincronizar_estoque.yml",
    "conectividade_marketplaces.yml",
    "orquestrador_30min.yml",
    "push_deploy.yml",
)

# Secundários: fila própria por workflow (cancel stale).
_WORKFLOWS_FILA_PROPRIA = (
    "agente_principal.yml",
    "alibaba_importacao.yml",
    "branch_cleanup.yml",
    "relatorio_manha_ml.yml",
    "relatorio_estrategia_ml.yml",
    "monitor_margem_vendas.yml",
    "inteligencia_precos.yml",
    "monitor_sem_venda_ml.yml",
    "monitor_ml.yml",
    "monitor_concorrentes_ml.yml",
    "monitor_mercado_esmaltes.yml",
)

_WORKFLOWS_MONITOR_SECUNDARIO = (
    "leilao_veiculo.yml",
    "monitor_sumare_leiloes.yml",
    "lojas_veiculos.yml",
    "carros_batidos.yml",
    "licitacoes.yml",
)


class TestWorkflowsConcurrency(unittest.TestCase):
    def test_nucleo_oauth_usa_grupo_token_renewal(self):
        for nome in _WORKFLOWS_TOKEN_RENEWAL:
            path = WORKFLOWS_DIR / nome
            self.assertTrue(path.is_file(), f"workflow ausente: {nome}")
            texto = path.read_text(encoding="utf-8")
            self.assertIn("concurrency:", texto, nome)
            self.assertIn(f"group: {_GROUP_TOKEN}", texto, nome)
            self.assertIn("cancel-in-progress: false", texto, nome)

    def test_secundarios_usam_fila_por_workflow(self):
        for nome in _WORKFLOWS_FILA_PROPRIA:
            path = WORKFLOWS_DIR / nome
            self.assertTrue(path.is_file(), f"workflow ausente: {nome}")
            texto = path.read_text(encoding="utf-8")
            self.assertIn("concurrency:", texto, nome)
            self.assertIn(f"group: {_GROUP_POR_WORKFLOW}", texto, nome)
            self.assertNotIn(f"group: {_GROUP_TOKEN}", texto, nome)
            self.assertIn("cancel-in-progress: true", texto, nome)

    def test_vigia_datadog_tem_fila_propria(self):
        path = WORKFLOWS_DIR / "vigia_datadog.yml"
        texto = path.read_text(encoding="utf-8")
        self.assertIn(f"group: {_GROUP_VIGIA}", texto)
        self.assertNotIn(f"group: {_GROUP_TOKEN}", texto)
        self.assertIn("cancel-in-progress: false", texto)

    def test_push_main_tem_fila_propria_e_nao_dispara_pos_ci(self):
        path = WORKFLOWS_DIR / "push_main_rotinas.yml"
        texto = path.read_text(encoding="utf-8")
        self.assertIn(f"group: {_GROUP_PUSH_MAIN}", texto)
        self.assertNotIn(f"group: {_GROUP_TOKEN}", texto)
        self.assertIn("workflow_dispatch:", texto)
        self.assertNotIn("workflow_run:", texto)
        self.assertIn("cancel-in-progress: false", texto)

    def test_monitores_secundarios_tem_fila_propria(self):
        for nome in _WORKFLOWS_MONITOR_SECUNDARIO:
            path = WORKFLOWS_DIR / nome
            self.assertTrue(path.is_file(), f"workflow ausente: {nome}")
            texto = path.read_text(encoding="utf-8")
            self.assertIn(f"group: {_GROUP_SECUNDARIO}", texto, nome)
            self.assertNotIn(f"group: {_GROUP_TOKEN}", texto, nome)
            self.assertIn("cancel-in-progress: false", texto, nome)
            # Sem resumo periódico — só oportunidade nova (acompanhar sem poluir)
            self.assertRegex(
                texto,
                r"(ALERTA_RESUMO|SUMARE_LEILOES_ALERTA_RESUMO):\s*[\"']0[\"']",
                msg=f"{nome} deve desligar resumo periódico",
            )

    def test_vigia_le_heartbeats_compartilhados_sem_regravar(self):
        path = WORKFLOWS_DIR / "vigia_datadog.yml"
        texto = path.read_text(encoding="utf-8")
        self.assertIn("./.github/actions/saude-heartbeats", texto)
        self.assertIn("modo: restore", texto)
        # Não deve regravar heartbeats dos produtores no cache do vigia
        save_bloco = texto.split("Salvar cache vigia")[-1]
        self.assertNotIn("orquestrador_ultimo_ciclo.json", save_bloco)
        self.assertNotIn("saude-heartbeats", save_bloco)
        self.assertIn("datadog_vigia_history.json", save_bloco)

    def test_produtores_publicam_saude_heartbeats(self):
        for nome in (
            "orquestrador_30min.yml",
            "conectividade_marketplaces.yml",
            "operacao_24h_seguranca.yml",
            "renovar_tokens.yml",
            "relatorio_manha_ml.yml",
            "relatorio_estrategia_ml.yml",
            "monitor_mercado_esmaltes.yml",
            "ads_gatilho_ml.yml",
            "sincronizar_estoque.yml",
            "ponto_ruptura_segundo_cnpj.yml",
        ):
            texto = (WORKFLOWS_DIR / nome).read_text(encoding="utf-8")
            self.assertIn("./.github/actions/saude-heartbeats", texto, nome)
            self.assertIn("modo: restore", texto, nome)
            self.assertIn("modo: save", texto, nome)

    def test_nenhum_step_tem_with_duplicado(self):
        """Dois `with:` no mesmo step quebram o workflow em 0s (sem job)."""
        import re

        for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
            with_count = 0
            for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if re.match(r"^      - ", raw):
                    with_count = 0
                elif re.match(r"^        with:", raw):
                    with_count += 1
                    self.assertLessEqual(
                        with_count,
                        1,
                        f"{path.name}:{i} tem `with:` duplicado no mesmo step",
                    )

    def test_agentes_pesados_tem_cron_proprio(self):
        esperados = {
            "inteligencia_precos.yml": "20 */2 * * *",
            "monitor_ml.yml": "15 */2 * * *",
            "monitor_concorrentes_ml.yml": "30 */4 * * *",
            "monitor_sem_venda_ml.yml": "0 13 * * *",
            "monitor_mercado_esmaltes.yml": "0 12 * * *",
        }
        for nome, cron in esperados.items():
            texto = (WORKFLOWS_DIR / nome).read_text(encoding="utf-8")
            self.assertIn("schedule:", texto, nome)
            self.assertIn(cron, texto, nome)
            self.assertNotIn(f"group: {_GROUP_TOKEN}", texto, nome)


if __name__ == "__main__":
    unittest.main()
