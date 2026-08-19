"""
tests/test_acetona_cruzeiro.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.esmaltes import analise_acetona_cruzeiro as aa


class AnaliseAcetonaCruzeiroTests(unittest.TestCase):
    def test_detectar_cruzeiro_e_volume(self):
        self.assertTrue(aa.eh_cruzeiro("Removedor Esmalte Cruzeiro Acetona 100ml"))
        self.assertEqual(aa.extrair_volume_ml("Acetona Cruzeiro 500ml Profissional"), 500)

    def test_analisar_termo_vendedores_margem(self):
        item = {
            "id": "cruzeiro-100",
            "nome": "100ml",
            "termo_busca": "acetona cruzeiro",
            "volume_ml": 100,
            "custo_total": 5.80,
            "meu_preco": 12.90,
            "taxa_marketplace_pct": 18,
        }
        anuncios = [
            {"titulo": "Removedor Cruzeiro Acetona 100ml", "preco": 11.90, "quantidade_vendida": 40, "seller_id": "S1"},
            {"titulo": "Removedor Cruzeiro Acetona 100ml Profissional", "preco": 13.50, "quantidade_vendida": 25, "seller_id": "S2"},
            {"titulo": "Acetona Genérica 100ml", "preco": 8.90, "quantidade_vendida": 10, "seller_id": "S3"},
        ]
        out = aa.analisar_termo(item, anuncios)
        self.assertEqual(out["vendedores_cruzeiro"], 2)
        self.assertEqual(out["total_cruzeiro"], 2)
        self.assertEqual(len(out["anuncios_cruzeiro"]), 2)
        self.assertIsNotNone(out["margem_media_mercado_pct"])
        self.assertGreater(out["margem_media_mercado_pct"], 0)

    def test_consolidar_vendedores_unicos(self):
        r1 = {
            "ok": True,
            "vendedores_ids": ["S1", "S2"],
            "margem_media_mercado_pct": 50.0,
            "preco_medio_cruzeiro": 12.0,
            "unidades_vendidas_cruzeiro": 10,
            "anuncios_cruzeiro": [
                {"item_id": "MLB1", "seller_id": "S1", "quantidade_vendida": 10},
                {"item_id": "MLB2", "seller_id": "S2", "quantidade_vendida": 4},
            ],
        }
        r2 = {
            "ok": True,
            "vendedores_ids": ["S2", "S3"],
            "margem_media_mercado_pct": 40.0,
            "preco_medio_cruzeiro": 14.0,
            "unidades_vendidas_cruzeiro": 5,
            "anuncios_cruzeiro": [
                {"item_id": "MLB2", "seller_id": "S2", "quantidade_vendida": 8},
                {"item_id": "MLB3", "seller_id": "S3", "quantidade_vendida": 1},
            ],
        }
        c = aa.consolidar_acetona([r1, r2])
        self.assertEqual(c["vendedores_cruzeiro_unicos"], 3)
        self.assertEqual(c["margem_media_mercado_pct"], 45.0)
        ids = {a["item_id"] for a in c["anuncios_cruzeiro"]}
        self.assertEqual(ids, {"MLB1", "MLB2", "MLB3"})
        by = {a["item_id"]: a for a in c["anuncios_cruzeiro"]}
        self.assertEqual(by["MLB2"]["quantidade_vendida"], 8)

    def test_resumir_impala(self):
        produtos = [
            {
                "sku": "IMP-BAIL-005",
                "nome": "Kit 5",
                "custo_total": 35.0,
                "preco": 48.9,
                "fase_atual": 1,
                "canais": {"mercadolivre": {"ativo": True, "preco": 48.9}},
            }
        ]
        out = aa.resumir_impala_para_claude(produtos)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["sku"], "IMP-BAIL-005")

    def test_montar_painel_agente(self):
        from agentes.esmaltes import agente_monitor_acetona_cruzeiro as ag

        consolidado = {
            "vendedores_cruzeiro_unicos": 12,
            "unidades_vendidas_cruzeiro": 200,
            "preco_medio_cruzeiro": 13.5,
            "margem_media_mercado_pct": 42.0,
            "resultados": [{"nome": "100ml", "vendedores_cruzeiro": 5, "preco_medio_cruzeiro": 12.0, "margem_media_mercado_pct": 40, "destaques_cruzeiro": []}],
        }
        manicures = {"mei_manicure_cabeleireiro": 735940, "estabelecimentos_ativos_cnae_9602501": 974949, "publico_ampliado_salao_mei": 1018228, "penetracao_ml_estimada_pct": 12, "manicures_enderecaveis_ml_estimado": 122187}
        estrategias = {"visao_mercado": "Mercado aquecido.", "estrategias": [{"titulo": "Bundle", "acao": "Kit + acetona", "prioridade": "alta"}]}
        painel = ag._montar_painel(consolidado, manicures, estrategias)
        self.assertIn("735.940", painel)
        self.assertIn("Bundle", painel)

    @patch("agentes.esmaltes.agente_monitor_acetona_cruzeiro._gerar_estrategias_claude")
    @patch("agentes.esmaltes.agente_monitor_acetona_cruzeiro._monitorar_item")
    @patch("agentes.esmaltes.agente_monitor_acetona_cruzeiro._carregar_itens")
    def test_agente_executar(self, mock_itens, mock_mon, mock_claude):
        from agentes.esmaltes import agente_monitor_acetona_cruzeiro as ag

        mock_itens.return_value = [{"id": "x", "ativo": True, "prioridade": 1}]
        mock_mon.return_value = {
            "ok": True,
            "id": "x",
            "vendedores_cruzeiro": 5,
            "vendedores_ids": ["S1"],
            "margem_media_mercado_pct": 35.0,
            "preco_medio_cruzeiro": 12.5,
            "unidades_vendidas_cruzeiro": 20,
            "destaques_cruzeiro": [],
        }
        mock_claude.return_value = {
            "visao_mercado": "Mercado fragmentado.",
            "estrategias": [{"titulo": "Bundle", "acao": "Kit Impala + acetona", "prioridade": "alta"}],
        }
        with patch.object(ag, "escrever_json_atomico"):
            with patch(
                "agentes.esmaltes.agente_monitor_acetona_cruzeiro.carregar_produtos_para_operacao",
                return_value=[],
            ):
                out = ag.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["consolidado"]["vendedores_cruzeiro_unicos"], 1)


if __name__ == "__main__":
    unittest.main()
