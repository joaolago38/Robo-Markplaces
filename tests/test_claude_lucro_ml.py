"""tests/test_claude_lucro_ml.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.esmaltes import claude_lucro_ml as cl


class TestMomentoLucroMl(unittest.TestCase):
    def test_candidato_com_margem_e_momento(self):
        out = cl.momento_lucro_ml(
            produtos={
                "candidatos_margem": [
                    {"sku": "IMP-PERL-004", "margem_real_pct": 16.26, "bloqueios": ["sem_mlb"]}
                ]
            }
        )
        self.assertTrue(out["momento"])
        self.assertEqual(out["sku_lucro"], "IMP-PERL-004")
        self.assertGreaterEqual(out["margem_pct"], 15.0)

    def test_sem_sku_nao_e_momento(self):
        out = cl.momento_lucro_ml(produtos={"candidatos_margem": []}, kits_manicure={})
        self.assertFalse(out["momento"])
        self.assertEqual(out["sku_lucro"], "")

    def test_kit_manicure_condicao_ganha(self):
        out = cl.momento_lucro_ml(
            produtos={"candidatos_margem": [{"sku": "IMP-MIMO-003", "margem_real_pct": 19.35}]},
            kits_manicure={
                "ofertas_condicao": [{"sku": "IMP-PERL-004", "margem_pct": 16.26, "condicao_ok": True}]
            },
        )
        self.assertEqual(out["sku_lucro"], "IMP-PERL-004")
        self.assertEqual(out["motivo"], "kit_manicure_condicao")

    @patch("core.resumo_ia.sintetizar_claude", return_value="FAZER: PERL-004. NÃO FAZER: Ads.")
    def test_sintetizar_so_no_momento(self, mock_sint):
        vazio = cl.sintetizar_lucro_ml({}, "fb", momento={"momento": False})
        self.assertEqual(vazio, "")
        mock_sint.assert_not_called()
        txt = cl.sintetizar_lucro_ml(
            {"sku": "IMP-PERL-004"},
            "fb",
            momento={"momento": True, "sku_lucro": "IMP-PERL-004", "margem_pct": 16.26, "piso_pct": 15},
        )
        self.assertIn("FAZER", txt)
        self.assertTrue(mock_sint.call_args.kwargs.get("forcar_chamada"))
        self.assertEqual(mock_sint.call_args.kwargs.get("proposito"), "lucro_ml_ruptura_moderada")


if __name__ == "__main__":
    unittest.main()
