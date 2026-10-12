"""tests/test_avaliacao_ia_masterprint.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.masterprint import avaliacao_ia_secundaria as ia
from integracoes.masterprint import ramo as ramo_mod


class TestRamoMasterprint(unittest.TestCase):
    def setUp(self):
        ramo_mod.limpar_cache_ramo()

    def test_formatar_cnpj(self):
        self.assertEqual(ramo_mod.formatar_cnpj("12345678000199"), "12.345.678/0001-99")

    @patch("integracoes.masterprint.ramo.MASTERPRINT_CNPJ", "12345678000199")
    @patch("integracoes.masterprint.ramo.MASTERPRINT_ML_SELLER_ID", "999888")
    @patch("integracoes.masterprint.ramo.MASTERPRINT_ML_NICKNAME", "LOJA_MP")
    @patch("integracoes.masterprint.ramo.MASTERPRINT_TELEGRAM_GESTOR_CHAT_ID", "-100111")
    @patch("integracoes.masterprint.ramo.TELEGRAM_GESTOR_CHAT_ID", "-100222")
    def test_conta_separada_dos_esmaltes(self):
        ramo_mod.limpar_cache_ramo()
        r = ramo_mod.carregar_ramo()
        self.assertTrue(r["conta_separada"])
        self.assertEqual(r["ml_seller_id"], "999888")
        self.assertEqual(r["telegram_gestor_chat_id"], "-100111")
        self.assertTrue(r["telegram_chat_proprio"])
        linha = ramo_mod.linha_identidade_telegram(r)
        self.assertIn("12.345.678/0001-99", linha)
        self.assertIn("≠ esmaltes", linha)


class TestAvaliacaoIaMasterprint(unittest.TestCase):
    def test_formatar_secao_vazia(self):
        self.assertEqual(ia.formatar_secao_ia_masterprint(None), "")

    def test_formatar_secao_ecosistema(self):
        txt = ia.formatar_secao_ia_masterprint(
            {
                "ecosistema_ml": "PETG Masterprint com margem estável e pouca guerra de preço.",
                "pressao_preco": "Baixa no topo do ranking.",
                "oportunidade": "Empurrar Preto 1kg.",
                "acoes": [
                    {
                        "prioridade": "alta",
                        "acao": "Manter preço Preto",
                        "motivo": "Maior lucro proxy",
                    }
                ],
                "alertas": [],
                "_fonte": "nova_chamada_diaria",
            }
        )
        self.assertIn("ecossistema ML Masterprint", txt)
        self.assertIn("1×/dia", txt)
        self.assertIn("O que está acontecendo", txt)
        self.assertIn("Manter preço Preto", txt)

    @patch("integracoes.masterprint.avaliacao_ia_secundaria.MASTERPRINT_CLAUDE_DIARIO", False)
    def test_diario_off_nao_chama(self):
        with patch(
            "integracoes.masterprint.avaliacao_ia_secundaria.perguntar_estruturado"
        ) as mock_p, patch(
            "integracoes.masterprint.avaliacao_ia_secundaria.cache_claude_hoje",
            return_value=None,
        ):
            out = ia.avaliar_masterprint_secundario(
                escopo="petg",
                consolidado={"total_anuncios_ativos": 3},
            )
            self.assertIsNone(out)
            mock_p.assert_not_called()

    @patch("integracoes.masterprint.avaliacao_ia_secundaria.MASTERPRINT_CLAUDE_DIARIO", True)
    def test_reutiliza_cache_do_dia(self):
        cached = {"ecosistema_ml": "cache", "acoes": []}
        with patch(
            "integracoes.masterprint.avaliacao_ia_secundaria.cache_claude_hoje",
            return_value=cached,
        ), patch(
            "integracoes.masterprint.avaliacao_ia_secundaria.perguntar_estruturado"
        ) as mock_p:
            out = ia.avaliar_masterprint_secundario(
                escopo="petg",
                consolidado={"total_anuncios_ativos": 2},
            )
            self.assertEqual(out.get("ecosistema_ml"), "cache")
            self.assertEqual(out.get("_fonte"), "cache_diario")
            mock_p.assert_not_called()

    @patch("integracoes.masterprint.avaliacao_ia_secundaria.MASTERPRINT_CLAUDE_DIARIO", True)
    @patch("integracoes.masterprint.avaliacao_ia_secundaria.MASTERPRINT_CLAUDE_SO_NOITE", True)
    @patch("integracoes.masterprint.avaliacao_ia_secundaria.MASTERPRINT_CLAUDE_RESTANTE_MIN_USD", 2.5)
    def test_reserva_esmaltes_bloqueia_nova_chamada(self):
        with patch(
            "integracoes.masterprint.avaliacao_ia_secundaria.cache_claude_hoje",
            return_value=None,
        ), patch(
            "integracoes.masterprint.avaliacao_ia_secundaria.ja_usou_claude_hoje",
            return_value=False,
        ), patch(
            "integracoes.masterprint.avaliacao_ia_secundaria._na_janela_claude_nova",
            return_value=True,
        ), patch("core.claude_orcamento.pode_chamar", return_value=(True, "ok")), patch(
            "core.claude_orcamento.resumo",
            return_value={"restante_usd": 1.0},
        ), patch(
            "integracoes.masterprint.avaliacao_ia_secundaria.perguntar_estruturado"
        ) as mock_p:
            out = ia.avaliar_masterprint_secundario(
                escopo="escritorio",
                consolidado={"total_anuncios_ativos": 2},
            )
            self.assertIsNone(out)
            mock_p.assert_not_called()

    @patch("integracoes.masterprint.avaliacao_ia_secundaria.MASTERPRINT_CLAUDE_DIARIO", True)
    @patch("integracoes.masterprint.avaliacao_ia_secundaria.MASTERPRINT_CLAUDE_SO_NOITE", True)
    def test_manha_nao_chama_claude_nova(self):
        with patch(
            "integracoes.masterprint.avaliacao_ia_secundaria.cache_claude_hoje",
            return_value=None,
        ), patch(
            "integracoes.masterprint.avaliacao_ia_secundaria.ja_usou_claude_hoje",
            return_value=False,
        ), patch(
            "integracoes.masterprint.avaliacao_ia_secundaria._na_janela_claude_nova",
            return_value=False,
        ), patch(
            "integracoes.masterprint.avaliacao_ia_secundaria.perguntar_estruturado"
        ) as mock_p:
            out = ia.avaliar_masterprint_secundario(
                escopo="petg",
                consolidado={"total_anuncios_ativos": 1},
            )
            self.assertIsNone(out)
            mock_p.assert_not_called()

    def test_janela_noite_brt(self):
        from types import SimpleNamespace

        with patch(
            "integracoes.masterprint.avaliacao_ia_secundaria.MASTERPRINT_CLAUDE_SO_NOITE",
            True,
        ), patch(
            "integracoes.masterprint.avaliacao_ia_secundaria.agora_brasil",
            return_value=SimpleNamespace(hour=21),
        ):
            self.assertTrue(ia._na_janela_claude_nova())
        with patch(
            "integracoes.masterprint.avaliacao_ia_secundaria.MASTERPRINT_CLAUDE_SO_NOITE",
            True,
        ), patch(
            "integracoes.masterprint.avaliacao_ia_secundaria.agora_brasil",
            return_value=SimpleNamespace(hour=14),
        ):
            self.assertFalse(ia._na_janela_claude_nova())


class TestTelegramMantemFormato(unittest.TestCase):
    def test_petg_sem_historico_nao_duplica_mais_vendidos(self):
        from agentes.filamentos.agente_monitor_masterprint_petg import montar_mensagem_telegram

        msg = montar_mensagem_telegram(
            {
                "total_anuncios_ativos": 1,
                "preco_min": 80,
                "preco_max": 90,
                "preco_medio": 85,
                "custo_padrao_1kg_brl": 45.96,
                "tabela_valida_em": "2026-07-23",
                "margem_media_brl": 20,
                "lucro_proxy_total": 100,
                "vendas_totais": 10,
                "receita_proxy_total": 850,
                "termos_varridos": 1,
                "mais_rentaveis": [
                    {
                        "titulo": "PETG Preto",
                        "preco": 90,
                        "custo_unitario_brl": 45.96,
                        "margem_brl": 30,
                        "margem_pct": 33,
                        "lucro_proxy": 300,
                        "quantidade_vendida": 10,
                        "item_id": "MLB1",
                    }
                ],
                "maior_ganho": [
                    {
                        "titulo": "PETG Preto",
                        "preco": 90,
                        "quantidade_vendida": 10,
                        "ganho_fonte": "sem_historico_usa_vendas",
                        "delta_vendas": 10,
                        "item_id": "MLB1",
                    }
                ],
                "mais_vendidos": [
                    {
                        "titulo": "PETG Preto",
                        "preco": 90,
                        "quantidade_vendida": 10,
                        "receita_proxy": 900,
                        "item_id": "MLB1",
                    }
                ],
            }
        )
        self.assertIn("AGIR — priorize margem", msg)
        self.assertIn("ATENÇÃO", msg)
        self.assertIn("Sem histórico Δ", msg)
        self.assertNotIn("*Volume*", msg)

    def test_petg_com_ia_anexa_no_final(self):
        from agentes.filamentos.agente_monitor_masterprint_petg import montar_mensagem_telegram

        msg = montar_mensagem_telegram(
            {
                "total_anuncios_ativos": 1,
                "preco_min": 80,
                "preco_max": 90,
                "preco_medio": 85,
                "custo_padrao_1kg_brl": 45.96,
                "tabela_valida_em": "2026-07-23",
                "margem_media_brl": 20,
                "lucro_proxy_total": 100,
                "vendas_totais": 10,
                "receita_proxy_total": 850,
                "termos_varridos": 1,
                "mais_rentaveis": [],
                "maior_ganho": [],
                "mais_vendidos": [],
            },
            avaliacao_ia={
                "ecosistema_ml": "ok",
                "acoes": [],
                "alertas": [],
                "_fonte": "cache_diario",
            },
        )
        self.assertIn("AGIR — priorize margem", msg)
        self.assertIn("Claude — ecossistema ML Masterprint", msg)
        # com ganho vazio, Volume pode aparecer vazio - maior_ganho [] => sem_historico False
        # mais_vendidos [] => sem seção Volume
        self.assertLess(
            msg.index("AGIR — priorize margem"),
            msg.index("Claude — ecossistema ML Masterprint"),
        )


if __name__ == "__main__":
    unittest.main()
