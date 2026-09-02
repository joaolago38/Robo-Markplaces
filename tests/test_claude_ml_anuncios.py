"""tests/test_claude_ml_anuncios.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.claude_ml import anuncios as an
from core.claude_ml import estado as est


class TestClaudeMlAnuncios(unittest.TestCase):
    def test_placeholder_nao_conta_como_publicado(self):
        linha = an.compactar_linha(sku="IMP-MIMO-003", mlb="MLB_PREENCHER", titulo="Kit")
        self.assertFalse(linha["publicado"])
        self.assertEqual(linha["sku"], "IMP-MIMO-003")

    def test_mlb_valido_publicado(self):
        linha = an.compactar_linha(sku="X", mlb="MLB1234567890", titulo="Kit", preco=39.9)
        self.assertTrue(linha["publicado"])
        self.assertEqual(linha["mlb"], "MLB1234567890")

    def test_mesclar_prioriza_api_sobre_catalogo(self):
        vivo = [an.compactar_linha(sku="K1", mlb="MLB111", titulo="Ao vivo", preco=40, fonte="api")]
        cat = [an.compactar_linha(sku="K1", mlb="MLB_PREENCHER", titulo="Catalogo", preco=39.9, fonte="catalogo")]
        out = an.mesclar_linhas(vivo, cat)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["publicado"])
        self.assertEqual(out[0]["titulo"], "Ao vivo")

    def test_bloco_catalogo_e_resumo(self):
        with patch.object(
            an,
            "linhas_catalogo_ml",
            return_value=[an.compactar_linha(sku="A", mlb="MLB_PREENCHER", titulo="A")],
        ):
            bloco = an.bloco_anuncios_ml(
                resumo_conta={
                    "anuncios_amostra": [
                        {"item_id": "MLB999888777", "titulo": "Kit vivo", "preco": 44.9, "vendidos": 3, "status": "active"}
                    ]
                },
                ao_vivo=False,
            )
        self.assertGreaterEqual(bloco["total"], 2)
        self.assertGreaterEqual(bloco["publicados"], 1)
        self.assertGreaterEqual(bloco["pendente_mlb"], 1)
        ids = {i.get("mlb") for i in bloco["itens"] if i.get("publicado")}
        self.assertIn("MLB999888777", ids)

    def test_estado_inclui_anuncios(self):
        with patch.object(est, "_snapshot", return_value={}), patch(
            "core.claude_ml.anuncios.bloco_anuncios_ml",
            return_value={
                "total": 2,
                "publicados": 1,
                "pendente_mlb": 1,
                "fonte": "catalogo",
                "itens": [{"sku": "X", "publicado": False}],
            },
        ):
            out = est.carregar_estado_ml(ao_vivo=False)
        self.assertEqual(out["anuncios"]["total"], 2)
        self.assertTrue(any("sem MLB" in a for a in out["alertas"]))


if __name__ == "__main__":
    unittest.main()
