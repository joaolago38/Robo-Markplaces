"""tests/test_integridade_dados_ml.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.ml import integridade_dados_ml as integ
from integracoes.ml import ml_client


class TestIntegridadeDadosMl(unittest.TestCase):
    def test_meta_e_99_99(self):
        self.assertEqual(integ.META_PCT, 99.99)

    def test_espelho_completo_atinge_meta(self):
        anuncios = [
            {
                "item_id": "MLB1",
                "titulo": "Kit",
                "preco": 39.9,
                "status": "active",
                "sold_quantity": 1,
                "estoque": 4,
            }
        ]
        vivo = {
            "item_id": "MLB1",
            "titulo": "Kit",
            "preco": 39.9,
            "status": "active",
            "sold_quantity": 1,
            "estoque": 4,
        }
        out = integ.auditar_espelho(
            anuncios,
            meta_listagem={"ok": True, "ids_busca": 1, "ids_ok": 1, "ids_faltando": []},
            buscar_item=lambda _iid: vivo,
        )
        self.assertEqual(out["pct"], 100.0)
        self.assertTrue(out["atinge_meta"])
        self.assertTrue(out["espelho_confiavel"])
        self.assertEqual(out["corrigidos"], 0)

    def test_preco_divergente_e_corrigido_in_place(self):
        anuncios = [
            {
                "item_id": "MLB1",
                "titulo": "Kit",
                "preco": 10.0,
                "status": "active",
                "sold_quantity": 0,
                "estoque": 1,
            }
        ]
        vivo = {
            "item_id": "MLB1",
            "titulo": "Kit",
            "preco": 39.9,
            "status": "active",
            "sold_quantity": 0,
            "estoque": 1,
        }
        out = integ.auditar_espelho(
            anuncios,
            meta_listagem={"ok": True, "ids_busca": 1, "ids_ok": 1, "ids_faltando": []},
            buscar_item=lambda _iid: vivo,
        )
        self.assertEqual(anuncios[0]["preco"], 39.9)
        self.assertEqual(out["corrigidos"], 1)
        self.assertEqual(out["pct"], 100.0)
        self.assertTrue(out["atinge_meta"])

    def test_listagem_falhou_fica_abaixo_da_meta(self):
        out = integ.auditar_espelho(
            [],
            meta_listagem={"ok": False, "ids_busca": 0, "ids_ok": 0, "ids_faltando": [], "motivo": "excecao"},
            buscar_item=lambda _iid: {},
        )
        self.assertFalse(out["atinge_meta"])
        self.assertLess(out["pct"], integ.META_PCT)
        self.assertFalse(out["espelho_confiavel"])

    def test_get_falhou_nao_atinge_meta(self):
        anuncios = [{"item_id": "MLB1", "titulo": "X", "preco": 1, "status": "active"}]
        out = integ.auditar_espelho(
            anuncios,
            meta_listagem={"ok": True, "ids_busca": 1, "ids_ok": 1, "ids_faltando": []},
            buscar_item=lambda _iid: {},
        )
        self.assertFalse(out["atinge_meta"])
        self.assertIn("get:MLB1", out["falhas"])

    def test_get_retry_atinge_meta(self):
        anuncios = [
            {
                "item_id": "MLB1",
                "titulo": "Kit",
                "preco": 10.0,
                "status": "active",
                "sold_quantity": 0,
                "estoque": 1,
            }
        ]
        vivo = {
            "item_id": "MLB1",
            "titulo": "Kit",
            "preco": 39.9,
            "status": "active",
            "sold_quantity": 0,
            "estoque": 2,
        }
        chamadas = {"n": 0}

        def _get(_iid: str) -> dict:
            chamadas["n"] += 1
            return {} if chamadas["n"] == 1 else vivo

        out = integ.auditar_espelho(
            anuncios,
            meta_listagem={"ok": True, "ids_busca": 1, "ids_ok": 1, "ids_faltando": []},
            buscar_item=_get,
        )
        self.assertEqual(chamadas["n"], 2)
        self.assertTrue(out["atinge_meta"])
        self.assertEqual(anuncios[0]["preco"], 39.9)
        self.assertEqual(anuncios[0]["estoque"], 2)

    def test_emitir_metricas(self):
        with patch.object(integ, "gauge") as g, patch.object(integ, "incrementar") as inc:
            integ.emitir_metricas(
                {
                    "pct": 100.0,
                    "atinge_meta": True,
                    "espelho_confiavel": True,
                    "checks_ok": 3,
                    "checks_total": 3,
                    "corrigidos": 0,
                    "amostra": 1,
                }
            )
        nomes = [c.args[0] for c in g.call_args_list]
        self.assertIn("ml.integridade.pct", nomes)
        self.assertIn("ml.integridade.amostra", nomes)
        self.assertIn("ml.integridade.ids_busca", nomes)
        self.assertIn("ml.integridade.paging_total", nomes)
        inc.assert_called_once_with("ml.integridade.ok")

    def test_paginacao_incompleta_nao_atinge_meta(self):
        out = integ.auditar_espelho(
            [{"item_id": "MLB1", "titulo": "X", "preco": 1, "status": "active", "sold_quantity": 0, "estoque": 1}],
            meta_listagem={
                "ok": True,
                "ids_busca": 9,
                "ids_ok": 9,
                "ids_faltando": [],
                "paging_total": 38,
            },
            buscar_item=lambda _iid: {
                "item_id": "MLB1",
                "titulo": "X",
                "preco": 1,
                "status": "active",
                "sold_quantity": 0,
                "estoque": 1,
            },
        )
        self.assertFalse(out["atinge_meta"])
        self.assertTrue(any("paging=38" in f for f in out["falhas"]))

    def test_amostra_vazia_com_ids_ok_nao_atinge_meta(self):
        """Foco vazio + listagem hidratada não pode virar 100% sem GET /items."""
        out = integ.auditar_espelho(
            [],
            meta_listagem={
                "ok": True,
                "ids_busca": 9,
                "ids_ok": 9,
                "ids_faltando": [],
            },
            buscar_item=lambda _iid: {"item_id": "MLB1"},
        )
        self.assertEqual(out["amostra"], 0)
        self.assertFalse(out["atinge_meta"])
        self.assertFalse(out["espelho_confiavel"])
        self.assertTrue(any(f.startswith("amostra_vazia:") for f in out["falhas"]))
        self.assertLess(out["pct"], integ.META_PCT)

    def test_conta_vazia_real_atinge_meta(self):
        out = integ.auditar_espelho(
            [],
            meta_listagem={"ok": True, "ids_busca": 0, "ids_ok": 0, "ids_faltando": []},
            buscar_item=lambda _iid: {},
        )
        self.assertEqual(out["amostra"], 0)
        self.assertTrue(out["atinge_meta"])
        self.assertTrue(out["espelho_confiavel"])

    def test_aceita_id_como_item_id(self):
        anuncios = [{"id": "MLB1", "titulo": "Kit", "preco": 1, "status": "active", "sold_quantity": 0, "estoque": 1}]
        vivo = {"item_id": "MLB1", "titulo": "Kit", "preco": 1, "status": "active", "sold_quantity": 0, "estoque": 1}
        out = integ.auditar_espelho(
            anuncios,
            meta_listagem={"ok": True, "ids_busca": 1, "ids_ok": 1, "ids_faltando": []},
            buscar_item=lambda _iid: vivo,
        )
        self.assertEqual(out["amostra"], 1)
        self.assertTrue(out["atinge_meta"])

    def test_executar_relisa_sem_foco_quando_lote_filtrado(self):
        hidratados = [
            {
                "item_id": "MLB9",
                "titulo": "Bolsa",
                "preco": 10.0,
                "status": "active",
                "sold_quantity": 0,
                "estoque": 1,
            }
        ]
        with patch.object(
            ml_client,
            "ultima_listagem_anuncios",
            return_value={"ok": True, "ids_busca": 1, "ids_ok": 1, "ids_faltando": []},
        ), patch.object(
            ml_client, "listar_meus_anuncios", return_value=hidratados
        ) as listar, patch.object(
            ml_client, "_hidratar_anuncios_por_ids", return_value=(hidratados, [])
        ), patch.object(integ, "emitir_metricas"), patch.object(
            integ, "escrever_json_atomico"
        ):
            out = integ.executar(anuncios=[], amostra_max=5)
        listar.assert_called_once_with(statuses=("active", "paused"), aplicar_foco=False)
        self.assertEqual(out["amostra"], 1)
        self.assertTrue(out["atinge_meta"])


class TestListarAnunciosIntegridade(unittest.TestCase):
    def test_excecao_nao_e_catalogo_vazio(self):
        with patch.object(ml_client, "_enabled", return_value=True), patch.object(
            ml_client, "get_token_ml", return_value="tok"
        ), patch.object(ml_client, "request", side_effect=RuntimeError("rede")):
            out = ml_client.listar_meus_anuncios()
        self.assertEqual(out, [])
        meta = ml_client.ultima_listagem_anuncios()
        self.assertFalse(meta["ok"])
        self.assertEqual(meta["motivo"], "excecao")

    def test_retry_hidrata_item_que_falhou_no_lote(self):
        search = type("R", (), {})()
        search.status_code = 200
        search.json = lambda: {"results": ["MLB1", "MLB2"], "paging": {"total": 2}}
        search.raise_for_status = lambda: None
        search.text = ""

        lote1 = type("R", (), {})()
        lote1.status_code = 200
        lote1.raise_for_status = lambda: None
        lote1.json = lambda: [
            {"code": 200, "body": {"id": "MLB1", "title": "A", "price": 1, "status": "active"}},
            {"code": 500, "body": {}},
        ]

        lote2 = type("R", (), {})()
        lote2.status_code = 200
        lote2.raise_for_status = lambda: None
        lote2.json = lambda: [
            {"code": 200, "body": {"id": "MLB2", "title": "B", "price": 2, "status": "paused"}},
        ]

        with patch.object(ml_client, "_enabled", return_value=True), patch.object(
            ml_client, "get_token_ml", return_value="tok"
        ), patch.object(
            ml_client, "request", side_effect=[search, lote1, lote2]
        ), patch.object(ml_client, "ML_IGNORAR_ANUNCIOS_FORA_FOCO", False):
            out = ml_client.listar_meus_anuncios(aplicar_foco=False)
        self.assertEqual([a["item_id"] for a in out], ["MLB1", "MLB2"])
        meta = ml_client.ultima_listagem_anuncios()
        self.assertTrue(meta["ok"])
        self.assertEqual(meta["ids_busca"], 2)
        self.assertEqual(meta["ids_ok"], 2)


if __name__ == "__main__":
    unittest.main()
