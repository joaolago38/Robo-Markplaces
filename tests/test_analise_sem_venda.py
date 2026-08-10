"""
tests/test_analise_sem_venda.py
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.ml import agente_monitor_sem_venda_ml as ag
from integracoes.ml import analise_sem_venda as sv


class TestAnaliseSemVenda(unittest.TestCase):
    def test_detecta_sem_venda_e_sugere_acao(self):
        anuncios = [
            {"item_id": "MLB1", "titulo": "Kit A", "preco": 48.9, "sku": "A", "sold_quantity": 0},
            {"item_id": "MLB2", "titulo": "Kit B", "preco": 30.0, "sku": "B", "sold_quantity": 5},
        ]
        out = sv.analisar_anuncios_sem_venda(
            anuncios,
            {"MLB2"},
            {"MLB1": {"visitas_30d": 50, "visitas_7d": 10}},
            visitas_altas=20,
        )
        self.assertEqual(out["total_sem_venda"], 1)
        self.assertEqual(out["itens"][0]["acao"], "baixar_preco_ou_listing")
        msg = sv.montar_mensagem_sem_venda(out)
        self.assertIn("sem venda", msg.lower())

    def test_sem_visitas_sugere_republicar(self):
        out = sv.analisar_anuncios_sem_venda(
            [{"item_id": "MLB9", "titulo": "X", "preco": 10}],
            set(),
            {"MLB9": {"visitas_30d": 0}},
        )
        self.assertEqual(out["itens"][0]["acao"], "republicar_ou_ads")

    def test_sugerir_acao_com_venda_conversao_baixa(self):
        self.assertEqual(
            sv.sugerir_acao(
                visitas_30d=40,
                unidades_periodo=1,
                conversao_pct=1.5,
                conversao_confiavel=True,
                conv_baixa_pct=2.0,
            ),
            "melhorar_conversao_listing",
        )

    def test_sugerir_acao_usa_visitas_7d_se_30_zerada(self):
        self.assertEqual(
            sv.sugerir_acao(visitas_30d=0, visitas_7d=25, visitas_altas=20),
            "baixar_preco_ou_listing",
        )


class TestAgenteSemVenda(unittest.TestCase):
    @patch.object(ag, "alertar_gestor", return_value=True)
    @patch.object(ag, "gestor_telegram_configurado", return_value=True)
    @patch.object(ag, "buscar_metricas_item", return_value={"visitas_30d": 25, "visitas_7d": 5})
    @patch.object(ag, "listar_pedidos_detalhado", return_value=([], True))
    @patch.object(
        ag,
        "listar_meus_anuncios",
        return_value=[{"item_id": "MLB1", "titulo": "Kit", "preco": 40.0, "sku": "K1"}],
    )
    def test_executar_envia_quando_ha_sem_venda(self, *_):
        out = ag.executar(enviar_alerta=True, dias=30)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_sem_venda"], 1)
        self.assertTrue(out["enviado"])


if __name__ == "__main__":
    unittest.main()
