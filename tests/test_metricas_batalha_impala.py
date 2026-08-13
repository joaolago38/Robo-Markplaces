"""tests/test_metricas_batalha_impala.py"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integracoes.esmaltes import metricas_batalha_impala as b


class TestBatalhaImpala(unittest.TestCase):
    def setUp(self):
        self.kits = [
            {
                "item_id": "MLB111",
                "titulo": "Kit 10 Esmaltes Impala Sortidos Atacado",
                "marca": "Impala",
                "qtd_kit": 10,
                "preco": 45.0,
                "quantidade_vendida": 120,
                "seller_id": "S1",
            },
            {
                "item_id": "MLB222",
                "titulo": "Kit 10 Esmaltes Impala Nude",
                "marca": "Impala",
                "qtd_kit": 10,
                "preco": 52.0,
                "quantidade_vendida": 40,
                "seller_id": "S2",
            },
            {
                "item_id": "MLB333",
                "titulo": "Kit 15 Esmaltes Impala Vermelho Rosa",
                "marca": "Impala",
                "qtd_kit": 15,
                "preco": 70.0,
                "quantidade_vendida": 200,
                "seller_id": "S1",
            },
            {
                "item_id": "MLB999",
                "titulo": "Kit 10 Esmaltes Anita",
                "marca": "Anita",
                "qtd_kit": 10,
                "preco": 55.0,
                "quantidade_vendida": 90,
                "seller_id": "S9",
            },
            {
                "item_id": "MLB_PREENCHER",
                "titulo": "Kit Impala placeholder",
                "marca": "Impala",
                "qtd_kit": 5,
                "preco": 40.0,
            },
            {
                "item_id": "MLB444",
                "titulo": "Esmalte Impala Creme (sem marca field)",
                "qtd_kit": 1,
                "preco": "x",
                "quantidade_vendida": 1,
            },
        ]
        self.produtos = [
            {
                "sku": "IMP-SORT-010",
                "prioridade": "P0",
                "nome": "Kit 10 Esmaltes Impala Sortidas",
                "preco": 48.0,
                "preco_ml_mercado": 48.0,
                "cores": [{"nome": f"c{i}"} for i in range(10)],
                "canais": {"mercadolivre": {"preco": 48.0, "item_id": "MLB_PREENCHER"}},
            },
            {
                "sku": "IMP-VR-015",
                "prioridade": "P0",
                "nome": "Kit 15 Esmaltes Impala Vermelho",
                "preco": 69.9,
                "preco_ml_mercado": 72.9,
                "cores": [{"nome": f"c{i}"} for i in range(15)],
                "canais": {"mercadolivre": {"preco": 69.9, "item_id": "MLB12345678"}},
            },
            {
                "sku": "KIT-SEM-NUM",
                "prioridade": "P1",
                "nome": "Kit 12 Esmaltes Clássicos",
                "preco": 54.9,
                "preco_ml_mercado": 59.9,
                "canais": {"mercadolivre": {"preco": 54.9}},
            },
            {
                "sku": "",
                "nome": "sem sku",
            },
            "nao-dict",
        ]
        self.guerra = [
            {"sku": "IMP-SORT-010", "papel": "atacado"},
            {"sku": "IMP-VR-015", "papel": "giro"},
            {"sku": "  ", "papel": "x"},
        ]

    def test_helpers_edge(self):
        self.assertEqual(b._f("x"), 0.0)
        self.assertIsNone(b._qtd_kit({"qtd_kit": "bad"}))
        self.assertIsNone(b._qtd_kit({"qtd_kit": 1}))
        self.assertEqual(b._qtd_nosso_sku({"sku": "X", "nome": "Kit 12 cores"}), 12)
        self.assertIsNone(b._qtd_nosso_sku({"sku": "X", "nome": "unitario"}))
        self.assertTrue(b._eh_impala({"titulo": "Kit Impala sortido", "marca": ""}))

    def test_extrair_so_impala(self):
        out = b.extrair_anuncios_impala(self.kits)
        ids = {x["item_id"] for x in out}
        self.assertIn("MLB111", ids)
        self.assertNotIn("MLB999", ids)
        self.assertNotIn("MLB_PREENCHER", ids)

    @patch("integracoes.esmaltes.metricas_batalha_impala.carregar_skus_guerra")
    @patch("integracoes.esmaltes.metricas_batalha_impala.carregar_produtos_catalogo")
    def test_montar_batalha_gap(self, mock_prod, mock_guerra):
        mock_prod.return_value = self.produtos
        mock_guerra.return_value = self.guerra
        anuncios = b.extrair_anuncios_impala(self.kits)
        bat = b.montar_batalha(
            anuncios_impala=anuncios, produtos=self.produtos, guerra=self.guerra
        )
        self.assertEqual(bat["anuncios_unicos"], 4)
        self.assertEqual(bat["sellers_unicos"], 2)
        by = {c["sku"]: c for c in bat["comparacoes"]}
        self.assertGreater(by["IMP-SORT-010"]["gap_pct"], 0)
        self.assertEqual(by["IMP-SORT-010"]["rivais_no_tam"], 2)
        self.assertEqual(by["IMP-VR-015"]["rivais_no_tam"], 1)
        self.assertEqual(by["KIT-SEM-NUM"]["tam"], 12)

    @patch("integracoes.esmaltes.metricas_batalha_impala.incrementar")
    @patch("integracoes.esmaltes.metricas_batalha_impala.gauge")
    @patch("integracoes.esmaltes.metricas_batalha_impala.carregar_skus_guerra")
    @patch("integracoes.esmaltes.metricas_batalha_impala.carregar_produtos_catalogo")
    def test_emitir(self, mock_prod, mock_guerra, mock_gauge, mock_inc):
        mock_prod.return_value = self.produtos
        mock_guerra.return_value = self.guerra
        out = b.emitir_metricas_batalha_impala(kits_unicos=self.kits)
        self.assertTrue(out["ok"])
        nomes = [c.args[0] for c in mock_gauge.call_args_list]
        self.assertIn("impala.batalha.anuncios_unicos", nomes)
        self.assertIn("impala.batalha.gap_vs_rival_pct", nomes)
        for c in mock_gauge.call_args_list:
            tags = c.kwargs.get("tags") or []
            self.assertFalse(any(str(t).startswith("sku:") for t in tags))
        mock_inc.assert_any_call("impala.batalha.rodadas")

    @patch("integracoes.esmaltes.metricas_batalha_impala.incrementar")
    @patch("integracoes.esmaltes.metricas_batalha_impala.gauge", side_effect=RuntimeError("dd"))
    def test_emitir_erro(self, _g, mock_inc):
        out = b.emitir_metricas_batalha_impala({"anuncios_unicos": 1})
        self.assertFalse(out["ok"])
        mock_inc.assert_any_call("impala.batalha.erro")

    @patch("integracoes.esmaltes.decisao_batalha_agir.processar_agir_batalha", return_value={"criticas": 0, "top": [], "por_acao": {}})
    @patch("integracoes.esmaltes.metricas_batalha_impala.emitir_metricas_batalha_impala")
    @patch("integracoes.esmaltes.metricas_batalha_impala.escrever_json_atomico")
    @patch("integracoes.esmaltes.metricas_batalha_impala.montar_batalha")
    @patch("integracoes.esmaltes.metricas_batalha_impala.extrair_anuncios_impala")
    def test_processar_e_persistir(self, mock_ext, mock_mont, mock_w, mock_emit, mock_agir):
        mock_ext.return_value = [{"item_id": "MLB1"}]
        mock_mont.return_value = {"anuncios_unicos": 1, "comparacoes": []}
        mock_emit.return_value = {"ok": True}
        out = b.processar_e_persistir([{"item_id": "MLB1"}], origem="teste")
        self.assertEqual(out["origem"], "teste")
        self.assertEqual(out["amostra_impala"], 1)
        self.assertGreaterEqual(mock_w.call_count, 1)
        mock_emit.assert_called_once()
        mock_agir.assert_called_once()
        self.assertIn("agir", out)

    @patch("integracoes.esmaltes.metricas_batalha_impala.processar_e_persistir")
    def test_processar_de_snapshot_kits(self, mock_proc):
        mock_proc.return_value = {"ok": True}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "snap.json"
            path.write_text(
                json.dumps({"consolidado": {"kits_unicos": [{"item_id": "MLB1"}]}}),
                encoding="utf-8",
            )
            out = b.processar_de_snapshot_kits(str(path))
        self.assertTrue(out["ok"])
        mock_proc.assert_called_once()
        args = mock_proc.call_args
        self.assertEqual(args.kwargs.get("origem"), "snapshot_kits")

    @patch("integracoes.esmaltes.metricas_batalha_impala.ler_json", return_value=[])
    def test_processar_snapshot_invalido(self, _ler):
        out = b.processar_de_snapshot_kits("logs/x.json")
        self.assertFalse(out["ok"])
        self.assertEqual(out["erro"], "snapshot_invalido")


if __name__ == "__main__":
    unittest.main()
