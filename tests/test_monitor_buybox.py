"""tests/test_monitor_buybox.py"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.ml import monitor_buybox as bb
from tests.http_fixtures import make_http_response

# Exemplo real (MLB41490081): cinco ofertas de R$28,90 a R$34,90
_OFERTAS_MLB41490081 = [
    {
        "item_id": "MLB111",
        "seller_id": "3365946217",
        "price": 28.90,
        "listing_type_id": "gold_special",
    },
    {
        "item_id": "MLB222",
        "seller_id": "1001",
        "price": 29.90,
        "listing_type_id": "gold_special",
    },
    {
        "item_id": "MLB333",
        "seller_id": "1002",
        "price": 31.50,
        "listing_type_id": "gold_pro",
    },
    {
        "item_id": "MLB444",
        "seller_id": "1003",
        "price": 33.00,
        "listing_type_id": "gold_special",
    },
    {
        "item_id": "MLB555",
        "seller_id": "1004",
        "price": 34.90,
        "listing_type_id": "gold_special",
    },
]


class TestConsultarOfertas(unittest.TestCase):
    @patch.object(bb.ml_client, "_enabled", return_value=True)
    @patch.object(bb.ml_client, "_request_ml")
    def test_resposta_vazia(self, mock_req, _en):
        mock_req.return_value = make_http_response(json_body={"results": []})
        self.assertEqual(bb.consultar_ofertas_catalogo("MLB41490081"), [])

    @patch.object(bb.ml_client, "_enabled", return_value=True)
    @patch.object(bb.ml_client, "_request_ml")
    def test_uma_oferta(self, mock_req, _en):
        mock_req.return_value = make_http_response(
            json_body={"results": [_OFERTAS_MLB41490081[0]]}
        )
        out = bb.consultar_ofertas_catalogo("MLB41490081")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["posicao_na_lista"], 0)
        self.assertEqual(out[0]["preco"], 28.90)
        self.assertEqual(out[0]["seller_id"], "3365946217")

    @patch.object(bb.ml_client, "_enabled", return_value=True)
    @patch.object(bb.ml_client, "_request_ml")
    def test_cinco_ofertas_mlb41490081(self, mock_req, _en):
        mock_req.return_value = make_http_response(
            json_body={"results": _OFERTAS_MLB41490081}
        )
        out = bb.consultar_ofertas_catalogo("MLB41490081")
        self.assertEqual(len(out), 5)
        self.assertEqual(out[0]["preco"], 28.90)
        self.assertEqual(out[4]["preco"], 34.90)
        self.assertEqual([o["posicao_na_lista"] for o in out], [0, 1, 2, 3, 4])

    @patch.object(bb.ml_client, "_enabled", return_value=True)
    @patch.object(bb.ml_client, "_request_ml")
    def test_http_nao_200(self, mock_req, _en):
        mock_req.return_value = make_http_response(status_code=403, json_body={})
        self.assertEqual(bb.consultar_ofertas_catalogo("MLB41490081"), [])

    def test_id_vazio(self):
        self.assertEqual(bb.consultar_ofertas_catalogo(""), [])

    def test_detectar_vencedor_posicao_zero(self):
        ofertas = [
            {"seller_id": "A", "preco": 10, "posicao_na_lista": 1},
            {"seller_id": "B", "preco": 28.9, "posicao_na_lista": 0, "item_id": "MLB1"},
        ]
        v = bb.detectar_vencedor_buybox(ofertas)
        self.assertEqual(v["seller_id"], "B")
        self.assertEqual(v["metodo"], "posicao_lista_api")

    def test_detectar_vencedor_lista_vazia(self):
        self.assertIsNone(bb.detectar_vencedor_buybox([]))


class TestEstabilidade(unittest.TestCase):
    def test_historico_insuficiente(self):
        with patch.object(bb, "_carregar_historico", return_value={}):
            out = bb.analisar_estabilidade_vencedor("MLB41490081", dias=7)
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "historico insuficiente")

    def test_pct_tempo_cada_seller(self):
        agora = datetime.now(timezone.utc)
        snaps = []
        for i in range(5):
            sid = "3365946217" if i < 3 else "1001"
            preco = 28.90 if sid == "3365946217" else 29.90
            ts = (agora - timedelta(hours=i)).isoformat()
            snaps.append(
                {
                    "timestamp": ts,
                    "vencedor_atual": {
                        "seller_id": sid,
                        "preco": preco,
                        "posicao_na_lista": 0,
                        "metodo": "posicao_lista_api",
                    },
                }
            )
        hist = {"MLB41490081": {"snapshots": snaps}}
        with patch.object(bb, "_carregar_historico", return_value=hist):
            out = bb.analisar_estabilidade_vencedor("MLB41490081", dias=7)
        self.assertTrue(out["ok"])
        self.assertEqual(out["pct_tempo_cada_seller"]["3365946217"], 60.0)
        self.assertEqual(out["pct_tempo_cada_seller"]["1001"], 40.0)
        self.assertEqual(out["recomendacao_preco"], 28.89)

    def test_registrar_snapshot(self):
        ofertas = [
            {
                "item_id": "MLB1",
                "seller_id": "1",
                "preco": 10.0,
                "posicao_na_lista": 0,
            }
        ]
        with patch.object(bb, "_carregar_historico", return_value={}):
            with patch.object(bb, "escrever_json_atomico") as mock_w:
                snap = bb.registrar_snapshot_buybox("MLB41490081", ofertas)
        self.assertEqual(snap["vencedor_atual"]["seller_id"], "1")
        mock_w.assert_called_once()

    def test_emitir_metricas_buybox(self):
        with patch.object(bb, "gauge") as mock_g:
            bb.emitir_metricas_buybox(
                "MLB41490081",
                [{"seller_id": "3365946217", "preco": 28.9}],
                {"seller_id": "3365946217", "preco": 28.9},
                {"ok": True, "pct_tempo_cada_seller": {"3365946217": 80.0}},
                produto_id="kit-mimo",
                nosso_seller_id="3365946217",
            )
        nomes = [c.args[0] for c in mock_g.call_args_list]
        self.assertIn("buybox.preco_vencedor", nomes)
        self.assertIn("buybox.n_ofertas", nomes)
        self.assertIn("buybox.ganhando", nomes)
        self.assertIn("buybox.pct_tempo_vencedor", nomes)
        ganhando = next(c.args[1] for c in mock_g.call_args_list if c.args[0] == "buybox.ganhando")
        self.assertEqual(ganhando, 1.0)


if __name__ == "__main__":
    unittest.main()
