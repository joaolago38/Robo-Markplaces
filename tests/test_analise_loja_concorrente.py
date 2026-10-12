"""
tests/test_analise_loja_concorrente.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.ml import analise_loja_concorrente as al


class AnaliseLojaTests(unittest.TestCase):
    @patch.object(al, "buscar_perfil_loja", return_value={
        "ok": True,
        "seller_id": "1666381510",
        "nickname": "NOVAMIX_COMERCIAL",
        "level_id": "5_green",
        "power_seller_status": "platinum",
        "transactions_total": 71423,
        "cidade": "São Paulo",
        "estado": "BR-SP",
    })
    @patch.object(al, "coletar_anuncios_loja", return_value=[
        {
            "item_id": "MLB1",
            "titulo": "Kit 5 Esmaltes Impala Bailarina",
            "preco": 42.0,
            "quantidade_vendida": 10,
            "seller_id": "1666381510",
            "marcas": ["impala"],
        }
    ])
    @patch.object(al, "_comparar_com_catalogo", return_value=[
        {
            "sku": "IMP-BAIL-005",
            "nome": "Kit 5 Bailarina",
            "meu_preco": 48.9,
            "menor_preco_loja": 42.0,
            "gap_pct": 16.4,
            "anuncios_loja": 1,
            "amostra": [],
        }
    ])
    @patch(
        "integracoes.ml.analise_anuncio_concorrente.enriquecer_lista",
        side_effect=lambda xs, **kw: xs,
    )
    def test_analisar_loja(self, *_):
        out = al.analisar_loja("1666381510", nickname="NOVAMIX_COMERCIAL")
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_anuncios_coletados"], 1)
        self.assertEqual(out["preco_min"], 42.0)
        self.assertEqual(len(out["ameacas_preco"]), 1)
        msg = al.montar_mensagem_analise(out)
        self.assertIn("NOVAMIX", msg)
        self.assertIn("platinum", msg.lower() or "Platinum" in msg or "Líder" in msg)

    def test_filtrar_seller_em_coleta(self):
        rows = [
            {
                "item_id": "A",
                "titulo": "Kit Impala",
                "preco": 40,
                "seller_id": "1666381510",
                "fonte_busca": "products_api",
            },
            {
                "item_id": "B",
                "titulo": "Kit Impala",
                "preco": 39,
                "seller_id": "999",
                "fonte_busca": "products_api",
            },
        ]
        with patch.object(al.ml_client, "_enabled", return_value=True), patch.object(
            al.ml_client, "hidratar_itens", return_value=[]
        ), patch.object(
            al.ml_client, "listar_ids_anuncios_vendedor", return_value=[]
        ), patch(
            "integracoes.ml.busca_termo_ml._buscar_via_products_api", return_value=rows
        ):
            out = al.coletar_anuncios_loja("1666381510", termos=["kit impala"], limite_por_termo=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["item_id"], "A")

    def test_coleta_prioriza_item_ids(self):
        hidratado = [
            {
                "item_id": "MLB1234567",
                "titulo": "Kit Impala Novamix",
                "preco": 41.0,
                "seller_id": "1666381510",
                "quantidade_vendida": 8,
                "permalink": "https://mlb/MLB1234567",
                "fonte_busca": "items_ids",
            }
        ]
        with patch.object(al.ml_client, "_enabled", return_value=True), patch.object(
            al.ml_client, "hidratar_itens", return_value=hidratado
        ) as mock_hid, patch.object(
            al.ml_client, "listar_ids_anuncios_vendedor"
        ) as mock_loja, patch(
            "integracoes.ml.busca_termo_ml._buscar_via_products_api"
        ) as mock_prod:
            out = al.coletar_anuncios_loja(
                "1666381510",
                termos=["NOVAMIX_COMERCIAL esmalte"],
                item_ids=["MLB1234567"],
                limite_por_termo=5,
            )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["item_id"], "MLB1234567")
        mock_hid.assert_called()
        mock_loja.assert_not_called()
        mock_prod.assert_not_called()

    @patch.object(al, "buscar_perfil_loja", return_value={"ok": True, "nickname": "NOVAMIX_COMERCIAL"})
    @patch.object(al, "coletar_anuncios_loja", return_value=[])
    @patch.object(al, "_comparar_com_catalogo", return_value=[])
    def test_analisar_loja_nao_busca_nickname(self, _cmp, mock_coletar, _perfil):
        al.analisar_loja(
            "1666381510",
            nickname="NOVAMIX_COMERCIAL",
            termos=["kit esmalte impala"],
            enriquecer_metricas=False,
        )
        kwargs = mock_coletar.call_args.kwargs
        termos = kwargs.get("termos") or []
        self.assertTrue(all("novamix" not in str(t).lower() for t in termos))
        self.assertEqual(termos, ["kit esmalte impala"])

    def test_montar_mensagem_com_metricas(self):
        msg = al.montar_mensagem_analise(
            {
                "nickname": "NOVAMIX",
                "seller_id": "1",
                "total_anuncios_coletados": 1,
                "preco_min": 30.0,
                "preco_med": 30.0,
                "preco_max": 30.0,
                "marcas": {"impala": 1},
                "ameacas_preco": [],
                "perfil": {
                    "level_id": "5_green",
                    "power_seller_status": "platinum",
                    "transactions_total": 10,
                    "cidade": "SP",
                    "estado": "BR-SP",
                },
                "estrategia": {
                    "porte": "grande",
                    "ameaca_geral": "alta",
                    "pontos_fortes_loja": ["Líder"],
                    "implicacoes_para_voce": ["Diferencie"],
                },
                "anuncios": [
                    {
                        "titulo": "Kit Bailarina",
                        "metricas": {
                            "preco": 30.99,
                            "nota": 4.9,
                            "avaliacoes": 10,
                            "receita_liquida_un": 25.0,
                        },
                    }
                ],
            }
        )
        self.assertIn("NOVAMIX", msg)
        self.assertIn("Amostra métricas", msg)
        self.assertIn("Bailarina", msg)

    def test_comparar_com_catalogo(self):
        with patch(
            "core.catalogo_produtos.carregar_produtos_catalogo",
            return_value=[
                {
                    "sku": "IMP-BAIL-005",
                    "nome": "Kit 5 Bailarina Impala",
                    "canais": {"mercadolivre": {"preco": 48.9}},
                }
            ],
        ):
            overlaps = al._comparar_com_catalogo(
                [
                    {
                        "titulo": "Kit 5 Esmaltes Impala Bailarina",
                        "preco": 30.0,
                        "item_id": "MLB1",
                    }
                ]
            )
        self.assertEqual(len(overlaps), 1)
        self.assertEqual(overlaps[0]["sku"], "IMP-BAIL-005")
        self.assertGreater(overlaps[0]["gap_pct"], 0)

    @patch.object(al.ml_client, "_enabled", return_value=True)
    @patch.object(al.ml_client, "_h", return_value={})
    @patch.object(al, "request")
    def test_buscar_perfil_loja(self, mock_req, *_):
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {
            "nickname": "NOVAMIX_COMERCIAL",
            "permalink": "http://x",
            "address": {"city": "São Paulo", "state": "BR-SP"},
            "status": {"site_status": "active"},
            "seller_reputation": {
                "level_id": "5_green",
                "power_seller_status": "platinum",
                "transactions": {"total": 100},
            },
        }
        out = al.buscar_perfil_loja("1666381510")
        self.assertTrue(out["ok"])
        self.assertEqual(out["nickname"], "NOVAMIX_COMERCIAL")
        self.assertEqual(out["power_seller_status"], "platinum")

    def test_analise_estrategica(self):
        e = al._analise_estrategica(
            {"transactions_total": 70000, "power_seller_status": "platinum", "level_id": "5_green"},
            [{"preco": 30}],
            [{"sku": "X", "gap_pct": 10}],
        )
        self.assertEqual(e["porte"], "gigante")
        self.assertEqual(e["ameaca_geral"], "alta")
        self.assertIn("X", e["skus_sob_pressao"])


if __name__ == "__main__":
    unittest.main()
