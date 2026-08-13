"""tests/test_conversao_manicures.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.meta import meta_inbox
from integracoes.social import conversao_manicures as conv


class TestConversaoCore(unittest.TestCase):
    def test_lead_id_estavel(self):
        a = conv.lead_id("facebook", "c1", "quero kit")
        b = conv.lead_id("facebook", "c1", "quero kit")
        self.assertEqual(a, b)

    def test_pergunta_parece_manicure(self):
        self.assertTrue(conv.pergunta_parece_manicure("Vocês tem kit atacado?"))
        self.assertFalse(conv.pergunta_parece_manicure("oi"))

    def test_diagnosticar_canais_pendente(self):
        d = conv.diagnosticar_canais(
            {
                "wa": False,
                "tg_manicures": False,
                "fb": False,
                "ig": False,
                "ig_imagem": False,
                "claude": True,
                "ml": True,
                "reply_meta": False,
                "reply_wa": False,
                "publicar_fb": False,
                "publicar_ig": False,
                "enviar_wa": False,
                "enviar_tg": False,
                "escrita": False,
            }
        )
        self.assertIn("facebook", d["pendentes"])
        self.assertIn("instagram", d["pendentes"])
        self.assertTrue(d["checklist_meta"])
        self.assertFalse(d["escrita_habilitada"])
        self.assertTrue(d["como_ativar"])

    def test_avaliar_prontidao_escrita_off(self):
        diag = conv.diagnosticar_canais(
            {
                "wa": True,
                "tg_manicures": True,
                "fb": True,
                "ig": True,
                "ig_imagem": True,
                "claude": True,
                "ml": True,
                "enviar_wa": True,
                "enviar_tg": False,
                "publicar_fb": False,
                "publicar_ig": False,
                "reply_meta": False,
                "reply_wa": False,
                "chat_ml": False,
                "escrita": False,
            }
        )
        out = conv.avaliar_prontidao(
            oferta={"link_ml": "https://produto.mercadolivre.com.br/MLB-1", "link_valido": True},
            diagnostico=diag,
            escrita=False,
        )
        self.assertFalse(out["pronta_para_escrita"])
        self.assertIn("CONVERSAO_MANICURES_ESCRITA=0", out["faltando"])

    def test_avaliar_prontidao_pronta(self):
        diag = conv.diagnosticar_canais(
            {
                "wa": True,
                "tg_manicures": False,
                "fb": False,
                "ig": False,
                "ig_imagem": False,
                "claude": True,
                "ml": True,
                "enviar_wa": True,
                "enviar_tg": False,
                "publicar_fb": False,
                "publicar_ig": False,
                "reply_meta": False,
                "reply_wa": False,
                "chat_ml": False,
                "escrita": True,
            }
        )
        out = conv.avaliar_prontidao(
            oferta={"link_ml": "https://produto.mercadolivre.com.br/MLB-1", "link_valido": True},
            diagnostico=diag,
            escrita=True,
        )
        self.assertTrue(out["pronta_para_escrita"])
        self.assertIn("whatsapp", out["canais_armados"])

    @patch.object(conv, "ANTHROPIC_API_KEY", "")
    @patch.object(conv, "carregar_campanhas")
    @patch.object(conv, "montar_mensagem_campanha")
    def test_escolher_oferta_fallback(self, mock_montar, mock_camp):
        mock_camp.return_value = [
            {"id": "kit-3", "nome": "Kit 3", "ativo": True, "sku": "X", "prioridade": 1}
        ]
        mock_montar.return_value = {
            "ok": True,
            "campanha_id": "kit-3",
            "campanha_nome": "Kit 3",
            "sku": "X",
            "preco_brl": 39.9,
            "link_ml": "https://produto.mercadolivre.com.br/MLB1",
            "link_valido": True,
            "texto": "Oferta *Kit 3*\nlink",
        }
        out = conv.escolher_oferta_haiku()
        self.assertTrue(out["ok"])
        self.assertEqual(out["campanha_id"], "kit-3")
        self.assertTrue(out["link_valido"])
        self.assertIn("MLB1", out["copy_whatsapp"] + out["cta_ml"])

    @patch.object(conv, "ANTHROPIC_API_KEY", "")
    def test_classificar_fallback(self):
        out = conv.classificar_e_responder_lead(
            "Quanto custa o kit?",
            canal="instagram",
            link_ml="https://ml.exemplo/1",
            oferta_nome="Kit 5",
        )
        self.assertTrue(out["converter"])
        self.assertIn("https://ml.exemplo/1", out["resposta"])

    def test_montar_mensagem_gestor(self):
        msg = conv.montar_mensagem_gestor(
            {
                "diagnostico": {"pendentes": ["instagram"], "checklist_meta": ["token"]},
                "oferta": {"campanha_nome": "Kit 3", "fonte": "fallback", "angulo": "atacado", "link_ml": "http://x"},
                "envios": {"whatsapp": True, "telegram": False, "facebook": False, "instagram": False},
                "inbox": {"novos": 2, "respondidos": 1, "enfileirados": 1},
                "chat_ml": {"respondidas": 0},
            }
        )
        self.assertIn("Conversão manicures", msg)
        self.assertIn("instagram", msg.lower())


class TestMetaInbox(unittest.TestCase):
    @patch.object(meta_inbox, "META_ACCESS_TOKEN", "")
    @patch.object(meta_inbox, "META_PAGE_ID", "")
    def test_fb_sem_config(self):
        out = meta_inbox.listar_comentarios_facebook()
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], "config_pendente")

    @patch.object(meta_inbox, "META_ACCESS_TOKEN", "tok")
    @patch.object(meta_inbox, "META_PAGE_ID", "page1")
    @patch.object(meta_inbox, "request")
    def test_fb_lista_comentarios(self, mock_req):
        class R:
            def __init__(self, data):
                self._data = data

            def raise_for_status(self):
                return None

            def json(self):
                return self._data

        mock_req.side_effect = [
            R({"data": [{"id": "p1", "message": "post"}]}),
            R({"data": [{"id": "c1", "message": "quero kit", "from": {"name": "Ana"}}]}),
        ]
        out = meta_inbox.listar_comentarios_facebook(limite_posts=1)
        self.assertTrue(out["ok"])
        self.assertEqual(out["comentarios"][0]["texto"], "quero kit")
        self.assertEqual(out["comentarios"][0]["canal"], "facebook")

    @patch.object(meta_inbox, "META_ACCESS_TOKEN", "tok")
    @patch.object(meta_inbox, "request")
    def test_responder_comentario(self, mock_req):
        class R:
            status_code = 200
            text = "{}"

            def raise_for_status(self):
                return None

            def json(self):
                return {"id": "r1"}

        mock_req.return_value = R()
        out = meta_inbox.responder_comentario("c1", "Segue o link ML")
        self.assertTrue(out["ok"])


class TestSustentabilidade(unittest.TestCase):
    def test_critico_quando_gasto_maior_que_ml(self):
        from integracoes.social.sustentabilidade_ads_ml import avaliar_sustentabilidade

        out = avaliar_sustentabilidade(
            gasto_meta=100,
            receita_meta_pixel=200,
            receita_ml=40,
            pedidos_ml=1,
            roas_min_real=2.0,
            gasto_minimo_avaliar=20,
        )
        self.assertEqual(out["status"], "critico")
        self.assertFalse(out["permitido_impulsionar"])

    def test_sustentavel_quando_roas_ok(self):
        from integracoes.social.sustentabilidade_ads_ml import avaliar_sustentabilidade

        out = avaliar_sustentabilidade(
            gasto_meta=50,
            receita_meta_pixel=120,
            receita_ml=150,
            pedidos_ml=3,
            roas_min_real=2.0,
            gasto_minimo_avaliar=20,
        )
        self.assertEqual(out["status"], "sustentavel")
        self.assertTrue(out["permitido_impulsionar"])
        self.assertGreaterEqual(out["roas_real"], 2.0)

    def test_gestor_mostra_sustentabilidade(self):
        msg = conv.montar_mensagem_gestor(
            {
                "diagnostico": {"pendentes": [], "checklist_meta": []},
                "oferta": {"campanha_nome": "Kit 3", "fonte": "fallback", "angulo": "a", "link_ml": "http://x"},
                "envios": {},
                "inbox": {},
                "chat_ml": {},
                "sustentabilidade": {
                    "status": "alerta",
                    "gasto_meta": 80,
                    "receita_ml": 100,
                    "pedidos_ml": 2,
                    "roas_real": 1.25,
                    "roas_pixel": 3.0,
                    "recomendacao": "reduzir verba",
                },
            }
        )
        self.assertIn("Sustentabilidade", msg)
        self.assertIn("alerta", msg)


class TestAgenteConversao(unittest.TestCase):
    @patch("agentes.social.agente_conversao_manicures.alertar_gestor", return_value=False)
    @patch("agentes.social.agente_conversao_manicures._chat_ml_manicures", return_value={"respondidas": 0})
    @patch("agentes.social.agente_conversao_manicures._envios_ativos", return_value={"whatsapp": False})
    @patch("agentes.social.agente_conversao_manicures._processar_inbox", return_value={"novos": 0, "respondidos": 0, "enfileirados": 0})
    @patch("agentes.social.agente_conversao_manicures.escolher_oferta_haiku")
    @patch("agentes.social.agente_conversao_manicures._sinal_ads", return_value={"campanhas": 0, "sustentabilidade": {"status": "sustentavel", "roas_real": 3.0}})
    @patch("agentes.social.agente_conversao_manicures.CONVERSAO_MANICURES_ESCRITA", False)
    @patch("agentes.social.agente_conversao_manicures.CONVERSAO_MANICURES_ATIVO", True)
    def test_executar_dry(self, _ads, mock_oferta, mock_inbox, mock_envios, _chat, _alerta):
        from agentes.social import agente_conversao_manicures as ag

        mock_oferta.return_value = {
            "ok": True,
            "campanha_id": "kit-3",
            "campanha_nome": "Kit 3",
            "sku": "X",
            "preco_brl": 40,
            "link_ml": "https://ml/x",
            "link_valido": False,
            "angulo": "atacado",
            "motivo": "t",
            "fonte": "fallback",
            "cta_ml": "compre",
            "copy_whatsapp": "wa",
            "copy_facebook": "fb",
            "copy_instagram": "ig",
        }
        out = ag.executar(enviar=True, enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["campanha_id"], "kit-3")
        self.assertEqual(out.get("sustentabilidade"), "sustentavel")
        self.assertEqual(out.get("modo"), "armado_sem_escrita")
        self.assertFalse(out["prontidao"]["pronta_para_escrita"])
        self.assertFalse(mock_inbox.call_args.kwargs.get("enviar"))
        self.assertFalse(mock_envios.call_args.kwargs.get("enviar"))

    @patch("agentes.social.agente_conversao_manicures.alertar_gestor", return_value=False)
    @patch("agentes.social.agente_conversao_manicures._chat_ml_manicures", return_value={"respondidas": 0})
    @patch("agentes.social.agente_conversao_manicures._envios_ativos", return_value={"whatsapp": True})
    @patch("agentes.social.agente_conversao_manicures._processar_inbox", return_value={"novos": 0, "respondidos": 0, "enfileirados": 0})
    @patch("agentes.social.agente_conversao_manicures.escolher_oferta_haiku")
    @patch(
        "agentes.social.agente_conversao_manicures._sinal_ads",
        return_value={"campanhas": 0, "sustentabilidade": {"status": "sustentavel", "roas_real": 3.0}},
    )
    @patch("agentes.social.agente_conversao_manicures.whatsapp_grupo_manicures_configurado", return_value=True)
    @patch("agentes.social.agente_conversao_manicures.manicures_telegram_configurado", return_value=False)
    @patch("agentes.social.agente_conversao_manicures.ANTHROPIC_API_KEY", "sk-test")
    @patch("agentes.social.agente_conversao_manicures.CONVERSAO_MANICURES_ENVIAR_WA", True)
    @patch("agentes.social.agente_conversao_manicures.CONVERSAO_MANICURES_ESCRITA", True)
    @patch("agentes.social.agente_conversao_manicures.CONVERSAO_MANICURES_ATIVO", True)
    def test_executar_escrita_pronta_envia(
        self,
        _tg,
        _wa,
        _ads,
        mock_oferta,
        mock_inbox,
        mock_envios,
        _chat,
        _alerta,
    ):
        from agentes.social import agente_conversao_manicures as ag

        mock_oferta.return_value = {
            "ok": True,
            "campanha_id": "kit-3",
            "campanha_nome": "Kit 3",
            "sku": "X",
            "preco_brl": 40,
            "link_ml": "https://produto.mercadolivre.com.br/MLB-123",
            "link_valido": True,
            "angulo": "atacado",
            "motivo": "t",
            "fonte": "fallback",
            "cta_ml": "compre",
            "copy_whatsapp": "wa",
            "copy_facebook": "fb",
            "copy_instagram": "ig",
        }
        out = ag.executar(enviar=True, enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertTrue(out["prontidao"]["pronta_para_escrita"])
        self.assertEqual(out.get("modo"), "envio")
        self.assertTrue(mock_envios.call_args.kwargs.get("enviar"))
        self.assertTrue(mock_inbox.call_args.kwargs.get("enviar"))


if __name__ == "__main__":
    unittest.main()
