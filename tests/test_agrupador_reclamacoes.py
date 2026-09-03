"""tests/test_agrupador_reclamacoes.py"""
from __future__ import annotations

import unittest

from integracoes.ml.agrupador_reclamacoes import (
    agrupar_padroes_reclamacao,
    emitir_metricas_reclamacao,
)


class TestAgrupadorReclamacoes(unittest.TestCase):
    def test_tres_padroes_repetidos(self):
        avaliacoes = [
            {"texto": "Demorou muito a entrega", "nota_estrelas": 2},
            {"texto": "Atraso de uma semana", "nota_estrelas": 1},
            {"texto": "Demorou e ainda veio quebrado", "nota_estrelas": 2},
            {"texto": "Frasco chegou vazando", "nota_estrelas": 3},
            {"texto": "Vazando na caixa", "nota_estrelas": 2},
            {"texto": "Produto ótimo", "nota_estrelas": 5},
        ]
        perguntas = [
            {"texto": "Veio quebrado o vidro?"},
            {"texto": "Tamanho errado do kit?"},
        ]
        out = agrupar_padroes_reclamacao(avaliacoes, perguntas)
        ids = {r["padrao"]: r["frequencia"] for r in out}
        self.assertEqual(ids["atraso"], 3)
        self.assertEqual(ids["quebrado"], 2)
        self.assertEqual(ids["vazando"], 2)
        self.assertEqual(ids["tamanho_errado"], 1)
        self.assertLessEqual(len(out[0]["exemplos"]), 3)
        self.assertNotIn("falso_copia", ids)

    def test_ignora_avaliacao_positiva(self):
        out = agrupar_padroes_reclamacao(
            [{"texto": "demorou mas gostei", "nota_estrelas": 5}],
            [],
        )
        self.assertEqual(out, [])

    def test_vazio(self):
        self.assertEqual(agrupar_padroes_reclamacao([], []), [])

    def test_emitir_metricas_reclamacao(self):
        from unittest.mock import patch

        with patch("integracoes.ml.agrupador_reclamacoes.gauge") as mock_g:
            emitir_metricas_reclamacao(
                [{"padrao": "atraso", "frequencia": 3}],
                tags=["produto:imp-mimo-003"],
            )
        nomes = [c.args[0] for c in mock_g.call_args_list]
        self.assertIn("reclamacao.total", nomes)
        self.assertIn("reclamacao.frequencia", nomes)


if __name__ == "__main__":
    unittest.main()
