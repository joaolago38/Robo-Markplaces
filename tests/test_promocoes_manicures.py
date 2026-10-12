"""
tests/test_promocoes_manicures.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.social import promocoes_manicures as pm

_PRODUTO = {
    "sku": "IMP-MIMO-003",
    "nome": "Kit 3 Mimo + Carmed Impala",
    "preco": 44.9,
    "canais": {
        "mercadolivre": {
            "ativo": True,
            "preco": 44.9,
            "item_id": "MLB1234567890",
            "titulo_anuncio": "Kit Impala Mimo",
        }
    },
}


class PromocoesManicuresTests(unittest.TestCase):
    @patch.object(pm, "carregar_produtos_catalogo", return_value=[_PRODUTO])
    def test_montar_mensagem_ok(self, *_):
        campanha = {
            "id": "kit-3",
            "sku": "IMP-MIMO-003",
            "preco_de": 52.9,
            "template": "*{produto}* R$ {preco} — {link}",
        }
        out = pm.montar_mensagem_campanha(campanha)
        self.assertTrue(out["ok"])
        self.assertIn("44,90", out["texto"])
        self.assertIn("MLB1234567890", out["link_ml"])
        self.assertNotIn("*", out["texto_whatsapp"])

    @patch.object(pm, "carregar_produtos_catalogo", return_value=[])
    def test_montar_mensagem_sku_inexistente(self, *_):
        out = pm.montar_mensagem_campanha({"id": "x", "sku": "NAO-EXISTE", "template": "{produto}"})
        self.assertFalse(out["ok"])
        self.assertIn("sku não encontrado", out["motivo"])

    def test_escolher_campanha_rotacao(self):
        campanhas = [
            {"id": "a", "prioridade": 1},
            {"id": "b", "prioridade": 2},
            {"id": "c", "prioridade": 3},
        ]
        self.assertEqual(pm.escolher_campanha(campanhas, ultimo_id=None)["id"], "a")
        self.assertEqual(pm.escolher_campanha(campanhas, ultimo_id="a")["id"], "b")
        self.assertEqual(pm.escolher_campanha(campanhas, ultimo_id="c")["id"], "a")

    @patch.object(pm, "ler_json", return_value=[{"id": "c1", "ativo": True}])
    def test_carregar_campanhas_ativas(self, *_):
        with patch.object(pm, "ROOT", pm.ROOT):
            out = pm.carregar_campanhas()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "c1")

    def test_campanhas_liberadas_fase_0_so_mimo(self):
        camps = [
            {"id": "mimo", "fase_minima": 0},
            {"id": "perl", "fase_minima": 1},
            {"id": "sort", "fase_minima": 2},
        ]
        lib = pm.campanhas_liberadas(camps, fase=0)
        self.assertEqual([c["id"] for c in lib], ["mimo"])
        self.assertEqual([c["id"] for c in pm.campanhas_liberadas(camps, fase=1)], ["mimo", "perl"])

    def test_link_ml_rejeita_mlb_curto(self):
        self.assertFalse(pm.link_ml_valido("https://produto.mercadolivre.com.br/MLB-123"))
        self.assertTrue(pm.link_ml_valido("https://produto.mercadolivre.com.br/MLB1234567890"))


class AgentePromocoesManicuresTests(unittest.TestCase):
    @patch("agentes.social.agente_promocoes_manicures.alertar_gestor", return_value=True)
    @patch("agentes.social.agente_promocoes_manicures.gestor_telegram_configurado", return_value=True)
    @patch("agentes.social.agente_promocoes_manicures.pode_divulgar_promocoes_manicures", return_value=(True, "ok"))
    @patch("agentes.social.agente_promocoes_manicures.campanhas_liberadas")
    @patch("agentes.social.agente_promocoes_manicures._montar_com_fallback")
    def test_sem_mlb_pula_sem_falhar(self, mock_montar, mock_camps, *_):
        from agentes.social import agente_promocoes_manicures as ag

        mock_camps.return_value = [{"id": "kit-3", "ativo": True}]
        mock_montar.return_value = {
            "ok": False,
            "motivo": "sem_mlb_publicado",
            "pulado_esperado": True,
            "tentativas": [{"id": "kit-3", "ok": False, "motivo": "contrato:link_mlb_invalido"}],
        }
        out = ag.executar(enviar=False)
        self.assertTrue(out["ok"])
        self.assertTrue(out.get("pulado"))
        self.assertEqual(out.get("motivo"), "sem_mlb_publicado")
        self.assertEqual(ag.main(["--sem-envio"]), 0)


if __name__ == "__main__":
    unittest.main()
