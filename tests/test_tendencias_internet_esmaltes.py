"""
tests/test_tendencias_internet_esmaltes.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.esmaltes import cruzamento_tendencias_mercado as cruz
from integracoes.esmaltes import tendencias_internet as mod


class TendenciasInternetTests(unittest.TestCase):
    def test_extrair_sinais_web_detecta_cores_e_termos(self):
        hits = [
            {
                "url": "https://blog.com/tendencia",
                "titulo": "Tendência esmalte nude chrome viral moda 2026",
                "snippet": "Cores perolado e glitter em alta",
            },
            {
                "url": "https://revista.com/esmalte",
                "titulo": "Esmalte marsala inverno lançamento",
                "snippet": "Moda unhas profissional",
            },
        ]
        sinais = mod.extrair_sinais_web(hits)
        self.assertEqual(sinais["total_hits"], 2)
        cores = {c["cor"] for c in sinais["cores"]}
        self.assertIn("Nude", cores)
        termos = {t["termo"] for t in sinais["termos"]}
        self.assertIn("tendencia", termos)
        self.assertIn("viral", termos)

    @patch.object(mod, "_buscar_brave", return_value=[])
    @patch.object(mod, "_buscar_ddg")
    def test_buscar_web_fallback_ddg(self, mock_ddg, _mock_brave):
        mock_ddg.return_value = [
            {"url": "https://x.com/a", "titulo": "Esmalte jelly", "snippet": "moda", "fonte": "ddg"}
        ]
        out = mod.buscar_web("esmalte jelly tendencia")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["titulo"], "Esmalte jelly")


class CruzamentoTendenciasTests(unittest.TestCase):
    def test_cruzar_sinais_oportunidade(self):
        web = {
            "cores": [{"cor": "Nude", "mencoes": 10}, {"cor": "Rosa", "mencoes": 2}],
            "total_hits": 5,
        }
        anuncios = [
            {"titulo": "Esmalte rosa impala", "preco": 12, "quantidade_vendida": 200},
        ]
        tendencias = cruz.cruzar_sinais(web, anuncios, cores_alvo=["nude"])
        nude = next(t for t in tendencias if t["cor"] == "Nude")
        self.assertEqual(nude["status"], "oportunidade")
        self.assertTrue(nude["alvo_catalogo"])

    def test_consolidar_varredura(self):
        out = cruz.consolidar_varredura(
            [
                {
                    "ok": True,
                    "id": "a",
                    "nome": "Seg A",
                    "total_web_hits": 5,
                    "total_anuncios_mp": 3,
                    "web_sinais": {"termos": [{"termo": "viral", "mencoes": 4}]},
                    "tendencias": [
                        {
                            "cor": "Nude",
                            "status": "oportunidade",
                            "score_web": 80,
                            "score_mp": 10,
                            "mencoes_web": 5,
                            "peso_vendas_mp": 0,
                        }
                    ],
                }
            ]
        )
        self.assertEqual(out["segmentos_varridos"], 1)
        self.assertEqual(len(out["top_oportunidades"]), 1)
        self.assertEqual(out["top_oportunidades"][0]["segmento"], "Seg A")

    @patch.object(cruz, "coletar_segmento_web")
    def test_processar_segmento(self, mock_web):
        mock_web.return_value = {
            "total_hits": 3,
            "cores": [{"cor": "Glitter", "mencoes": 3}],
            "termos": [],
            "termos_varridos": ["tendencia glitter"],
        }

        def _buscar(termo, *, limite=10, item_id_referencia=None):
            _ = item_id_referencia
            return [{"titulo": f"Kit esmalte {termo}", "preco": 50, "quantidade_vendida": 10, "marketplace": "mercadolivre"}]

        seg = {
            "id": "glitter",
            "nome": "Glitter",
            "termos_web": ["tendencia glitter"],
            "termos_marketplace": ["esmalte glitter"],
            "cores_alvo": ["glitter"],
            "limite_resultados": 10,
        }
        r = cruz.processar_segmento(seg, _buscar)
        self.assertTrue(r["ok"])
        self.assertGreaterEqual(r["total_anuncios_mp"], 1)
        self.assertTrue(r["tendencias"])
        self.assertIn("oportunidades_marca_kit", r)


class CruzamentoMarcaKitTests(unittest.TestCase):
    def test_identifica_kit_com_tendencia_confirmada(self):
        anuncios = [
            {"titulo": "Kit 5 Esmaltes Anita Nude Rosa", "preco": 45.0, "quantidade_vendida": 80},
            {"titulo": "Kit 5 Esmaltes Anita Nude", "preco": 42.0, "quantidade_vendida": 40},
            {"titulo": "Esmalte unitario Colorama vermelho", "preco": 8.0, "quantidade_vendida": 500},
        ]
        tendencias = [
            {"cor": "Nude", "status": "confirmada", "score_web": 70, "score_mp": 60},
            {"cor": "Rosa", "status": "emergente", "score_web": 25, "score_mp": 20},
        ]
        out = cruz.cruzar_marca_kit_tendencia(anuncios, tendencias)
        self.assertTrue(out)
        top = out[0]
        self.assertEqual(top["slug"], "anita")
        self.assertEqual(top["qtd_kit"], 5)
        self.assertEqual(top["status_tendencia"], "confirmada")
        self.assertTrue(top["condicao_ok"])
        self.assertTrue(top["performance_boa"])
        self.assertNotIn(1, [x["qtd_kit"] for x in out])

    def test_sem_tendencia_nao_marca_performance_boa(self):
        anuncios = [
            {"titulo": "Kit 10 Esmaltes Risque Vermelho", "preco": 70.0, "quantidade_vendida": 12},
            {"titulo": "Kit 10 Esmaltes Risque", "preco": 68.0, "quantidade_vendida": 8},
        ]
        out = cruz.cruzar_marca_kit_tendencia(anuncios, [])
        self.assertEqual(out[0]["slug"], "risque")
        self.assertTrue(out[0]["condicao_ok"])
        self.assertFalse(out[0]["performance_boa"])
        self.assertEqual(out[0]["status_tendencia"], "sem_tendencia")

    def test_de_snapshots_anita(self):
        anita = {
            "resultados": [
                {
                    "analises": [
                        {
                            "titulo": "Kit 5 Esmaltes Impala Nude",
                            "preco": 42.0,
                            "quantidade_vendida": 200,
                        },
                        {
                            "titulo": "Kit 5 Esmaltes Anita Nude",
                            "preco": 45.0,
                            "quantidade_vendida": 120,
                        },
                    ]
                }
            ]
        }
        tendencias = {
            "consolidado": {
                "todas_tendencias": [{"cor": "Nude", "status": "oportunidade"}],
            }
        }
        out = cruz.cruzar_marca_kit_de_snapshots(
            mercado={},
            anita=anita,
            kits={},
            tendencias=tendencias,
        )
        slugs = {r["slug"] for r in out}
        self.assertIn("anita", slugs)
        self.assertIn("impala", slugs)
        anita_kit = next(r for r in out if r["slug"] == "anita")
        self.assertEqual(anita_kit["qtd_kit"], 5)
        self.assertTrue(anita_kit["performance_boa"])

    def test_overlay_marca_detectada_sem_cor_no_titulo(self):
        anita = {
            "resultados": [
                {
                    "analises": [
                        {
                            "titulo": "Kit 5 Impala Bailarina",
                            "preco": 42.0,
                            "quantidade_vendida": 200,
                            "marca_detectada": "Impala",
                            "qtd_kit_detectada": 5,
                            "cores_encontradas": ["Nude"],
                        }
                    ]
                }
            ]
        }
        tendencias = {"consolidado": {"todas_tendencias": [{"cor": "Nude", "status": "confirmada"}]}}
        out = cruz.cruzar_marca_kit_de_snapshots(
            mercado={},
            anita=anita,
            kits={},
            tendencias=tendencias,
        )
        self.assertEqual(out[0]["slug"], "impala")
        self.assertEqual(out[0]["qtd_kit"], 5)
        self.assertTrue(out[0]["performance_boa"])
        self.assertIn("Nude", out[0]["cores_tendencia"])


if __name__ == "__main__":
    unittest.main()
