"""tests/test_ponto_ruptura_segundo_cnpj.py"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.empresa import agente_ponto_ruptura_segundo_cnpj as agente
from integracoes.empresa import ponto_ruptura_segundo_cnpj as pr


def _kits(*, mlb_ok: bool = True, estoque: int = 60) -> list[dict]:
    mlb = "MLB123" if mlb_ok else "MLB_PREENCHER"
    return [
        {
            "sku": "IMP-MIMO-003",
            "mlb": mlb,
            "mlb_ok": mlb_ok,
            "estoque": estoque,
            "encontrado": True,
        },
        {
            "sku": "IMP-SORT-006",
            "mlb": "MLB456" if mlb_ok else "",
            "mlb_ok": mlb_ok,
            "estoque": estoque,
            "encontrado": True,
        },
    ]


def _sinais(**kw) -> dict:
    base = {
        "avaliacoes": 0,
        "nota": 0.0,
        "vendas_completadas": 0,
        "claims_rate": 0.0,
        "claims": 0,
        "kits": _kits(mlb_ok=False, estoque=0),
        "itens_margem": 0,
        "receita_bruta": 0.0,
        "acos": 0.0,
        "decisao_ads": "",
    }
    base.update(kw)
    return base


def _cnae(*, seller: str = "999", pronto: bool = True) -> dict:
    itens = [
        {"id": "impala_cnae_cosmetico", "ok": True, "rotulo": "Impala CNAE"},
        {"id": "masterprint_cnae_informatica", "ok": True, "rotulo": "TI"},
        {"id": "masterprint_cnae_resinas", "ok": True, "rotulo": "resinas"},
        {"id": "masterprint_cnae_papelaria", "ok": True, "rotulo": "papelaria"},
        {
            "id": "masterprint_seller_ml",
            "ok": bool(seller),
            "rotulo": "Seller ML Masterprint",
        },
        {"id": "cnpjs_nao_ambiguos", "ok": True, "rotulo": "sellers distintos"},
    ]
    if not pronto:
        itens[4]["ok"] = False
        seller = ""
    gaps = [c for c in itens if not c["ok"]]
    return {
        "itens": itens,
        "gaps": gaps,
        "gaps_n": len(gaps),
        "pronto": len(gaps) == 0,
        "seller_masterprint": seller,
        "cnpj_masterprint": "23.811.261/0001-97",
        "cnpj_impala": "52.668.583/0001-27",
    }


class TestMlbPreenchido(unittest.TestCase):
    def test_placeholder_e_vazio(self):
        self.assertFalse(pr.mlb_preenchido(""))
        self.assertFalse(pr.mlb_preenchido("MLB_PREENCHER"))
        self.assertFalse(pr.mlb_preenchido("sku-interno"))
        self.assertTrue(pr.mlb_preenchido("MLB123456"))


class TestColetarSinais(unittest.TestCase):
    def test_injetados(self):
        produtos = [
            {
                "sku": "IMP-MIMO-003",
                "estoque_total": 40,
                "canais": {"mercadolivre": {"item_id": "MLB1", "estoque": 40}},
            },
            {
                "sku": "IMP-SORT-006",
                "canais": {"mercadolivre": {"item_id": "MLB_PREENCHER", "estoque": 0}},
            },
        ]
        s = pr.coletar_sinais_impala(
            reputacao={
                "metrics": {
                    "total_ratings": 5,
                    "average_rating": 4.2,
                    "transactions": {"completed": 2},
                    "claims": {"rate": 0.01},
                }
            },
            produtos=produtos,
            margem={"analise": {"total_itens": 1, "receita_bruta": 80.5}},
            ads={"acos_atual": 0.11, "decisao": "aguardar"},
            resumo={"pos_venda_claims": 0},
        )
        self.assertEqual(s["avaliacoes"], 5)
        self.assertAlmostEqual(s["nota"], 4.2)
        self.assertEqual(s["vendas_completadas"], 2)
        self.assertEqual(s["itens_margem"], 1)
        self.assertTrue(s["kits"][0]["mlb_ok"])
        self.assertFalse(s["kits"][1]["mlb_ok"])
        self.assertEqual(s["kits"][0]["estoque"], 40)


class TestAvaliacao(unittest.TestCase):
    def test_ainda_nao(self):
        out = pr.avaliar_ponto_ruptura(
            sinais=_sinais(),
            cnae=_cnae(pronto=False),
            avaliacoes_min=20,
            nota_min=4.8,
            estoque_min=30,
            aproximando_avaliacoes=10,
        )
        self.assertEqual(out["veredito"], "ainda_nao")
        self.assertFalse(out["liberado"])
        self.assertFalse(out["aproximando"])
        self.assertEqual(out["cnae_preparacao"]["gaps_n"], 1)

    def test_aproximando_por_avaliacoes(self):
        out = pr.avaliar_ponto_ruptura(
            sinais=_sinais(avaliacoes=12, nota=4.5),
            cnae=_cnae(pronto=True),
            avaliacoes_min=20,
            nota_min=4.8,
            estoque_min=30,
            aproximando_avaliacoes=10,
        )
        self.assertEqual(out["veredito"], "aproximando")
        self.assertTrue(out["aproximando"])
        self.assertFalse(out["liberado"])

    def test_liberado(self):
        out = pr.avaliar_ponto_ruptura(
            sinais=_sinais(
                avaliacoes=22,
                nota=4.9,
                vendas_completadas=3,
                claims=0,
                kits=_kits(mlb_ok=True, estoque=60),
                itens_margem=1,
                acos=0.12,
            ),
            cnae=_cnae(pronto=True),
            avaliacoes_min=20,
            nota_min=4.8,
            estoque_min=30,
            acos_max=0.20,
        )
        self.assertEqual(out["veredito"], "liberado")
        self.assertTrue(out["liberado"])
        self.assertEqual(out["checks_ok"], out["checks_total"])


class TestPreparacaoCnae(unittest.TestCase):
    def test_seller_vazio_e_gap(self):
        out = pr.coletar_preparacao_cnae(
            esmaltes={
                "cnpj": "52668583000127",
                "cnaes": [{"codigo": "4772-5/00"}],
                "ml": {"seller_id": "111"},
            },
            masterprint={
                "cnpj": "23811261000197",
                "cnaes": [
                    {"codigo": "4751-2/01"},
                    {"codigo": "4689-3/02"},
                    {"codigo": "4761-0/03"},
                ],
                "ml": {"seller_id": ""},
            },
        )
        self.assertFalse(out["pronto"])
        self.assertGreaterEqual(out["gaps_n"], 1)
        ids = {g["id"] for g in out["gaps"]}
        self.assertIn("masterprint_seller_ml", ids)

    def test_catalogo_pronto_quando_seller_preenchido(self):
        out = pr.coletar_preparacao_cnae(
            esmaltes={
                "cnpj": "52668583000127",
                "cnaes": [{"codigo": "4772-5/00"}],
                "ml": {"seller_id": "111"},
            },
            masterprint={
                "cnpj": "23811261000197",
                "cnaes": [
                    {"codigo": "4751-2/01"},
                    {"codigo": "4689-3/02"},
                    {"codigo": "4761-0/03"},
                ],
                "ml": {"seller_id": "222"},
            },
        )
        self.assertTrue(out["pronto"])
        self.assertEqual(out["gaps_n"], 0)

    def test_cnae_codigo_norm_e_string(self):
        out = pr.coletar_preparacao_cnae(
            esmaltes={
                "cnpj": "52668583000127",
                "cnaes": [{"codigo_norm": "4772500"}],
                "ml": {"seller_id": "111"},
            },
            masterprint={
                "cnpj": "23811261000197",
                "cnaes": ["4751-2/01", "4689302", "4761-0/03"],
                "ml": {"seller_id": "222"},
            },
        )
        self.assertTrue(out["pronto"])

    def test_import_falha_usa_dicts_vazios(self):
        with patch(
            "core.empresa.catalogo.empresa_por_id",
            side_effect=RuntimeError("sem catalogo"),
        ):
            out = pr.coletar_preparacao_cnae()
        self.assertFalse(out["pronto"])
        self.assertGreaterEqual(out["gaps_n"], 1)

    def test_catalogo_real_cnaes_ok_seller_vazio(self):
        out = pr.coletar_preparacao_cnae()
        ids_ok = {c["id"] for c in out["itens"] if c["ok"]}
        self.assertIn("impala_cnae_cosmetico", ids_ok)
        self.assertIn("masterprint_cnae_informatica", ids_ok)
        self.assertIn("masterprint_cnae_resinas", ids_ok)
        self.assertIn("masterprint_cnae_papelaria", ids_ok)


class TestMensagemEAgente(unittest.TestCase):
    def test_montar_mensagem_cnae(self):
        resultado = pr.avaliar_ponto_ruptura(
            sinais=_sinais(),
            cnae=_cnae(pronto=False),
        )
        msg = agente.montar_mensagem(resultado, modo="cnae")
        self.assertIn("prepare o segundo CNPJ", msg)
        self.assertIn("23.811.261/0001-97", msg)
        self.assertIn("Checklist Impala", msg)

    def test_agente_alerta_cnae_mesmo_ainda_nao(self):
        resultado = pr.avaliar_ponto_ruptura(
            sinais=_sinais(),
            cnae=_cnae(pronto=False),
        )
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "ponto.json"
            with (
                patch.object(agente, "avaliar_ponto_ruptura", return_value=resultado),
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
        self.assertEqual(out["modo_alerta"], "cnae")
        self.assertTrue(out["alerta_enviado"])
        mock_tg.assert_called_once()
        self.assertEqual(mock_tg.call_args.kwargs["chave"], "ponto_ruptura:cnae_prep")

    def test_agente_ainda_nao_sem_gap_nao_telegram(self):
        resultado = pr.avaliar_ponto_ruptura(
            sinais=_sinais(),
            cnae=_cnae(pronto=True),
        )
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "ponto.json"
            with (
                patch.object(agente, "avaliar_ponto_ruptura", return_value=resultado),
                patch.object(agente, "PONTO_RUPTURA_ATIVO", True),
                patch.object(agente, "PONTO_RUPTURA_ALERTA", True),
                patch.object(agente, "SNAPSHOT_PATH", snap),
                patch.object(agente, "gauge"),
                patch.object(agente, "incrementar"),
                patch.object(agente, "gestor_telegram_configurado", return_value=True),
                patch.object(agente, "alertar_gestor") as mock_tg,
                patch.object(agente, "escrever_json_atomico"),
            ):
                out = agente.executar()
        self.assertEqual(out["veredito"], "ainda_nao")
        self.assertFalse(out["alerta_enviado"])
        mock_tg.assert_not_called()

    def test_agente_liberado_telegram(self):
        resultado = pr.avaliar_ponto_ruptura(
            sinais=_sinais(
                avaliacoes=22,
                nota=4.9,
                vendas_completadas=3,
                kits=_kits(mlb_ok=True, estoque=60),
                itens_margem=1,
            ),
            cnae=_cnae(pronto=True),
        )
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "ponto.json"
            with (
                patch.object(agente, "avaliar_ponto_ruptura", return_value=resultado),
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
        self.assertEqual(mock_tg.call_args.kwargs["chave"], "ponto_ruptura:liberado")

    def test_agente_desligado(self):
        with patch.object(agente, "PONTO_RUPTURA_ATIVO", False):
            out = agente.executar()
        self.assertEqual(out["motivo"], "agente_desligado")

    def test_agente_forcar_ainda_nao(self):
        resultado = pr.avaliar_ponto_ruptura(sinais=_sinais(), cnae=_cnae(pronto=True))
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "ponto.json"
            with (
                patch.object(agente, "avaliar_ponto_ruptura", return_value=resultado),
                patch.object(agente, "PONTO_RUPTURA_ATIVO", True),
                patch.object(agente, "PONTO_RUPTURA_ALERTA", True),
                patch.object(agente, "SNAPSHOT_PATH", snap),
                patch.object(agente, "gauge"),
                patch.object(agente, "incrementar"),
                patch.object(agente, "gestor_telegram_configurado", return_value=True),
                patch.object(agente, "alertar_gestor", return_value=True) as mock_tg,
                patch.object(agente, "escrever_json_atomico"),
            ):
                out = agente.executar(forcar=True)
        self.assertTrue(out["alerta_enviado"])
        self.assertEqual(mock_tg.call_args.kwargs["chave"], "ponto_ruptura:forcar")

    def test_agente_telegram_nao_configurado(self):
        resultado = pr.avaliar_ponto_ruptura(sinais=_sinais(), cnae=_cnae(pronto=False))
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "ponto.json"
            with (
                patch.object(agente, "avaliar_ponto_ruptura", return_value=resultado),
                patch.object(agente, "PONTO_RUPTURA_ATIVO", True),
                patch.object(agente, "PONTO_RUPTURA_ALERTA", True),
                patch.object(agente, "SNAPSHOT_PATH", snap),
                patch.object(agente, "gauge"),
                patch.object(agente, "incrementar"),
                patch.object(agente, "gestor_telegram_configurado", return_value=False),
                patch.object(agente, "alertar_gestor") as mock_tg,
                patch.object(agente, "escrever_json_atomico"),
            ):
                out = agente.executar()
        self.assertFalse(out["alerta_enviado"])
        mock_tg.assert_not_called()

    def test_agente_falha_capturada(self):
        with (
            patch.object(agente, "PONTO_RUPTURA_ATIVO", True),
            patch.object(agente, "avaliar_ponto_ruptura", side_effect=RuntimeError("boom")),
            patch.object(agente, "incrementar"),
            patch.object(agente, "escrever_json_atomico"),
        ):
            out = agente.executar()
        self.assertFalse(out["ok"])
        self.assertIn("boom", out["erro"])

    def test_montar_mensagem_liberado_e_aproximando(self):
        resultado = pr.avaliar_ponto_ruptura(
            sinais=_sinais(
                avaliacoes=22,
                nota=4.9,
                vendas_completadas=3,
                kits=_kits(mlb_ok=True, estoque=60),
                itens_margem=1,
            ),
            cnae=_cnae(pronto=True),
        )
        lib = agente.montar_mensagem(resultado, modo="liberado")
        self.assertIn("LIBERADO", lib)
        self.assertIn("CNPJ_DONO_PRODUTOS_USAR_ALVO", lib)
        aprox = agente.montar_mensagem(resultado, modo="aproximando")
        self.assertIn("aproximando", aprox)

    def test_aproximando_por_checks_sem_20_reviews(self):
        out = pr.avaliar_ponto_ruptura(
            sinais=_sinais(
                avaliacoes=0,
                kits=_kits(mlb_ok=True, estoque=60),
                itens_margem=1,
            ),
            cnae=_cnae(pronto=True),
            avaliacoes_min=20,
            estoque_min=30,
        )
        self.assertEqual(out["veredito"], "aproximando")
        self.assertGreaterEqual(out["checks_ok"], 5)


if __name__ == "__main__":
    unittest.main()
