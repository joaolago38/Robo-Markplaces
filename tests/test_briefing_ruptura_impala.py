"""tests/test_briefing_ruptura_impala.py"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.empresa import agente_ponto_ruptura_segundo_cnpj as agente_cnpj
from agentes.esmaltes import agente_ponto_ruptura_outra_marca as agente_marca
from integracoes.esmaltes import briefing_ruptura_impala as br


def _kit(
    sku: str,
    *,
    mlb_ok: bool = True,
    estoque_zero: bool = False,
    margem: float | None = 22.0,
    preco: float = 42.0,
    lucro: float = 8.0,
    guerra: bool = False,
) -> dict:
    return {
        "sku": sku,
        "kit_tag": f"kit:{sku.lower().replace('imp-', '')}",
        "papel": "guerra" if guerra else "catalogo",
        "mlb_ok": mlb_ok,
        "estoque_zero": estoque_zero,
        "margem_real_pct": margem,
        "preco": preco,
        "lucro_ref_ml": lucro,
        "guerra": guerra,
    }


class TestEsforcoEProdutos(unittest.TestCase):
    def test_esforco_separa_faltando_e_feitos(self):
        checks = [
            {"id": "mlb", "ok": False, "rotulo": "MLB", "atual": "falta", "minimo": "ambos"},
            {"id": "claims", "ok": True, "rotulo": "Claims", "atual": 0, "minimo": "<2"},
        ]
        out = br.esforco_da_checklist(checks)
        self.assertEqual(out["faltando_n"], 1)
        self.assertEqual(out["feitos_n"], 1)
        self.assertIn("MLB", out["faltando"][0]["atitude"])

    def test_produto_seguro_exige_margem_mlb_estoque(self):
        out = br.produtos_com_margem_segura(
            [
                _kit("IMP-MIMO-003", margem=22.0),
                _kit("IMP-SORT-006", margem=8.0),
                _kit("IMP-PERL-004", mlb_ok=False, margem=30.0),
                _kit("OUTRO-001", margem=40.0),
            ],
            piso_pct=15.0,
        )
        self.assertEqual(out["seguros_n"], 1)
        self.assertEqual(out["seguros"][0]["sku"], "IMP-MIMO-003")
        self.assertEqual(out["seguros"][0]["veredito"], "seguro")
        self.assertGreater(out["risco_n"], 0)

    def test_saude_score_sobe_com_anuncio_e_reviews(self):
        fraca = br.saude_score(
            {"avaliacoes": 0, "nota": 0, "anuncios_ativos_foco": 0, "vendas_completadas": 0, "itens_margem_24h": 0, "claims": 0},
            {},
            3,
            7,
        )
        forte = br.saude_score(
            {"avaliacoes": 20, "nota": 4.9, "anuncios_ativos_foco": 2, "vendas_completadas": 5, "itens_margem_24h": 2, "claims": 0},
            {},
            7,
            7,
        )
        self.assertLess(fraca, 40)
        self.assertGreater(forte, 80)

    def test_saude_ignora_review_sem_foco(self):
        com_legado = br.saude_score(
            {
                "avaliacoes": 12,
                "nota": 4.9,
                "anuncios_ativos_foco": 0,
                "vendas_completadas": 8,
                "itens_margem_24h": 0,
                "claims": 0,
            },
            {},
            3,
            8,
        )
        self.assertLess(com_legado, 25)

    def test_alinhar_kits_sinais_prevalece(self):
        kits = [_kit("IMP-MIMO-003", mlb_ok=True, margem=22.0)]
        alinhado = br._alinhar_kits_com_sinais(
            kits,
            {"kits": [{"sku": "IMP-MIMO-003", "mlb_ok": False, "estoque": 0}]},
        )
        out = br.produtos_com_margem_segura(alinhado, piso_pct=15.0)
        self.assertEqual(out["seguros_n"], 0)
        self.assertIn("sem_mlb", out["risco_top"][0]["bloqueios"])


class TestMontarBriefing(unittest.TestCase):
    def test_briefing_sem_claude_traz_previa_e_esforco(self):
        ruptura = {
            "veredito": "aproximando",
            "checks_ok": 5,
            "checks_total": 7,
            "progresso_pct": 71.4,
            "checks": [
                {"id": "avaliacoes", "ok": False, "rotulo": "Avaliações Impala", "atual": 12, "minimo": 20},
                {"id": "mlb", "ok": True, "rotulo": "MLB", "atual": "ok", "minimo": "ambos"},
                {"id": "claims", "ok": True, "rotulo": "Claims", "atual": 0, "minimo": "<2"},
            ],
            "sinais": {"avaliacoes": 12, "nota": 4.9, "vendas_completadas": 2, "claims": 0, "itens_margem": 1, "receita_bruta": 90.0, "acos": 0.0},
        }
        catalogo = {"kits": [_kit("IMP-MIMO-003", margem=18.5, guerra=True), _kit("IMP-SORT-006", margem=9.0)]}
        resumo = {
            "anuncios_ativos": 1,
            "anuncios_pausados": 0,
            "anuncios_ignorados_fora_foco": 38,
            "reputacao": {"cor": "Amarelo", "avaliacoes": 12, "nota": 4.9, "vendas_completadas": 2},
        }
        out = br.montar_briefing_ruptura(
            ruptura,
            resumo=resumo,
            catalogo=catalogo,
            batalha={"agir": {"top": [{"sku": "IMP-MIMO-003", "acao": "observar", "motivo": "ok", "critica": False}]}},
            margem={"analise": {"total_itens": 1, "receita_bruta": 90.0}},
            chamar_claude=False,
        )
        self.assertTrue(out["ok"])
        self.assertFalse(out["claude_ok"])
        self.assertEqual(out["produtos"]["seguros_n"], 1)
        self.assertEqual(out["esforco"]["faltando_n"], 1)
        self.assertIn("IMP-MIMO-003", out["resumo_deterministico"])
        self.assertEqual(out["previa_ml"]["anuncios_ativos_foco"], 1)
        linhas = br.formatar_secao_briefing(out)
        blob = "\n".join(linhas)
        self.assertIn("Prévia ML Impala", blob)
        self.assertIn("IMP-MIMO-003", blob)
        self.assertIn("Esforço para ruptura tranquila", blob)
        self.assertIn("Números âncora", blob)
        self.assertIn("±", blob)

    def test_ancora_expõe_margem_de_erro_e_candidatos(self):
        catalogo = {
            "kits": [
                _kit("IMP-PERL-004", mlb_ok=False, margem=16.26),
                _kit("IMP-MIMO-003", mlb_ok=False, estoque_zero=True, margem=19.35),
            ]
        }
        out = br.montar_briefing_ruptura(
            {"veredito": "ainda_nao", "checks_ok": 3, "checks_total": 7, "checks": [], "sinais": {}},
            resumo={"anuncios_ativos": 0, "anuncios_ignorados_fora_foco": 38},
            catalogo=catalogo,
            batalha={},
            margem={},
            chamar_claude=False,
        )
        ancora = out["ancora_numerica"]
        self.assertEqual(ancora["margem_erro_pp"], 0.5)
        self.assertEqual(ancora["radar_ml"], "cego")
        self.assertGreaterEqual(ancora["saude_erro_pct"], 5.0)
        skus = {c["sku"] for c in out["produtos"]["candidatos_margem"]}
        self.assertIn("IMP-PERL-004", skus)
        self.assertFalse(out["claude_ok"])
        self.assertFalse(out["claude_assertividade_maxima"])

    @patch.object(br, "_claude_ruptura", return_value="FAZER: publicar MIMO-003. NÃO FAZER: Ads.")
    def test_claude_quando_pedido(self, mock_ia):
        ruptura = {"veredito": "aproximando", "checks_ok": 5, "checks_total": 7, "checks": [], "sinais": {}}
        with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}, clear=False):
            out = br.montar_briefing_ruptura(
                ruptura,
                resumo={},
                catalogo={"kits": []},
                batalha={},
                margem={},
                chamar_claude=True,
            )
        self.assertTrue(out["claude_ok"])
        self.assertIn("FAZER", out["resumo_claude"])
        mock_ia.assert_called_once()
        ctx = mock_ia.call_args[0][0]
        self.assertIn("ancora_numerica", ctx)
        self.assertEqual(ctx["ancora_numerica"]["margem_erro_pp"], 0.5)

    @patch("core.resumo_ia.sintetizar_claude", return_value="FAZER: PERL-004. NÃO FAZER: Ads.")
    @patch("integracoes.esmaltes.claude_ciclo_ruptura.fase_claude_ruptura", return_value="maxima")
    def test_claude_ruptura_forca_assertividade_maxima(self, _fase, mock_sint):
        from core.config import CLAUDE_MODELO

        out = br._claude_ruptura({"veredito": "ainda_nao", "ancora_numerica": {"margem_erro_pp": 0.5}}, "fb")
        self.assertIn("FAZER", out)
        kwargs = mock_sint.call_args.kwargs
        self.assertEqual(kwargs.get("temperature"), 0.0)
        self.assertTrue(kwargs.get("forcar_chamada"))
        self.assertTrue(kwargs.get("forcar_modelo"))
        self.assertEqual(kwargs.get("forcar_profundidade"), "ampliada")
        self.assertTrue(kwargs.get("somente_ia"))
        self.assertEqual(kwargs.get("proposito"), "ruptura_impala")
        self.assertEqual(kwargs.get("origem"), "ruptura_impala")
        self.assertEqual(kwargs.get("modelo"), CLAUDE_MODELO)

    @patch("core.resumo_ia.sintetizar_claude", return_value="OBSERVAR: saude 21. NÃO FAZER: Ads.")
    @patch("integracoes.esmaltes.claude_ciclo_ruptura.fase_claude_ruptura", return_value="moderada")
    def test_claude_ruptura_volta_moderado_depois_datadog(self, _fase, mock_sint):
        out = br._claude_ruptura({"veredito": "ainda_nao"}, "fb")
        self.assertIn("OBSERVAR", out)
        kwargs = mock_sint.call_args.kwargs
        self.assertIsNone(kwargs.get("temperature"))
        self.assertFalse(kwargs.get("forcar_chamada"))
        self.assertFalse(kwargs.get("forcar_modelo"))
        self.assertEqual(kwargs.get("forcar_profundidade"), "padrao")
        self.assertEqual(kwargs.get("proposito"), "ruptura_impala_moderada")
        self.assertEqual(kwargs.get("max_tokens"), 220)
        self.assertTrue(kwargs.get("somente_ia"))

    @patch("core.resumo_ia.sintetizar_claude", return_value="FAZER: PERL-004 MLB+estoque. NÃO FAZER: Ads.")
    @patch("integracoes.esmaltes.claude_ciclo_ruptura.fase_claude_ruptura", return_value="moderada")
    def test_claude_momento_lucro_forca_chamada_moderada(self, _fase, mock_sint):
        out = br._claude_ruptura({"veredito": "ainda_nao"}, "fb", momento_lucro=True)
        self.assertIn("FAZER", out)
        kwargs = mock_sint.call_args.kwargs
        self.assertTrue(kwargs.get("forcar_chamada"))
        self.assertEqual(kwargs.get("forcar_profundidade"), "padrao")
        self.assertFalse(kwargs.get("forcar_modelo"))


class TestAgenteMensagem(unittest.TestCase):
    def test_mensagem_cnpj_inclui_briefing(self):
        resultado = {
            "veredito": "aproximando",
            "progresso_pct": 71.4,
            "checks_ok": 5,
            "checks_total": 7,
            "checks": [{"ok": False, "rotulo": "MLB", "atual": "falta", "minimo": "ambos"}],
            "cnae_preparacao": {"pronto": True, "gaps_n": 0, "itens": []},
            "briefing": br.montar_briefing_ruptura(
                {
                    "veredito": "aproximando",
                    "checks_ok": 5,
                    "checks_total": 7,
                    "checks": [{"id": "mlb", "ok": False, "rotulo": "MLB", "atual": "falta", "minimo": "ambos"}],
                    "sinais": {"avaliacoes": 12, "nota": 4.9},
                },
                resumo={"anuncios_ativos": 1, "reputacao": {"cor": "Amarelo"}},
                catalogo={"kits": [_kit("IMP-MIMO-003")]},
                batalha={},
                margem={},
                chamar_claude=False,
            ),
        }
        msg = agente_cnpj.montar_mensagem(resultado, modo="aproximando")
        self.assertIn("Prévia ML Impala", msg)
        self.assertIn("IMP-MIMO-003", msg)
        self.assertIn("margem segura", msg.lower())

    def test_mensagem_outra_marca_inclui_briefing(self):
        resultado = {
            "cnpj_formatado": "52.668.583/0001-27",
            "veredito": "aproximando",
            "progresso_pct": 50,
            "checks_ok": 3,
            "checks_total": 6,
            "top_marca": "Anita",
            "top_score": 120,
            "checks": [],
            "canais": {"itens": []},
            "candidatas": [],
            "briefing": {
                "ok": True,
                "saude_score": 22.0,
                "previa_ml": {
                    "anuncios_ativos_foco": 0,
                    "anuncios_pausados_foco": 0,
                    "legado_ignorado": 38,
                    "reputacao_cor": "Sem cor ainda",
                    "avaliacoes": 0,
                    "nota": 0,
                    "vendas_completadas": 0,
                    "itens_margem_24h": 0,
                    "receita_bruta_24h": 0,
                },
                "esforco": {"faltando": [{"atitude": "Preencher MLB dos kits de validação."}], "feitos": []},
                "produtos": {"piso_pct": 15.0, "seguros": []},
                "resumo_deterministico": "Nenhum kit no piso.",
                "resumo_claude": "",
            },
        }
        msg = agente_marca.montar_mensagem(resultado, modo="aproximando")
        self.assertIn("52.668.583/0001-27", msg)
        self.assertIn("Prévia ML Impala", msg)
        self.assertIn("Preencher MLB", msg)


if __name__ == "__main__":
    unittest.main()
