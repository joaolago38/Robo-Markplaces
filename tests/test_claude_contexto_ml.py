"""tests/test_claude_contexto_ml.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core import claude_contexto_ml as ccm


class TestClaudeContextoMl(unittest.TestCase):
    def test_stress_baixo_sem_dados(self):
        st = ccm.stress_produto({})
        self.assertEqual(st["nivel"], "baixo")
        self.assertEqual(st["score"], 0)

    def test_stress_alto_sem_venda(self):
        st = ccm.stress_produto({"total_anuncios_ativos": 10, "vendas_totais": 0})
        self.assertEqual(st["nivel"], "alto")
        self.assertGreaterEqual(st["score"], 40)

    def test_dosagem_ml_ok_produto_calmo_minima(self):
        d = ccm.dosar_analise_para_decisao(
            estado_ml={"nivel": "ok"},
            stress={"nivel": "baixo", "score": 0},
            proposito="masterprint_petg",
        )
        self.assertEqual(d["profundidade"], "minima")
        self.assertLess(d["fator_tokens"], 1.0)

    def test_dosagem_ml_critico_ampliada(self):
        d = ccm.dosar_analise_para_decisao(
            estado_ml={"nivel": "critico"},
            stress={"nivel": "medio", "score": 30},
            proposito="analise_ml",
        )
        self.assertEqual(d["profundidade"], "ampliada")
        self.assertIn("DEFENDER_REPUTACAO", d["foco_decisao"])

    def test_max_tokens_dosados(self):
        self.assertEqual(ccm.max_tokens_dosados(1000, {"fator_tokens": 0.55}), 550)
        self.assertGreater(ccm.max_tokens_dosados(1000, {"fator_tokens": 1.35}), 1000)

    @patch.object(ccm, "carregar_estado_ml", return_value={"nivel": "atencao", "alertas": ["x"]})
    def test_enriquecer_injeta_estado(self, _mock):
        ctx, dosagem = ccm.enriquecer_contexto_claude(
            {"totais": {"anuncios": 3}},
            consolidado={"total_anuncios_ativos": 3, "vendas_totais": 0},
            proposito="masterprint_petg",
        )
        self.assertIn("estado_ml", ctx)
        self.assertIn("situacao_produto", ctx)
        self.assertIn("dosagem_analise", ctx)
        self.assertIn("orientacao_decisao", ctx)
        self.assertEqual(ctx["estado_ml"]["nivel"], "atencao")
        self.assertIn(dosagem["profundidade"], ("minima", "padrao", "ampliada"))
        self.assertEqual(ctx.get("empresa_cnpj", {}).get("cnpj"), "23811261000197")
        self.assertEqual(
            ctx.get("dois_cnpjs_operacao", {}).get("esmaltes", {}).get("cnpj"),
            "52668583000127",
        )
        self.assertEqual(
            ctx.get("dois_cnpjs_operacao", {}).get("dono_produtos", {}).get("cnpj_efetivo"),
            "52668583000127",
        )

    def test_system_com_decisao_nao_duplica(self):
        d = {"instrucoes": ccm._SYSTEM_DECISAO}
        out = ccm.system_com_decisao("Base system.", d)
        self.assertIn("Base system.", out)
        self.assertIn("estado_ml", out)
        out2 = ccm.system_com_decisao(out, d)
        self.assertEqual(out2.count("À LUZ de estado_ml"), 1)

    def test_carregar_estado_sem_arquivos(self):
        with patch.object(ccm, "_snapshot", return_value={}):
            est = ccm.carregar_estado_ml(ao_vivo=False)
        self.assertEqual(est["marketplace"], "mercadolivre")
        self.assertIn(est["nivel"], ("ok", "atencao", "critico", "desconhecido"))


if __name__ == "__main__":
    unittest.main()
