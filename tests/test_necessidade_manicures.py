"""tests/test_necessidade_manicures.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.social import necessidade_manicures as nec


class TestNecessidadeCore(unittest.TestCase):
    def test_angulo_atacado(self):
        self.assertEqual(nec._angulo_do_texto("quero kit 10 atacado"), "atacado")

    def test_angulo_kit_entrada(self):
        self.assertEqual(nec._angulo_do_texto("kit 3 mimo manicure"), "kit_entrada")

    @patch.object(nec, "carregar_campanhas")
    @patch.object(nec, "montar_mensagem_campanha")
    @patch.object(nec, "coletar_sinais")
    @patch.object(nec, "_estoque_campanha", return_value=(10, True))
    @patch.object(
        nec,
        "_status_sustentabilidade",
        return_value={"status": "sustentavel", "permitido_impulsionar": True},
    )
    def test_match_link_valido_pode_enviar(
        self, _sust, _est, mock_sinais, mock_montar, mock_camp
    ):
        mock_sinais.return_value = [
            {
                "fonte": "leads",
                "rotulo": "lead:atacado",
                "texto": "quero atacado kit 10",
                "peso": 40,
            }
        ]
        mock_camp.return_value = [
            {"id": "kit-10-atacado-manicure", "nome": "Kit 10", "sku": "IMP-ATAC-010", "ativo": True}
        ]
        mock_montar.return_value = {
            "ok": True,
            "campanha_id": "kit-10-atacado-manicure",
            "campanha_nome": "Kit 10",
            "sku": "IMP-ATAC-010",
            "preco_brl": 69.9,
            "link_ml": "https://produto.mercadolivre.com.br/MLB1234567890",
            "link_valido": True,
            "texto": "Oferta Kit 10",
            "texto_whatsapp": "Oferta Kit 10",
            "texto_telegram": "Oferta Kit 10",
        }
        out = nec.casar_necessidades_com_ml()
        self.assertTrue(out["ok"])
        self.assertTrue(out["pronto_enviar"])
        self.assertEqual(out["escolhida"]["campanha_id"], "kit-10-atacado-manicure")
        self.assertTrue(out["escolhida"]["pode_enviar"])

    @patch.object(nec, "carregar_campanhas")
    @patch.object(nec, "montar_mensagem_campanha")
    @patch.object(nec, "coletar_sinais")
    @patch.object(nec, "_estoque_campanha", return_value=(5, True))
    @patch.object(
        nec,
        "_status_sustentabilidade",
        return_value={"status": "sustentavel", "permitido_impulsionar": True},
    )
    def test_link_invalido_bloqueia_envio(
        self, _sust, _est, mock_sinais, mock_montar, mock_camp
    ):
        mock_sinais.return_value = [
            {"fonte": "tendencias", "rotulo": "nude", "texto": "esmalte nude", "peso": 50}
        ]
        mock_camp.return_value = [{"id": "kit-3", "nome": "Kit 3", "sku": "X", "ativo": True}]
        mock_montar.return_value = {
            "ok": True,
            "campanha_nome": "Kit 3",
            "sku": "X",
            "preco_brl": 44.9,
            "link_ml": "https://x/MLB_PREENCHER",
            "link_valido": False,
            "aviso_link": "placeholder",
            "texto": "t",
            "texto_whatsapp": "t",
        }
        out = nec.casar_necessidades_com_ml()
        self.assertFalse(out["pronto_enviar"])
        self.assertFalse(out["escolhida"]["pode_enviar"])
        self.assertTrue(any("link_invalido" in g for g in out["gaps"]))

    def test_montar_mensagem_gestor(self):
        msg = nec.montar_mensagem_gestor(
            {
                "sinais_lidos": 2,
                "campanhas_avaliadas": 1,
                "sustentabilidade": {"status": "sustentavel", "roas_real": 3.0},
                "escolhida": {
                    "campanha_id": "kit-3",
                    "campanha_nome": "Kit 3",
                    "score": 70,
                    "pode_enviar": False,
                    "sinal": {"fonte": "leads", "rotulo": "preco"},
                    "condicoes": {
                        "angulo": "kit_entrada",
                        "cta": "teste",
                        "obs_estoque": "estoque=0",
                    },
                    "aviso_link": "preencher MLB",
                },
                "matches": [],
                "gaps": ["link_invalido:kit-3"],
            }
        )
        self.assertIn("Necessidade manicures", msg)
        self.assertIn("Kit 3", msg)
        self.assertIn("preencher MLB", msg)


class TestAgenteNecessidade(unittest.TestCase):
    @patch("agentes.social.agente_necessidade_manicures.escrever_json_atomico")
    @patch("agentes.social.agente_necessidade_manicures.alertar_gestor", return_value=True)
    @patch("agentes.social.agente_necessidade_manicures.casar_necessidades_com_ml")
    @patch("agentes.social.agente_necessidade_manicures.NECESSIDADE_MANICURES_ATIVO", True)
    @patch("agentes.social.agente_necessidade_manicures.NECESSIDADE_MANICURES_ALERTA", True)
    def test_executar_dry(self, mock_plano, _alert, _write):
        from agentes.social import agente_necessidade_manicures as ag

        mock_plano.return_value = {
            "ok": True,
            "sinais_lidos": 1,
            "pronto_enviar": False,
            "sustentabilidade": {"status": "insuficiente_dados"},
            "escolhida": {
                "campanha_id": "kit-3",
                "campanha_nome": "Kit 3",
                "score": 10,
                "pode_enviar": False,
                "condicoes": {"angulo": "geral", "cta": "x", "obs_estoque": "n/d"},
                "sinal": {"fonte": "leads", "rotulo": "interesse"},
            },
            "matches": [],
            "gaps": ["link_invalido:kit-3"],
        }
        out = ag.executar(enviar=False, enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["envios"]["motivo"], "dry_run")


if __name__ == "__main__":
    unittest.main()
