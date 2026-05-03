"""
tests/test_ads_confirmacao.py
Testa o fluxo de confirmação antes de acionar ads.
"""
import unittest
from unittest.mock import patch

from agentes.ml.agente_ads_gatilho import avaliar_momento_ads


class TestAdsConfirmacao(unittest.TestCase):

    @patch("agentes.ml.agente_ads_gatilho.perguntar_gestor_e_aguardar", return_value=True)
    @patch("agentes.ml.agente_ads_gatilho.alertar_gestor")
    def test_ligar_ads_gestor_aprova(self, mock_alerta, mock_pergunta):
        """Gestor aprova: decisão deve permanecer 'ligar' e confirmado_gestor=True"""
        resultado = avaliar_momento_ads(avaliacoes=25, nota_media=4.9)
        self.assertEqual(resultado["decisao"], "ligar")
        self.assertTrue(resultado["confirmado_gestor"])
        mock_pergunta.assert_called_once()

    @patch("agentes.ml.agente_ads_gatilho.perguntar_gestor_e_aguardar", return_value=False)
    @patch("agentes.ml.agente_ads_gatilho.alertar_gestor")
    def test_ligar_ads_gestor_recusa(self, mock_alerta, mock_pergunta):
        """Gestor recusa: decisão deve virar 'aguardar' e confirmado_gestor=False"""
        resultado = avaliar_momento_ads(avaliacoes=25, nota_media=4.9)
        self.assertEqual(resultado["decisao"], "aguardar")
        self.assertFalse(resultado["confirmado_gestor"])

    @patch("agentes.ml.agente_ads_gatilho.perguntar_gestor_e_aguardar", return_value=True)
    @patch("agentes.ml.agente_ads_gatilho.alertar_gestor")
    def test_pausar_ads_gestor_aprova(self, mock_alerta, mock_pergunta):
        """ACOS alto + gestor aprova: decisão permanece 'pausar'"""
        resultado = avaliar_momento_ads(avaliacoes=30, nota_media=4.9, acos_atual=0.30)
        self.assertEqual(resultado["decisao"], "pausar")
        self.assertTrue(resultado["confirmado_gestor"])

    @patch("agentes.ml.agente_ads_gatilho.perguntar_gestor_e_aguardar", return_value=False)
    @patch("agentes.ml.agente_ads_gatilho.alertar_gestor")
    def test_pausar_ads_gestor_recusa(self, mock_alerta, mock_pergunta):
        """ACOS alto + gestor recusa: decisão vira 'manter'"""
        resultado = avaliar_momento_ads(avaliacoes=30, nota_media=4.9, acos_atual=0.30)
        self.assertEqual(resultado["decisao"], "manter")
        self.assertFalse(resultado["confirmado_gestor"])

    @patch("agentes.ml.agente_ads_gatilho.perguntar_gestor_e_aguardar")
    def test_aguardar_nao_pergunta(self, mock_pergunta):
        """Quando avaliações insuficientes, não deve perguntar ao gestor"""
        resultado = avaliar_momento_ads(avaliacoes=5, nota_media=4.9)
        self.assertEqual(resultado["decisao"], "aguardar")
        mock_pergunta.assert_not_called()


if __name__ == "__main__":
    unittest.main()
