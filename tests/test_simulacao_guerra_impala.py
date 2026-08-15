"""tests/test_simulacao_guerra_impala.py"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integracoes.esmaltes import simulacao_guerra_impala as sg


def _prod(sku: str, preco: float, custo: float, *, item: str = "MLB_PREENCHER", est: int = 0):
    return {
        "sku": sku,
        "custo_total": custo,
        "fase_atual": 1,
        "preco": preco,
        "estoque_total": est,
        "canais": {
            "mercadolivre": {
                "item_id": item,
                "preco": preco,
                "estoque": est,
                "taxa_canal_pct": 18.0,
            }
        },
    }


FRENTE = [
    _prod("IMP-MIMO-003", 44.9, 28.13),
    _prod("IMP-PERL-004", 39.9, 26.23),
    _prod("IMP-JUPAES-006", 64.9, 41.42),
]


def _por_sku(frente: list[dict], sku: str) -> dict:
    return next(x for x in frente if x.get("sku") == sku)


class TestSimulacaoGuerra(unittest.TestCase):
    def setUp(self):
        self.fx = sg.carregar_fixture()
        self.assertTrue(self.fx.get("cenarios"))

    def _cenario(self, cid: str) -> dict:
        for c in self.fx.get("cenarios") or []:
            if c.get("id") == cid:
                return c
        self.fail(f"cenário {cid} ausente")

    def test_hidratar_nao_muta_catalogo(self):
        original = copy.deepcopy(FRENTE)
        out = sg.hidratar_produtos_simulados(
            FRENTE, nossos_mlb=self.fx["nossos_mlb"], estoque=60
        )
        self.assertEqual(FRENTE, original)
        mimo = next(p for p in out if p["sku"] == "IMP-MIMO-003")
        self.assertEqual(mimo["canais"]["mercadolivre"]["item_id"], "MLB9000110003")
        self.assertEqual(mimo["estoque_total"], 60)
        self.assertEqual(FRENTE[0]["canais"]["mercadolivre"]["item_id"], "MLB_PREENCHER")

    def test_hoje_sem_mlb_ignora(self):
        r = sg.rodar_cenario(self._cenario("hoje"), fixture=self.fx, produtos=FRENTE)
        self.assertFalse(r["hidratar_nossos"])
        self.assertFalse(r["golpe"]["disparar"])
        por = {_por_sku(r["frente"], s["sku"])["sku"]: s for s in r["frente"]}
        for sku in ("IMP-MIMO-003", "IMP-PERL-004", "IMP-JUPAES-006"):
            self.assertEqual(por[sku]["classificacao"], "ignorar")
            self.assertFalse(por[sku]["mlb_ok"])
        for s in r["guerra_status"]:
            if s["sku"] in ("IMP-MIMO-003", "IMP-PERL-004", "IMP-JUPAES-006"):
                self.assertFalse(s["mlb_ok"])
                self.assertIn("sem_mlb", s["bloqueios"] or [])
                self.assertIn("estoque_zero", s["bloqueios"] or [])

    def test_igual_para_igual_mimo_diferencia_perl_nao_corta(self):
        r = sg.rodar_cenario(
            self._cenario("igual_para_igual"), fixture=self.fx, produtos=FRENTE
        )
        por = {s["sku"]: s for s in r["frente"]}
        mimo = por["IMP-MIMO-003"]
        perl = por["IMP-PERL-004"]
        jup = por["IMP-JUPAES-006"]
        self.assertEqual(mimo["classificacao"], "diferenciar")
        self.assertTrue(mimo["disparar"])
        self.assertEqual(mimo["rival_min"], 42.9)
        self.assertNotEqual(mimo["rival_min"], mimo["nosso_preco"])
        self.assertEqual(perl["classificacao"], "ignorar")
        self.assertFalse(perl["disparar"])
        self.assertEqual(perl["rival_min"], 39.0)
        self.assertEqual(jup["classificacao"], "ignorar")
        self.assertEqual(r["golpe"]["sku"], "IMP-MIMO-003")
        self.assertEqual(r["golpe"]["classificacao"], "diferenciar")
        self.assertEqual(r["golpe"]["arma"], "listing")
        for s in r["guerra_status"]:
            if s["sku"] in ("IMP-MIMO-003", "IMP-PERL-004", "IMP-JUPAES-006"):
                self.assertTrue(s["mlb_ok"])
                self.assertTrue(s["pode_impulsionar"])
                self.assertNotIn("estoque_zero", s["bloqueios"] or [])

    def test_perl_pressionado_iguala_na_faixa(self):
        r = sg.rodar_cenario(
            self._cenario("perl_pressionado"), fixture=self.fx, produtos=FRENTE
        )
        perl = _por_sku(r["frente"], "IMP-PERL-004")
        self.assertEqual(perl["classificacao"], "igualar_faixa")
        self.assertTrue(perl["disparar"])
        self.assertEqual(perl["rival_min"], 37.0)
        self.assertGreaterEqual(perl["rival_min"], perl["piso_preco"])
        self.assertEqual(r["golpe"]["sku"], "IMP-PERL-004")
        self.assertEqual(r["golpe"]["classificacao"], "igualar_faixa")
        self.assertEqual(r["golpe"]["arma"], "preco")

    def test_dump_nao_perseguir(self):
        r = sg.rodar_cenario(
            self._cenario("dump_abaixo_piso"), fixture=self.fx, produtos=FRENTE
        )
        perl = _por_sku(r["frente"], "IMP-PERL-004")
        self.assertEqual(perl["classificacao"], "nao_perseguir")
        self.assertTrue(perl["disparar"])
        self.assertEqual(perl["rival_min"], 29.9)
        self.assertLess(perl["rival_min"], perl["piso_preco"])
        self.assertEqual(r["golpe"]["sku"], "IMP-PERL-004")
        self.assertEqual(r["golpe"]["classificacao"], "nao_perseguir")

    def test_filtra_nosso_mlb_da_amostra_rival(self):
        rivais = sg._filtrar_rivais(
            [
                {"item_id": "MLB9000110003", "preco": 10, "seller_id": "1"},
                {"item_id": "MLB9000210003", "preco": 42.9, "seller_id": "1666381510"},
                {"item_id": "MLB9X", "preco": 1, "seller_id": "1651424153"},
            ],
            nossos_mlb=self.fx["nossos_mlb"],
            seller_id_nosso=self.fx["seller_id_nosso"],
        )
        self.assertEqual(len(rivais), 1)
        self.assertEqual(rivais[0]["item_id"], "MLB9000210003")

    def test_rodar_nao_grava_produtos_json(self):
        from core.catalogo_produtos import carregar_produtos_catalogo

        antes = {
            str(p.get("sku")): ((p.get("canais") or {}).get("mercadolivre") or {}).get("item_id")
            for p in carregar_produtos_catalogo()
            if str(p.get("sku") or "").startswith("IMP-")
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sg, "SNAPSHOT_PATH", Path(tmp) / "snap.json"):
                out = sg.rodar_simulacao(cenario_id="igual_para_igual")
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("simulacao"))
        depois = {
            str(p.get("sku")): ((p.get("canais") or {}).get("mercadolivre") or {}).get("item_id")
            for p in carregar_produtos_catalogo()
            if str(p.get("sku") or "").startswith("IMP-")
        }
        self.assertEqual(antes, depois)
        self.assertEqual(antes.get("IMP-MIMO-003"), "MLB_PREENCHER")
        go = {x["sku"]: x for x in (out.get("catalogo_real") or [])}
        self.assertFalse(go["IMP-MIMO-003"]["mlb_ok"])
        self.assertFalse(go["IMP-MIMO-003"]["estoque_ok"])
