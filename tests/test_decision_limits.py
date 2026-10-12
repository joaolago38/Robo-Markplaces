"""tests/test_decision_limits.py"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integracoes.empresa import decision_limits as dl


class TestDecisionLimits(unittest.TestCase):
    def test_bloquear_import_cambio_instavel(self):
        with patch.object(
            dl,
            "coletar_sinais_cambio",
            return_value={
                "ok": True,
                "usd_brl": 5.8,
                "confiavel": False,
                "variacao_pct": 3.0,
                "volatil": True,
                "bloquear_import_por_fx": True,
            },
        ), patch.object(
            dl,
            "coletar_sinais_alibaba",
            return_value={"ok": True, "lucrativos": 2, "bloqueado": False, "tem_sinal_importar": True},
        ), patch.object(
            dl,
            "coletar_sinais_vendas",
            return_value={
                "ok": True,
                "margem_media_pct": 20.0,
                "total_alertas": 0,
                "abaixo_minimo": False,
                "saudavel": True,
            },
        ), patch.object(
            dl,
            "coletar_sinais_saude_produto",
            return_value={
                "ok": True,
                "degradado": False,
                "a_melhorar": 1,
                "perguntas": 0,
                "claims": 0,
                "nivel_ml": "ok",
                "nivel_ord": 1,
                "sem_venda": 0,
            },
        ), patch.object(
            dl,
            "coletar_sinais_volume_ml_cnae",
            return_value={"ok": True, "quantidade_vendida": 5, "volume_receita_proxy": 100.0},
        ), patch.object(
            dl,
            "coletar_sinais_destino_importacao",
            return_value={"destino_cep": "13467-694", "aeroporto_codigo": "VCP", "distancia_km": 120},
        ):
            lim = dl.computar_limites(
                vinculo={
                    "cnpj": "52668583000127",
                    "cnpj_formatado": "52.668.583/0001-27",
                    "empresa_id": "esmaltes_impala",
                    "cnae_principal": "4772-5/00",
                    "ramos": ["esmaltes"],
                    "produtos": {"total_skus": 10},
                }
            )
        self.assertFalse(lim["limites"]["permitidos"]["importar_alibaba"])
        self.assertTrue(
            any(b["motivo"] == "cambio_instavel_ou_nao_confiavel" for b in lim["bloqueios"])
        )

    def test_bloquear_ads_saude_critica(self):
        with patch.object(dl, "coletar_sinais_cambio", return_value={
            "ok": True, "usd_brl": 5.5, "confiavel": True, "variacao_pct": 0.1,
            "volatil": False, "bloquear_import_por_fx": False,
        }), patch.object(dl, "coletar_sinais_alibaba", return_value={
            "ok": True, "lucrativos": 0, "bloqueado": False, "tem_sinal_importar": False,
        }), patch.object(dl, "coletar_sinais_vendas", return_value={
            "ok": True, "margem_media_pct": 18.0, "total_alertas": 0, "abaixo_minimo": False, "saudavel": True,
        }), patch.object(dl, "coletar_sinais_saude_produto", return_value={
            "ok": True, "degradado": False, "a_melhorar": 0, "perguntas": 0, "claims": 3,
            "nivel_ml": "critico", "nivel_ord": 3, "sem_venda": 0,
        }), patch.object(dl, "coletar_sinais_volume_ml_cnae", return_value={
            "ok": True, "quantidade_vendida": 10, "volume_receita_proxy": 200.0,
        }), patch.object(dl, "coletar_sinais_destino_importacao", return_value={
            "destino_cep": "13467-694", "aeroporto_codigo": "VCP",
        }):
            lim = dl.computar_limites(
                vinculo={"cnpj": "23811261000197", "empresa_id": "masterprint", "cnae_principal": "4751-2/01", "ramos": ["petg"], "produtos": {}}
            )
        self.assertFalse(lim["limites"]["permitidos"]["impulsionar_ads"])
        ok, motivo = dl.pode_decidir("impulsionar_ads", lim)
        self.assertFalse(ok)
        self.assertIn("saude", motivo)

    def test_aplicar_limites_filtra_fazer(self):
        lim = {
            "ok": True,
            "contexto": {"cnpj": "52668583000127", "empresa_id": "esmaltes_impala"},
            "limites": {
                "max_acoes_fazer": 2,
                "permitidos": {
                    "responder_perguntas": True,
                    "corrigir_anuncio": True,
                    "impulsionar_ads": False,
                    "importar_alibaba": False,
                    "ajustar_preco": True,
                    "tratar_claims": True,
                    "despachar_envios": True,
                    "migrar_dono": True,
                    "rodar_agentes_ramo": True,
                },
            },
            "bloqueios": [
                {"tema": "impulsionar_ads", "motivo": "saude_ml_critica", "acao": "bloquear"}
            ],
            "sinais": {
                "cambio": {"usd_brl": 5.4, "bloquear_import_por_fx": False},
                "alibaba": {"lucrativos": 0},
                "vendas": {"margem_media_pct": 16.0},
                "saude_produto": {"nivel_ml": "atencao", "degradado": False},
            },
            "resumo_humano": "teste",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(dl, "CUPOS_PATH", Path(tmp) / "cupos.json"):
                out = dl.aplicar_limites_nas_acoes(
                    {
                        "fazer": [
                            "Responder *3* pergunta(s) pendente(s) no ML",
                            "Corrigir *2* anúncio(s) a melhorar",
                            "Impulsionar Ads agora",
                        ],
                        "nao_fazer": [],
                        "custo": [],
                        "urgencia": "baixa",
                    },
                    lim,
                    registrar=True,
                )
        self.assertEqual(len(out["fazer"]), 2)
        self.assertTrue(any("impulsionar_ads" in x for x in out["nao_fazer"]))
        self.assertTrue(out["limites_aplicados"])

    @patch("integracoes.empresa.decision_limits.gauge")
    @patch("integracoes.empresa.decision_limits.incrementar")
    def test_emitir_metricas(self, mock_inc, mock_gauge):
        lim = {
            "ok": True,
            "contexto": {
                "empresa_id": "esmaltes_impala",
                "cnae_principal": "4772-5/00",
                "ramos": ["esmaltes"],
                "total_skus": 5,
            },
            "limites": {"max_acoes_fazer": 3, "cupos_restantes": {"a": 1, "b": 0}},
            "sinais": {
                "saude_produto": {"nivel_ord": 2, "a_melhorar": 1, "perguntas": 2, "claims": 0, "sem_venda": 0},
                "cambio": {"usd_brl": 5.5, "confiavel": True},
                "alibaba": {"lucrativos": 1},
                "vendas": {"margem_media_pct": 17.0},
            },
            "bloqueios": [{"tema": "importar_alibaba", "motivo": "dolar_volatil"}],
        }
        dl.emitir_metricas(lim)
        self.assertTrue(mock_gauge.called)
        self.assertTrue(mock_inc.called)
        nomes = [c.args[0] for c in mock_gauge.call_args_list]
        self.assertIn("decision_limits.max_acoes_fazer", nomes)
        self.assertIn("decision_limits.usd_brl", nomes)


if __name__ == "__main__":
    unittest.main()
