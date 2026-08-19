# -*- coding: utf-8 -*-
"""tests/test_migracao_marcas.py"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.esmaltes import migracao_marcas as mm


def _impala(*, liberado: bool = False, saude: bool = True, progresso: float = 22.2) -> dict:
    return {
        "liberado": liberado,
        "veredito": "liberado" if liberado else "ainda_nao",
        "progresso_pct": progresso,
        "checks": [
            {"id": "saude_conta", "ok": saude},
            {"id": "anuncios_foco", "ok": liberado},
        ],
        "cnae_preparacao": {
            "pronto": False,
            "seller_masterprint": "",
            "gaps": [{"id": "masterprint_seller_ml"}],
        },
    }


def _outra(*, radar_cego: bool = True, guerra: int = 0, impala_lib: bool = False) -> dict:
    return {
        "progresso_pct": 28.6,
        "radar_cego": radar_cego,
        "impala": {"veredito": "liberado" if impala_lib else "ainda_nao", "liberado": impala_lib},
        "checks": [
            {"id": "fase_guerra", "ok": guerra >= 5, "atual": guerra},
        ],
        "candidatas": [
            {"slug": "anita", "elegivel": True, "anuncios": 6},
            {"slug": "risque", "elegivel": True, "anuncios": 4},
        ],
        "cnae_preparacao": {
            "pronto": False,
            "seller_masterprint": "",
            "gaps": [{"id": "masterprint_seller_ml"}],
        },
    }


class TestMigracaoMarcas(unittest.TestCase):
    def test_catalogo_tem_fila_e_cnpjs(self):
        cat = mm.carregar_catalogo()
        self.assertEqual(cat["fila_marcas"]["proxima_obrigatoria"], "anita")
        self.assertEqual(cat["cnpjs"]["esmaltes"]["cnpj"], "52668583000127")
        self.assertTrue(cat["trilha_cnpj2"]["nao_e_fase_de_esmalte"])
        ids = [f["id"] for f in cat["fases"]]
        self.assertEqual(ids, ["F0", "F1", "F1b", "F2"])

    def test_f0_quando_impala_nao_liberou(self):
        out = mm.avaliar_migracao(ruptura_impala=_impala(), ruptura_outra=_outra())
        self.assertEqual(out["fase"], "F0")
        self.assertEqual(out["proxima_marca"], "anita")
        self.assertFalse(out["impala_liberado"])
        self.assertEqual(out["cnpj2"]["veredito"], "preparar")
        self.assertFalse(out["cnpj2"]["pode_operar"])

    def test_saude_conta_congela_em_f0(self):
        out = mm.avaliar_migracao(
            ruptura_impala=_impala(liberado=True, saude=False),
            ruptura_outra=_outra(radar_cego=False, guerra=5, impala_lib=True),
            anita_nossa=True,
        )
        self.assertEqual(out["fase"], "F0")
        self.assertTrue(out["bloqueada"])
        self.assertEqual(out["motivo_bloqueio"], "saude_conta")

    def test_f1_depois_da_ruptura_impala(self):
        out = mm.avaliar_migracao(
            ruptura_impala=_impala(liberado=True),
            ruptura_outra=_outra(radar_cego=False, guerra=5, impala_lib=True),
        )
        self.assertEqual(out["fase"], "F1")
        self.assertEqual(out["proxima_marca"], "anita")
        self.assertFalse(out["bloqueada"])

    def test_f1_bloqueia_se_guerra_abaixo_de_5(self):
        out = mm.avaliar_migracao(
            ruptura_impala=_impala(liberado=True),
            ruptura_outra=_outra(radar_cego=False, guerra=2, impala_lib=True),
        )
        self.assertEqual(out["fase"], "F1")
        self.assertTrue(out["bloqueada"])
        self.assertEqual(out["motivo_bloqueio"], "guerra_fase")
        out = mm.avaliar_migracao(
            ruptura_impala=_impala(liberado=True),
            ruptura_outra=_outra(radar_cego=True, guerra=5, impala_lib=True),
        )
        self.assertEqual(out["fase"], "F1")
        self.assertTrue(out["bloqueada"])
        self.assertEqual(out["motivo_bloqueio"], "radar_cego")

    def test_f1b_anita_no_ar_sem_pedido(self):
        out = mm.avaliar_migracao(
            ruptura_impala=_impala(liberado=True),
            ruptura_outra=_outra(radar_cego=False, guerra=5, impala_lib=True),
            anita_nossa=True,
            anita_pedido_proprio=False,
        )
        self.assertEqual(out["fase"], "F1b")

    def test_f2_anita_estavel_proxima_risque(self):
        out = mm.avaliar_migracao(
            ruptura_impala=_impala(liberado=True),
            ruptura_outra=_outra(radar_cego=False, guerra=5, impala_lib=True),
            anita_nossa=True,
            anita_pedido_proprio=True,
        )
        self.assertEqual(out["fase"], "F2")
        self.assertEqual(out["proxima_marca"], "risque")

    def test_cnpj2_aguarda_impala_quando_cnae_pronto(self):
        outra = _outra(radar_cego=False, guerra=5, impala_lib=False)
        outra["cnae_preparacao"] = {
            "pronto": True,
            "seller_masterprint": "999",
            "gaps": [],
        }
        out = mm.avaliar_migracao(ruptura_impala=_impala(liberado=False), ruptura_outra=outra)
        self.assertEqual(out["cnpj2"]["veredito"], "pronto_aguardar_impala")
        self.assertFalse(out["cnpj2"]["pode_operar"])
        self.assertTrue(out["cnpj2"]["nunca_esmalte"])

    def test_cnpj2_opera_depois_da_ruptura(self):
        outra = _outra(radar_cego=False, guerra=5, impala_lib=True)
        outra["cnae_preparacao"] = {
            "pronto": True,
            "seller_masterprint": "999",
            "gaps": [],
        }
        out = mm.avaliar_migracao(ruptura_impala=_impala(liberado=True), ruptura_outra=outra)
        self.assertEqual(out["cnpj2"]["veredito"], "liberado_operar")
        self.assertTrue(out["cnpj2"]["pode_operar"])
        self.assertEqual(out["fase"], "F1")

    @patch("integracoes.esmaltes.migracao_marcas.gauge")
    def test_emite_sem_sku(self, mock_gauge):
        estado = mm.avaliar_migracao(ruptura_impala=_impala(), ruptura_outra=_outra())
        mm.emitir_metricas_migracao(estado)
        nomes = [c.args[0] for c in mock_gauge.call_args_list]
        self.assertIn("migracao.fase", nomes)
        self.assertIn("migracao.saude_conta", nomes)
        for c in mock_gauge.call_args_list:
            tags = c.kwargs.get("tags") or []
            self.assertFalse(any(str(t).startswith("sku:") for t in tags))
            self.assertFalse(any(str(t).startswith("item:") for t in tags))


if __name__ == "__main__":
    unittest.main()
