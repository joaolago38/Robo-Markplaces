"""tests/test_metricas_periodo_cnpj.py"""
from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from core.horario import TZ_BRASIL
from integracoes.vendas import metricas_periodo_cnpj as mp

_AGORA = datetime(2026, 9, 11, 15, 0, tzinfo=TZ_BRASIL)


def _ped(oid: str, data: str, sku: str, qtd: int, preco: float) -> dict:
    return {
        "order_id": oid,
        "data": data,
        "itens": [{"sku": sku, "quantidade": qtd, "preco_unitario": preco}],
    }


class TestAgregarPeriodo(unittest.TestCase):
    def test_separa_dia_semana_mes(self):
        pedidos = [
            _ped("hoje", "2026-09-11T12:00:00-03:00", "IMP-MIMO-003", 2, 40),
            _ped("semana", "2026-09-08T12:00:00-03:00", "IMP-PERL-004", 1, 50),
            _ped("mes", "2026-08-20T12:00:00-03:00", "IMP-MIMO-003", 3, 40),
        ]
        out = mp.agregar_periodo(pedidos, agora=_AGORA)
        self.assertEqual(out["totais"]["dia"]["pedidos"], 1)
        self.assertEqual(out["totais"]["dia"]["unidades"], 2)
        self.assertEqual(out["totais"]["semana"]["pedidos"], 2)
        self.assertEqual(out["totais"]["mes"]["pedidos"], 3)
        self.assertEqual(out["totais"]["dia"]["receita"], 80.0)
        rank_dia = out["ranking"]["dia"]
        self.assertEqual(rank_dia[0][0], "kit:mimo003")
        self.assertEqual(rank_dia[0][1], 2)

    def test_sem_data_ignora(self):
        out = mp.agregar_periodo([_ped("x", "", "IMP-MIMO-003", 1, 10)], agora=_AGORA)
        self.assertEqual(out["totais"]["dia"]["pedidos"], 0)
        self.assertEqual(out["sem_data"], 1)


class TestPedidosFonteImpala(unittest.TestCase):
    def test_ignora_shopee_mesmo_com_ok(self):
        pedidos = {
            "mercadolivre": [_ped("a", "2026-09-11T12:00:00-03:00", "IMP-MIMO-003", 1, 10)],
            "shopee": [_ped("b", "2026-09-11T12:00:00-03:00", "X", 9, 99)],
        }
        so_ml, ok = mp.pedidos_e_fonte_impala(pedidos, {"mercadolivre": True, "shopee": True})
        self.assertTrue(ok)
        self.assertEqual(so_ml["mercadolivre"][0]["order_id"], "a")
        self.assertNotIn("shopee", so_ml)

    def test_ml_falhou_fonte_false(self):
        so_ml, ok = mp.pedidos_e_fonte_impala(
            {"mercadolivre": [_ped("a", "2026-09-11T12:00:00-03:00", "IMP-MIMO-003", 1, 10)]},
            {"mercadolivre": False, "magalu": True},
        )
        self.assertFalse(ok)
        self.assertEqual(so_ml["mercadolivre"], [])


class TestEmitir(unittest.TestCase):
    @patch.object(mp, "gauge")
    def test_masterprint_sem_fonte_zera(self, mock_g):
        out = mp.emitir_periodo_cnpj(
            mp.CNPJ_MASTERPRINT, {}, fonte_ok=False, tag_produto="prod"
        )
        self.assertFalse(out["fonte_ok"])
        nomes = [c.args[0] for c in mock_g.call_args_list]
        self.assertIn("vendas.periodo.fonte_ok", nomes)
        self.assertIn("vendas.periodo.token_ausente", nomes)
        self.assertNotIn("vendas.periodo.ranking_unidades", nomes)
        self.assertIn("cnpj:masterprint", mock_g.call_args_list[0].kwargs["tags"])

    @patch.object(mp, "gauge")
    def test_impala_emite_ranking(self, mock_g):
        pedidos = {
            "mercadolivre": [
                _ped("hoje", "2026-09-11T12:00:00-03:00", "IMP-MIMO-003", 2, 40),
            ]
        }
        with patch.object(mp, "agora_brasil", return_value=_AGORA):
            out = mp.emitir_periodo_cnpj(mp.CNPJ_IMPALA, pedidos, fonte_ok=True)
        self.assertTrue(out["fonte_ok"])
        nomes = [c.args[0] for c in mock_g.call_args_list]
        self.assertIn("vendas.periodo.ranking_unidades", nomes)
        self.assertIn("vendas.periodo.ranking_receita", nomes)
        self.assertIn("vendas.periodo.sem_data", nomes)


class TestEmitirMarketplace(unittest.TestCase):
    @patch.object(mp, "gauge")
    def test_magalu_nao_usa_tag_cnpj(self, mock_g):
        pedidos = [_ped("hoje", "2026-09-11T12:00:00-03:00", "IMP-MIMO-003", 2, 40)]
        with patch.object(mp, "agora_brasil", return_value=_AGORA):
            out = mp.emitir_periodo_marketplace("magalu", pedidos, fonte_ok=True)
        self.assertTrue(out["fonte_ok"])
        tags = mock_g.call_args_list[0].kwargs["tags"]
        self.assertIn("marketplace:magalu", tags)
        self.assertTrue(all("cnpj:" not in t for c in mock_g.call_args_list for t in c.kwargs["tags"]))

    @patch.object(mp, "gauge")
    def test_magalu_fonte_false_zera(self, mock_g):
        out = mp.emitir_periodo_marketplace("magalu", [], fonte_ok=False)
        self.assertFalse(out["fonte_ok"])
        self.assertNotIn("vendas.periodo.ranking_unidades", [c.args[0] for c in mock_g.call_args_list])
