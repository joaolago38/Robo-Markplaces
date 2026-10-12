"""
tests/test_comparativo_ml_shopee.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.comparativo import agente_comparativo_ml_shopee as agente
from integracoes.comparativo import ml_shopee_categorias as cmp


def _anuncio(mp: str, preco: float, vendidos: int = 0, titulo: str = "Item") -> dict:
    return {
        "marketplace": mp,
        "titulo": titulo,
        "preco": preco,
        "quantidade_vendida": vendidos,
        "permalink": f"https://example.com/{mp}/{titulo}",
        "fonte_busca": "teste",
    }


class TestMlShopeeCategorias(unittest.TestCase):
    def test_analisar_termo_ml_vence_com_vendas(self):
        anuncios = [
            _anuncio("mercadolivre", 29.9, vendidos=200, titulo="Kit esmalte ML"),
            _anuncio("mercadolivre", 34.9, vendidos=80, titulo="Kit esmalte ML 2"),
            _anuncio("shopee", 24.9, vendidos=0, titulo="Kit esmalte SP"),
            _anuncio("shopee", 27.0, vendidos=0, titulo="Kit esmalte SP 2"),
        ]
        out = cmp.analisar_termo(
            {"id": "t1", "categoria": "esmalte", "nome": "Kit", "termo_busca": "kit"},
            anuncios,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["vencedor"], "mercadolivre")
        self.assertGreater(out["scores"]["mercadolivre"], out["scores"]["shopee"])
        self.assertFalse(out["por_marketplace"]["mercadolivre"]["volume_eh_proxy"])
        self.assertTrue(out["por_marketplace"]["shopee"]["volume_eh_proxy"])

    def test_analisar_termo_shopee_vence_por_densidade(self):
        anuncios = [
            _anuncio("mercadolivre", 90.0, vendidos=0, titulo="PLA ML"),
            _anuncio("shopee", 55.0, vendidos=0, titulo="PLA SP 1"),
            _anuncio("shopee", 58.0, vendidos=0, titulo="PLA SP 2"),
            _anuncio("shopee", 52.0, vendidos=0, titulo="PLA SP 3"),
            _anuncio("shopee", 50.0, vendidos=0, titulo="PLA SP 4"),
        ]
        out = cmp.analisar_termo(
            {"id": "t2", "categoria": "filamento", "nome": "PLA", "termo_busca": "pla"},
            anuncios,
        )
        self.assertEqual(out["vencedor"], "shopee")

    def test_consolidar_categoria_e_geral(self):
        t1 = cmp.analisar_termo(
            {"id": "a", "categoria": "esmalte", "nome": "A", "termo_busca": "a"},
            [
                _anuncio("mercadolivre", 30, 100),
                _anuncio("shopee", 28, 0),
            ],
        )
        t2 = cmp.analisar_termo(
            {"id": "b", "categoria": "esmalte", "nome": "B", "termo_busca": "b"},
            [
                _anuncio("mercadolivre", 32, 50),
                _anuncio("shopee", 31, 0),
            ],
        )
        cat = cmp.consolidar_categoria([t1, t2])
        self.assertTrue(cat["ok"])
        self.assertEqual(cat["categoria"], "esmalte")
        self.assertEqual(cat["termos"], 2)

        geral = cmp.consolidar_geral([cat])
        self.assertTrue(geral["ok"])
        self.assertIn(geral["vencedor_global"], ("mercadolivre", "shopee", "empate"))
        self.assertIn("proxy", geral["nota_metodologica"].lower())

    def test_gerar_recomendacoes(self):
        consolidado = {
            "ok": True,
            "vencedor_global": "mercadolivre",
            "categorias": [
                {
                    "categoria": "filamento",
                    "vencedor": "mercadolivre",
                    "por_marketplace": {
                        "mercadolivre": {"vendidos": 120, "anuncios": 5, "score": 0.8},
                        "shopee": {
                            "vendidos": 0,
                            "anuncios": 8,
                            "score": 0.5,
                            "volume_eh_proxy": True,
                        },
                    },
                }
            ],
        }
        recs = cmp.gerar_recomendacoes(consolidado)
        self.assertTrue(recs)
        self.assertTrue(any("Mercado Livre" in r for r in recs))

    def test_filtrar_pedidos_por_categoria(self):
        pedidos = [
            {"order_id": "1", "total": 50, "itens": [{"sku": "ESM-ANITA-01"}]},
            {"order_id": "2", "total": 80, "itens": [{"sku": "FIL-PLA-1KG"}]},
            {"order_id": "3", "total": 10, "itens": [{"sku": "OUTRO"}]},
        ]
        esm = cmp.filtrar_pedidos_por_categoria(pedidos, "esmalte")
        fil = cmp.filtrar_pedidos_por_categoria(pedidos, "filamento")
        self.assertEqual(len(esm), 1)
        self.assertEqual(len(fil), 1)

    def test_resumir_pedidos_proprios(self):
        out = cmp.resumir_pedidos_proprios(
            pedidos_ml=[{"order_id": "m1", "total": 40, "itens": [{"sku": "esmalte-kit"}]}],
            pedidos_shopee=[{"order_id": "s1", "total": 90, "itens": [{"sku": "filamento-pla"}]}],
            categorias=["esmalte", "filamento"],
        )
        self.assertTrue(out["tem_dados"])
        self.assertEqual(out["mercadolivre"]["pedidos"], 1)
        self.assertEqual(out["shopee"]["pedidos"], 1)
        self.assertEqual(out["por_categoria"]["esmalte"]["vencedor"], "mercadolivre")
        self.assertEqual(out["por_categoria"]["filamento"]["vencedor"], "shopee")


class TestAgenteComparativoMlShopee(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_montar_painel_contem_proxy_e_marketplaces(self):
        consolidado = {
            "ok": True,
            "vencedor_global": "mercadolivre",
            "scores_globais": {"mercadolivre": 0.82, "shopee": 0.55},
            "vitorias_categoria": {"mercadolivre": 2, "shopee": 0},
            "empates_categoria": 0,
            "nota_metodologica": "Shopee competitiva não expõe quantidade vendida neste robô.",
            "categorias": [
                {
                    "categoria": "esmalte",
                    "vencedor": "mercadolivre",
                    "por_marketplace": {
                        "mercadolivre": {
                            "label": "Mercado Livre",
                            "score": 0.8,
                            "anuncios": 10,
                            "preco_mediana": 29.9,
                            "vendidos": 150,
                            "volume_eh_proxy": False,
                        },
                        "shopee": {
                            "label": "Shopee",
                            "score": 0.5,
                            "anuncios": 12,
                            "preco_mediana": 24.0,
                            "vendidos": 0,
                            "volume_sinal": 8.0,
                            "volume_eh_proxy": True,
                        },
                    },
                }
            ],
        }
        msg = agente._montar_painel(
            consolidado,
            ["Priorize estoque e ads no Mercado Livre."],
            {
                "tem_dados": True,
                "mercadolivre": {"pedidos": 2, "receita": 100},
                "shopee": {"pedidos": 1, "receita": 40},
                "por_categoria": {
                    "esmalte": {
                        "mercadolivre": {"pedidos": 2},
                        "shopee": {"pedidos": 0},
                    }
                },
            },
        )
        self.assertIn("Mercado Livre", msg)
        self.assertIn("Shopee", msg)
        self.assertIn("proxy", msg.lower())
        self.assertIn("Suas vendas", msg)
        self.assertIn("Recomendações", msg)

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "_coletar_pedidos_proprios")
    @patch.object(agente, "buscar_todos_marketplaces")
    @patch.object(agente, "_carregar_segmentos")
    def test_executar_fluxo(self, mock_seg, mock_busca, mock_pedidos, mock_alertar):
        mock_seg.return_value = [
            {
                "id": "cmp-esmalte-kit5",
                "ativo": True,
                "categoria": "esmalte",
                "nome": "Kit 5",
                "termo_busca": "kit 5 esmaltes",
                "limite_resultados": 10,
                "prioridade": 1,
            },
            {
                "id": "cmp-filamento-pla",
                "ativo": True,
                "categoria": "filamento",
                "nome": "PLA",
                "termo_busca": "filamento pla",
                "limite_resultados": 10,
                "prioridade": 1,
            },
        ]
        mock_busca.return_value = [
            _anuncio("mercadolivre", 30, 40),
            _anuncio("shopee", 25, 0),
        ]
        mock_pedidos.return_value = {
            "ok": True,
            "tem_dados": False,
            "mercadolivre": {"pedidos": 0, "receita": 0},
            "shopee": {"pedidos": 0, "receita": 0},
            "por_categoria": {},
        }
        with patch.object(agente, "HISTORY_PATH", self.tmp_path / "hist.json"), patch.object(
            agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"
        ), patch.object(agente, "COMPARATIVO_ML_SHOPEE_PAUSA_SEG", 0), patch.object(
            agente, "COMPARATIVO_ML_SHOPEE_ALERTA_RESUMO", True
        ):
            out = agente.executar(enviar_alerta=True)

        self.assertTrue(out["ok"])
        self.assertEqual(out["total_segmentos"], 2)
        self.assertTrue(out["alerta_enviado"])
        mock_alertar.assert_called_once()
        msg = mock_alertar.call_args[0][0]
        self.assertIn("ML × Shopee", msg)
        self.assertIn("proxy", msg.lower())

    @patch.object(agente, "_carregar_segmentos", return_value=[])
    def test_sem_segmentos(self, _):
        out = agente.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_segmentos"], 0)


if __name__ == "__main__":
    unittest.main()
