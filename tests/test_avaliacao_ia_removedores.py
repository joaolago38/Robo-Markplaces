"""
tests/test_avaliacao_ia_removedores.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.esmaltes.avaliacao_ia_removedores import formatar_secao_ia


class AvaliacaoIaRemovedoresTests(unittest.TestCase):
    def test_formatar_secao_ia(self):
        texto = formatar_secao_ia(
            {
                "resumo_situacao": "Zero resultados — termos longos demais.",
                "segmentos": [
                    {
                        "segmento_id": "cruzeiro",
                        "termo_busca_sugerido": "acetona cruzeiro",
                        "termos_alternativos": ["removedor cruzeiro"],
                        "motivo": "Termo curto",
                        "confianca": "alta",
                    }
                ],
                "alertas": ["API ML pode estar bloqueada"],
            }
        )
        self.assertIn("Claude", texto)
        self.assertIn("acetona cruzeiro", texto)
        self.assertIn("API ML", texto)


if __name__ == "__main__":
    unittest.main()
