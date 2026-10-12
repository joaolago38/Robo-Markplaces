"""tests/test_contexto_playbook_operacao.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.ml.contexto_playbook_operacao import montar_contexto_operacao


class TestContextoPlaybookOperacao(unittest.TestCase):
    def test_vazio_nao_inventa_joompulse(self):
        with patch(
            "integracoes.ml.contexto_playbook_operacao.ler_json",
            side_effect=lambda path, default=None: [] if "concorrentes_monitorados" in str(path) else {},
        ):
            with patch(
                "integracoes.ml.coleta_demanda_ml.calcular_tendencia_demanda",
                return_value={"tendencia": "indeterminado", "motivo": "historico insuficiente"},
            ):
                out = montar_contexto_operacao()
        self.assertFalse(out["fontes"]["joompulse"])
        self.assertEqual(out["termos_monitorados"], [])
        self.assertIn("JoomPulse", out["fontes"]["aviso"])

    def test_faixas_e_buybox(self):
        lista = [
            {
                "id": "kit",
                "ativo": True,
                "nome": "Kit",
                "termo_busca": "kit impala",
                "meu_preco": 44.9,
                "custo_unitario": 28.13,
            }
        ]
        hist = {"kit": {"menor_preco": 30.0, "total_concorrentes": 4, "amostra_cega": False}}
        buy = {"MLB41490081": {"snapshots": [{"vencedor_atual": {"seller_id": "1", "preco": 28.9}}]}}

        def _ler(path, default=None):
            p = str(path)
            if "concorrentes_monitorados" in p:
                return lista
            if "concorrentes_ml_history" in p:
                return hist
            if "buybox" in p:
                return buy
            return {}

        with patch("integracoes.ml.contexto_playbook_operacao.ler_json", side_effect=_ler):
            with patch(
                "integracoes.ml.coleta_demanda_ml.calcular_tendencia_demanda",
                return_value={"tendencia": "alta", "variacao_pct": 10, "confiabilidade": "baixa"},
            ):
                out = montar_contexto_operacao()
        self.assertEqual(out["termos_monitorados"][0]["tendencia_demanda"]["tendencia"], "alta")
        self.assertGreaterEqual(out["faixas_preco"]["n_pontos"], 2)
        self.assertEqual(out["buybox"][0]["catalog_product_id"], "MLB41490081")


if __name__ == "__main__":
    unittest.main()
