"""Playbook vira system; roteador tira do dataset o que iria para o Sonnet."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from core.claude_finetune import (
    BASE_BEDROCK,
    FinetuneRecusado,
    carregar_pares,
    elegivel,
    exportar_jsonl,
    montar_linha,
    talvez_capturar,
)

_ANALISE_BAIXA = {"deve_aumentar_ia": False, "score": 10, "nivel": "baixo", "resumo": "frio"}


class TestClaudeFinetune(unittest.TestCase):
    def test_repricing_fica_de_fora(self):
        ok, motivo = elegivel("repricing")
        self.assertFalse(ok)
        self.assertEqual(motivo, "complexidade_algoritmo_ml")

    def test_ruptura_fica_de_fora(self):
        ok, motivo = elegivel("guerra_impala")
        self.assertFalse(ok)
        self.assertEqual(motivo, "complexidade_algoritmo_ml")

    def test_sazonal_entra_e_o_system_e_o_playbook(self):
        with patch("core.claude_roteador.restante_orcamento_usd", return_value=10.0):
            linha = montar_linha(
                "sazonal",
                entrada='{"meses":["maio","novembro"]}',
                resposta="Maio | alta | antecipar estoque.",
                campos={"nicho": "esmaltes"},
                analise=_ANALISE_BAIXA,
            )
        self.assertIn("analista de sazonalidade", linha["system"])
        self.assertIn("esmaltes", linha["system"])
        self.assertEqual(linha["messages"][0]["role"], "user")
        self.assertEqual(linha["messages"][-1]["role"], "assistant")
        self.assertIn("antecipar estoque", linha["messages"][-1]["content"])

    def test_chat_com_intencao_de_compra_nao_entra(self):
        with patch("core.claude_roteador.restante_orcamento_usd", return_value=10.0):
            ok, motivo = elegivel(
                "chat_ml",
                canal="mercadolivre",
                texto="quanto custa o kit",
                preco_produto=30.0,
                analise=_ANALISE_BAIXA,
            )
        self.assertFalse(ok)
        self.assertIn("intencao_compra_ml", motivo)

    def test_exportar_grava_so_o_haiku(self):
        pares = [
            {
                "proposito": "sazonal",
                "entrada": "pico de maio",
                "resposta": "Maio | alta | preparar anúncio 30 dias antes.",
                "analise": _ANALISE_BAIXA,
            },
            {
                "proposito": "pricing",
                "entrada": "faixas",
                "resposta": "não deve entrar",
            },
        ]
        with patch("core.claude_roteador.restante_orcamento_usd", return_value=10.0):
            resumo = exportar_jsonl(pares, self.tmp / "treino.jsonl")
        self.assertEqual(resumo["gravadas"], 1)
        self.assertEqual(resumo["base"], BASE_BEDROCK)
        self.assertEqual(resumo["recusadas"][0]["motivo"], "complexidade_algoritmo_ml")
        gravado = json.loads((self.tmp / "treino.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(gravado["messages"][1]["content"].startswith("Maio"), True)

    def test_candidato_nao_entra_no_treino(self):
        caminho = self.tmp / "pares.jsonl"
        caminho.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "aprovado": False,
                            "proposito": "sazonal",
                            "entrada": "x",
                            "resposta": "y",
                        }
                    ),
                    json.dumps(
                        {
                            "proposito": "sazonal",
                            "entrada": "pico",
                            "resposta": "Maio | alta | preparar.",
                            "analise": _ANALISE_BAIXA,
                        }
                    ),
                ]
            ),
            encoding="utf-8",
        )
        self.assertEqual(len(carregar_pares(caminho)), 1)

    def test_par_vazio_e_recusado(self):
        with patch("core.claude_roteador.restante_orcamento_usd", return_value=10.0):
            with self.assertRaises(FinetuneRecusado) as ctx:
                montar_linha("sazonal", entrada="  ", resposta="ok", analise=_ANALISE_BAIXA)
        self.assertEqual(ctx.exception.motivo, "par_vazio")

    def test_captura_desligada_nao_grava(self):
        with patch("core.config.CLAUDE_FINETUNE_CAPTURAR", False):
            self.assertFalse(
                talvez_capturar(proposito="sazonal", entrada="pico", resposta="maio")
            )

    def test_captura_ligada_grava_candidato_do_haiku(self):
        destino = self.tmp / "candidatos.jsonl"
        with (
            patch("core.config.CLAUDE_FINETUNE_CAPTURAR", True),
            patch("core.claude_finetune.CANDIDATOS_PATH", destino),
            patch("core.claude_roteador.restante_orcamento_usd", return_value=10.0),
            patch(
                "core.claude_finetune.resolver_modelo_vendas",
                return_value={"escalou": False, "motivo": "haiku_padrao"},
            ),
        ):
            ok = talvez_capturar(
                proposito="sazonal",
                entrada="pico de maio",
                resposta="Maio | alta | preparar.",
                origem="teste",
            )
        self.assertTrue(ok)
        linha = json.loads(destino.read_text(encoding="utf-8"))
        self.assertFalse(linha["aprovado"])
        self.assertEqual(linha["playbook"], "sazonalidade")

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        from pathlib import Path

        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
