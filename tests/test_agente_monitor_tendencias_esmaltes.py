"""
tests/test_agente_monitor_tendencias_esmaltes.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.esmaltes import agente_monitor_tendencias_esmaltes as agente


class AgenteMonitorTendenciasEsmaltesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "processar_segmento")
    @patch.object(agente, "_carregar_segmentos")
    def test_executar_envia_telegram(self, mock_seg, mock_proc, mock_alertar):
        mock_seg.return_value = [
            {
                "id": "nude-chrome",
                "ativo": True,
                "nome": "Nude chrome",
                "prioridade": 1,
            }
        ]
        mock_proc.return_value = {
            "ok": True,
            "id": "nude-chrome",
            "nome": "Nude chrome",
            "total_web_hits": 8,
            "total_anuncios_mp": 5,
            "top_oportunidades": [{"cor": "Nude", "score_web": 70, "score_mp": 10}],
            "top_confirmadas": [],
            "tendencias": [{"cor": "Nude", "status": "oportunidade", "score_web": 70, "score_mp": 10}],
            "web_sinais": {"termos": [{"termo": "viral", "mencoes": 3}]},
        }

        with patch.object(agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"), patch.object(
            agente, "HISTORY_PATH", self.tmp_path / "hist.json"
        ), patch.object(agente, "SERIES_PATH", self.tmp_path / "series.json"), patch.object(
            agente, "GRAFICO_PATH", self.tmp_path / "g.png"
        ), patch.object(agente, "enviar_foto_gestor", return_value=True), patch.object(
            agente, "pode_alertar_esmaltes", return_value=(True, "ok")
        ), patch.object(agente, "ESMALTES_TENDENCIAS_PAUSA_SEG", 0):
            out = agente.executar(enviar_alerta=True)

        self.assertTrue(out["ok"])
        self.assertEqual(out["total_segmentos"], 1)
        mock_alertar.assert_called_once()
        msg = mock_alertar.call_args[0][0]
        self.assertIn("Oportunidades", msg)
        self.assertIn("Nude", msg)

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "enviar_foto_gestor", return_value=True)
    @patch.object(agente, "processar_segmento")
    @patch.object(agente, "_carregar_segmentos")
    def test_nao_alerta_quando_nao_configurado(self, mock_seg, mock_proc, mock_foto, mock_alertar):
        mock_seg.return_value = [{"id": "a", "ativo": True, "nome": "A", "prioridade": 1}]
        mock_proc.return_value = {
            "ok": True, "id": "a", "nome": "A", "total_web_hits": 1, "total_anuncios_mp": 1,
            "top_oportunidades": [], "top_confirmadas": [], "tendencias": [],
            "web_sinais": {"termos": []},
        }
        with patch.object(agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"), patch.object(
            agente, "HISTORY_PATH", self.tmp_path / "hist.json"
        ), patch.object(agente, "SERIES_PATH", self.tmp_path / "series.json"), patch.object(
            agente, "pode_alertar_esmaltes", return_value=(False, "telegram_nao_configurado")
        ), patch.object(agente, "ESMALTES_TENDENCIAS_PAUSA_SEG", 0):
            out = agente.executar(enviar_alerta=True)

        self.assertTrue(out["ok"])
        self.assertFalse(out["alerta_enviado"])
        mock_alertar.assert_not_called()
        mock_foto.assert_not_called()

    def test_montar_mensagem(self):
        msg = agente.montar_mensagem_telegram(
            {
                "segmentos_varridos": 2,
                "total_web_hits": 20,
                "total_anuncios_mp": 15,
                "top_oportunidades": [
                    {"cor": "Perolado", "segmento": "Chrome", "score_web": 80, "score_mp": 15}
                ],
                "top_confirmadas": [
                    {"cor": "Marsala", "segmento": "Vinho", "mencoes_web": 5, "peso_vendas_mp": 120}
                ],
                "top_termos_web": [{"termo": "viral", "mencoes": 6}],
            },
            [{"ok": True, "nome": "Chrome", "total_web_hits": 10, "total_anuncios_mp": 8, "top_oportunidades": [{"cor": "Perolado"}]}],
        )
        self.assertIn("web × marketplaces", msg)
        self.assertIn("Perolado", msg)
        self.assertIn("viral", msg)

    def test_montar_mensagem_aviso_coleta_vazia(self):
        diag = {
            "coleta_vazia": True,
            "segmentos": 8,
            "dicas": [
                "Brave Search autenticou mas retornou 0 resultados — verifique cota/plano da `BRAVE_SEARCH_API_KEY`",
                "DDG sem resultados (comum em IP de datacenter/CI do GitHub Actions)",
            ],
        }
        msg = agente.montar_mensagem_telegram(
            {"segmentos_varridos": 8, "total_web_hits": 0, "total_anuncios_mp": 0},
            [
                {"ok": True, "nome": "Nude chrome", "total_web_hits": 0, "total_anuncios_mp": 0},
                {"ok": True, "nome": "Jelly", "total_web_hits": 0, "total_anuncios_mp": 0},
            ],
            diag_coleta=diag,
        )
        self.assertIn("Fontes sem dados", msg)
        self.assertIn("não* indica ausência", msg)
        self.assertIn("BRAVE_SEARCH_API_KEY", msg)

    def test_diagnosticar_fontes_vazias(self):
        vazio = [
            {"ok": True, "total_web_hits": 0, "total_anuncios_mp": 0},
            {"ok": True, "total_web_hits": 0, "total_anuncios_mp": 0},
        ]
        diag = agente.diagnosticar_fontes_vazias(vazio)
        self.assertIsNotNone(diag)
        self.assertTrue(diag["coleta_vazia"])
        self.assertEqual(diag["segmentos"], 2)

        com_dados = [{"ok": True, "total_web_hits": 3, "total_anuncios_mp": 0}]
        self.assertIsNone(agente.diagnosticar_fontes_vazias(com_dados))

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "enviar_foto_gestor", return_value=True)
    @patch.object(agente, "processar_segmento")
    @patch.object(agente, "_carregar_segmentos")
    def test_executar_marca_coleta_vazia(self, mock_seg, mock_proc, _mock_foto, mock_alertar):
        mock_seg.return_value = [{"id": "a", "ativo": True, "nome": "A", "prioridade": 1}]
        mock_proc.return_value = {
            "ok": True,
            "id": "a",
            "nome": "A",
            "total_web_hits": 0,
            "total_anuncios_mp": 0,
            "top_oportunidades": [],
            "top_confirmadas": [],
            "tendencias": [],
            "web_sinais": {"termos": []},
        }
        with patch.object(agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"), patch.object(
            agente, "HISTORY_PATH", self.tmp_path / "hist.json"
        ), patch.object(agente, "SERIES_PATH", self.tmp_path / "series.json"), patch.object(
            agente, "GRAFICO_PATH", self.tmp_path / "g.png"
        ), patch.object(agente, "pode_alertar_esmaltes", return_value=(True, "ok")), patch.object(
            agente, "ESMALTES_TENDENCIAS_PAUSA_SEG", 0
        ):
            out = agente.executar(enviar_alerta=True)

        self.assertTrue(out["coleta_vazia"])
        self.assertTrue(out["consolidado"]["coleta_vazia"])
        msg = mock_alertar.call_args[0][0]
        self.assertIn("Fontes sem dados", msg)


if __name__ == "__main__":
    unittest.main()
