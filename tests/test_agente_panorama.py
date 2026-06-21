"""
tests/test_agente_panorama.py
Cobre o orquestrador panorama ML + Magalu + Bling (sem rede).
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.panorama import agente_panorama as pan


class TestClassificarDecisao(unittest.TestCase):
    def test_baixar_preco(self):
        d = pan.classificar_decisao_ml(
            {"meu_preco": 110, "menor_concorrente": 100, "visitas_7d": 5}
        )
        self.assertIn("BAIXAR PREÇO", d)

    def test_revisar_anuncio(self):
        d = pan.classificar_decisao_ml(
            {
                "meu_preco": 100,
                "menor_concorrente": 100,
                "visitas_7d": 25,
                "estoque": 50,
            }
        )
        self.assertIn("REVISAR ANÚNCIO", d)

    def test_sem_catalogo(self):
        self.assertEqual(
            pan.classificar_decisao_ml({"meu_preco": 10, "menor_concorrente": 0}),
            "SEM DADOS DE CATÁLOGO",
        )

    def test_manter(self):
        self.assertEqual(
            pan.classificar_decisao_ml({"meu_preco": 100, "menor_concorrente": 100}),
            "MANTER",
        )


class TestGerarPanorama(unittest.TestCase):
    @patch.object(pan, "alertar_gestor", return_value=True)
    @patch.object(pan, "_alguma_integracao", return_value=False)
    def test_nenhuma_integracao(self, *_):
        out = pan.gerar_panorama(enviar_alerta=True)
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "nenhuma integração configurada")
        self.assertTrue(out["enviado"])

    @patch.object(pan, "alertar_gestor")
    @patch.object(pan, "alertar_critico")
    @patch.object(pan, "perguntar", return_value="Situação ok\nRiscos baixos\nAções: nada")
    @patch.object(pan, "emitir_nfe_pedido")
    @patch.object(pan.ml_client, "listar_pedidos", return_value=[])
    @patch.object(pan, "_coletar_bling", return_value={"configurado": False})
    @patch.object(pan, "_coletar_magalu", return_value={"configurado": False})
    @patch.object(pan, "_coletar_mercado_livre")
    @patch.object(pan, "_alguma_integracao", return_value=True)
    def test_so_ml_com_claude(self, mock_alguma, mock_coletar_ml, *_rest):
        mock_coletar_ml.return_value = {
            "configurado": True,
            "monitor": {
                "conta": {"perguntas_pendentes": 2},
                "ads": {"campanhas_acos_alto": [{"nome": "C1"}]},
                "recomendacoes": ["Responder perguntas"],
            },
            "urgentes": [
                {
                    "item_id": "MLB1",
                    "titulo": "Kit",
                    "decisao": "BAIXAR PREÇO (estou 10.0% acima)",
                    "prioridade": 10,
                }
            ],
            "recomendacoes": ["Responder perguntas"],
            "decisoes": [],
        }
        out = pan.gerar_panorama(enviar_alerta=True, emitir_nfe=False)
        self.assertTrue(out["ok"])
        self.assertIn("Situação", out["resumo_claude"])
        self.assertTrue(out["enviado"])
        pan.alertar_gestor.assert_called_once()

    @patch.object(pan, "alertar_gestor")
    @patch.object(pan, "alertar_critico")
    @patch.object(pan.cfg, "ANTHROPIC_API_KEY", "")
    @patch.object(pan, "emitir_nfe_pedido")
    @patch.object(pan, "_coletar_bling", return_value={"configurado": False})
    @patch.object(pan, "_coletar_mercado_livre", return_value={"configurado": False})
    @patch.object(pan, "_coletar_magalu")
    @patch.object(pan, "_alguma_integracao", return_value=True)
    def test_so_magalu(self, mock_alguma, mock_coletar_magalu, mock_coletar_ml, mock_coletar_bling, mock_emitir, *_):
        mock_coletar_magalu.return_value = {
            "configurado": True,
            "perguntas_pendentes": 3,
            "pedidos_total": 2,
            "pedidos": [{"order_id": "M1", "itens": [{"sku": "SKU1", "quantidade": 1, "preco_unitario": 9.9}]}],
        }
        mock_emitir.return_value = {"ok": False, "erro": "sem NCM", "erros": ["ncm"]}
        out = pan.gerar_panorama(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["magalu"]["perguntas_pendentes"], 3)
        self.assertEqual(out["nfe"]["a_faturar"], 1)
        self.assertEqual(len(out["nfe"]["pendencias"]), 1)

    @patch.object(pan, "alertar_gestor")
    @patch.object(pan, "alertar_critico")
    @patch.object(pan.cfg, "ANTHROPIC_API_KEY", "")
    @patch.object(pan, "emitir_nfe_pedido")
    @patch.object(pan, "_coletar_magalu", return_value={"configurado": False})
    @patch.object(pan, "_coletar_mercado_livre", return_value={"configurado": False})
    @patch.object(pan, "_coletar_bling")
    @patch.object(pan, "_alguma_integracao", return_value=True)
    def test_bling_estoque_critico(self, mock_alguma, mock_coletar_bling, mock_coletar_ml, mock_coletar_magalu, *_):
        mock_coletar_bling.return_value = {
            "configurado": True,
            "total_produtos": 50,
            "estoque_critico_total": 2,
            "estoque_critico": [{"sku": "A"}],
        }
        out = pan.gerar_panorama(enviar_alerta=False)
        self.assertTrue(any("crítico" in a for a in out["alertas"]))

    @patch.object(pan, "alertar_gestor")
    @patch.object(pan, "alertar_critico")
    @patch.object(pan.cfg, "ANTHROPIC_API_KEY", "")
    @patch.object(pan, "emitir_nfe_pedido")
    @patch.object(pan, "_coletar_magalu", return_value={"configurado": False})
    @patch.object(pan, "_coletar_mercado_livre", return_value={"configurado": False})
    @patch.object(
        pan,
        "_coletar_bling",
        return_value={"configurado": True, "total_produtos": 10, "estoque_critico_total": 0},
    )
    @patch.object(pan, "_alguma_integracao", return_value=True)
    def test_bling_sem_critico(self, *_):
        out = pan.gerar_panorama(enviar_alerta=False)
        self.assertFalse(any("crítico" in a for a in out.get("alertas", [])))

    @patch.object(pan, "alertar_gestor")
    @patch.object(pan, "alertar_critico")
    @patch.object(pan.cfg, "ANTHROPIC_API_KEY", "")
    @patch.object(pan, "emitir_nfe_pedido")
    @patch.object(pan, "_coletar_bling", return_value={"configurado": False})
    @patch.object(pan, "_coletar_mercado_livre", return_value={"configurado": False})
    @patch.object(pan, "_coletar_magalu")
    @patch.object(pan, "_alguma_integracao", return_value=True)
    def test_nfe_dry_run_pronto(self, mock_alguma, mock_coletar_magalu, mock_coletar_ml, mock_coletar_bling, mock_emitir, *_):
        mock_coletar_magalu.return_value = {
            "configurado": True,
            "perguntas_pendentes": 0,
            "pedidos": [{"order_id": "P1", "itens": [{"sku": "SKU-OK", "quantidade": 1, "preco_unitario": 10}]}],
            "pedidos_total": 1,
        }
        mock_emitir.return_value = {"ok": True, "dry_run": True, "itens_total": 1}
        out = pan.gerar_panorama(enviar_alerta=False, emitir_nfe=False)
        self.assertEqual(out["nfe"]["prontos"], 1)

    @patch.object(pan, "alertar_gestor")
    @patch.object(pan, "alertar_critico")
    @patch.object(pan.cfg, "ANTHROPIC_API_KEY", "")
    @patch.object(pan, "emitir_nfe_pedido")
    @patch.object(pan, "_coletar_bling", return_value={"configurado": False})
    @patch.object(pan, "_coletar_mercado_livre", return_value={"configurado": False})
    @patch.object(pan, "_coletar_magalu")
    @patch.object(pan, "_alguma_integracao", return_value=True)
    def test_emitir_nfe_true(self, mock_alguma, mock_coletar_magalu, mock_coletar_ml, mock_coletar_bling, mock_emitir, *_):
        mock_coletar_magalu.return_value = {
            "configurado": True,
            "perguntas_pendentes": 0,
            "pedidos": [{"order_id": "P2", "itens": [{"sku": "SKU-OK", "quantidade": 1, "preco_unitario": 10}]}],
            "pedidos_total": 1,
        }
        mock_emitir.side_effect = [
            {"ok": True, "dry_run": True},
            {"ok": True, "pedido_id": "MAGALU-P2"},
        ]
        out = pan.gerar_panorama(enviar_alerta=False, emitir_nfe=True)
        self.assertEqual(out["nfe"]["emitidos"], 1)
        self.assertEqual(mock_emitir.call_count, 2)

    @patch.object(pan, "alertar_gestor")
    @patch.object(pan, "alertar_critico")
    @patch.object(pan, "perguntar", side_effect=RuntimeError("falha"))
    @patch.object(pan.cfg, "ANTHROPIC_API_KEY", "sk-test")
    @patch.object(pan, "emitir_nfe_pedido")
    @patch.object(pan.ml_client, "listar_pedidos", return_value=[])
    @patch.object(pan, "_coletar_bling", return_value={"configurado": False})
    @patch.object(pan, "_coletar_magalu", return_value={"configurado": False})
    @patch.object(pan, "_coletar_mercado_livre", return_value={"configurado": False})
    @patch.object(pan, "_alguma_integracao", return_value=True)
    def test_fallback_claude(self, *_):
        out = pan.gerar_panorama(enviar_alerta=False)
        self.assertIn("Situação", out["resumo_claude"])

    @patch.object(pan, "alertar_gestor")
    @patch.object(pan, "alertar_critico")
    @patch.object(pan, "perguntar", return_value="⚠️ Erro na IA")
    @patch.object(pan.cfg, "ANTHROPIC_API_KEY", "sk-test")
    @patch.object(pan, "emitir_nfe_pedido")
    @patch.object(pan.ml_client, "listar_pedidos", return_value=[])
    @patch.object(pan, "_coletar_bling", return_value={"configurado": False})
    @patch.object(pan, "_coletar_magalu", return_value={"configurado": False})
    @patch.object(pan, "_coletar_mercado_livre", return_value={"configurado": False})
    @patch.object(pan, "_alguma_integracao", return_value=True)
    def test_fallback_quando_claude_retorna_aviso(self, *_):
        out = pan.gerar_panorama(enviar_alerta=False)
        self.assertIn("*Situação*", out["resumo_claude"])

    @patch.object(pan, "alertar_gestor")
    @patch.object(pan, "alertar_critico")
    @patch.object(pan.cfg, "ANTHROPIC_API_KEY", "")
    @patch.object(pan, "emitir_nfe_pedido")
    @patch.object(pan.ml_client, "listar_pedidos", return_value=[])
    @patch.object(pan, "_coletar_bling", return_value={"configurado": False})
    @patch.object(pan, "_coletar_magalu", return_value={"configurado": False})
    @patch.object(pan, "_coletar_mercado_livre")
    @patch.object(pan, "_alguma_integracao", return_value=True)
    def test_enviar_alerta_false_nao_chama_gestor(self, mock_alguma, mock_coletar_ml, *_):
        mock_coletar_ml.return_value = {
            "configurado": True,
            "urgentes": [],
            "recomendacoes": [],
            "monitor": {},
        }
        out = pan.gerar_panorama(enviar_alerta=False)
        self.assertFalse(out["enviado"])
        pan.alertar_gestor.assert_not_called()

    @patch.object(pan, "alertar_gestor", side_effect=RuntimeError("zap"))
    @patch.object(pan, "_alguma_integracao", return_value=False)
    def test_nenhuma_integracao_alerta_falha(self, *_):
        out = pan.gerar_panorama(enviar_alerta=True)
        self.assertFalse(out["enviado"])

    @patch.object(pan, "alertar_gestor")
    @patch.object(pan, "alertar_critico", side_effect=RuntimeError("crit"))
    @patch.object(pan.cfg, "ANTHROPIC_API_KEY", "")
    @patch.object(pan, "emitir_nfe_pedido")
    @patch.object(pan.ml_client, "listar_pedidos", side_effect=RuntimeError("ml ped"))
    @patch.object(pan, "_coletar_bling", return_value={"configurado": False})
    @patch.object(pan, "_coletar_magalu", return_value={"configurado": False})
    @patch.object(pan, "_coletar_mercado_livre", return_value={"configurado": True, "urgentes": [], "recomendacoes": [], "monitor": {}})
    @patch.object(pan, "_alguma_integracao", return_value=True)
    def test_ml_pedidos_erro_com_alertas(self, *_):
        out = pan.gerar_panorama(enviar_alerta=True)
        self.assertTrue(out["ok"])

    @patch.object(pan, "alertar_gestor", side_effect=RuntimeError("gestor"))
    @patch.object(pan, "alertar_critico")
    @patch.object(pan.cfg, "ANTHROPIC_API_KEY", "")
    @patch.object(pan, "emitir_nfe_pedido")
    @patch.object(pan, "_coletar_bling", return_value={"configurado": False})
    @patch.object(pan, "_coletar_mercado_livre", return_value={"configurado": False})
    @patch.object(pan, "_coletar_magalu", return_value={"configurado": True, "perguntas_pendentes": 1, "pedidos": []})
    @patch.object(pan, "_alguma_integracao", return_value=True)
    def test_alertar_gestor_falha(self, *_):
        out = pan.gerar_panorama(enviar_alerta=True)
        self.assertFalse(out["enviado"])

    @patch.object(pan, "gerar_panorama", return_value={"ok": True, "resumo_claude": "ok", "alertas": [], "decisoes": [], "nfe": {}})
    def test_main(self, *_):
        self.assertEqual(pan.main(), 0)


class TestColetores(unittest.TestCase):
    @patch.object(pan.ml_client, "_enabled", return_value=False)
    def test_coletar_ml_desligado(self, *_):
        self.assertEqual(pan._coletar_mercado_livre(5)["configurado"], False)

    @patch.object(pan.agente_monitor_ml, "analisar", side_effect=RuntimeError("ml down"))
    @patch.object(pan.ml_client, "_enabled", return_value=True)
    def test_coletar_ml_erro_monitor(self, *_):
        out = pan._coletar_mercado_livre(5)
        self.assertFalse(out["monitor"]["ok"])

    @patch.object(pan.agente_monitor_ml, "analisar")
    @patch.object(pan.ml_client, "_enabled", return_value=True)
    def test_coletar_ml_com_concorrencia(self, mock_enabled, mock_analisar):
        mock_analisar.return_value = {
            "concorrencia": [
                {"item_id": "MLB1", "titulo": "X", "meu_preco": 100, "menor_concorrente": 90, "prioridade": 1}
            ],
            "recomendacoes": ["rec"],
        }
        out = pan._coletar_mercado_livre(5)
        self.assertEqual(len(out["decisoes"]), 1)

    @patch.object(pan.magalu_client, "_enabled", return_value=False)
    def test_coletar_magalu_desligado(self, *_):
        self.assertEqual(pan._coletar_magalu()["configurado"], False)

    @patch.object(pan.magalu_client, "listar_pedidos", side_effect=RuntimeError("pedidos"))
    @patch.object(pan.magalu_client, "listar_perguntas_nao_respondidas", side_effect=RuntimeError("perg"))
    @patch.object(pan.magalu_client, "obter_saude_conta", side_effect=RuntimeError("saude"))
    @patch.object(pan.magalu_client, "_enabled", return_value=True)
    def test_coletar_magalu_erros(self, *_):
        out = pan._coletar_magalu()
        self.assertEqual(out["pedidos_total"], 0)
        self.assertEqual(out["perguntas_pendentes"], 0)
        self.assertIn("erro_saude", out)

    @patch.object(pan.magalu_client, "listar_pedidos", return_value=[])
    @patch.object(pan.magalu_client, "listar_perguntas_nao_respondidas", return_value=[])
    @patch.object(pan.magalu_client, "obter_saude_conta", return_value={"configurado": True})
    @patch.object(pan.magalu_client, "_enabled", return_value=True)
    def test_coletar_magalu_ligado(self, *_):
        self.assertTrue(pan._coletar_magalu()["configurado"])

    @patch.object(pan, "_bling_configurado", return_value=False)
    def test_coletar_bling_desligado(self, *_):
        self.assertEqual(pan._coletar_bling()["configurado"], False)

    @patch.object(pan.bling_client, "estoques_criticos", side_effect=RuntimeError("est"))
    @patch.object(pan.bling_client, "listar_produtos", side_effect=RuntimeError("prod"))
    @patch.object(pan, "_bling_configurado", return_value=True)
    def test_coletar_bling_erros(self, *_):
        out = pan._coletar_bling()
        self.assertEqual(out["total_produtos"], 0)
        self.assertEqual(out["estoque_critico_total"], 0)

    @patch.object(pan.bling_client, "estoques_criticos", return_value=[])
    @patch.object(pan.bling_client, "listar_produtos", return_value=[{"sku": "A"}])
    @patch.object(pan, "_bling_configurado", return_value=True)
    def test_coletar_bling_ligado(self, *_):
        self.assertEqual(pan._coletar_bling()["total_produtos"], 1)


class TestHelpersPanorama(unittest.TestCase):
    def test_bling_configurado(self):
        with patch.object(pan.cfg, "BLING_ACCESS_TOKEN", "tok"):
            self.assertTrue(pan._bling_configurado())

    def test_alguma_integracao(self):
        with patch.object(pan.ml_client, "_enabled", return_value=True):
            self.assertTrue(pan._alguma_integracao())

    def test_pct_acima_menor_zero(self):
        self.assertEqual(pan._pct_acima(10, 0), 0.0)

    def test_pedido_para_nfe_qtd_invalida(self):
        p = pan._pedido_para_nfe(
            {"order_id": "1", "itens": [{"sku": "A", "quantidade": "x", "preco_unitario": "y"}]},
            "ML",
        )
        self.assertEqual(p["itens"][0]["quantidade"], 1)
        self.assertEqual(p["itens"][0]["valor_unitario"], 0.0)

    def test_pedido_para_nfe_sem_sku(self):
        self.assertIsNone(pan._pedido_para_nfe({"order_id": "1", "itens": [{"sku": ""}]}, "ML"))

    def test_pedido_para_nfe_ok(self):
        p = pan._pedido_para_nfe(
            {"order_id": "99", "itens": [{"sku": "A", "quantidade": 2, "preco_unitario": 5}]},
            "ML",
        )
        self.assertEqual(p["pedido_id"], "ML-99")

    def test_processar_nfe_emitir_falha(self):
        with patch.object(
            pan,
            "emitir_nfe_pedido",
            side_effect=[{"ok": True, "dry_run": True}, {"ok": False, "erro": "rejeitada"}],
        ):
            out = pan._processar_nfe(
                [("ML", {"order_id": "1", "itens": [{"sku": "X", "quantidade": 1, "preco_unitario": 1}]})],
                emitir_nfe=True,
            )
        self.assertEqual(out["emitidos"], 0)
        self.assertEqual(len(out["pendencias"]), 1)

    def test_processar_nfe_emitir_excecao(self):
        with patch.object(
            pan,
            "emitir_nfe_pedido",
            side_effect=[{"ok": True, "dry_run": True}, RuntimeError("sefaz")],
        ):
            out = pan._processar_nfe(
                [("ML", {"order_id": "1", "itens": [{"sku": "X", "quantidade": 1, "preco_unitario": 1}]})],
                emitir_nfe=True,
            )
        self.assertEqual(len(out["pendencias"]), 1)

    def test_montar_alertas_nfe_pendencias(self):
        alertas = pan._montar_alertas({}, {}, {}, {"pendencias": [{"pedido_id": "1"}]})
        self.assertTrue(any("NF-e" in a for a in alertas))

    def test_processar_nfe_excecao(self):
        with patch.object(pan, "emitir_nfe_pedido", side_effect=RuntimeError("boom")):
            out = pan._processar_nfe(
                [("ML", {"order_id": "1", "itens": [{"sku": "X", "quantidade": 1, "preco_unitario": 1}]})],
                emitir_nfe=False,
            )
        self.assertEqual(len(out["pendencias"]), 1)

    def test_safe_int(self):
        self.assertEqual(pan._safe_int("3"), 3)
        self.assertEqual(pan._safe_int(None), 0)


class TestMainModule(unittest.TestCase):
    def test_main_guard(self):
        import runpy

        with patch.object(pan, "main", return_value=0):
            with self.assertRaises(SystemExit) as ctx:
                runpy.run_module("agentes.panorama.agente_panorama", run_name="__main__")
            self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
