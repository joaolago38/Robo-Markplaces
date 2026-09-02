"""
tests/test_claude_client.py — CC01–CC05
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import claude_client


def _mock_resp(body: dict) -> MagicMock:
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = body
    return r


class TestClaudePerguntar(unittest.TestCase):
    def setUp(self):
        # Isola pausa operacional (CLAUDE_ATIVO / logs/claude_toggle.json)
        self._toggle = patch(
            "core.claude_toggle.claude_esta_ativo",
            return_value=(True, ""),
        )
        self._toggle.start()
        self.addCleanup(self._toggle.stop)
        # Isola orçamento real mesmo fora do pytest (unittest direto)
        import tempfile
        from pathlib import Path

        from core import claude_orcamento as _orc

        self._tmp_uso = tempfile.TemporaryDirectory()
        self._uso = patch.object(
            _orc, "USO_PATH", Path(self._tmp_uso.name) / "uso.json"
        )
        self._uso.start()
        self.addCleanup(self._uso.stop)
        self.addCleanup(self._tmp_uso.cleanup)

    @patch.object(claude_client, "ANTHROPIC_API_KEY", "")
    def test_CC01_pergunta_sem_api_key(self, *_patches):
        out = claude_client.perguntar("oi")
        self.assertTrue("API" in out or "configurada" in out.lower())

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_CC02_pergunta_retorna_texto_resposta(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({"content": [{"text": "resposta IA"}]})
        self.assertEqual(claude_client.perguntar("pergunta"), "resposta IA")

    @patch.object(claude_client, "request", side_effect=Exception("timeout"))
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_CC03_pergunta_fallback_em_excecao(self, *_patches):
        out = claude_client.perguntar("teste")
        self.assertTrue(out.startswith("⚠️"))

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_CC06_pergunta_system_customizado(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({"content": [{"text": "ok"}]})
        claude_client.perguntar("pergunta", system="outro system")
        payload = mock_request.call_args.kwargs["json"]
        self.assertEqual(payload["system"][0]["text"], "outro system")
        self.assertEqual(payload["system"][0]["cache_control"], {"type": "ephemeral"})

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_CC07_pergunta_sem_system_usa_padrao(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({"content": [{"text": "ok"}]})
        claude_client.perguntar("pergunta")
        payload = mock_request.call_args.kwargs["json"]
        self.assertEqual(payload["system"][0]["text"], claude_client.SYSTEM)
        self.assertEqual(payload["system"][0]["cache_control"], {"type": "ephemeral"})

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_perguntar_temperature_zero(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({"content": [{"text": "ok"}]})
        claude_client.perguntar("pergunta", temperature=0.0)
        payload = mock_request.call_args.kwargs["json"]
        self.assertEqual(payload["temperature"], 0.0)

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_perguntar_sem_temperature_nao_envia_campo(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({"content": [{"text": "ok"}]})
        claude_client.perguntar("pergunta")
        payload = mock_request.call_args.kwargs["json"]
        self.assertNotIn("temperature", payload)

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_CC08_pergunta_com_imagens_envia_blocos_multimodal(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({"content": [{"text": "ok"}]})
        claude_client.perguntar("pergunta", imagens=["https://x/foto.jpg"])
        payload = mock_request.call_args.kwargs["json"]
        content = payload["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "image")
        self.assertEqual(content[0]["source"]["url"], "https://x/foto.jpg")
        self.assertEqual(content[1]["type"], "text")

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_CC09_pergunta_sem_imagens_content_so_texto(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({"content": [{"text": "ok"}]})
        claude_client.perguntar("pergunta")
        content = mock_request.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[0]["text"], "pergunta")

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_CC10_pergunta_system_com_cache_control(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({"content": [{"text": "ok"}]})
        claude_client.perguntar("pergunta")
        system = mock_request.call_args.kwargs["json"]["system"]
        self.assertIsInstance(system, list)
        self.assertEqual(system[0]["cache_control"], {"type": "ephemeral"})

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_CC11_perguntar_estruturado_retorna_input_tool(self, mock_request, *_patches):
        esperado = {"sugestoes": [{"titulo": "A", "motivo": "B"}]}
        mock_request.return_value = _mock_resp({
            "content": [{"type": "tool_use", "name": "meu_tool", "input": esperado}],
        })
        out = claude_client.perguntar_estruturado("p", {"type": "object"}, "meu_tool")
        self.assertEqual(out, esperado)

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_CC12_perguntar_estruturado_sem_tool_use_retorna_none(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({"content": [{"type": "text", "text": "x"}]})
        out = claude_client.perguntar_estruturado("p", {"type": "object"}, "meu_tool")
        self.assertIsNone(out)

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_CC13_modelo_customizado_no_payload(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({"content": [{"text": "ok"}]})
        claude_client.perguntar("p", modelo="claude-haiku-4-5")
        payload = mock_request.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "claude-haiku-4-5")
        mock_request.reset_mock()
        mock_request.return_value = _mock_resp({
            "content": [{"type": "tool_use", "name": "t", "input": {}}],
        })
        claude_client.perguntar_estruturado("p", {"type": "object"}, "t", modelo="claude-haiku-4-5")
        payload = mock_request.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "claude-haiku-4-5")

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    @patch.object(claude_client, "CLAUDE_ECONOMICO", True)
    @patch.object(claude_client, "MODELO_RAPIDO", "claude-haiku-4-5")
    def test_economico_forca_haiku_mesmo_pedindo_sonnet(self, mock_request, *_):
        mock_request.return_value = _mock_resp({"content": [{"text": "ok"}]})
        claude_client.perguntar("p", modelo="claude-sonnet-4-5")
        self.assertEqual(mock_request.call_args.kwargs["json"]["model"], "claude-haiku-4-5")

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    @patch.object(claude_client, "CLAUDE_ECONOMICO", True)
    @patch.object(claude_client, "MODELO_RAPIDO", "claude-haiku-4-5")
    def test_economico_permite_sonnet_com_forcar_modelo(self, mock_request, *_):
        mock_request.return_value = _mock_resp({"content": [{"text": "ok"}]})
        claude_client.perguntar(
            "p",
            modelo="claude-sonnet-4-5",
            forcar_modelo=True,
        )
        self.assertEqual(mock_request.call_args.kwargs["json"]["model"], "claude-sonnet-4-5")

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_claude_401_loga_warning(self, mock_request, *_patches):
        from unittest.mock import MagicMock

        import requests

        resp = MagicMock()
        resp.status_code = 401
        err = requests.HTTPError("401 Client Error: Unauthorized")
        err.response = resp
        mock_request.return_value = resp
        resp.raise_for_status.side_effect = err
        with self.assertLogs("claude", level="WARNING") as logs:
            out = claude_client.perguntar_estruturado("p", {"type": "object"}, "meu_tool")
        self.assertIsNone(out)
        self.assertTrue(any("indisponível" in line for line in logs.output))

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_texto_util_sem_usage_tokens_conta_ok(self, mock_request, *_patches):
        from core import claude_orcamento as orc

        mock_request.return_value = _mock_resp({"content": [{"text": "análise útil"}]})
        out = claude_client.perguntar("p", origem="teste.assertividade")
        self.assertEqual(out, "análise útil")
        r = orc.resumo()
        self.assertEqual(r["resultados"].get("ok"), 1)
        self.assertEqual(r["resultados"].get("vazio"), 0)

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_estruturado_sem_tokens_com_payload_conta_ok(self, mock_request, *_patches):
        from core import claude_orcamento as orc

        esperado = {"sugestoes": [{"titulo": "A", "motivo": "B"}]}
        mock_request.return_value = _mock_resp({
            "content": [{"type": "tool_use", "name": "t", "input": esperado}],
        })
        out = claude_client.perguntar_estruturado(
            "p", {"type": "object"}, "t", origem="teste.estruturado"
        )
        self.assertEqual(out, esperado)
        r = orc.resumo()
        self.assertEqual(r["resultados"].get("ok"), 1)
        self.assertEqual(r["resultados"].get("vazio"), 0)

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_exigir_contexto_pula_api(self, mock_request, *_patches):
        out = claude_client.perguntar(
            "p", contexto="curto", exigir_contexto=True, origem="teste.skip"
        )
        self.assertIn("pulado", out.lower())
        mock_request.assert_not_called()

    @patch.object(claude_client, "_emitir_orcamento_datadog")
    @patch("core.claude_orcamento.pode_chamar", return_value=(False, "orçamento Claude esgotado"))
    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_bloqueio_orcamento_emite_datadog(self, mock_request, _pode, mock_emit):
        out = claude_client.perguntar("p", origem="teste.orcamento")
        self.assertIn("pausado", out.lower())
        mock_request.assert_not_called()
        mock_emit.assert_called()

    @patch.object(claude_client, "_emitir_orcamento_datadog")
    @patch("core.claude_orcamento.pode_chamar", return_value=(False, "orçamento Claude esgotado"))
    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_estruturado_bloqueio_orcamento_emite_datadog(self, mock_request, _pode, mock_emit):
        out = claude_client.perguntar_estruturado("p", {"type": "object"}, "t")
        self.assertIsNone(out)
        mock_request.assert_not_called()
        mock_emit.assert_called()

    def test_mlb_invalido_placeholder(self):
        self.assertTrue(claude_client.mlb_invalido("MLB_PREENCHER"))
        self.assertTrue(claude_client.mlb_invalido(""))
        self.assertFalse(claude_client.mlb_invalido("MLB1234567890"))


class TestClaudeResponderGerar(unittest.TestCase):
    @patch.object(claude_client, "perguntar", return_value="ok")
    def test_CC04_responder_chat_prompt_contem_canal_e_produto(self, mock_perguntar):
        produto = {"nome": "Kit 12", "preco": 59.90, "estoque": 50}
        claude_client.responder_chat("Qual a composição química do esmalte?", produto, "shopee")
        prompt = mock_perguntar.call_args[0][0]
        self.assertIn("shopee", prompt.lower())
        self.assertIn("Kit 12", prompt)
        self.assertIn("59.90", prompt)

    @patch("core.config.CLAUDE_ANALISE_FURA_TEMPLATE", False)
    def test_CC04b_frete_nao_inventa_full_gratis(self):
        from core.chat_seguro_ml import MSG_CONSULTAR_ANUNCIO

        produto = {"nome": "Kit 12", "preco": 59.90, "estoque": 50}
        out = claude_client.responder_chat("Tem frete full para meu CEP?", produto, "mercadolivre")
        self.assertEqual(out, MSG_CONSULTAR_ANUNCIO)

    @patch("core.config.CLAUDE_ANALISE_FURA_TEMPLATE", False)
    def test_CC04c_atacado_sem_preco_especial(self):
        from core.chat_seguro_ml import MSG_SEM_DESCONTO

        produto = {"nome": "Kit 12", "preco": 59.90, "estoque": 50}
        out = claude_client.responder_chat("Tem preço de atacado?", produto, "mercadolivre")
        self.assertEqual(out, MSG_SEM_DESCONTO)

    @patch.object(claude_client, "perguntar", return_value="post")
    def test_CC05_gerar_post_prompt_contem_canal_e_nome(self, mock_perguntar):
        produto = {"nome": "Kit Impala", "preco": 49.90}
        claude_client.gerar_post(produto, "instagram")
        prompt = mock_perguntar.call_args[0][0]
        self.assertIn("instagram", prompt.lower())
        self.assertIn("Kit Impala", prompt)

    def test_erro_credito_insuficiente(self):
        exc = Exception("timeout")
        self.assertFalse(claude_client._erro_credito_insuficiente(exc))
        http = Exception("Error")
        http.response = MagicMock()
        http.response.text = '{"error":{"message":"Your credit balance is too low to access the Anthropic API"}}'
        http.response.status_code = 400
        self.assertTrue(claude_client._erro_credito_insuficiente(http))

    @patch("core.claude_orcamento.marcar_saldo_zerado_console")
    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_pergunta_zera_saldo_quando_credito_acabou(self, mock_request, mock_zerar):
        http = Exception("400")
        http.response = MagicMock()
        http.response.text = "Your credit balance is too low"
        http.response.status_code = 400
        mock_request.side_effect = http
        out = claude_client.perguntar("oi")
        self.assertTrue(out.startswith("⚠️"))
        mock_zerar.assert_called()

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_proposito_listing_usa_sonnet(self, mock_request, *_):
        mock_request.return_value = _mock_resp({"content": [{"text": "ok"}]})
        with patch(
            "core.claude_roteador.resolver_modelo_chamada",
            return_value=("claude-sonnet-4-5", True),
        ):
            claude_client.perguntar("p", proposito="otimizar_listing")
            claude_client.perguntar_estruturado(
                "p", {"type": "object"}, "t", proposito="descoberta_produtos"
            )
        modelos = [
            c.kwargs["json"]["model"] for c in mock_request.call_args_list
        ]
        self.assertEqual(modelos, ["claude-sonnet-4-5", "claude-sonnet-4-5"])


if __name__ == "__main__":
    unittest.main()
