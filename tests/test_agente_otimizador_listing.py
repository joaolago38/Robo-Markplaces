"""
tests/test_agente_otimizador_listing.py — otimizador de título ML (somente sugestão).
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.ml import agente_otimizador_listing as opt


class TestAnalisarItem(unittest.TestCase):
    def test_item_id_vazio(self):
        out = opt.analisar_item("")
        self.assertFalse(out["ok"])
        self.assertIn("inválido", out["erro"].lower())

    @patch.object(opt.ml_client, "buscar_metricas_item", return_value={})
    def test_item_nao_encontrado(self, *_):
        out = opt.analisar_item("MLB999")
        self.assertFalse(out["ok"])
        self.assertIn("não encontrado", out["erro"].lower())

    @patch.object(opt, "perguntar", return_value="1. Kit Impala 12 Cores - Profissional\nMotivo: palavras-chave")
    @patch.object(
        opt.ml_client,
        "buscar_detalhes_concorrentes",
        return_value=[{"titulo": "Concorrente", "preco": 49.9, "quantidade_vendida": 100, "frete_gratis": True, "condicao": "new"}],
    )
    @patch.object(
        opt.ml_client,
        "buscar_metricas_item",
        return_value={"titulo": "Kit Atual", "preco": 59.9, "estoque": 10, "visitas_7d": 5, "visitas_30d": 20, "status": "active"},
    )
    def test_sucesso_chama_claude_com_system(self, *_):
        out = opt.analisar_item("MLB123")
        self.assertTrue(out["ok"])
        self.assertEqual(out["item_id"], "MLB123")
        self.assertEqual(out["titulo_atual"], "Kit Atual")
        self.assertEqual(out["visitas_7d"], 5)
        self.assertEqual(out["concorrentes_analisados"], 1)
        self.assertIn("Kit Impala", out["sugestoes_texto"])

        mock_perguntar = opt.perguntar
        mock_perguntar.assert_called_once()
        kwargs = mock_perguntar.call_args.kwargs
        self.assertEqual(kwargs.get("system"), opt.SYSTEM_OTIMIZADOR)
        self.assertIn("Kit Atual", kwargs.get("contexto", ""))
        self.assertIn("Concorrente", kwargs.get("contexto", ""))

    @patch.object(opt, "perguntar", return_value="⚠️ Erro na IA: falha de comunicação com o provedor.")
    @patch.object(opt.ml_client, "buscar_detalhes_concorrentes", return_value=[{"titulo": "X", "preco": 10, "quantidade_vendida": 1}])
    @patch.object(
        opt.ml_client,
        "buscar_metricas_item",
        return_value={"titulo": "T", "preco": 10, "estoque": 1, "visitas_7d": 1, "visitas_30d": 2, "status": "active"},
    )
    def test_ia_falhou_mantem_ok_true(self, *_):
        out = opt.analisar_item("MLB1")
        self.assertTrue(out["ok"])
        self.assertTrue(out.get("ia_falhou"))
        self.assertTrue(out["sugestoes_texto"].startswith("⚠️"))

    @patch.object(opt, "perguntar", side_effect=RuntimeError("boom"))
    @patch.object(opt.ml_client, "buscar_detalhes_concorrentes", return_value=[])
    @patch.object(
        opt.ml_client,
        "buscar_metricas_item",
        return_value={"titulo": "T", "preco": 10, "estoque": 1, "visitas_7d": 1, "visitas_30d": 2, "status": "active"},
    )
    def test_excecao_retorna_ok_false(self, *_):
        out = opt.analisar_item("MLB-ERR")
        self.assertFalse(out["ok"])
        self.assertIn("boom", out["erro"])


class TestExecutar(unittest.TestCase):
    @patch.object(opt, "analisar_catalogo", return_value={"ok": True, "total_analisados": 1, "alerta_enviado": True})
    def test_executar_sucesso(self, *_):
        self.assertTrue(opt.executar(limite_itens=3))

    @patch.object(opt, "analisar_catalogo", return_value={"ok": False, "erro": "falha"})
    def test_executar_falha(self, *_):
        self.assertFalse(opt.executar())

    @patch.object(opt, "executar", return_value=True)
    def test_main_retorna_zero(self, *_):
        self.assertEqual(opt.main(), 0)


class TestCarregarCatalogo(unittest.TestCase):
    @patch.object(opt, "CATALOGO_PATH")
    def test_catalogo_ausente(self, mock_path):
        mock_path.is_file.return_value = False
        self.assertEqual(opt._carregar_catalogo(), [])

    def test_listar_itens_ignora_entradas_invalidas(self):
        itens = opt._listar_itens_ml_ativos(
            [
                "invalido",
                {"canais": "x"},
                {"canais": {"mercadolivre": {"ativo": True, "item_id": "MLB-OK"}}},
            ]
        )
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["item_id"], "MLB-OK")


_CATALOGO_FIXTURE = [
    {
        "sku": "SKU-A",
        "nome": "Produto A",
        "canais": {
            "mercadolivre": {"ativo": True, "item_id": "MLB-A"},
            "shopee": {"ativo": False},
        },
    },
    {
        "sku": "SKU-B",
        "nome": "Produto B",
        "canais": {
            "mercadolivre": {"ativo": True, "item_id": "MLB-B"},
        },
    },
    {
        "sku": "SKU-C",
        "nome": "Produto C",
        "canais": {
            "mercadolivre": {"ativo": False, "item_id": "MLB-C"},
        },
    },
    {
        "sku": "SKU-D",
        "nome": "Produto D",
        "canais": {
            "mercadolivre": {"ativo": True, "item_id": "MLB_PREENCHER"},
        },
    },
]


class TestAnalisarCatalogo(unittest.TestCase):
    @patch("core.notificador.alertar_gestor", return_value=True)
    @patch.object(opt, "analisar_item")
    @patch.object(opt, "_carregar_catalogo", return_value=_CATALOGO_FIXTURE)
    def test_respeita_limite_e_ignora_inativos(self, mock_catalogo, mock_analisar, mock_alertar):
        mock_analisar.side_effect = [
            {
                "ok": True,
                "item_id": "MLB-A",
                "titulo_atual": "A",
                "visitas_7d": 10,
                "sugestoes_texto": "1. Título sugerido A",
                "concorrentes_analisados": 2,
            },
            {
                "ok": True,
                "item_id": "MLB-B",
                "titulo_atual": "B",
                "visitas_7d": 5,
                "sugestoes_texto": "1. Título sugerido B",
                "concorrentes_analisados": 1,
            },
        ]

        out = opt.analisar_catalogo(limite_itens=1)

        self.assertTrue(out["ok"])
        self.assertEqual(out["total_analisados"], 1)
        self.assertEqual(mock_analisar.call_count, 1)
        mock_analisar.assert_called_with("MLB-A")
        mock_alertar.assert_called_once()
        self.assertTrue(out["alerta_enviado"])
        self.assertEqual(len(out["resultados"]), 1)

    @patch("core.notificador.alertar_gestor", return_value=True)
    @patch.object(opt, "analisar_item", return_value={"ok": True, "concorrentes_analisados": 0, "sugestoes_texto": "x"})
    @patch.object(opt, "_carregar_catalogo", return_value=_CATALOGO_FIXTURE[:1])
    def test_omite_sem_concorrentes_no_resumo(self, _cat, _analisar, mock_alertar):
        out = opt.analisar_catalogo(limite_itens=5)
        self.assertTrue(out["ok"])
        msg = mock_alertar.call_args[0][0]
        self.assertIn("Nenhum item", msg)

    @patch("core.notificador.alertar_gestor", return_value=True)
    @patch.object(
        opt,
        "analisar_item",
        return_value={
            "ok": True,
            "item_id": "MLB-A",
            "titulo_atual": "A",
            "visitas_7d": 3,
            "sugestoes_texto": "1. Novo título",
            "concorrentes_analisados": 2,
        },
    )
    @patch.object(opt, "_carregar_catalogo", return_value=_CATALOGO_FIXTURE[:1])
    def test_alertar_gestor_com_itens_relevantes(self, _cat, _analisar, mock_alertar):
        opt.analisar_catalogo(limite_itens=5)
        msg = mock_alertar.call_args[0][0]
        self.assertIn("MLB-A", msg)
        self.assertIn("Novo título", msg)


class TestHelpers(unittest.TestCase):
    def test_item_id_preencher_invalido(self):
        self.assertFalse(opt._item_id_valido("MLB_PREENCHER"))

    def test_montar_contexto_inclui_dados(self):
        ctx = opt._montar_contexto(
            {"titulo": "Meu Kit", "preco": 50, "estoque": 3, "visitas_7d": 7, "visitas_30d": 30, "status": "active"},
            [{"titulo": "Conc", "preco": 45, "quantidade_vendida": 99, "frete_gratis": True, "condicao": "new"}],
        )
        self.assertIn("Meu Kit", ctx)
        self.assertIn("Conc", ctx)

    def test_montar_contexto_sem_concorrentes(self):
        ctx = opt._montar_contexto({"titulo": "X", "preco": 1, "estoque": 0, "visitas_7d": 0, "visitas_30d": 0, "status": "active"}, [])
        self.assertIn("nenhum concorrente", ctx.lower())

    def test_primeira_sugestao_vazia(self):
        self.assertEqual(opt._primeira_sugestao("⚠️ erro"), "")


if __name__ == "__main__":
    unittest.main()
