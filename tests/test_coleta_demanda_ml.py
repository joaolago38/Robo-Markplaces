"""tests/test_coleta_demanda_ml.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.ml import coleta_demanda_ml as cd


class ColetaDemandaMlTests(unittest.TestCase):
    def test_montar_pontos_cegos_marca_vendas_e_busca(self):
        pc = cd.montar_pontos_cegos(
            consolidado={
                "anuncios_com_vendas_api": 0,
                "anuncios_com_avaliacoes": 0,
                "anuncios_com_visitas": 3,
            },
            funil={
                "ok": True,
                "pedidos_ok": True,
                "visitas_ok": True,
                "totais": {"visitas_7d": 100, "unidades_7d": 2, "conversao_pct": 2.0},
            },
            visitas_enriquecidas=3,
            contexto="teste",
        )
        self.assertEqual(pc["ranking_fonte_sugerida"], "visitas")
        ids = {i["id"]: i["status"] for i in pc["itens"]}
        self.assertEqual(ids["vendas_concorrente"], "cego")
        self.assertEqual(ids["busca_oficial"], "cego")
        self.assertEqual(ids["visitas_rivais"], "ok")
        self.assertEqual(ids["funil_proprio"], "ok")

    def test_top_por_visitas(self):
        top = cd.top_por_visitas(
            [
                {"titulo": "A", "visitas_7d": 10, "preco": 1},
                {"titulo": "B", "visitas_7d": 50, "preco": 2},
                {"titulo": "C", "visitas_7d": 0, "preco": 3},
            ],
            top_n=2,
        )
        self.assertEqual([t["titulo"] for t in top], ["B", "A"])

    @patch.object(cd.ml_client, "buscar_visitas_item")
    def test_enriquecer_visitas_lista(self, mock_vis):
        mock_vis.return_value = {
            "ok": True,
            "disponivel": True,
            "visitas_7d": 42,
            "visitas_30d": 100,
        }
        produtos = [{"item_id": "MLB1", "titulo": "X"}, {"item_id": "MLB1", "titulo": "X"}]
        n = cd.enriquecer_visitas_lista(produtos, limite=5)
        self.assertEqual(n, 1)
        self.assertEqual(produtos[0]["visitas_7d"], 42)
        self.assertEqual(produtos[1]["visitas_7d"], 42)

    @patch.object(cd.ml_client, "_enabled", return_value=True)
    @patch.object(cd.ml_client, "buscar_visitas_item")
    @patch.object(cd.ml_client, "listar_pedidos_detalhado")
    @patch.object(cd.ml_client, "listar_meus_anuncios")
    def test_funil_proprio_conversao(self, mock_an, mock_ped, mock_vis, _en):
        mock_an.return_value = [
            {"item_id": "MLB1", "titulo": "Filamento PETG Preto", "sku": "P1", "status": "active", "sold_quantity": 1}
        ]
        mock_ped.return_value = (
            [
                {
                    "order_id": "1",
                    "itens": [{"item_id": "MLB1", "quantidade": 2, "preco_unitario": 90.0}],
                }
            ],
            True,
        )
        mock_vis.return_value = {"ok": True, "disponivel": True, "visitas_7d": 50, "visitas_30d": 120}
        out = cd.coletar_funil_proprio(dias=7, filtro_titulo=r"petg|filamento")
        self.assertTrue(out["ok"])
        self.assertTrue(out["pedidos_ok"])
        self.assertEqual(out["totais"]["visitas_7d"], 50)
        self.assertEqual(out["totais"]["unidades_7d"], 2)
        self.assertEqual(out["totais"]["conversao_pct"], 4.0)
        self.assertEqual(out["totais"]["visitas_convertidas_proxy"], 2)
        self.assertTrue(out["itens"][0]["conversao_confiavel"])

    def test_formatar_secoes(self):
        funil = {
            "ok": True,
            "dias": 7,
            "pedidos_ok": True,
            "visitas_ok": True,
            "totais": {
                "visitas_7d": 10,
                "unidades_7d": 1,
                "conversao_pct": 10.0,
                "conversao_confiavel": True,
            },
            "itens": [
                {
                    "titulo": "Meu PETG",
                    "visitas_7d": 10,
                    "unidades_pedidos": 1,
                    "conversao_pct": 10.0,
                    "conversao_confiavel": True,
                }
            ],
        }
        pc = cd.montar_pontos_cegos(
            consolidado={"anuncios_com_visitas": 1}, funil=funil, visitas_enriquecidas=1
        )
        txt = "\n".join(cd.formatar_secao_funil(funil) + cd.formatar_secao_pontos_cegos(pc))
        self.assertIn("Funil próprio", txt)
        self.assertIn("Pontos cegos", txt)
        self.assertIn("10.0%", txt)

    @patch.object(cd.ml_client, "buscar_visitas_item")
    def test_enriquecer_visitas_amostra(self, mock_vis):
        mock_vis.return_value = {
            "ok": True,
            "disponivel": True,
            "visitas_7d": 12,
            "visitas_30d": 40,
        }
        resultados = [
            {
                "ok": True,
                "produtos": [
                    {"item_id": "MLB1", "titulo": "A", "quantidade_vendida": 0},
                    {"item_id": "MLB2", "titulo": "B", "quantidade_vendida": 0},
                ],
            }
        ]
        n = cd.enriquecer_visitas_amostra(resultados, limite=2)
        self.assertEqual(n, 2)
        self.assertEqual(resultados[0]["produtos"][0]["visitas_7d"], 12)

    def test_emitir_metricas_demanda(self):
        with patch("integracoes.ml.coleta_demanda_ml.gauge") as mock_g:
            cd.emitir_metricas_demanda(
                "pref",
                funil={
                    "totais": {"visitas_7d": 10, "unidades_7d": 1, "conversao_pct": 10.0}
                },
                pontos_cegos={
                    "cegos": 3,
                    "itens": [{"id": "vendas_concorrente", "status": "cego"}],
                },
                visitas_enriquecidas=2,
            )
            nomes = [c.args[0] for c in mock_g.call_args_list]
            self.assertIn("pref.funil.visitas_7d", nomes)
            self.assertIn("pref.blindspot.vendas_api", nomes)

    def test_formatar_visitas_rivais(self):
        linhas = cd.formatar_secao_visitas_rivais(
            [{"titulo": "RIVAL", "visitas_7d": 50, "preco": 99.9}]
        )
        self.assertTrue(any("Rivais" in linha for linha in linhas))
        self.assertTrue(any("50" in linha for linha in linhas))


if __name__ == "__main__":
    unittest.main()
