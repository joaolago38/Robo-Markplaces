"""tests/test_operacao_destino_cnae_importacao.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.empresa import contexto_ml_cnae_importacao as ctx
from integracoes.importacao import operacao_destino as dest


class TestOperacaoDestino(unittest.TestCase):
    def test_cep_default(self):
        op = dest.carregar_operacao_destino()
        r = dest.resumo_destino(op)
        self.assertEqual(r["destino_cep"], "13467-694")
        self.assertEqual(r["aeroporto_codigo"], "VCP")
        self.assertEqual(r["aeroporto_cidade"], "Campinas")

    def test_cep_via_env(self):
        with patch("core.config.IMPORTACAO_DESTINO_CEP", "13010-050"), patch(
            "core.config.IMPORTACAO_DESTINO_CIDADE", "Campinas"
        ), patch("core.config.IMPORTACAO_DESTINO_UF", "SP"), patch(
            "core.config.IMPORTACAO_DESTINO_KM_VIRACOPOS", "20"
        ), patch("core.config.IMPORTACAO_AEROPORTO_CODIGO", ""), patch(
            "core.config.IMPORTACAO_AEROPORTO_NOME", ""
        ), patch("core.config.IMPORTACAO_AEROPORTO_CIDADE", ""), patch(
            "core.config.IMPORTACAO_AEROPORTO_UF", ""
        ):
            op = dest.carregar_operacao_destino()
            r = dest.resumo_destino(op)
        self.assertEqual(r["destino_cep"], "13010-050")
        self.assertEqual(r["destino_cidade"], "Campinas")
        self.assertEqual(r["distancia_km"], 20.0)
        self.assertTrue(r["cep_via_env"])

    def test_normalizar_cep(self):
        self.assertEqual(dest.normalizar_cep("13467694"), "13467-694")
        self.assertEqual(dest.normalizar_cep("13467-694"), "13467-694")


class TestAssociacaoCnae(unittest.TestCase):
    def test_associar_por_cnpj_esmaltes(self):
        out = ctx.associar_produto_a_cnae(cnpj="52668583000127")
        self.assertTrue(out["ok"])
        self.assertEqual(out["cnpj"], "52668583000127")
        self.assertIn("4772", str(out.get("cnae_principal") or "").replace("-", "").replace("/", ""))

    def test_associar_por_cnae(self):
        out = ctx.associar_produto_a_cnae(cnae="4751-2/01")
        self.assertTrue(out["ok"])
        self.assertEqual(out["cnpj"], "23811261000197")

    def test_quadro_sem_fob(self):
        with patch.object(ctx, "coletar_volume_vendas_ml_por_cnae", return_value={
            "ok": True, "quantidade_vendida": 12, "volume_receita_proxy": 500.0, "fontes": ["x"]
        }), patch(
            "integracoes.cambio.cotacao_usd.obter_cotacao_usd",
            return_value={"ok": True, "usd_brl": 5.5, "fonte": "teste", "confiavel": True},
        ), patch(
            "integracoes.cambio.cotacao_usd.cotacao_confiavel_para_margem",
            return_value=True,
        ), patch(
            "integracoes.empresa.contexto_ml_cnae_importacao.coletar_sinais_alibaba",
            create=True,
        ), patch(
            "integracoes.empresa.decision_limits.coletar_sinais_alibaba",
            return_value={"ok": True, "lucrativos": 1, "bloqueado": False, "tem_sinal_importar": True},
        ), patch("core.atomic_io.escrever_json_atomico"), patch(
            "integracoes.empresa.contexto_ml_cnae_importacao.gauge"
        ), patch("integracoes.empresa.contexto_ml_cnae_importacao.incrementar"):
            quadro = ctx.montar_quadro_importacao_cnae(cnpj="52668583000127")
        self.assertTrue(quadro["ok"])
        self.assertEqual(quadro["destino_operacao"]["destino_cep"], "13467-694")
        self.assertEqual(quadro["destino_operacao"]["aeroporto_codigo"], "VCP")
        self.assertEqual(quadro["volume_ml_cnae"]["quantidade_vendida"], 12)
        self.assertIn("cambio", quadro)
        self.assertIn("alibaba", quadro)

    def test_calculo_respeita_cep_env(self):
        from integracoes.importacao.calculo_importacao_aerea import (
            calcular_custo_importacao_aerea_formal,
            montar_entradas_de_produto,
        )

        with patch("core.config.IMPORTACAO_DESTINO_CEP", "13100-100"), patch(
            "core.config.IMPORTACAO_DESTINO_CIDADE", "Campinas"
        ), patch("core.config.IMPORTACAO_DESTINO_UF", "SP"), patch(
            "core.config.IMPORTACAO_DESTINO_KM_VIRACOPOS", ""
        ), patch("core.config.IMPORTACAO_AEROPORTO_CODIGO", ""), patch(
            "core.config.IMPORTACAO_AEROPORTO_NOME", ""
        ), patch("core.config.IMPORTACAO_AEROPORTO_CIDADE", ""), patch(
            "core.config.IMPORTACAO_AEROPORTO_UF", ""
        ):
            op = dest.carregar_operacao_destino()
            entradas = montar_entradas_de_produto(
                {"peso_kg": 1.0, "preco_fob_usd": 2.0, "moq_referencia": 10},
                {"preco_usd": 2.0, "moq": 10},
                cambio_usd_brl=5.0,
                operacao=op,
            )
            # Forçar frete simples no calc
            entradas["frete_aereo_usd"] = 20.0
            entradas["estimar_frete_por_kg"] = False
            out = calcular_custo_importacao_aerea_formal(entradas)
        self.assertTrue(out["ok"])
        self.assertEqual(out["destino_cep"], "13100-100")


if __name__ == "__main__":
    unittest.main()
