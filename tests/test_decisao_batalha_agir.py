"""tests/test_decisao_batalha_agir.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.esmaltes import decisao_batalha_agir as dba


class TestDecisaoBatalhaAgir(unittest.TestCase):
    def test_revisar_preco_quando_gap_alto(self):
        row = dba.classificar_acao(
            {
                "sku": "KIT-5",
                "gap_pct": 12.0,
                "rivais_no_tam": 3,
                "mlb_ok": True,
                "nosso_preco": 56.0,
                "rival_min": 50.0,
                "papel": "guerra",
                "prio": "p0",
                "kit_tag": "kit:kit-5",
            }
        )
        self.assertEqual(row["acao"], "revisar_preco")
        self.assertTrue(row["critica"])

    def test_listing_quando_preco_ok_muitos_rivais(self):
        row = dba.classificar_acao(
            {
                "sku": "KIT-3",
                "gap_pct": -1.0,
                "rivais_no_tam": 20,
                "mlb_ok": True,
                "papel": "catalogo",
                "prio": "p2",
            }
        )
        self.assertEqual(row["acao"], "melhorar_listing")

    def test_publicar_mlb(self):
        row = dba.classificar_acao(
            {
                "sku": "KIT-X",
                "gap_pct": 5.0,
                "rivais_no_tam": 2,
                "mlb_ok": False,
            }
        )
        self.assertEqual(row["acao"], "publicar_mlb")

    def test_publicar_mlb_sem_gap(self):
        row = dba.classificar_acao({"sku": "IMP-MIMO-003", "mlb_ok": False, "rivais_no_tam": 0})
        self.assertEqual(row["acao"], "publicar_mlb")
        self.assertTrue(row["critica"])

    def test_jupaes_espera_primeiro_pedido(self):
        row = dba.classificar_acao({"sku": "IMP-JUPAES-006", "mlb_ok": False, "rivais_no_tam": 0})
        self.assertEqual(row["acao"], "observar")
        self.assertIn("pedido", row["motivo"].lower())
        self.assertFalse(row["critica"])

    def test_quarto_sku_nao_publica_na_frente(self):
        row = dba.classificar_acao({"sku": "IMP-VR-015", "mlb_ok": False, "rivais_no_tam": 0})
        self.assertEqual(row["acao"], "observar")
        self.assertFalse(row["critica"])

    def test_nao_revisar_preco_com_planilha(self):
        row = dba.classificar_acao(
            {
                "sku": "IMP-PERL-004",
                "gap_pct": -5.0,
                "rivais_no_tam": 0,
                "mlb_ok": True,
                "fonte_rival": "catalogo",
                "nosso_preco": 39.9,
                "rival_min": 42.0,
            }
        )
        self.assertEqual(row["acao"], "observar")
        self.assertIn("planilha", row["motivo"].lower())
        self.assertFalse(row["critica"])

    def test_mimo_com_gap_diferencia_nao_revisa_preco(self):
        row = dba.classificar_acao(
            {
                "sku": "IMP-MIMO-003",
                "gap_pct": 12.0,
                "rivais_no_tam": 3,
                "mlb_ok": True,
                "fonte_rival": "ao_vivo",
                "nosso_preco": 44.9,
                "rival_min": 40.0,
                "papel": "entrada",
                "prio": "p0",
            }
        )
        self.assertEqual(row["acao"], "melhorar_listing")
        self.assertFalse(row["critica"])

    @patch.object(dba, "gauge")
    @patch.object(dba, "incrementar")
    def test_gerar_e_emitir(self, mock_inc, mock_gauge):
        batalha = {
            "anuncios_unicos": 10,
            "sellers_unicos": 4,
            "nossos_acima_rival": 1,
            "comparacoes": [
                {
                    "sku": "A",
                    "gap_pct": 10,
                    "rivais_no_tam": 2,
                    "mlb_ok": True,
                    "nosso_preco": 55,
                    "rival_min": 50,
                    "papel": "guerra",
                    "prio": "p0",
                    "kit_tag": "kit:a",
                },
                {
                    "sku": "B",
                    "gap_pct": 0,
                    "rivais_no_tam": 1,
                    "mlb_ok": True,
                    "papel": "catalogo",
                    "prio": "p3",
                    "kit_tag": "kit:b",
                },
            ],
        }
        out = dba.processar_agir_batalha(batalha, limite=3)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["criticas"], 1)
        self.assertTrue(out["top"])
        txt = "\n".join(dba.formatar_secao_agir(out))
        self.assertIn("AGIR hoje", txt)
        mock_gauge.assert_any_call("impala.batalha.agir_preco", 1.0)
        mock_inc.assert_any_call("impala.batalha.agir_rodadas")


if __name__ == "__main__":
    unittest.main()
