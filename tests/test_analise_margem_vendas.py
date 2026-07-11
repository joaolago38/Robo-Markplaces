"""
tests/test_analise_margem_vendas.py
tests/test_agente_monitor_margem_vendas.py (mesmo arquivo)
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.vendas import agente_monitor_margem_vendas as ag
from integracoes.vendas import analise_margem_vendas as margem


_PRODUTOS = [
    {
        "sku": "IMP-BAIL-005",
        "custo": 25.0,
        "canais": {"mercadolivre": {"taxa_canal_pct": 18.0, "preco": 48.9}},
    }
]


class TestAnaliseMargemVendas(unittest.TestCase):
    def test_margem_ok(self):
        pedidos = {
            "mercadolivre": [
                {
                    "order_id": "1",
                    "itens": [
                        {"sku": "IMP-BAIL-005", "quantidade": 1, "preco_unitario": 48.9}
                    ],
                }
            ]
        }
        out = margem.analisar_pedidos(pedidos, _PRODUTOS, margem_min_pct=15.0)
        self.assertEqual(out["total_itens"], 1)
        self.assertEqual(out["total_alertas"], 0)
        self.assertEqual(out["linhas"][0]["status"], "ok")
        self.assertGreater(out["linhas"][0]["margem_operacional_pct"], 15.0)

    def test_prejuizo_e_alerta(self):
        pedidos = {
            "shopee": [
                {
                    "order_id": "2",
                    "itens": [
                        {"sku": "IMP-BAIL-005", "quantidade": 1, "preco_unitario": 20.0}
                    ],
                }
            ]
        }
        out = margem.analisar_pedidos(pedidos, _PRODUTOS, margem_min_pct=15.0)
        self.assertEqual(out["total_alertas"], 1)
        self.assertEqual(out["linhas"][0]["status"], "prejuizo")
        msg = margem.montar_mensagem_alerta_baixa(out["linhas"][0], margem_min_pct=15.0)
        self.assertIn("Prejuízo", msg)

    def test_sem_custo(self):
        pedidos = {
            "amazon": [
                {
                    "order_id": "3",
                    "itens": [{"sku": "SKU-X", "quantidade": 1, "preco_unitario": 50.0}],
                }
            ]
        }
        out = margem.analisar_pedidos(pedidos, _PRODUTOS, margem_min_pct=15.0)
        self.assertEqual(out["linhas"][0]["status"], "sem_custo")
        self.assertEqual(out["total_alertas"], 0)
        self.assertEqual(out["total_incompletos"], 1)

    def test_mensagem_resumo(self):
        pedidos = {
            "mercadolivre": [
                {
                    "order_id": "1",
                    "itens": [
                        {"sku": "IMP-BAIL-005", "quantidade": 2, "preco_unitario": 48.9}
                    ],
                }
            ]
        }
        out = margem.analisar_pedidos(pedidos, _PRODUTOS, margem_min_pct=15.0)
        txt = margem.montar_mensagem_resumo(out, dias=2)
        self.assertIn("Margem das vendas", txt)
        self.assertIn("Mercado Livre", txt)


class TestAgenteMonitorMargem(unittest.TestCase):
    @patch.object(ag, "_salvar_alertadas")
    @patch.object(ag, "_carregar_alertadas", return_value=set())
    @patch.object(ag, "alertar_gestor", return_value=True)
    @patch.object(ag, "gestor_telegram_configurado", return_value=True)
    @patch.object(ag, "_carregar_produtos", return_value=_PRODUTOS)
    @patch.object(
        ag,
        "_buscar_pedidos",
        return_value=(
            {
                "mercadolivre": [
                    {
                        "order_id": "99",
                        "itens": [
                            {
                                "sku": "IMP-BAIL-005",
                                "quantidade": 1,
                                "preco_unitario": 22.0,
                            }
                        ],
                    }
                ]
            },
            {"mercadolivre": True},
        ),
    )
    def test_envia_alerta_margem_baixa(self, *_):
        out = ag.executar(enviar_alerta=True, dias=1, margem_min_pct=15.0)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["total_alertas"], 1)
        self.assertGreaterEqual(out["alertas_enviados"], 1)

    @patch.object(ag, "alertar_gestor")
    @patch.object(ag, "gestor_telegram_configurado", return_value=True)
    @patch.object(ag, "_carregar_produtos", return_value=_PRODUTOS)
    @patch.object(ag, "_buscar_pedidos", return_value=({}, {"mercadolivre": True}))
    def test_sem_vendas_nao_quebra(self, *_):
        out = ag.executar(enviar_alerta=False, dias=1)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_itens"], 0)


if __name__ == "__main__":
    unittest.main()
