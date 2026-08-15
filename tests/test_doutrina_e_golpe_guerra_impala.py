"""tests/test_doutrina_e_golpe_guerra_impala.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.esmaltes import doutrina_guerra_impala as dg
from integracoes.esmaltes import golpe_guerra_impala as gg


class TestDoutrinaGuerra(unittest.TestCase):
    def test_arquivo_tem_frente_e_perl_preco(self):
        d = dg.carregar_doutrina()
        self.assertEqual(d.get("sku_preco"), "IMP-PERL-004")
        self.assertEqual(
            set(d.get("skus_frente") or []),
            {"IMP-MIMO-003", "IMP-PERL-004", "IMP-JUPAES-006"},
        )

    def test_so_perl_mexe_preco_entre_imp(self):
        self.assertTrue(dg.sku_pode_mexer_preco("IMP-PERL-004"))
        self.assertFalse(dg.sku_pode_mexer_preco("IMP-MIMO-003"))
        self.assertFalse(dg.sku_pode_mexer_preco("IMP-JUPAES-006"))
        self.assertFalse(dg.sku_pode_mexer_preco("IMP-VR-015"))
        self.assertTrue(dg.sku_pode_mexer_preco("KIT-5"))

    def test_piso_fase1(self):
        piso = dg.piso_preco({"custo_total": 26.23, "fase_atual": 1})
        self.assertIsNotNone(piso)
        self.assertGreater(piso, 26.23)
        self.assertLess(piso, 39.9)

    def test_ignorar_sem_rival_ao_vivo(self):
        row = dg.classificar_golpe(
            {
                "sku": "IMP-PERL-004",
                "mlb_ok": True,
                "fonte_rival": "ausente",
                "gap_pct": None,
                "rivais_no_tam": 0,
                "nosso_preco": 39.9,
            },
            produto={"custo_total": 26.23, "fase_atual": 1},
        )
        self.assertEqual(row["classificacao"], dg.CLASSIF_IGNORAR)
        self.assertFalse(row["disparar"])

    def test_igualar_perl_acima_do_piso(self):
        row = dg.classificar_golpe(
            {
                "sku": "IMP-PERL-004",
                "mlb_ok": True,
                "fonte_rival": "ao_vivo",
                "gap_pct": 8.0,
                "rivais_no_tam": 2,
                "nosso_preco": 39.9,
                "rival_min": 37.0,
            },
            produto={"custo_total": 26.23, "fase_atual": 1},
        )
        self.assertEqual(row["classificacao"], dg.CLASSIF_IGUALAR)
        self.assertTrue(row["disparar"])
        self.assertEqual(row["arma"], "preco")

    def test_nao_perseguir_abaixo_do_piso(self):
        row = dg.classificar_golpe(
            {
                "sku": "IMP-PERL-004",
                "mlb_ok": True,
                "fonte_rival": "ao_vivo",
                "gap_pct": 20.0,
                "rivais_no_tam": 2,
                "nosso_preco": 39.9,
                "rival_min": 30.0,
            },
            produto={"custo_total": 26.23, "fase_atual": 1},
        )
        self.assertEqual(row["classificacao"], dg.CLASSIF_NAO_PERSEGUIR)
        self.assertTrue(row["disparar"])
        self.assertEqual(row["arma"], "observar")

    def test_mimo_diferencia(self):
        row = dg.classificar_golpe(
            {
                "sku": "IMP-MIMO-003",
                "mlb_ok": True,
                "fonte_rival": "ao_vivo",
                "gap_pct": 10.0,
                "rivais_no_tam": 2,
                "nosso_preco": 44.9,
                "rival_min": 40.0,
            },
            produto={"custo_total": 28.13, "fase_atual": 1},
        )
        self.assertEqual(row["classificacao"], dg.CLASSIF_DIFERENCIAR)
        self.assertEqual(row["arma"], "listing")
        self.assertTrue(row["disparar"])

    def test_fora_da_frente_none(self):
        self.assertIsNone(
            dg.classificar_golpe({"sku": "IMP-VR-015", "mlb_ok": True, "gap_pct": 10})
        )


class TestGolpeCompilador(unittest.TestCase):
    def test_escolhe_igualar_antes_de_diferenciar(self):
        batalha = {
            "comparacoes": [
                {
                    "sku": "IMP-MIMO-003",
                    "mlb_ok": True,
                    "fonte_rival": "ao_vivo",
                    "gap_pct": 12.0,
                    "rivais_no_tam": 2,
                    "nosso_preco": 44.9,
                    "rival_min": 40.0,
                    "kit_tag": "kit:mimo003",
                },
                {
                    "sku": "IMP-PERL-004",
                    "mlb_ok": True,
                    "fonte_rival": "ao_vivo",
                    "gap_pct": 8.0,
                    "rivais_no_tam": 2,
                    "nosso_preco": 39.9,
                    "rival_min": 37.0,
                    "kit_tag": "kit:perl004",
                },
            ]
        }
        produtos = [
            {"sku": "IMP-MIMO-003", "custo_total": 28.13, "fase_atual": 1},
            {"sku": "IMP-PERL-004", "custo_total": 26.23, "fase_atual": 1},
        ]
        out = gg.montar_golpe(batalha, produtos=produtos)
        self.assertTrue(out["disparar"])
        self.assertEqual(out["golpe"]["sku"], "IMP-PERL-004")
        self.assertEqual(out["golpe"]["classificacao"], dg.CLASSIF_IGUALAR)

    @patch.object(gg, "emitir_metricas_golpe")
    @patch.object(gg, "escrever_json_atomico")
    def test_overlay_nao_dispara_golpe(self, _w, _em):
        batalha = {
            "visao_operacional": True,
            "comparacoes": [
                {
                    "sku": "IMP-PERL-004",
                    "mlb_ok": True,
                    "fonte_rival": "ao_vivo",
                    "gap_pct": 8.0,
                    "rivais_no_tam": 2,
                    "nosso_preco": 39.9,
                    "rival_min": 37.0,
                    "kit_tag": "kit:perl004",
                }
            ],
        }
        produtos = [{"sku": "IMP-PERL-004", "custo_total": 26.23, "fase_atual": 1}]
        out = gg.processar_golpe_batalha(batalha, produtos=produtos, enviar_alerta=True)
        self.assertFalse(out["disparar"])
        self.assertTrue(out.get("overlay_sem_golpe"))
        self.assertFalse(out.get("alerta_enviado"))

    @patch.object(gg, "GOLPE_GUERRA_CLAUDE", True)
    @patch("core.resumo_ia.sintetizar_claude")
    def test_claude_so_no_disparo(self, mock_sint):
        mock_sint.return_value = "FAZER: PERL."
        ign = gg.sintetizar_golpe_claude({"disparar": False, "golpe": {"sku": "X"}})
        self.assertEqual(ign, "")
        mock_sint.assert_not_called()
        txt = gg.sintetizar_golpe_claude(
            {
                "disparar": True,
                "frente": ["IMP-PERL-004"],
                "golpe": {
                    "sku": "IMP-PERL-004",
                    "classificacao": "igualar_faixa",
                    "fazer": "igualar",
                    "nao_fazer": "dump",
                    "arma": "preco",
                },
            }
        )
        self.assertEqual(txt, "FAZER: PERL.")
        mock_sint.assert_called_once()
        self.assertEqual(mock_sint.call_args.kwargs.get("proposito"), "guerra_impala")


class TestRepricingDoutrina(unittest.TestCase):
    @patch("agentes.repricing.agente_repricing_impala.deve_congelar_repricing", return_value=(False, ""))
    @patch("agentes.repricing.agente_repricing_impala.carregar_produtos_catalogo")
    def test_mimo_nao_entra_em_ajustes(self, mock_cat, _cong):
        mock_cat.return_value = [
            {
                "sku": "IMP-MIMO-003",
                "nome": "Kit Impala Mimo",
                "custo_total": 28.13,
                "fase_atual": 1,
                "preco": 30.0,
                "precos_por_fase": {"fase1": 44.9},
                "canais": {"mercadolivre": {"item_id": "MLB123456789", "preco": 30.0}},
            }
        ]
        from agentes.repricing.agente_repricing_impala import executar

        out = executar(dry_run=True)
        self.assertEqual(out.get("total_ajustes"), 0)
        det = out.get("detalhes") or []
        self.assertTrue(any(r.get("congelado_doutrina") for r in det))


class TestAgenteGolpe(unittest.TestCase):
    @patch("agentes.esmaltes.agente_golpe_guerra_impala.alertar_gestor")
    @patch(
        "agentes.esmaltes.agente_golpe_guerra_impala.processar_de_snapshot_batalha",
        return_value={"ok": True, "disparar": False, "golpe": None, "mensagem": ""},
    )
    def test_sem_disparo_nao_alerta(self, _proc, mock_alert):
        from agentes.esmaltes.agente_golpe_guerra_impala import executar

        out = executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertFalse(out["disparar"])
        mock_alert.assert_not_called()


def _kit(sku: str, *, mlb: bool = False, estoque: int = 0, nome: str = "") -> dict:
    ml: dict = {"preco": 44.9, "estoque": estoque, "titulo_anuncio": nome or sku}
    if mlb:
        ml["item_id"] = "MLB12345678"
    return {
        "sku": sku,
        "nome": nome or sku,
        "estoque_total": estoque,
        "custo_total": 28.13,
        "preco": 44.9,
        "canais": {"mercadolivre": ml},
    }


class TestCondicoesGuerra(unittest.TestCase):
    def test_hoje_fase_0_sem_mlb(self):
        out = dg.avaliar_condicoes_guerra(
            produtos=[
                _kit("IMP-MIMO-003", nome="Kit 3 Mimo + Carmed"),
                _kit("IMP-PERL-004"),
                _kit("IMP-JUPAES-006"),
            ],
            radar={"mercado_confiavel": False},
            resumo_conta={"avaliacoes": 0, "nota": 0},
        )
        self.assertEqual(out["fase"], 0)
        self.assertEqual(out["fase_nome"], "abrir_frente")
        self.assertTrue(out["liberar"]["mimo"])
        self.assertFalse(out["liberar"]["ads"])
        self.assertFalse(out["liberar"]["golpe_preco"])
        self.assertFalse(out["liberar"]["ruptura"])
        self.assertIn("MIMO", out["fazer"])
        pode, motivo = dg.sku_pode_publicar_agora("IMP-MIMO-003", condicoes=out)
        self.assertTrue(pode)
        self.assertIn("mimo", motivo)
        self.assertFalse(dg.sku_pode_publicar_agora("IMP-PERL-004", condicoes=out)[0])
        self.assertFalse(dg.sku_pode_publicar_agora("IMP-JUPAES-006", condicoes=out)[0])

    def test_fase_1_mimo_no_ar_sem_pedido(self):
        out = dg.avaliar_condicoes_guerra(
            produtos=[
                _kit("IMP-MIMO-003", mlb=True, estoque=10, nome="Kit 3 Mimo + Carmed"),
                _kit("IMP-PERL-004"),
            ],
            radar={"mercado_confiavel": False},
            resumo_conta={"avaliacoes": 0, "nota": 0},
        )
        self.assertEqual(out["fase"], 1)
        self.assertTrue(out["liberar"]["perl"])
        self.assertTrue(dg.sku_pode_publicar_agora("IMP-PERL-004", condicoes=out)[0])
        self.assertFalse(dg.sku_pode_publicar_agora("IMP-JUPAES-006", condicoes=out)[0])

    def test_fase_3_ads_sem_mercado_vivo(self):
        frente = [
            _kit("IMP-MIMO-003", mlb=True, estoque=30, nome="Kit 3 Mimo + Carmed"),
            _kit("IMP-PERL-004", mlb=True, estoque=30),
            _kit("IMP-JUPAES-006", mlb=True, estoque=30),
        ]
        out = dg.avaliar_condicoes_guerra(
            produtos=frente,
            radar={"mercado_confiavel": False},
            resumo_conta={"avaliacoes": 20, "nota": 4.8},
        )
        self.assertEqual(out["fase"], 3)
        self.assertTrue(out["liberar"]["ads"])
        self.assertFalse(out["liberar"]["golpe_preco"])

    def test_fase_5_ruptura(self):
        frente = [
            _kit("IMP-MIMO-003", mlb=True, estoque=30, nome="Kit 3 Mimo + Carmed"),
            _kit("IMP-PERL-004", mlb=True, estoque=30),
            _kit("IMP-JUPAES-006", mlb=True, estoque=30),
        ]
        out = dg.avaliar_condicoes_guerra(
            produtos=frente,
            radar={"mercado_confiavel": True},
            resumo_conta={"avaliacoes": 20, "nota": 4.9},
        )
        self.assertEqual(out["fase"], 5)
        self.assertTrue(out["liberar"]["ruptura"])
        self.assertTrue(out["liberar"]["golpe_preco"])

    @patch("integracoes.esmaltes.doutrina_guerra_impala.gauge")
    def test_emitir_condicoes_fase_0(self, mock_g):
        cond = dg.avaliar_condicoes_guerra(
            produtos=[
                _kit("IMP-MIMO-003", nome="Kit 3 Mimo + Carmed"),
                _kit("IMP-PERL-004"),
                _kit("IMP-JUPAES-006"),
            ],
            radar={"mercado_confiavel": False},
            resumo_conta={"avaliacoes": 0, "nota": 0},
        )
        out = dg.emitir_metricas_condicoes(cond)
        self.assertEqual(out["fase"], 0)
        nomes = {c.args[0]: c.args[1] for c in mock_g.call_args_list}
        self.assertEqual(nomes["impala.guerra.fase"], 0.0)
        self.assertEqual(nomes["impala.guerra.liberar_mimo"], 1.0)
        self.assertEqual(nomes["impala.guerra.liberar_ads"], 0.0)
        self.assertEqual(nomes["impala.guerra.publicar_agora"], 1.0)
        self.assertEqual(nomes["impala.guerra.titulo_atracao"], 0.0)

    def test_titulo_mimo_atracao(self):
        fraco = "Kit 3 Mimo + Carmed"
        cheio = dg.TITULO_MIMO_ML
        self.assertFalse(dg.titulo_mimo_atracao_ok(fraco))
        self.assertTrue(dg.titulo_mimo_atracao_ok(cheio))
        self.assertLessEqual(len(cheio), 60)
        pecas = dg.pecas_titulo_mimo(cheio)
        self.assertTrue(all(pecas.values()))
        self.assertFalse(dg.pecas_titulo_mimo("Kit 3 Francesinha Impala")["sem_francesinha"])

    def test_canal_secundario_bloqueado_na_fase_0(self):
        cond = dg.avaliar_condicoes_guerra(
            produtos=[
                _kit("IMP-MIMO-003", nome="Kit 3 Esmaltes Impala Mimo + Carmed Manicure"),
                _kit("IMP-PERL-004"),
                _kit("IMP-JUPAES-006"),
            ],
            radar={"mercado_confiavel": False},
            resumo_conta={"avaliacoes": 0, "nota": 0},
        )
        ok_ml, motivo_ml = dg.canal_pode_entrar("mercadolivre", condicoes=cond)
        self.assertTrue(ok_ml)
        self.assertEqual(motivo_ml, "abrir_frente_mimo_carmed")
        for canal in ("shopee", "magalu", "amazon"):
            ok, motivo = dg.canal_pode_entrar(canal, condicoes=cond)
            self.assertFalse(ok, msg=canal)
            self.assertIn("aguardar_ml_fase_3", motivo)
        ok_x, motivo_x = dg.canal_pode_entrar("lojahub", condicoes=cond)
        self.assertFalse(ok_x)
        self.assertEqual(motivo_x, "canal_desconhecido")

    def test_canal_secundario_libera_na_fase_3(self):
        cond = {"fase": 3, "checks": {"mlb_mimo": True}}
        ok, motivo = dg.canal_pode_entrar("shopee", condicoes=cond)
        self.assertTrue(ok)
        self.assertEqual(motivo, "ml_referente_saudavel")


if __name__ == "__main__":
    unittest.main()
