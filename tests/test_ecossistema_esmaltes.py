"""tests/test_ecossistema_esmaltes.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.esmaltes import ecossistema_esmaltes as eco


class TestEcossistemaEsmaltes(unittest.TestCase):
    def test_montar_plano_vazio_ainda_ok(self):
        fontes = {
            k: {"disponivel": False, "timestamp": None, "dados": {}}
            for k in eco._PATHS
        }
        plano = eco.montar_plano(fontes)
        self.assertTrue(plano["ok"])
        self.assertIn("tese", plano)
        self.assertGreater(len(plano["acoes"]), 0)
        self.assertEqual(plano["cobertura_fontes_pct"], 0.0)
        msg = eco.montar_mensagem_telegram(plano)
        self.assertIn("Ecossistema esmaltes", msg)
        self.assertIn("7 dias", msg)

    def test_plano_com_kits_e_anita(self):
        fontes = {
            k: {"disponivel": False, "timestamp": None, "dados": {}}
            for k in eco._PATHS
        }
        fontes["montar_kits"] = {
            "disponivel": True,
            "timestamp": "2026-08-01T12:00:00+00:00",
            "dados": {
                "ok": True,
                "cruzamento": {
                    "ok": True,
                    "top_cores": [
                        {"nome_cor": "Bailarina", "score_demanda": 12.0},
                        {"nome_cor": "Vinho", "score_demanda": 9.0},
                    ],
                    "kits_sugeridos": [
                        {
                            "nome_sugerido": "Kit Iniciante Nude",
                            "score_medio": 10,
                            "preco_sugerido_faixa": "R$ 25–35",
                            "cores": [{"nome_cor": "Bailarina"}, {"nome_cor": "Nude"}],
                        }
                    ],
                    "tamanhos_quentes_ml": [{"qtd": 5, "vendas": 100}],
                },
            },
        }
        fontes["anita"] = {
            "disponivel": True,
            "timestamp": "2026-08-01T12:00:00+00:00",
            "dados": {
                "ok": True,
                "consolidado_impala": {
                    "share_impala_global_pct": 62.5,
                    "margem_media_pct": 32.9,
                    "unidades_vendidas_impala": 200,
                    "unidades_vendidas_anita": 120,
                },
            },
        }
        fontes["removedores"] = {
            "disponivel": True,
            "timestamp": "2026-08-01T12:00:00+00:00",
            "dados": {
                "ok": True,
                "consolidado": {
                    "ranking_fabricantes": [{"fabricante": "Cruzeiro"}],
                },
            },
        }

        plano = eco.montar_plano(fontes)
        self.assertTrue(plano["ok"])
        self.assertGreater(plano["score_ecossistema"], 50)
        self.assertGreaterEqual(plano["cobertura_fontes_pct"], 20)
        camadas = {a["camada"] for a in plano["acoes"]}
        self.assertIn("core", camadas)
        self.assertIn("kits", camadas)
        self.assertIn("anexos", camadas)
        top = plano["top_7d"]
        self.assertTrue(any("Bailarina" in (a.get("detalhe") or "") or "âncora" in (a.get("titulo") or "") for a in top))
        msg = eco.montar_mensagem_telegram(plano)
        self.assertIn("kits", msg.lower() + str(plano.get("top_7d")))

    def test_marca_kit_vira_acao_7d(self):
        fontes = {
            k: {"disponivel": False, "timestamp": None, "dados": {}}
            for k in eco._PATHS
        }
        fontes["anita"] = {
            "disponivel": True,
            "timestamp": "2026-08-14T12:00:00+00:00",
            "dados": {
                "resultados": [
                    {
                        "analises": [
                            {
                                "titulo": "Kit 5 Esmaltes Anita Nude",
                                "preco": 45.0,
                                "quantidade_vendida": 120,
                            },
                            {
                                "titulo": "Kit 5 Esmaltes Anita Nude Rosa",
                                "preco": 46.0,
                                "quantidade_vendida": 80,
                            },
                        ]
                    }
                ]
            },
        }
        fontes["tendencias"] = {
            "disponivel": True,
            "timestamp": "2026-08-14T12:00:00+00:00",
            "dados": {"consolidado": {"todas_tendencias": [{"cor": "Nude", "status": "confirmada"}]}},
        }
        plano = eco.montar_plano(fontes)
        titulos = " ".join(a.get("titulo") or "" for a in plano["acoes"])
        self.assertIn("Anita kit 5", titulos)
        self.assertTrue(any(a.get("horizonte") == "7d" and "Anita" in (a.get("titulo") or "") for a in plano["acoes"]))

    @patch("integracoes.esmaltes.ecossistema_esmaltes.ler_json", return_value={})
    def test_coletar_fontes(self, _mock):
        fontes = eco.coletar_fontes()
        self.assertEqual(len(fontes), len(eco._PATHS))
        for v in fontes.values():
            self.assertFalse(v["disponivel"])


class TestAgenteEcossistema(unittest.TestCase):
    @patch("agentes.esmaltes.agente_ecossistema_esmaltes.alertar_gestor", return_value=True)
    @patch("agentes.esmaltes.agente_ecossistema_esmaltes.gestor_telegram_configurado", return_value=True)
    @patch("agentes.esmaltes.agente_ecossistema_esmaltes.pode_alertar_esmaltes", return_value=(True, "ok"))
    @patch("agentes.esmaltes.agente_ecossistema_esmaltes.escrever_json_atomico")
    @patch("agentes.esmaltes.agente_ecossistema_esmaltes.coletar_fontes")
    def test_executar_ok(self, mock_fontes, _write, _pode, _gestor, _alerta):
        mock_fontes.return_value = {
            k: {"disponivel": False, "timestamp": None, "dados": {}}
            for k in eco._PATHS
        }
        from agentes.esmaltes.agente_ecossistema_esmaltes import executar

        out = executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["alerta_enviado"])
        self.assertIn("score_ecossistema", out)


if __name__ == "__main__":
    unittest.main()
