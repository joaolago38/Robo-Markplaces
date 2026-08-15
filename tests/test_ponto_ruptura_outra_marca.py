"""tests/test_ponto_ruptura_outra_marca.py"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.esmaltes import agente_ponto_ruptura_outra_marca as agente
from integracoes.esmaltes import ponto_ruptura_outra_marca as om

_CATALOGO = {
    "marca_propria": "impala",
    "amostra_minima_anuncios": 5,
    "marcas_candidatas": ["anita", "risque", "colorama", "dailus"],
}


def _canais(*, ml: str = "1651424153", shopee: str = "", magalu: str = "", amazon: str = "") -> dict:
    ids = {
        "mercadolivre": ml,
        "shopee": shopee,
        "magalu": magalu,
        "amazon": amazon,
    }
    return {
        "cnpj": "52668583000127",
        "cnpj_formatado": "52.668.583/0001-27",
        "ids": ids,
        "itens": [],
        "ml_ok": bool(ml),
        "canais_ok": sum(1 for v in ids.values() if v),
        "canais_total": 4,
    }


def _cnae(*, ok: bool = True) -> dict:
    return {
        "itens": [
            {"id": "impala_cnae_cosmetico", "ok": ok, "rotulo": "CNAE cosmético"},
        ]
    }


def _candidata(slug: str, *, score: int = 0, anuncios: int = 0, vendidos: int = 0) -> dict:
    return {
        "marca": slug.replace("_", " ").title(),
        "slug": slug,
        "score": score,
        "anuncios": anuncios,
        "vendidos": vendidos,
        "volume_proxy": 0,
        "preco_medio": 0.0,
        "elegivel": anuncios >= 2 or vendidos > 0,
    }


class TestRankingMl(unittest.TestCase):
    def test_impala_fica_de_fora_e_anita_soma(self):
        ranking = om.consolidar_ranking_ml(
            mercado={
                "ranking_marcas_global": [
                    {"marca": "Impala", "vendidos": 500, "anuncios": 20},
                    {"marca": "Anita", "vendidos": 80, "anuncios": 6, "preco_medio": 45.0},
                    {"marca": "Risque", "vendidos": 40, "anuncios": 4},
                ]
            },
            anita={
                "resultados": [
                    {
                        "ranking_marcas": [
                            {"marca": "Impala", "vendidos": 200, "anuncios": 1},
                            {"marca": "Anita", "vendidos": 120, "anuncios": 1, "preco_medio": 48.0},
                        ]
                    }
                ]
            },
            kits={"ranking_marcas": []},
        )
        slugs = [r["slug"] for r in ranking]
        self.assertNotIn("impala", slugs)
        anita = next(r for r in ranking if r["slug"] == "anita")
        self.assertEqual(anita["vendidos"], 120)
        self.assertEqual(anita["anuncios"], 6)
        self.assertGreater(anita["score"], 0)
        self.assertEqual(ranking[0]["slug"], "anita")

    def test_pontuar_preenche_marcas_zeradas(self):
        ranking = [{"marca": "Anita", "slug": "anita", "vendidos": 10, "anuncios": 3, "score": 106}]
        out = om.pontuar_candidatas(ranking, catalogo=_CATALOGO)
        slugs = [c["slug"] for c in out]
        self.assertEqual(slugs[0], "anita")
        self.assertTrue(out[0]["elegivel"])
        self.assertIn("risque", slugs)
        risque = next(c for c in out if c["slug"] == "risque")
        self.assertFalse(risque["elegivel"])
        self.assertEqual(risque["score"], 0)

    def test_um_anuncio_viral_nao_e_elegivel(self):
        out = om.pontuar_candidatas(
            [{"marca": "Anita", "slug": "anita", "vendidos": 120, "anuncios": 1, "score": 1202}],
            catalogo=_CATALOGO,
        )
        anita = next(c for c in out if c["slug"] == "anita")
        self.assertFalse(anita["elegivel"])


class TestCnpjCanais(unittest.TestCase):
    def test_ml_ok_outros_vazios(self):
        out = om.coletar_cnpj_canais(
            empresa={
                "id": "esmaltes_impala",
                "cnpj": "52.668.583/0001-27",
                "ml": {"seller_id": "1651424153"},
                "shopee": {"shop_id": ""},
                "magalu": {"seller_id": ""},
                "amazon": {"seller_id": ""},
            }
        )
        self.assertEqual(out["cnpj"], "52668583000127")
        self.assertEqual(out["cnpj_formatado"], "52.668.583/0001-27")
        self.assertTrue(out["ml_ok"])
        self.assertEqual(out["canais_ok"], 1)
        self.assertEqual(out["ids"]["mercadolivre"], "1651424153")
        self.assertFalse(out["ids"]["shopee"])

    def test_placeholder_nao_conta_como_id(self):
        out = om.coletar_cnpj_canais(
            empresa={
                "id": "esmaltes_impala",
                "cnpj": "52668583000127",
                "ml": {"seller_id": "1651424153"},
                "shopee": {"shop_id": "..."},
                "magalu": {"seller_id": "n/a"},
                "amazon": {"seller_id": "tbd"},
            }
        )
        self.assertTrue(out["ml_ok"])
        self.assertEqual(out["canais_ok"], 1)
        self.assertFalse(out["itens"][1]["ok"])


class TestAvaliacao(unittest.TestCase):
    def test_ainda_nao_radar_cego(self):
        out = om.avaliar_ruptura_outra_marca(
            ruptura_impala={"liberado": False, "aproximando": False, "veredito": "ainda_nao"},
            candidatas=[_candidata("anita"), _candidata("risque")],
            canais=_canais(ml="1651424153"),
            resumo={"anuncios_ativos": 0},
            catalogo=_CATALOGO,
            cnae=_cnae(),
        )
        self.assertEqual(out["veredito"], "ainda_nao")
        self.assertTrue(out["radar_cego"])
        self.assertEqual(out["cnpj_formatado"], "52.668.583/0001-27")
        self.assertEqual(out["marketplace_referente"], "mercadolivre")
        self.assertFalse(out["liberado"])

    def test_radar_cego_nao_e_aproximando(self):
        out = om.avaliar_ruptura_outra_marca(
            ruptura_impala={"liberado": False, "aproximando": True, "veredito": "aproximando"},
            candidatas=[_candidata("anita", score=1202, anuncios=1, vendidos=120)],
            canais=_canais(ml="1651424153"),
            resumo={"anuncios_ativos": 0},
            catalogo=_CATALOGO,
            cnae=_cnae(),
        )
        self.assertTrue(out["radar_cego"])
        self.assertNotEqual(out["veredito"], "aproximando")
        self.assertFalse(out["liberado"])

    def test_cnae_ausente_nao_passa(self):
        out = om.avaliar_ruptura_outra_marca(
            ruptura_impala={"liberado": True, "aproximando": False, "veredito": "liberado"},
            candidatas=[_candidata("anita", score=200, anuncios=8, vendidos=12)],
            canais=_canais(),
            resumo={"anuncios_ativos": 3},
            catalogo=_CATALOGO,
            cnae={"itens": []},
        )
        cnae = next(c for c in out["checks"] if c["id"] == "cnae_cosmetico")
        self.assertFalse(cnae["ok"])
        self.assertFalse(out["liberado"])

    def test_aproximando_com_impala_quase(self):
        out = om.avaliar_ruptura_outra_marca(
            ruptura_impala={"liberado": False, "aproximando": True, "veredito": "aproximando"},
            candidatas=[
                _candidata("anita", score=200, anuncios=8, vendidos=12),
                _candidata("risque", score=40, anuncios=4, vendidos=2),
            ],
            canais=_canais(),
            resumo={"anuncios_ativos": 2},
            catalogo=_CATALOGO,
            cnae=_cnae(),
        )
        self.assertEqual(out["veredito"], "aproximando")
        self.assertEqual(out["top_slug"], "anita")
        self.assertFalse(out["radar_cego"])
        self.assertFalse(out["liberado"])

    def test_liberado(self):
        out = om.avaliar_ruptura_outra_marca(
            ruptura_impala={"liberado": True, "aproximando": False, "veredito": "liberado"},
            candidatas=[
                _candidata("anita", score=200, anuncios=8, vendidos=12),
                _candidata("colorama", score=30, anuncios=3, vendidos=1),
            ],
            canais=_canais(),
            resumo={"anuncios_ativos": 3},
            catalogo=_CATALOGO,
            cnae=_cnae(),
            condicoes={"ok": True, "fase": 5},
        )
        self.assertEqual(out["veredito"], "liberado")
        self.assertTrue(out["liberado"])
        self.assertEqual(out["checks_ok"], out["checks_total"])
        self.assertEqual(out["top_marca"], "Anita")


class TestAgente(unittest.TestCase):
    def test_montar_mensagem_inclui_cnpj_e_ranking(self):
        resultado = om.avaliar_ruptura_outra_marca(
            ruptura_impala={"liberado": False, "aproximando": True, "veredito": "aproximando"},
            candidatas=[_candidata("anita", score=80, anuncios=6, vendidos=5)],
            canais=_canais(),
            resumo={"anuncios_ativos": 1},
            catalogo=_CATALOGO,
            cnae=_cnae(),
        )
        msg = agente.montar_mensagem(resultado, modo="aproximando")
        self.assertIn("52.668.583/0001-27", msg)
        self.assertIn("Anita", msg)
        self.assertIn("referente *ML*", msg)

    def test_agente_radar_cego_telegram(self):
        resultado = om.avaliar_ruptura_outra_marca(
            ruptura_impala={"liberado": False, "aproximando": False, "veredito": "ainda_nao"},
            candidatas=[_candidata("anita", score=1202, anuncios=1, vendidos=120)],
            canais=_canais(),
            resumo={"anuncios_ativos": 0},
            catalogo=_CATALOGO,
            cnae=_cnae(),
        )
        self.assertTrue(resultado["radar_cego"])
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "ponto.json"
            with (
                patch.object(agente, "avaliar_ruptura_outra_marca", return_value=resultado),
                patch.object(agente, "PONTO_RUPTURA_ATIVO", True),
                patch.object(agente, "PONTO_RUPTURA_ALERTA", True),
                patch.object(agente, "SNAPSHOT_PATH", snap),
                patch.object(agente, "gauge"),
                patch.object(agente, "incrementar"),
                patch.object(agente, "gestor_telegram_configurado", return_value=True),
                patch.object(agente, "alertar_gestor", return_value=True) as mock_tg,
                patch.object(agente, "escrever_json_atomico"),
            ):
                out = agente.executar()
        self.assertEqual(out["modo_alerta"], "radar")
        self.assertTrue(out["alerta_enviado"])
        self.assertEqual(mock_tg.call_args.kwargs["chave"], "marca_esmalte:radar")

    def test_agente_ainda_nao_sem_telegram(self):
        resultado = om.avaliar_ruptura_outra_marca(
            ruptura_impala={"liberado": False, "aproximando": False, "veredito": "ainda_nao"},
            candidatas=[
                _candidata("anita", anuncios=0),
                _candidata("risque", score=40, anuncios=6, vendidos=2),
            ],
            canais=_canais(ml=""),
            resumo={"anuncios_ativos": 0},
            catalogo=_CATALOGO,
            cnae=_cnae(ok=False),
        )
        self.assertFalse(resultado["radar_cego"])
        self.assertEqual(resultado["veredito"], "ainda_nao")
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "ponto.json"
            with (
                patch.object(agente, "avaliar_ruptura_outra_marca", return_value=resultado),
                patch.object(agente, "PONTO_RUPTURA_ATIVO", True),
                patch.object(agente, "PONTO_RUPTURA_ALERTA", True),
                patch.object(agente, "SNAPSHOT_PATH", snap),
                patch.object(agente, "gauge"),
                patch.object(agente, "incrementar"),
                patch.object(agente, "gestor_telegram_configurado", return_value=True),
                patch.object(agente, "alertar_gestor", return_value=True) as mock_tg,
                patch.object(agente, "escrever_json_atomico"),
            ):
                out = agente.executar()
        self.assertEqual(out["modo_alerta"], "ainda_nao")
        self.assertFalse(out["alerta_enviado"])
        mock_tg.assert_not_called()

    def test_agente_liberado_telegram(self):
        resultado = om.avaliar_ruptura_outra_marca(
            ruptura_impala={"liberado": True, "aproximando": False, "veredito": "liberado"},
            candidatas=[_candidata("anita", score=200, anuncios=8, vendidos=12)],
            canais=_canais(),
            resumo={"anuncios_ativos": 2},
            catalogo=_CATALOGO,
            cnae=_cnae(),
            condicoes={"ok": True, "fase": 5},
        )
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "ponto.json"
            with (
                patch.object(agente, "avaliar_ruptura_outra_marca", return_value=resultado),
                patch.object(agente, "PONTO_RUPTURA_ATIVO", True),
                patch.object(agente, "PONTO_RUPTURA_ALERTA", True),
                patch.object(agente, "SNAPSHOT_PATH", snap),
                patch.object(agente, "gauge"),
                patch.object(agente, "incrementar"),
                patch.object(agente, "gestor_telegram_configurado", return_value=True),
                patch.object(agente, "alertar_gestor", return_value=True) as mock_tg,
                patch.object(agente, "escrever_json_atomico"),
            ):
                out = agente.executar()
        self.assertEqual(out["modo_alerta"], "liberado")
        self.assertTrue(out["alerta_enviado"])
        mock_tg.assert_called_once()
        self.assertEqual(mock_tg.call_args.kwargs["agente_id"], "ponto_ruptura_outra_marca")

    def test_agente_desligado(self):
        with patch.object(agente, "PONTO_RUPTURA_ATIVO", False):
            out = agente.executar()
        self.assertEqual(out["motivo"], "agente_desligado")


if __name__ == "__main__":
    unittest.main()
