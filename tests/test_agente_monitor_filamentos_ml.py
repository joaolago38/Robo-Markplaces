"""
tests/test_agente_monitor_filamentos_ml.py
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.filamentos import agente_monitor_filamentos_ml as agente


class AgenteMonitorFilamentosMlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_materiais_monitorados(self):
        self.assertEqual(agente.MATERIAIS_MONITORADOS, ("TPU", "PLA", "PETG", "ABS"))

    def test_catalogo_ativo_tem_tpu_pla_petg_abs(self):
        root = Path(__file__).resolve().parent.parent
        data = json.loads((root / "catalogo" / "filamentos_3d_monitor.json").read_text(encoding="utf-8"))
        ativos = {str(t.get("material") or "").upper() for t in data if t.get("ativo")}
        for mat in ("TPU", "PLA", "PETG", "ABS"):
            self.assertIn(mat, ativos)

    def test_resumo_por_material(self):
        linhas = agente._resumo_por_material(
            [
                {
                    "ok": True,
                    "material": "TPU",
                    "total_filamentos": 3,
                    "preco_medio": 120.0,
                    "preco_min": 100.0,
                    "preco_max": 140.0,
                },
                {
                    "ok": True,
                    "material": "PLA",
                    "total_filamentos": 10,
                    "preco_medio": 80.0,
                    "preco_min": 60.0,
                    "preco_max": 100.0,
                },
                {
                    "ok": True,
                    "material": "PLA",
                    "total_filamentos": 5,
                    "preco_medio": 85.0,
                    "preco_min": 70.0,
                    "preco_max": 95.0,
                },
            ]
        )
        texto = "\n".join(linhas)
        self.assertIn("*TPU*", texto)
        self.assertIn("*PLA*", texto)
        self.assertIn("*PETG*: sem anúncios", texto)
        self.assertIn("*ABS*: sem anúncios", texto)
        self.assertIn("15 anúncio(s)", texto)  # 10+5 PLA

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente.ml_client, "buscar_concorrentes_por_termo")
    @patch.object(agente, "_carregar_termos")
    def test_executar_envia_telegram(self, mock_termos, mock_busca, mock_alertar):
        mock_termos.return_value = [
            {
                "id": "fil-tpu",
                "ativo": True,
                "nome": "TPU",
                "material": "TPU",
                "termo_busca": "filamento tpu",
                "limite_resultados": 10,
                "prioridade": 1,
            },
            {
                "id": "fil-pla",
                "ativo": True,
                "nome": "PLA",
                "material": "PLA",
                "termo_busca": "filamento pla",
                "limite_resultados": 10,
                "prioridade": 1,
            },
            {
                "id": "fil-petg",
                "ativo": True,
                "nome": "PETG",
                "material": "PETG",
                "termo_busca": "filamento petg",
                "limite_resultados": 10,
                "prioridade": 1,
            },
            {
                "id": "fil-abs",
                "ativo": True,
                "nome": "ABS",
                "material": "ABS",
                "termo_busca": "filamento abs",
                "limite_resultados": 10,
                "prioridade": 1,
            },
        ]

        def _busca(termo, limite=10):
            t = (termo or "").lower()
            if "tpu" in t:
                return [
                    {
                        "item_id": "MLB-TPU",
                        "titulo": "Filamento TPU flexivel preto 1kg",
                        "preco": 129.9,
                        "quantidade_vendida": 40,
                    }
                ]
            if "petg" in t:
                return [
                    {
                        "item_id": "MLB-PETG",
                        "titulo": "eSUN Filamento PETG branco 1kg",
                        "preco": 99.0,
                        "quantidade_vendida": 80,
                    }
                ]
            if "abs" in t:
                return [
                    {
                        "item_id": "MLB-ABS",
                        "titulo": "Creality Filamento ABS cinza 1kg",
                        "preco": 89.0,
                        "quantidade_vendida": 30,
                    }
                ]
            return [
                {
                    "item_id": "MLB-PLA",
                    "titulo": "Printalot Filamento PLA preto 1kg",
                    "preco": 79.9,
                    "quantidade_vendida": 200,
                }
            ]

        mock_busca.side_effect = _busca

        with patch.object(agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"), patch.object(
            agente, "HISTORY_PATH", self.tmp_path / "hist.json"
        ), patch.object(agente, "SERIES_PATH", self.tmp_path / "series.json"), patch.object(
            agente, "GRAFICO_PATH", self.tmp_path / "g.png"
        ), patch.object(agente, "enviar_foto_gestor", return_value=True), patch.object(
            agente, "gestor_telegram_configurado", return_value=True
        ), patch.object(agente, "FILAMENTOS_ML_PAUSA_SEG", 0), patch.object(
            agente, "FILAMENTOS_ML_CRUZAR_ALIBABA", False
        ), patch.object(agente, "FILAMENTOS_ML_ALERTA_RESUMO", True), patch.object(
            agente, "enriquecer_avaliacoes_amostra", return_value=0
        ), patch(
            "integracoes.ml.coleta_demanda_ml.enriquecer_visitas_amostra",
            return_value=0,
        ), patch(
            "integracoes.ml.coleta_demanda_ml.coletar_funil_proprio",
            return_value={
                "ok": True,
                "dias": 7,
                "pedidos_ok": True,
                "visitas_ok": True,
                "totais": {"visitas_7d": 0, "unidades_7d": 0, "conversao_pct": None},
                "itens": [],
            },
        ), patch(
            "integracoes.ml.coleta_demanda_ml.emitir_metricas_demanda",
        ), patch(
            "integracoes.ml.acoes_funil_ml.processar_e_persistir_acoes",
            return_value={"ok": True, "acoes": [], "criticas": 0, "alerta_enviado": False},
        ):
            out = agente.executar(enviar_alerta=True)

        self.assertTrue(out["ok"])
        self.assertEqual(out["total_termos"], 4)
        self.assertGreaterEqual(out["consolidado"]["total_filamentos_unicos"], 4)
        mock_alertar.assert_called_once()
        msg = mock_alertar.call_args[0][0]
        self.assertIn("Materiais monitorados", msg)
        self.assertIn("TPU", msg)
        self.assertIn("PLA", msg)
        self.assertIn("PETG", msg)
        self.assertIn("ABS", msg)
        self.assertIn("Por material", msg)

    def test_montar_mensagem(self):
        msg = agente.montar_mensagem_telegram(
            {
                "total_filamentos_unicos": 12,
                "total_vendas": 900,
                "preco_min": 59.0,
                "preco_max": 149.0,
                "preco_medio": 89.0,
                "termos_varridos": 4,
                "ranking_cores": [
                    {"cor": "Preto", "vendidos": 400, "anuncios": 5, "preco_medio": 85.0}
                ],
                "ranking_marcas": [
                    {"marca": "eSUN", "vendidos": 500, "anuncios": 4, "preco_medio": 85.0}
                ],
                "ranking_materiais": [
                    {"material": "PLA", "vendidos": 700, "anuncios": 8, "preco_medio": 80.0}
                ],
                "top_baratos": [
                    {
                        "titulo": "Filamento PLA barato",
                        "preco": 59.0,
                        "marca": "Genérico/Outros",
                        "cor": "Preto",
                    }
                ],
                "top_vendas": [
                    {
                        "titulo": "eSUN PLA 1kg",
                        "preco": 89.0,
                        "quantidade_vendida": 400,
                        "marca": "eSUN",
                        "cor": "Preto",
                        "material": "PLA",
                    }
                ],
            },
            [
                {
                    "ok": True,
                    "nome": "TPU",
                    "material": "TPU",
                    "preco_min": 100,
                    "preco_max": 140,
                    "preco_medio": 120,
                    "total_filamentos": 3,
                    "total_bruto": 5,
                },
                {
                    "ok": True,
                    "nome": "PLA",
                    "material": "PLA",
                    "preco_min": 59,
                    "preco_max": 120,
                    "preco_medio": 85,
                    "total_filamentos": 8,
                    "total_bruto": 10,
                },
                {
                    "ok": True,
                    "nome": "PETG",
                    "material": "PETG",
                    "preco_min": 70,
                    "preco_max": 110,
                    "preco_medio": 90,
                    "total_filamentos": 4,
                    "total_bruto": 6,
                },
                {
                    "ok": True,
                    "nome": "ABS",
                    "material": "ABS",
                    "preco_min": 65,
                    "preco_max": 100,
                    "preco_medio": 80,
                    "total_filamentos": 2,
                    "total_bruto": 4,
                },
            ],
            cruzamento={
                "ok": True,
                "cores_usadas": ["Preto"],
                "cambio_usd_brl": 5.5,
                "cruzamentos": [],
            },
        )
        self.assertIn("Materiais monitorados", msg)
        self.assertIn("TPU · PLA · PETG · ABS", msg)
        self.assertIn("Por material (TPU / PLA / PETG / ABS)", msg)
        self.assertIn("eSUN", msg)
        self.assertIn("Comparativo ML × Alibaba", msg)
        self.assertIn("400 vendas", msg)

    def test_montar_mensagem_vendas_nd(self):
        msg = agente.montar_mensagem_telegram(
            {
                "total_filamentos_unicos": 90,
                "total_vendas": 0,
                "anuncios_com_vendas_api": 0,
                "preco_min": 100.0,
                "preco_max": 169.0,
                "preco_medio": 133.0,
                "termos_varridos": 4,
                "ranking_cores": [
                    {"cor": "Preto", "vendidos": 0, "anuncios": 42, "preco_medio": 124.97}
                ],
                "ranking_marcas": [
                    {
                        "marca": "Genérico/Outros",
                        "vendidos": 0,
                        "anuncios": 90,
                        "preco_medio": 133.0,
                    }
                ],
                "top_vendas": [
                    {
                        "titulo": "Filamento PETG preto 1kg",
                        "preco": 124.0,
                        "quantidade_vendida": 0,
                        "avaliacoes": 12,
                        "marca": "Genérico/Outros",
                        "cor": "Preto",
                        "material": "PETG",
                    }
                ],
            },
            [
                {
                    "ok": True,
                    "nome": "PETG",
                    "material": "PETG",
                    "preco_min": 100,
                    "preco_max": 169,
                    "preco_medio": 133,
                    "total_filamentos": 90,
                    "total_bruto": 100,
                }
            ],
        )
        self.assertIn("vendas API n/d", msg)
        self.assertIn("vendas n/d", msg)
        self.assertNotIn("0 vendas", msg)
        self.assertIn("12 aval.", msg)

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "cruzar_filamentos_ml_alibaba")
    @patch.object(agente.ml_client, "buscar_concorrentes_por_termo", return_value=[])
    @patch.object(agente, "_carregar_termos")
    def test_cruzamento_cambio_falhou_alerta(self, mock_termos, _busca, mock_cruzar, mock_alertar):
        mock_termos.return_value = [
            {
                "id": "fil-pla",
                "ativo": True,
                "nome": "PLA",
                "material": "PLA",
                "termo_busca": "filamento pla",
                "limite_resultados": 5,
                "prioridade": 1,
            }
        ]
        mock_cruzar.return_value = {
            "ok": False,
            "motivo": "cambio: fallback",
            "cruzamentos": [],
            "lucrativos": 0,
        }
        with patch.object(agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"), patch.object(
            agente, "HISTORY_PATH", self.tmp_path / "hist.json"
        ), patch.object(agente, "SERIES_PATH", self.tmp_path / "series.json"), patch.object(
            agente, "GRAFICO_PATH", self.tmp_path / "g.png"
        ), patch.object(agente, "enviar_foto_gestor", return_value=True), patch.object(
            agente, "gestor_telegram_configurado", return_value=True
        ), patch.object(agente, "FILAMENTOS_ML_PAUSA_SEG", 0), patch.object(
            agente, "FILAMENTOS_ML_CRUZAR_ALIBABA", True
        ), patch.object(agente, "FILAMENTOS_ML_ALERTA_RESUMO", False), patch.object(
            agente, "enriquecer_avaliacoes_amostra", return_value=0
        ), patch(
            "integracoes.ml.coleta_demanda_ml.enriquecer_visitas_amostra",
            return_value=0,
        ), patch(
            "integracoes.ml.coleta_demanda_ml.coletar_funil_proprio",
            return_value={
                "ok": True,
                "dias": 7,
                "pedidos_ok": True,
                "visitas_ok": True,
                "totais": {},
                "itens": [],
            },
        ), patch(
            "integracoes.ml.coleta_demanda_ml.emitir_metricas_demanda",
        ), patch(
            "integracoes.ml.acoes_funil_ml.processar_e_persistir_acoes",
            return_value={"ok": True, "acoes": [], "criticas": 0, "alerta_enviado": False},
        ):
            out = agente.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertTrue(
            any(
                "cruzamento_cambio_falhou" in str(c.kwargs.get("chave", ""))
                for c in mock_alertar.call_args_list
            )
        )


if __name__ == "__main__":
    unittest.main()
