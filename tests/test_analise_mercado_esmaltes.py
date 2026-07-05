"""
tests/test_analise_mercado_esmaltes.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.esmaltes import analise_mercado as am


class AnaliseMercadoEsmaltesTests(unittest.TestCase):
    def test_extrair_cores_titulo(self):
        cores = am.extrair_cores_titulo("Kit 5 Esmaltes Impala Nude Rosa Vermelho")
        self.assertIn("Nude", cores)
        self.assertIn("Rosa", cores)

    def test_classificar_anuncio_kit(self):
        an = {"titulo": "Kit 10 Esmaltes Impala Atacado Nude", "preco": 69.90, "quantidade_vendida": 50}
        out = am.classificar_anuncio(an)
        self.assertEqual(out["qtd_kit"], 10)
        self.assertEqual(out["tipo_anuncio"], "kit")
        self.assertIn("10 esmalte", out["descricao_kit"])

    def test_margem_satisfatoria(self):
        diag = am.margem_em_preco(50.0, 25.0, 18, 10)
        self.assertTrue(diag["margem_satisfatoria"])
        self.assertGreater(diag["margem_operacional_pct"], 10)

    def test_padroes_kits(self):
        anuncios = [
            am.classificar_anuncio({"titulo": "Kit 5 Impala", "preco": 45, "quantidade_vendida": 100}),
            am.classificar_anuncio({"titulo": "Kit 5 Anita", "preco": 48, "quantidade_vendida": 80}),
            am.classificar_anuncio({"titulo": "Kit 10 Atacado", "preco": 70, "quantidade_vendida": 40}),
        ]
        kits = am.padroes_kits(anuncios)
        self.assertEqual(kits[0]["qtd"], 5)
        self.assertEqual(kits[0]["vendidos"], 180)

    def test_gerar_propostas_competir(self):
        segmento = {
            "id": "seg-kit5",
            "nome": "Kit 5",
            "qtd_esmaltes_referencia": 5,
        }
        referencia = {
            "sku": "IMP-BAIL-005",
            "custo_total": 25.0,
            "meu_preco": 52.0,
            "taxa_marketplace_pct": 18,
            "margem_minima_pct": 10,
            "titulo_ml": "Kit 5 Impala Bailarina",
        }
        anuncios = [
            {
                "titulo": "Kit 5 Esmaltes Impala Nude Rosa",
                "preco": 44.90,
                "quantidade_vendida": 120,
                "frete_gratis": True,
            },
            {
                "titulo": "Kit 5 Risque Sortido",
                "preco": 42.0,
                "quantidade_vendida": 90,
            },
        ]
        props = am.gerar_propostas_competir(segmento, anuncios, referencia, vendas_min=5)
        tipos = {p["tipo"] for p in props}
        self.assertIn("kit", tipos)
        self.assertIn("cores", tipos)
        altas = [p for p in props if p.get("prioridade") == "alta"]
        self.assertTrue(any(p.get("sku") == "IMP-BAIL-005" for p in altas))

    def test_consolidar_mercado(self):
        r1 = {
            "ok": True,
            "propostas": [{"prioridade": "alta", "texto": "A"}],
            "ranking_marcas": [{"marca": "Impala", "vendidos": 100}],
            "destaques": [{"item_id": "MLB1", "titulo": "Kit 5", "quantidade_vendida": 50, "preco": 45}],
        }
        r2 = {
            "ok": True,
            "propostas": [{"prioridade": "alta", "texto": "A"}],
            "ranking_marcas": [{"marca": "Anita", "vendidos": 80}],
            "destaques": [{"item_id": "MLB1", "titulo": "Kit 5", "quantidade_vendida": 50, "preco": 45}],
        }
        out = am.consolidar_mercado([r1, r2])
        self.assertEqual(out["total_anuncios_unicos"], 1)
        self.assertEqual(len(out["propostas"]), 1)


if __name__ == "__main__":
    unittest.main()
