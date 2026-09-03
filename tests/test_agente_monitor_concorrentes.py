"""
tests/test_agente_monitor_concorrentes.py
"""
import importlib.util
import os
import sys
import unittest
from contextlib import ExitStack
from unittest.mock import patch

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "agente_monitor_concorrentes",
    os.path.join(ROOT, "agentes", "ml", "agente_monitor_concorrentes.py"),
)
mon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mon)


def _isolar_batalha(test_case) -> None:
    """Monitor unitário não dispara radar/golpe/Datadog de guerra nem novos kits."""
    stack = ExitStack()
    stack.enter_context(
        patch(
            "integracoes.esmaltes.metricas_batalha_impala.processar_e_persistir",
            return_value={},
        )
    )
    stack.enter_context(
        patch(
            "integracoes.esmaltes.novos_kits_impala.processar",
            return_value={"ok": True, "alertas": [], "n_novos": 0},
        )
    )
    stack.enter_context(
        patch.object(
            mon,
            "_aplicar_lacunas_monitor",
            return_value={
                "avaliacoes_texto": [],
                "perguntas": [],
                "padroes_reclamacao": [],
                "tendencia_demanda": {"tendencia": "indeterminado", "motivo": "historico insuficiente"},
                "margem_real": {"margem_disponivel": False, "motivo": "custo_unitario nao informado"},
            },
        )
    )
    stack.enter_context(patch.object(mon, "_persistir_lacunas_ciclo"))
    test_case.addCleanup(stack.close)


_LISTA_ALERTA = [
    {
        "id": "kit1",
        "ativo": True,
        "nome": "Kit Teste",
        "termo_busca": "kit impala",
        "meu_preco": 50.0,
        "limite_resultados": 5,
    }
]

_LISTA_ESTAVEL = [
    {
        "id": "kit1",
        "ativo": True,
        "nome": "Kit Teste",
        "termo_busca": "kit impala",
        "meu_preco": 38.0,
        "limite_resultados": 5,
    }
]

_CONC = {"item_id": "MLB2", "titulo": "Kit Impala Teste", "preco": 40.0, "quantidade_vendida": 1}


class TestMonitorConcorrentes(unittest.TestCase):
    def setUp(self):
        _isolar_batalha(self)

    @patch.object(mon, "MONITOR_CONCORRENTES_ALERTAR_GAP_SO_ANUNCIO_VIVO", False)
    @patch.object(mon, "alertar_gestor", return_value=True)
    @patch.object(mon, "_salvar_historico")
    @patch.object(mon, "_carregar_historico", return_value={})
    @patch.object(mon, "_carregar_lista", return_value=_LISTA_ALERTA)
    @patch.object(mon.ml_client, "buscar_concorrentes_por_termo", return_value=[_CONC])
    def test_alerta_preco_acima(self, *_):
        out = mon.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["total_alertas"], 1)
        self.assertTrue(out["enviado"])
        texto = " ".join(out.get("alertas") or [])
        if not texto:
            for r in out.get("resultados") or []:
                texto += " ".join(r.get("alertas") or [])
        self.assertIn("preço alvo", texto)
        self.assertNotIn("seu preço", texto)
        self.assertEqual(out["resultados"][0].get("origem_preco"), "alvo_json")

    @patch.object(mon, "MONITOR_CONCORRENTES_ALERTAR_GAP_SO_ANUNCIO_VIVO", True)
    @patch.object(mon, "alertar_gestor", return_value=True)
    @patch.object(mon, "_salvar_historico")
    @patch.object(mon, "_carregar_historico", return_value={})
    @patch.object(mon, "_carregar_lista", return_value=_LISTA_ALERTA)
    @patch.object(mon.ml_client, "buscar_concorrentes_por_termo", return_value=[_CONC])
    def test_sem_alerta_gap_sem_anuncio_vivo(self, *_):
        out = mon.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_alertas"], 0)
        self.assertEqual(out["resultados"][0].get("origem_preco"), "alvo_json")

    @patch.object(mon, "alertar_gestor")
    @patch.object(mon, "_salvar_historico")
    @patch.object(mon, "_carregar_historico", return_value={"kit1": {"menor_preco": 40.0}})
    @patch.object(mon, "_carregar_lista", return_value=_LISTA_ESTAVEL)
    @patch.object(mon.ml_client, "buscar_concorrentes_por_termo", return_value=[
        {"item_id": "MLB2", "titulo": "Kit Impala Teste", "preco": 40.0},
    ])
    def test_sem_alerta_quando_estavel(
        self,
        mock_buscar,
        mock_carregar_lista,
        mock_carregar_historico,
        mock_salvar_historico,
        mock_alertar,
    ):
        out = mon.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_alertas"], 0)
        mock_alertar.assert_not_called()
        mock_buscar.assert_called_once()

    @patch.object(mon, "_carregar_lista", return_value=[])
    def test_lista_vazia(self, *_):
        out = mon.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_monitorados"], 0)

    @patch.object(mon, "MONITOR_CONCORRENTES_ALERTAR_GAP_SO_ANUNCIO_VIVO", False)
    @patch.object(mon, "alertar_gestor", return_value=False)
    @patch.object(mon, "_salvar_historico")
    @patch.object(mon, "_carregar_historico", return_value={})
    @patch.object(
        mon,
        "_carregar_lista",
        return_value=[
            {
                "id": "loja-novamix-comercial",
                "ativo": True,
                "tipo": "loja",
                "nome": "NOVAMIX_COMERCIAL",
                "seller_id": "1666381510",
                "nickname": "NOVAMIX_COMERCIAL",
                "meu_preco": 44.9,
                "limite_resultados": 5,
            }
        ],
    )
    @patch("integracoes.ml.analise_loja_concorrente.analisar_loja")
    def test_monitora_loja_novamix(self, mock_analisar, *_):
        mock_analisar.return_value = {
            "ok": True,
            "nickname": "NOVAMIX_COMERCIAL",
            "anuncios": [{"item_id": "MLB1", "titulo": "Kit Impala", "preco": 40.0}],
            "preco_min": 40.0,
            "ameacas_preco": [
                {
                    "sku": "IMP-MIMO-003",
                    "meu_preco": 44.9,
                    "menor_preco_loja": 40.0,
                    "gap_pct": 12.3,
                }
            ],
            "perfil": {"level_id": "5_green", "power_seller_status": "platinum"},
        }
        out = mon.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_monitorados"], 1)
        self.assertGreaterEqual(out["total_alertas"], 1)
        self.assertEqual(out["resultados"][0]["tipo"], "loja")
        texto = " ".join(
            " ".join(r.get("alertas") or []) for r in (out.get("resultados") or [])
        )
        self.assertIn("preço alvo", texto)
        self.assertNotIn("seu R$", texto)


class TestResolverPrecoReferencia(unittest.TestCase):
    def test_fallback_alvo_json(self):
        preco, origem = mon._resolver_preco_referencia({"meu_preco": 48.9})
        self.assertEqual(preco, 48.9)
        self.assertEqual(origem, "alvo_json")
        self.assertEqual(mon._rotulo_preco_referencia(origem), "preço alvo")

    def test_ignora_mlb_preencher(self):
        self.assertFalse(mon._item_id_ml_valido("MLB_PREENCHER"))
        self.assertFalse(mon._item_id_ml_valido("MLB1"))
        self.assertTrue(mon._item_id_ml_valido("MLB123456789"))
        self.assertEqual(mon._item_ids_da_entrada({"item_ids": ["MLB_PREENCHER", "MLB123456789"]}), ["MLB123456789"])

    @patch.object(mon.ml_client, "buscar_metricas_item", return_value={"preco": 47.5})
    def test_preco_vivo_quando_item_valido(self, *_):
        preco, origem = mon._resolver_preco_referencia(
            {"meu_preco": 48.9, "item_id": "MLB123456789"}
        )
        self.assertEqual(preco, 47.5)
        self.assertEqual(origem, "anuncio_vivo")
        self.assertEqual(mon._rotulo_preco_referencia(origem), "seu anúncio")


class TestMonitorConcorrentesMetricasDatadog(unittest.TestCase):
    """Garante que as métricas são enviadas ao Datadog a cada ciclo do agente."""

    def setUp(self):
        _isolar_batalha(self)

    @patch.object(mon.ml_client, "buscar_concorrentes_por_termo", return_value=[
        {"item_id": "MLB1", "titulo": "Kit Impala X", "preco": 38.0, "quantidade_vendida": 5},
        {"item_id": "MLB2", "titulo": "Kit Impala Y", "preco": 42.0, "quantidade_vendida": 2},
    ])
    @patch.object(mon, "_carregar_lista", return_value=[_LISTA_ESTAVEL[0]])
    @patch.object(mon, "_carregar_historico", return_value={})
    @patch.object(mon, "_salvar_historico")
    @patch.object(mon, "alertar_gestor", return_value=False)
    @patch.object(mon, "gauge")
    @patch.object(mon, "incrementar")
    def test_gauge_preco_e_gap_emitidos(self, mock_incrementar, mock_gauge, *_):
        mon.executar(enviar_alerta=False)

        nomes_gauge = [c.args[0] for c in mock_gauge.call_args_list]
        self.assertIn("mercado.meu_preco", nomes_gauge)
        self.assertIn("mercado.menor_preco_concorrente", nomes_gauge)
        self.assertIn("mercado.gap_preco_pct", nomes_gauge)
        self.assertIn("mercado.total_concorrentes", nomes_gauge)

    @patch.object(mon, "MONITOR_CONCORRENTES_ALERTAR_GAP_SO_ANUNCIO_VIVO", False)
    @patch.object(mon.ml_client, "buscar_concorrentes_por_termo", return_value=[
        {"item_id": "MLB1", "titulo": "Kit Impala X", "preco": 30.0, "quantidade_vendida": 10},
    ])
    @patch.object(mon, "_carregar_lista", return_value=[_LISTA_ALERTA[0]])
    @patch.object(mon, "_carregar_historico", return_value={})
    @patch.object(mon, "_salvar_historico")
    @patch.object(mon, "alertar_gestor", return_value=True)
    @patch.object(mon, "gauge")
    @patch.object(mon, "incrementar")
    def test_incrementa_alertas_quando_preco_acima(self, mock_incrementar, mock_gauge, *_):
        mon.executar(enviar_alerta=True)

        nomes_incr = [c.args[0] for c in mock_incrementar.call_args_list]
        self.assertIn("mercado.alertas_preco", nomes_incr)

    @patch.object(mon.ml_client, "buscar_concorrentes_por_termo", return_value=[
        {"item_id": "MLB1", "titulo": "Kit Impala X", "preco": 38.0, "quantidade_vendida": 5},
    ])
    @patch.object(mon, "_carregar_lista", return_value=[_LISTA_ESTAVEL[0]])
    @patch.object(mon, "_carregar_historico", return_value={})
    @patch.object(mon, "_salvar_historico")
    @patch.object(mon, "alertar_gestor", return_value=False)
    @patch.object(mon, "gauge")
    @patch.object(mon, "incrementar")
    def test_tag_produto_inclui_id_do_json(self, mock_incrementar, mock_gauge, *_):
        mon.executar(enviar_alerta=False)

        todas_tags = []
        for c in mock_gauge.call_args_list:
            tags = c.kwargs.get("tags") or []
            todas_tags.extend(tags)
        self.assertTrue(any("produto:kit1" in t for t in todas_tags))


class TestWatchlistItem(unittest.TestCase):
    def setUp(self):
        _isolar_batalha(self)

    @patch.object(mon, "MONITOR_CONCORRENTES_ALERTAR_GAP_SO_ANUNCIO_VIVO", False)
    @patch.object(mon, "alertar_gestor", return_value=True)
    @patch.object(mon, "_salvar_historico")
    @patch.object(
        mon,
        "_carregar_historico",
        return_value={"watch1": {"preco": 50.0, "status": "active", "menor_preco": 50.0}},
    )
    @patch.object(
        mon,
        "_carregar_lista",
        return_value=[
            {
                "id": "watch1",
                "ativo": True,
                "tipo": "item",
                "nome": "Rival Kit 10",
                "item_id_concorrente": "MLB999888777",
                "meu_preco": 69.9,
            }
        ],
    )
    @patch.object(
        mon.ml_client,
        "buscar_item_publico",
        return_value={
            "item_id": "MLB999888777",
            "titulo": "Kit 10 Rival",
            "preco": 40.0,
            "status": "active",
            "sold_quantity": 12,
            "seller_id": "1",
            "permalink": "https://mlb",
        },
    )
    def test_watchlist_alerta_preco_e_secao_telegram(self, *_):
        out = mon.executar(enviar_alerta=True, enriquecer_metricas=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["resultados"][0]["tipo"], "item")
        self.assertGreaterEqual(out["total_alertas"], 1)
        texto = " ".join(out.get("alertas") or [])
        self.assertIn("[watchlist]", texto)
        mon.alertar_gestor.assert_called_once()
        msg = mon.alertar_gestor.call_args[0][0]
        self.assertIn("Watchlist MLB", msg)

    @patch.object(mon, "MONITOR_CONCORRENTES_ALERTAR_GAP_SO_ANUNCIO_VIVO", True)
    @patch.object(mon, "_salvar_historico")
    @patch.object(mon, "_carregar_historico", return_value={})
    @patch.object(
        mon,
        "_carregar_lista",
        return_value=[
            {
                "id": "kit-ids",
                "ativo": True,
                "nome": "Kit via MLB",
                "termo_busca": "kit esmalte impala",
                "item_ids": ["MLB123456789"],
                "meu_preco": 44.9,
                "limite_resultados": 5,
            }
        ],
    )
    @patch.object(
        mon.ml_client,
        "hidratar_itens",
        return_value=[{"item_id": "MLB123456789", "titulo": "Kit Impala", "preco": 42.0}],
    )
    @patch.object(mon.ml_client, "buscar_concorrentes_por_termo")
    def test_termo_usa_item_ids_sem_busca(self, mock_termo, *_):
        out = mon.executar(enviar_alerta=False, enriquecer_metricas=False)
        self.assertTrue(out["ok"])
        mock_termo.assert_not_called()
        self.assertEqual(out["resultados"][0]["total_concorrentes"], 1)

    @patch.object(mon, "MONITOR_CONCORRENTES_ALERTAR_GAP_SO_ANUNCIO_VIVO", True)
    @patch.object(mon, "_salvar_historico")
    @patch.object(
        mon,
        "_carregar_historico",
        return_value={"kit-hist": {"item_ids": ["MLB123456789"], "menor_preco": 41.0}},
    )
    @patch.object(
        mon,
        "_carregar_lista",
        return_value=[
            {
                "id": "kit-hist",
                "ativo": True,
                "nome": "Kit hist",
                "termo_busca": "kit esmalte impala",
                "meu_preco": 44.9,
                "limite_resultados": 5,
            }
        ],
    )
    @patch.object(
        mon.ml_client,
        "hidratar_itens",
        return_value=[{"item_id": "MLB123456789", "titulo": "Kit Impala", "preco": 41.0}],
    )
    @patch.object(mon.ml_client, "buscar_concorrentes_por_termo")
    def test_reusa_item_ids_do_historico(self, mock_termo, mock_hid, _lista, _hist, mock_salvar, *_):
        out = mon.executar(enviar_alerta=False, enriquecer_metricas=False)
        self.assertTrue(out["ok"])
        mock_termo.assert_not_called()
        mock_hid.assert_called()
        gravado = mock_salvar.call_args[0][0]
        self.assertIn("MLB123456789", gravado["kit-hist"]["item_ids"])
        self.assertFalse(gravado["kit-hist"]["amostra_cega"])

    @patch.object(mon, "_salvar_historico")
    @patch.object(
        mon,
        "_carregar_historico",
        return_value={"kit-hist": {"item_ids": ["MLB123456789"], "menor_preco": 41.0}},
    )
    @patch.object(
        mon,
        "_carregar_lista",
        return_value=[
            {
                "id": "kit-hist",
                "ativo": True,
                "nome": "Kit hist",
                "termo_busca": "kit esmalte impala",
                "meu_preco": 44.9,
                "limite_resultados": 5,
            }
        ],
    )
    @patch.object(mon.ml_client, "hidratar_itens", return_value=[])
    @patch.object(mon.ml_client, "buscar_concorrentes_por_termo", return_value=[])
    def test_amostra_cega_preserva_item_ids(self, _termo, _hid, _lista, _hist, mock_salvar):
        out = mon.executar(enviar_alerta=False, enriquecer_metricas=False)
        self.assertTrue(out["ok"])
        self.assertTrue(out["resultados"][0]["amostra_cega"])
        gravado = mock_salvar.call_args[0][0]
        self.assertEqual(gravado["kit-hist"]["item_ids"], ["MLB123456789"])
        self.assertEqual(gravado["kit-hist"]["menor_preco"], 41.0)

    @patch.object(mon, "_salvar_historico")
    @patch.object(mon, "_carregar_historico", return_value={})
    @patch.object(
        mon,
        "_carregar_lista",
        return_value=[
            {
                "id": "watch-bad",
                "ativo": True,
                "tipo": "item",
                "nome": "Sem MLB",
                "item_id_concorrente": "MLB_PREENCHER",
                "meu_preco": 40.0,
            }
        ],
    )
    def test_watchlist_ignora_mlb_preencher(self, *_):
        out = mon.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertFalse(out["resultados"][0]["ok"])
        self.assertIn("PREENCHER", out["resultados"][0].get("erro", "").upper())


class TestNovosKitsImpalaNoMonitor(unittest.TestCase):
    def setUp(self):
        p = patch(
            "integracoes.esmaltes.metricas_batalha_impala.processar_e_persistir",
            return_value={},
        )
        p.start()
        self.addCleanup(p.stop)
        p2 = patch.object(
            mon,
            "_aplicar_lacunas_monitor",
            return_value={
                "avaliacoes_texto": [],
                "perguntas": [],
                "padroes_reclamacao": [],
                "tendencia_demanda": {"tendencia": "indeterminado"},
                "margem_real": {"margem_disponivel": False},
            },
        )
        p2.start()
        self.addCleanup(p2.stop)
        p3 = patch.object(mon, "_persistir_lacunas_ciclo")
        p3.start()
        self.addCleanup(p3.stop)

    @patch.object(mon, "MONITOR_CONCORRENTES_ALERTAR_GAP_SO_ANUNCIO_VIVO", True)
    @patch.object(mon, "alertar_gestor", return_value=True)
    @patch.object(mon, "_salvar_historico")
    @patch.object(mon, "_carregar_historico", return_value={})
    @patch.object(mon, "_carregar_lista", return_value=_LISTA_ESTAVEL)
    @patch.object(mon.ml_client, "buscar_concorrentes_por_termo", return_value=[_CONC])
    @patch(
        "integracoes.esmaltes.novos_kits_impala.processar",
        return_value={
            "ok": True,
            "n_novos": 1,
            "alerta_enviado": True,
            "alertas": [],
        },
    )
    def test_dispara_card_novos_kits(self, mock_proc, *_):
        out = mon.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        mock_proc.assert_called_once()
        self.assertTrue(mock_proc.call_args.kwargs.get("enviar_alerta"))
        self.assertTrue(mock_proc.call_args.kwargs.get("persistir"))


class TestAplicarLacunasMonitor(unittest.TestCase):
    def test_margem_e_padroes(self):
        entrada = {"custo_unitario": 28.13, "meu_preco": 44.90}
        anuncios = [{"item_id": "MLB1", "preco": 30.0, "avaliacoes": 4}]
        with patch.object(
            mon,
            "buscar_avaliacoes_item",
            return_value=[{"texto": "Demorou a entrega", "nota_estrelas": 2}],
        ):
            with patch.object(mon, "buscar_perguntas_item", return_value=[]):
                with patch.object(mon, "registrar_snapshot_demanda", return_value={}):
                    with patch.object(
                        mon,
                        "calcular_tendencia_demanda",
                        return_value={"tendencia": "alta", "variacao_pct": 10.0, "confiabilidade": "baixa"},
                    ):
                        out = mon._aplicar_lacunas_monitor(
                            entrada, anuncios, termo="kit impala", meu_preco=44.90
                        )
        self.assertTrue(out["margem_real"]["margem_disponivel"])
        self.assertEqual(out["tendencia_demanda"]["tendencia"], "alta")
        self.assertTrue(any(p["padrao"] == "atraso" for p in out["padroes_reclamacao"]))

    def test_linhas_telegram_lacunas(self):
        linhas = mon._linhas_telegram_lacunas(
            [
                {
                    "ok": True,
                    "nome": "Kit",
                    "tendencia_demanda": {"tendencia": "alta", "variacao_pct": 20, "confiabilidade": "baixa"},
                    "padroes_reclamacao": [{"padrao": "atraso", "frequencia": 3}],
                    "margem_real": {"margem_disponivel": True, "margem_rs": 8.69, "margem_pct": 19.4},
                }
            ]
        )
        self.assertTrue(any("demanda alta" in x for x in linhas))
        self.assertTrue(any("atraso" in x for x in linhas))


if __name__ == "__main__":
    unittest.main()
