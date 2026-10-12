"""
tests/test_cruzamento_filamentos_alibaba.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.filamentos import cruzamento_alibaba as cruz


class CruzamentoFilamentosTests(unittest.TestCase):
    def test_eh_produto_filamento(self):
        self.assertTrue(
            cruz._eh_produto_filamento(
                {"id": "filamento-impressora-3d-pla", "nome": "PLA", "material": "PLA"}
            )
        )
        self.assertTrue(
            cruz._eh_produto_filamento(
                {"id": "filamento-impressora-3d-tpu", "nome": "TPU", "material": "TPU"}
            )
        )
        self.assertTrue(
            cruz._eh_produto_filamento(
                {"id": "filamento-impressora-3d-abs", "nome": "ABS", "material": "ABS"}
            )
        )
        self.assertFalse(
            cruz._eh_produto_filamento({"id": "abracadeira", "nome": "Abraçadeira nylon"})
        )

    def test_catalogo_alibaba_tem_quatro_materiais(self):
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        data = json.loads(
            (root / "catalogo" / "alibaba_produtos_importacao.json").read_text(encoding="utf-8")
        )
        mats = {
            str(p.get("material") or "").upper()
            for p in data
            if p.get("ativo") and cruz._eh_produto_filamento(p)
        }
        for m in ("TPU", "PLA", "PETG", "ABS"):
            self.assertIn(m, mats)

    def test_carregar_produtos_filtro(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cat.json"
            path.write_text(
                '[{"id":"filamento-x","ativo":true,"nome":"Filamento PLA","material":"PLA"},'
                '{"id":"abra","ativo":true,"nome":"Abraçadeira"},'
                '{"id":"fil-off","ativo":false,"nome":"Filamento ABS","material":"ABS"}]',
                encoding="utf-8",
            )
            with patch("core.config.ROOT", Path(tmp)), patch(
                "core.config.ALIBABA_IMPORTACAO_CATALOGO", "cat.json"
            ):
                produtos = cruz.carregar_produtos_filamento_alibaba()
            self.assertEqual(len(produtos), 1)
            self.assertEqual(produtos[0]["id"], "filamento-x")

    def test_precos_ml_fallback_global(self):
        consolidado = {
            "preco_min": 60,
            "preco_medio": 80,
            "preco_max": 100,
            "total_filamentos_unicos": 3,
            "por_termo": [],
        }
        out = cruz._precos_ml_do_consolidado(
            consolidado, [], {"material": "PLA", "termo_marketplace": "filamento pla"}
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["preco_medio_brl"], 80)
        self.assertEqual(out["fonte"], "consolidado_global")

    def test_cruzar_sem_produtos(self):
        with patch.object(cruz, "carregar_produtos_filamento_alibaba", return_value=[]), patch(
            "integracoes.cambio.cotacao_usd.obter_cotacao_usd",
            return_value={"ok": True, "usd_brl": 5.0, "confiavel": True, "fonte": "api"},
        ), patch(
            "integracoes.cambio.cotacao_usd.cotacao_confiavel_para_margem", return_value=True
        ):
            out = cruz.cruzar_filamentos_ml_alibaba(
                {"ranking_cores": [{"cor": "Preto"}]}, [], max_cores=1, pausa_seg=0
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["produtos_catalogo"], 0)
        self.assertIn("sem produto", out.get("motivo", ""))

    def test_cruzar_cambio_invalido(self):
        with patch.object(
            cruz,
            "carregar_produtos_filamento_alibaba",
            return_value=[{"id": "f1", "nome": "PLA", "material": "PLA"}],
        ), patch(
            "integracoes.cambio.cotacao_usd.obter_cotacao_usd",
            return_value={"ok": False, "usd_brl": 0, "fonte": "fallback"},
        ), patch(
            "integracoes.cambio.cotacao_usd.cotacao_confiavel_para_margem", return_value=False
        ):
            out = cruz.cruzar_filamentos_ml_alibaba({}, [], max_cores=0, pausa_seg=0)
        self.assertFalse(out["ok"])
        self.assertIn("cambio", out.get("motivo", ""))

    @patch.object(cruz, "carregar_produtos_filamento_alibaba")
    def test_cruzar_com_mocks(self, mock_produtos):
        mock_produtos.return_value = [
            {
                "id": "filamento-impressora-3d-pla",
                "nome": "Filamento PLA",
                "material": "PLA",
                "termo_busca": "PLA filament wholesale",
                "termo_busca_pt": "filamento PLA",
                "termo_marketplace": "filamento pla 1kg",
                "peso_kg": 1,
                "preco_max_usd": 9,
                "moq_max": 500,
                "margem_minima_pct": 16,
                "margem_minima_reais": 8,
            }
        ]
        consolidado = {
            "preco_min": 70,
            "preco_medio": 90,
            "preco_max": 120,
            "total_filamentos_unicos": 5,
            "ranking_cores": [
                {"cor": "Preto", "vendidos": 100},
                {"cor": "Branco", "vendidos": 50},
            ],
            "por_termo": [
                {
                    "material": "PLA",
                    "preco_min": 70,
                    "preco_medio": 90,
                    "preco_max": 110,
                    "total": 5,
                }
            ],
        }

        with patch(
            "integracoes.cambio.cotacao_usd.obter_cotacao_usd",
            return_value={
                "ok": True,
                "usd_brl": 5.5,
                "confiavel": True,
                "fonte": "api",
                "idade_seg": 10,
            },
        ), patch(
            "integracoes.cambio.cotacao_usd.cotacao_confiavel_para_margem", return_value=True
        ), patch(
            "integracoes.alibaba.busca.buscar_oportunidades_detalhado",
            return_value={
                "oportunidades": [
                    {
                        "titulo": "PLA black 1kg",
                        "url": "https://www.alibaba.com/product-detail/1.html",
                        "preco_usd": 4.5,
                        "moq": 50,
                        "hash": "h1",
                    }
                ],
                "coleta": {
                    "bloqueado": False,
                    "motivo": None,
                    "direto": 1,
                    "ddg": 0,
                    "candidatos": 1,
                },
            },
        ), patch(
            "integracoes.importacao.analise_margem.analisar_produto_catalogo",
            return_value={
                "ok": True,
                "lucrativas": 1,
                "melhor_analise": {
                    "ok": True,
                    "preco_usd": 4.5,
                    "lucro_razoavel": True,
                    "melhor_frete": "maritimo",
                    "margem_melhor": {"ok": True, "margem_brl": 25, "margem_pct": 20},
                    "cenarios_frete": {"maritimo": {"custo_landed_brl": 45}},
                },
            },
        ):
            out = cruz.cruzar_filamentos_ml_alibaba(
                consolidado, [], max_cores=1, pausa_seg=0
            )

        self.assertTrue(out["ok"])
        self.assertEqual(out["cores_usadas"], ["Preto"])
        self.assertEqual(out["lucrativos"], 1)
        self.assertEqual(out["cruzamentos"][0]["precos_ml"]["preco_medio_brl"], 90)

    def test_formatar_secao(self):
        linhas = cruz.formatar_secao_cruzamento(
            {
                "ok": True,
                "cores_usadas": ["Preto"],
                "cambio_usd_brl": 5.5,
                "cruzamentos": [
                    {
                        "produto": "Filamento PLA",
                        "material": "PLA",
                        "precos_ml": {
                            "preco_min_brl": 70,
                            "preco_medio_brl": 90,
                            "preco_max_brl": 110,
                        },
                        "total_oportunidades_alibaba": 3,
                        "lucrativa": True,
                        "melhor_analise": {
                            "ok": True,
                            "preco_usd": 4.5,
                            "cor_foco": "Preto",
                            "melhor_frete": "maritimo",
                            "margem_melhor": {"margem_brl": 20, "margem_pct": 18},
                            "cenarios_frete": {"maritimo": {"custo_landed_brl": 50}},
                        },
                        "por_cor": [
                            {"cor": "Preto", "total_oportunidades": 2, "lucrativas": 1}
                        ],
                    }
                ],
            },
            fmt_brl=lambda v: f"R$ {v}" if v else "n/d",
        )
        texto = "\n".join(linhas)
        self.assertIn("Comparativo ML × Alibaba", texto)
        self.assertIn("*PLA*", texto)
        self.assertIn("ML:", texto)
        self.assertIn("Alibaba:", texto)
        self.assertIn("Preto", texto)

    def test_formatar_secao_bloqueado(self):
        linhas = cruz.formatar_secao_cruzamento(
            {
                "ok": True,
                "alibaba_bloqueado": True,
                "cambio_usd_brl": 5.5,
                "cruzamentos": [
                    {
                        "produto": "Filamento PLA",
                        "material": "PLA",
                        "precos_ml": {"preco_min_brl": 70, "preco_medio_brl": 90, "preco_max_brl": 110},
                        "total_oportunidades_alibaba": 0,
                        "coleta_alibaba": {"bloqueado": True, "motivo": "anti_bot:captcha"},
                        "melhor_analise": None,
                    }
                ],
            },
            fmt_brl=lambda v: f"R$ {v}" if v else "n/d",
        )
        texto = "\n".join(linhas)
        self.assertIn("bloqueada", texto.lower())
        self.assertIn("anti-bot", texto.lower())

    def test_formatar_secao_erro(self):
        linhas = cruz.formatar_secao_cruzamento(
            {"ok": False, "motivo": "cambio: fallback"},
            fmt_brl=lambda v: "n/d",
        )
        self.assertTrue(any("indisponível" in ln for ln in linhas))


if __name__ == "__main__":
    unittest.main()
