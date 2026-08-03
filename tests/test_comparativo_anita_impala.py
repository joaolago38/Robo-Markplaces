"""
tests/test_comparativo_anita_impala.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.esmaltes import comparativo_anita_impala as cmp
from integracoes.esmaltes.analise_mercado import classificar_anuncio


class ComparativoAnitaImpalaTests(unittest.TestCase):
    def _anuncios_fixture(self):
        return [
            {"titulo": "Kit 5 Esmaltes Impala Nude Rosa Atacado", "preco": 44.90, "quantidade_vendida": 120, "frete_gratis": True},
            {"titulo": "Kit 5 Esmaltes Anita Nude Bege", "preco": 48.90, "quantidade_vendida": 80, "frete_gratis": False},
            {"titulo": "Kit 5 Risque Sortido", "preco": 42.0, "quantidade_vendida": 30},
        ]

    def test_proxy_quando_sold_quantity_zero(self):
        anuncios = [
            {"titulo": "Kit 5 Esmaltes Impala Bailarina", "preco": 30.0, "quantidade_vendida": 0},
            {"titulo": "Kit 5 Esmaltes Impala Nude", "preco": 31.0, "quantidade_vendida": 0},
            {"titulo": "Kit 5 Esmaltes Anita Nude", "preco": 45.0, "quantidade_vendida": 0},
        ]
        seg = {"id": "cmp-kit5", "nome": "Kit 5", "termo_busca": "kit 5"}
        out = cmp.comparar_segmento(seg, anuncios)
        self.assertEqual(out["fonte_volume"], "anuncios")
        self.assertEqual(out["impala"]["volume_proxy"], 2)
        self.assertEqual(out["anita"]["volume_proxy"], 1)
        self.assertEqual(out["vencedor_vendas"], "Impala")
        self.assertAlmostEqual(out["impala"]["share_vendas_pct"], 66.7, places=0)

        consolidado = cmp.consolidar_comparativo([out])
        self.assertTrue(consolidado["volume_eh_proxy"])
        self.assertEqual(consolidado["vencedor_global"], "Impala")
        self.assertEqual(consolidado["impala_unidades_vendidas"], 2)
        self.assertEqual(consolidado["anita_unidades_vendidas"], 1)

    def test_proxy_avaliacoes(self):
        anuncios = [
            {
                "titulo": "Kit Impala",
                "preco": 30.0,
                "quantidade_vendida": 0,
                "avaliacoes": 100,
            },
            {
                "titulo": "Kit Anita",
                "preco": 40.0,
                "quantidade_vendida": 0,
                "avaliacoes": 20,
            },
        ]
        out = cmp.comparar_segmento({"id": "x", "nome": "X", "termo_busca": "kit"}, anuncios)
        self.assertEqual(out["fonte_volume"], "avaliacoes")
        self.assertEqual(out["vencedor_vendas"], "Impala")

    def test_inferir_perfil_salao(self):
        an = classificar_anuncio({"titulo": "Kit 10 Impala Atacado Salão", "preco": 69.9, "quantidade_vendida": 50})
        perfil = cmp.inferir_perfil_consumidor(an)
        self.assertEqual(perfil["perfil_principal"], "salao_atacado")

    def test_comparar_segmento_impala_lider(self):
        seg = {"id": "cmp-kit5", "nome": "Kit 5", "termo_busca": "kit 5 esmaltes"}
        out = cmp.comparar_segmento(seg, self._anuncios_fixture())
        self.assertTrue(out["ok"])
        self.assertEqual(out["vencedor_vendas"], "Impala")
        self.assertEqual(out["impala"]["unidades_vendidas"], 120)
        self.assertEqual(out["anita"]["unidades_vendidas"], 80)
        self.assertAlmostEqual(out["impala"]["share_vendas_pct"], 60.0)

    def test_consolidar_e_estrategias(self):
        seg = {"id": "cmp-kit5", "nome": "Kit 5", "termo_busca": "kit 5"}
        r1 = cmp.comparar_segmento(seg, self._anuncios_fixture())
        consolidado = cmp.consolidar_comparativo([r1])
        self.assertEqual(consolidado["vencedor_global"], "Impala")
        estrategias = cmp.gerar_estrategias_vencer(consolidado)
        self.assertTrue(any(e["prioridade"] == "alta" for e in estrategias))

    def test_dedup_perfis_consumidor(self):
        anuncios = [
            {"titulo": "Esmalte Anita Avoante unitario", "preco": 9.9, "quantidade_vendida": 15},
            {"titulo": "Esmalte Impala Bailarina", "preco": 8.9, "quantidade_vendida": 25},
        ]
        seg = {"id": "unit", "nome": "Unitário", "termo_busca": "esmalte"}
        out = cmp.comparar_segmento(seg, anuncios)
        self.assertEqual(out["anita"]["anuncios"], 1)
        self.assertEqual(out["impala"]["anuncios"], 1)

    def test_consolidar_anita_lider(self):
        anuncios = [
            {"titulo": "Kit 5 Anita Nude", "preco": 45.0, "quantidade_vendida": 150},
            {"titulo": "Kit 5 Impala Rosa", "preco": 44.0, "quantidade_vendida": 90},
        ]
        seg = {"id": "cmp-kit5", "nome": "Kit 5", "termo_busca": "kit 5"}
        r1 = cmp.comparar_segmento(seg, anuncios)
        consolidado = cmp.consolidar_comparativo([r1])
        self.assertEqual(consolidado["vencedor_global"], "Anita")
        estrategias = cmp.gerar_estrategias_vencer(consolidado)
        self.assertTrue(any("Consolidar" in e.get("titulo", "") for e in estrategias))

    def test_enriquecer_sinais_proprios(self):
        consolidado = cmp.consolidar_comparativo([])
        cmp.enriquecer_com_sinais_proprios(
            consolidado,
            sinais_anita=[{"sku": "a1", "visitas_7d": 100, "unidades_vendidas_7d": 5}],
            sinais_impala=[{"sku": "i1", "visitas_7d": 80, "unidades_vendidas_7d": 3}],
        )
        self.assertEqual(len(consolidado["sinais_proprios"]["anita"]), 1)
        self.assertEqual(consolidado["sinais_proprios"]["anita"][0]["conversao_pct"], 5.0)

    def test_montar_painel_agente(self):
        from agentes.esmaltes import agente_comparativo_anita_impala as ag

        consolidado = {
            "anita_unidades_vendidas": 80,
            "impala_unidades_vendidas": 120,
            "anita_share_pct": 40,
            "impala_share_pct": 60,
            "vencedor_global": "Impala",
            "diferenca_unidades": -40,
            "segmentos_anita_lider": 0,
            "segmentos_impala_lider": 1,
            "perfis_anita_global": [{"perfil": "manicure_autonoma", "peso_vendas": 80}],
            "perfis_impala_global": [{"perfil": "salao_atacado", "peso_vendas": 120}],
            "resultados": [
                {
                    "nome": "Kit 5",
                    "vencedor_vendas": "Impala",
                    "anita": {
                        "unidades_vendidas": 80,
                        "preco_por_unidade_medio": 9.5,
                        "destaques": [
                            {
                                "titulo": "Kit 5 Esmaltes Anita Nude Bege",
                                "preco": 48.9,
                                "quantidade_vendida": 80,
                                "permalink": "https://produto.mercadolivre.com.br/MLB-anita",
                                "descricao_kit": "kit 5",
                            }
                        ],
                    },
                    "impala": {
                        "unidades_vendidas": 120,
                        "preco_por_unidade_medio": 8.9,
                        "destaques": [
                            {
                                "titulo": "Kit 5 Esmaltes Impala Nude Rosa Atacado",
                                "preco": 44.9,
                                "quantidade_vendida": 120,
                                "item_id": "MLB123",
                                "descricao_kit": "kit 5",
                            }
                        ],
                    },
                }
            ],
            "sinais_proprios": {"anita": [{"visitas_7d": 50}], "impala": [{"visitas_7d": 70}]},
        }
        estrategias = [{"prioridade": "alta", "titulo": "Teste", "texto": "Ajustar preço"}]
        painel = ag._montar_painel(consolidado, estrategias)
        self.assertIn("Anita vs Impala", painel)
        self.assertIn("Impala", painel)
        self.assertIn("Anita Nude", painel)
        self.assertIn("Impala Nude", painel)
        self.assertIn("https://produto.mercadolivre.com.br/MLB-anita", painel)

    def test_destaques_lista_todos_anuncios(self):
        anuncios = [
            {"titulo": "Kit 5 Impala A", "preco": 30.0, "quantidade_vendida": 10, "item_id": "MLB1"},
            {"titulo": "Kit 5 Impala B", "preco": 31.0, "quantidade_vendida": 5, "item_id": "MLB2"},
            {"titulo": "Kit 5 Impala C", "preco": 32.0, "quantidade_vendida": 1, "item_id": "MLB3"},
            {"titulo": "Kit 5 Anita X", "preco": 40.0, "quantidade_vendida": 8, "item_id": "MLB4"},
        ]
        out = cmp.comparar_segmento({"id": "k5", "nome": "Kit 5", "termo_busca": "kit"}, anuncios)
        self.assertEqual(len(out["impala"]["destaques"]), 3)
        self.assertEqual(len(out["anita"]["destaques"]), 1)
        self.assertEqual(out["impala"]["destaques"][0]["item_id"], "MLB1")
        self.assertEqual(out["impala"]["destaques"][0]["titulo"], "Kit 5 Impala A")

    @patch("agentes.esmaltes.agente_comparativo_anita_impala.comparar_segmento")
    @patch("agentes.esmaltes.agente_comparativo_anita_impala._carregar_segmentos")
    def test_agente_executar(self, mock_seg, mock_cmp):
        from agentes.esmaltes import agente_comparativo_anita_impala as ag

        mock_seg.return_value = [{"id": "s1", "termo_busca": "kit 5", "ativo": True, "prioridade": 1, "limite_resultados": 10, "nome": "Kit 5"}]
        mock_cmp.return_value = {
            "ok": True,
            "id": "s1",
            "nome": "Kit 5",
            "vencedor_vendas": "Impala",
            "anita": {"unidades_vendidas": 80, "share_vendas_pct": 40, "perfis_consumidor": [], "cores_top": [], "kits_top": []},
            "impala": {"unidades_vendidas": 120, "share_vendas_pct": 60, "perfis_consumidor": [{"perfil": "manicure_autonoma", "peso_vendas": 120}], "cores_top": [{"cor": "Nude", "peso_vendas": 50}], "kits_top": [{"qtd": 5, "peso_vendas": 120}]},
            "diferenca_preco_pct": 5.0,
        }
        with patch.object(ag, "_coletar_sinais_referencia", return_value=([], [])):
            with patch.object(ag, "escrever_json_atomico"):
                out = ag.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["consolidado"]["vencedor_global"], "Impala")


if __name__ == "__main__":
    unittest.main()
