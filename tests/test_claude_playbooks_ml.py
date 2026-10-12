"""tests/test_claude_playbooks_ml.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core import claude_contexto_ml as ccm
from core.claude_ml import playbooks as pb


class TestClaudePlaybooksMl(unittest.TestCase):
    def test_proposito_escolhe_playbook(self):
        self.assertEqual(pb.id_playbook("otimizar_listing"), "seo_titulo")
        self.assertEqual(pb.id_playbook("monitor_concorrentes"), "inteligencia_competitiva")
        self.assertEqual(pb.id_playbook("chat_ml"), "atendimento_chat")
        self.assertEqual(pb.id_playbook("analise_ml"), "panorama_categoria")
        self.assertEqual(pb.id_playbook("inteligencia_precos"), "pricing_faixas")
        self.assertIsNone(pb.id_playbook("ruptura_impala"))
        self.assertIsNone(pb.id_playbook("guerra_impala"))
        self.assertIsNone(pb.id_playbook("golpe_guerra_impala"))

    def test_instrucoes_preenchem_contexto_sem_inventar(self):
        txt = pb.montar_instrucoes(
            "demanda_alta",
            campos={"nicho": "esmaltes Impala", "momento": "já vendendo nesse nicho"},
        )
        self.assertIn("Mercado Livre Brasil", txt)
        self.assertIn("esmaltes Impala", txt)
        self.assertIn("nunca invente", txt.lower())
        self.assertNotIn("[nicho/categoria]", txt)
        self.assertIn("JoomPulse", txt)

    def test_campos_momento_com_venda(self):
        cam = pb.campos_do_json(
            consolidado={"total_anuncios_ativos": 4, "vendas_totais": 12},
            produto={"titulo": "Kit MIMO"},
        )
        self.assertEqual(cam["momento"], "já vendendo nesse nicho")
        self.assertIn("Kit MIMO", cam["produto"])

    def test_anexar_nao_duplica(self):
        a, pid = pb.anexar_playbook("base", proposito="sintese_ml")
        self.assertEqual(pid, "panorama_categoria")
        self.assertIn("Playbook panorama_categoria", a)
        b, _ = pb.anexar_playbook(a, proposito="sintese_ml")
        self.assertEqual(a.count("Playbook panorama_categoria"), b.count("Playbook panorama_categoria"))

    def test_dosagem_analise_traz_playbook_guerra_nao(self):
        d = ccm.dosar_analise_para_decisao(
            estado_ml={"nivel": "ok"},
            stress={"nivel": "baixo", "score": 0},
            proposito="analise_ml",
        )
        self.assertEqual(d.get("playbook_id"), "panorama_categoria")
        self.assertIn("analista que resume mercados", d["instrucoes"])
        g = ccm.dosar_analise_para_decisao(
            estado_ml={"nivel": "ok"},
            stress={"nivel": "baixo", "score": 0},
            proposito="guerra_impala",
        )
        self.assertIsNone(g.get("playbook_id"))
        self.assertIn("UM golpe", g["instrucoes"])
        self.assertNotIn("Playbook", g["instrucoes"])

    @patch.object(ccm, "carregar_estado_ml", return_value={"nivel": "ok", "alertas": []})
    def test_enriquecer_injeta_bloco_playbook(self, _m):
        ctx, dosagem = ccm.enriquecer_contexto_claude(
            {"nicho": "esmaltes"},
            produto={"titulo": "Kit 6 cores", "preco": 44.9},
            proposito="otimizar_listing",
        )
        self.assertEqual(dosagem.get("playbook_id"), "seo_titulo")
        self.assertEqual(ctx["playbook_ml"]["id"], "seo_titulo")
        self.assertIn("60", ctx["playbook_ml"]["instrucoes"])
        self.assertIn("Kit 6 cores", ctx["playbook_ml"]["campos"]["produto"])


if __name__ == "__main__":
    unittest.main()
