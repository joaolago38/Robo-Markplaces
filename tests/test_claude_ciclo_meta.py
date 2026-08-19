"""tests/test_claude_ciclo_meta.py — Claude no ciclo IG/FB (não decide o gate)."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from integracoes.meta import claude_ciclo_meta as ccm


class DetectarFlipTests(unittest.TestCase):
    def test_deploy_com_pronto_nao_e_flip(self):
        out = ccm.detectar_flip_pronto(True, estado={})
        self.assertFalse(out["flip"])

    def test_flip_so_quando_anterior_false(self):
        out = ccm.detectar_flip_pronto(True, estado={"pronto": False})
        self.assertTrue(out["flip"])

    def test_continuar_pronto_nao_repete(self):
        out = ccm.detectar_flip_pronto(True, estado={"pronto": True})
        self.assertFalse(out["flip"])

    def test_voltar_a_zero_nao_e_flip(self):
        out = ccm.detectar_flip_pronto(False, estado={"pronto": True})
        self.assertFalse(out["flip"])


class PassouCooldownTests(unittest.TestCase):
    def test_sem_timestamp_libera(self):
        self.assertTrue(ccm._passou(None, 3600))

    def test_iso_invalido_libera(self):
        self.assertTrue(ccm._passou("nao-e-data", 3600))


class AuxiliarCicloTests(unittest.TestCase):
    @patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}, clear=False)
    @patch("integracoes.meta.claude_ciclo_meta._meta_token_ok", return_value=False)
    @patch("integracoes.meta.claude_ciclo_meta._pular_ia", return_value=False)
    @patch("integracoes.meta.claude_ciclo_meta._gravar")
    @patch("integracoes.meta.claude_ciclo_meta._ler", return_value={"pronto": False})
    @patch("integracoes.meta.claude_ciclo_meta.gauge")
    @patch("integracoes.meta.claude_ciclo_meta.incrementar")
    @patch("integracoes.meta.claude_ciclo_meta._alertar", return_value=True)
    @patch("integracoes.meta.claude_ciclo_meta._sintetizar", return_value="FAZER: campanha MIMO. NÃO FAZER: SORT.")
    def test_flip_dispara_briefing(self, mock_sint, mock_alert, *_):
        out = ccm.auxiliar_ciclo_meta(
            {"pronto": True, "saude_conta_ok": True, "impala_ok": True, "fase": 3, "motivo": "ligar_ig_fb"},
            eficiencia={"status": "insuficiente_dados", "roas_real": 0},
        )
        self.assertTrue(out["flip"])
        self.assertTrue(out["flip_enviado"])
        mock_sint.assert_called()
        mock_alert.assert_called()
        self.assertEqual(mock_alert.call_args.args[1], "meta:ciclo:flip_pronto")

    @patch("integracoes.meta.claude_ciclo_meta._meta_token_ok", return_value=False)
    @patch("integracoes.meta.claude_ciclo_meta._pular_ia", return_value=False)
    @patch("integracoes.meta.claude_ciclo_meta._gravar")
    @patch("integracoes.meta.claude_ciclo_meta._ler", return_value={"pronto": True, "efic_status": "sustentavel"})
    @patch("integracoes.meta.claude_ciclo_meta.gauge")
    @patch("integracoes.meta.claude_ciclo_meta.incrementar")
    @patch("integracoes.meta.claude_ciclo_meta._alertar", return_value=True)
    @patch("integracoes.meta.claude_ciclo_meta._sintetizar", return_value="OBSERVAR: ROAS real baixo.")
    def test_efic_alerta_dispara(self, mock_sint, mock_alert, *_):
        out = ccm.auxiliar_ciclo_meta(
            {"pronto": True, "saude_conta_ok": True, "impala_ok": True},
            eficiencia={"status": "alerta", "roas_real": 0.8, "gasto_meta": 50},
        )
        self.assertTrue(out["efic"])
        self.assertTrue(out["efic_enviado"])
        self.assertIn("efic:alerta", mock_alert.call_args.args[1])

    @patch("integracoes.meta.claude_ciclo_meta._meta_token_ok", return_value=False)
    @patch("integracoes.meta.claude_ciclo_meta._pular_ia", return_value=False)
    @patch("integracoes.meta.claude_ciclo_meta._gravar")
    @patch("integracoes.meta.claude_ciclo_meta._ler", return_value={"pronto": False})
    @patch("integracoes.meta.claude_ciclo_meta.gauge")
    @patch("integracoes.meta.claude_ciclo_meta._alertar")
    @patch("integracoes.meta.claude_ciclo_meta._sintetizar")
    def test_zero_nao_chama_efic(self, mock_sint, mock_alert, *_):
        out = ccm.auxiliar_ciclo_meta(
            {"pronto": False, "motivo": "Publicar MIMO"},
            eficiencia={"status": "insuficiente_dados", "roas_real": 0},
        )
        self.assertFalse(out["flip"])
        self.assertFalse(out["efic"])
        mock_sint.assert_not_called()
        mock_alert.assert_not_called()

    @patch("integracoes.meta.claude_ciclo_meta.CLAUDE_CICLO_META", False)
    def test_flag_off(self):
        out = ccm.auxiliar_ciclo_meta({"pronto": True})
        self.assertEqual(out.get("pulado"), "off")


class DigestEListingTests(unittest.TestCase):
    @patch("integracoes.meta.claude_ciclo_meta._pular_ia", return_value=False)
    @patch("integracoes.meta.claude_ciclo_meta._gravar")
    @patch("integracoes.meta.claude_ciclo_meta._ler", return_value={})
    @patch("integracoes.meta.claude_ciclo_meta.gauge")
    @patch("integracoes.meta.claude_ciclo_meta.incrementar")
    @patch("integracoes.meta.claude_ciclo_meta._alertar", return_value=True)
    @patch("integracoes.meta.claude_ciclo_meta._sintetizar", return_value="FAZER: publicar MIMO.")
    def test_digest_quando_bloqueado(self, _sint, mock_alert, *_):
        out = ccm.auxiliar_digest_bloqueio(
            {"pronto": False, "fase": 0, "motivo": "Publicar MIMO", "saude_conta_ok": True, "impala_ok": False}
        )
        self.assertTrue(out["enviado"])
        self.assertEqual(mock_alert.call_args.args[1], "meta:ciclo:bloqueio_digest")

    @patch("integracoes.meta.claude_ciclo_meta._alertar")
    def test_digest_pula_se_pronto(self, mock_alert):
        out = ccm.auxiliar_digest_bloqueio({"pronto": True, "motivo": "ligar_ig_fb"})
        self.assertEqual(out.get("pulado"), "ja_pronto")
        mock_alert.assert_not_called()

    @patch("integracoes.meta.claude_ciclo_meta._pular_ia", return_value=False)
    @patch("integracoes.meta.claude_ciclo_meta._gravar")
    @patch("integracoes.meta.claude_ciclo_meta._ler", return_value={})
    @patch("integracoes.meta.claude_ciclo_meta.gauge")
    @patch("integracoes.meta.claude_ciclo_meta.incrementar")
    @patch("integracoes.meta.claude_ciclo_meta._alertar", return_value=True)
    @patch("integracoes.meta.claude_ciclo_meta._sintetizar", return_value="FAZER: titulo MIMO.")
    def test_listing_mimo_fase_0(self, _sint, mock_alert, *_):
        out = ccm.auxiliar_listing_mimo(
            {
                "fase": 0,
                "proximo": "Publicar MIMO",
                "checks": {"mlb_mimo": False, "titulo_atracao": False, "estoque_mimo": 0},
            }
        )
        self.assertTrue(out["enviado"])
        self.assertEqual(mock_alert.call_args.args[1], "meta:ciclo:mimo_listing")

    def test_listing_pula_fase_alta_com_titulo(self):
        out = ccm.auxiliar_listing_mimo(
            {"fase": 3, "checks": {"mlb_mimo": True, "titulo_atracao": True}}
        )
        self.assertEqual(out.get("pulado"), "titulo_ok_ou_fase")


class ResolverIaCicloTests(unittest.TestCase):
    @patch("core.claude_roteador.restante_orcamento_usd", return_value=10.0)
    def test_volume_e_haiku(self, _):
        for papel in ("digest", "mimo", "p0", "copy"):
            rota = ccm.resolver_ia_ciclo_meta(papel)
            self.assertEqual(rota["familia"], "haiku", papel)
            self.assertTrue(rota["forcar_modelo"])
            self.assertGreater(rota["usd_chamada"], 0)

    @patch("core.claude_roteador.restante_orcamento_usd", return_value=10.0)
    def test_flip_e_sonnet(self, _):
        rota = ccm.resolver_ia_ciclo_meta("flip")
        self.assertEqual(rota["familia"], "sonnet")
        self.assertIn("sonnet", rota["modelo"].lower())

    @patch("core.claude_roteador.restante_orcamento_usd", return_value=10.0)
    def test_efic_alerta_haiku_critico_sonnet(self, _):
        alerta = ccm.resolver_ia_ciclo_meta("efic", efic_status="alerta")
        critico = ccm.resolver_ia_ciclo_meta("efic", efic_status="critico")
        self.assertEqual(alerta["familia"], "haiku")
        self.assertEqual(critico["familia"], "sonnet")
        self.assertEqual(critico["papel"], "efic_critico")

    @patch("core.claude_roteador.restante_orcamento_usd", return_value=0.2)
    def test_sonnet_cai_haiku_se_orcamento_baixo(self, _):
        rota = ccm.resolver_ia_ciclo_meta("flip")
        self.assertEqual(rota["familia"], "haiku")
        self.assertIn("orcamento_baixo", rota["motivo"])

    @patch("core.claude_roteador.restante_orcamento_usd", return_value=10.0)
    def test_p0_intencao_compra_sobe_sonnet(self, _):
        rota = ccm.resolver_ia_ciclo_meta("p0", texto="quero comprar, qual o preço do kit 3?")
        self.assertEqual(rota["familia"], "sonnet")
        self.assertEqual(rota["motivo"], "p0_intencao_compra")


class PreverEsforcoTests(unittest.TestCase):
    @patch("core.claude_roteador.restante_orcamento_usd", return_value=10.0)
    def test_fase0_so_digest_mimo_p0(self, _):
        out = ccm.prever_esforco_ciclo_meta("fase0")
        papeis = {c["papel"] for c in out["chamadas"]}
        self.assertEqual(papeis, {"digest", "mimo", "p0"})
        self.assertEqual(out["cenario"], "fase0")
        self.assertGreater(out["usd_mes"], 0)
        self.assertLess(out["usd_mes"], 1.0)

    @patch("core.claude_roteador.restante_orcamento_usd", return_value=10.0)
    def test_pronto_inclui_flip_copy_efic(self, _):
        out = ccm.prever_esforco_ciclo_meta("pronto")
        papeis = {c["papel"] for c in out["chamadas"]}
        self.assertTrue({"flip", "copy", "efic_alerta", "efic_critico", "p0"} <= papeis)
        flip = next(c for c in out["chamadas"] if c["papel"] == "flip")
        self.assertEqual(flip["familia"], "sonnet")
        self.assertEqual(flip["vezes_mes"], 1)
        copy = next(c for c in out["chamadas"] if c["papel"] == "copy")
        self.assertEqual(copy["familia"], "haiku")
        self.assertEqual(copy["vezes_mes"], 30)
        self.assertGreater(out["usd_mes"], 0)

    @patch("core.claude_roteador.restante_orcamento_usd", return_value=10.0)
    @patch("integracoes.meta.claude_ciclo_meta._gravar")
    @patch("integracoes.meta.claude_ciclo_meta._ler", return_value={"pronto": False})
    @patch("integracoes.meta.claude_ciclo_meta.gauge")
    def test_auxiliar_anexa_esforco_e_gauge(self, mock_gauge, *_):
        out = ccm.auxiliar_ciclo_meta(
            {"pronto": False, "motivo": "Publicar MIMO"},
            eficiencia={"status": "insuficiente_dados"},
        )
        self.assertEqual(out["esforco"]["cenario"], "fase0")
        nomes = [c.args[0] for c in mock_gauge.call_args_list]
        self.assertIn("meta.ciclo.claude_usd_previsto_mes", nomes)


if __name__ == "__main__":
    unittest.main()
