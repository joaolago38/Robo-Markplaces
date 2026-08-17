"""tests/test_novos_kits_impala.py"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integracoes.esmaltes import novos_kits_impala as nk


def _kit(**kwargs) -> dict:
    base = {
        "item_id": "MLB123456789",
        "titulo": "Kit 3 Esmaltes Impala Mimo Carmed",
        "preco": 44.9,
        "qtd_kit": 3,
    }
    base.update(kwargs)
    return base


class TestNovosKitsImpala(unittest.TestCase):
    def test_filtra_so_impala_kit(self):
        anuncios = [
            _kit(),
            {"item_id": "MLB222222222", "titulo": "Parafuso drywall GN25", "preco": 31.9},
            {"item_id": "MLB333333333", "titulo": "Kit 5 Esmaltes Anita Nude", "preco": 39.9, "qtd_kit": 5},
            {"item_id": "MLB1", "titulo": "Kit Impala lixo de amostra", "preco": 10.0},
        ]
        out = nk.filtrar_kits_impala(anuncios)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["item_id"], "MLB123456789")

    def test_assinatura_frente_e_fora(self):
        self.assertEqual(nk.assinatura_kit(_kit()), "3:mimo")
        self.assertEqual(
            nk.assinatura_kit(
                {
                    "titulo": "Kit 8 Esmaltes Impala Sortidos Atacado",
                    "qtd_kit": 8,
                    "item_id": "MLB444444444",
                }
            ),
            "8:outro",
        )

    def test_baseline_nao_alerta_kits_antigos(self):
        out = nk.montar_novos(
            [_kit(catalog_date_created="2024-01-01T00:00:00Z")],
            vistos={"ids": [], "assinaturas": []},
            dias_limite=14,
        )
        self.assertTrue(out["baseline"])
        self.assertEqual(out["n_kits_impala"], 1)
        self.assertEqual(out["n_novos"], 0)

    def test_baseline_alerta_recente(self):
        out = nk.montar_novos(
            [_kit(metricas={"dias_anuncio": 2, "preco": 44.9})],
            vistos={"ids": [], "assinaturas": []},
            dias_limite=14,
        )
        self.assertTrue(out["baseline"])
        self.assertEqual(out["n_novos"], 1)
        self.assertIn("recente", out["novos"][0]["motivos"])

    def test_mlb_novo_depois_do_baseline(self):
        out = nk.montar_novos(
            [
                _kit(item_id="MLB111111111"),
                _kit(
                    item_id="MLB999888777",
                    titulo="Kit 8 Esmaltes Impala Sortidos",
                    qtd_kit=8,
                    preco=52.0,
                ),
            ],
            vistos={"ids": ["MLB111111111"], "assinaturas": ["3:mimo"]},
            dias_limite=14,
        )
        self.assertFalse(out["baseline"])
        self.assertEqual(out["n_novos"], 1)
        row = out["novos"][0]
        self.assertEqual(row["item_id"], "MLB999888777")
        self.assertIn("anuncio_novo", row["motivos"])
        self.assertTrue(row["fora_frente"])
        self.assertIn("fora da frente", nk.formatar_alerta(row))
        self.assertIn("Kit 8 Impala", nk.formatar_alerta(row))

    def test_ja_visto_sem_alerta(self):
        out = nk.montar_novos(
            [_kit(item_id="MLB111111111")],
            vistos={"ids": ["MLB111111111"], "assinaturas": ["3:mimo"]},
            dias_limite=14,
        )
        self.assertEqual(out["n_novos"], 0)

    @patch.object(nk, "_enviar_telegram", return_value=(False, "teste"))
    @patch.object(nk, "emitir_metricas")
    @patch.object(nk, "incrementar")
    def test_processar_persiste_e_alerta(self, mock_i, _m, _tg):
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            with (
                patch.object(nk, "VISTOS_PATH", pasta / "vistos.json"),
                patch.object(nk, "SNAPSHOT_PATH", pasta / "snap.json"),
                patch.object(nk, "_cfg_ativo", return_value=True),
                patch.object(nk, "_cfg_alerta", return_value=True),
                patch.object(nk, "_cfg_dias", return_value=14),
                patch.object(nk, "_cfg_top_n", return_value=8),
            ):
                primeiro = nk.processar(
                    [_kit(item_id="MLB111111111", metricas={"dias_anuncio": 400})],
                    persistir=True,
                )
                self.assertTrue(primeiro.get("baseline"))
                self.assertEqual(primeiro.get("alertas"), [])
                segundo = nk.processar(
                    [
                        _kit(item_id="MLB111111111"),
                        _kit(
                            item_id="MLB222333444",
                            titulo="Kit 12 Esmaltes Impala Atacado",
                            qtd_kit=12,
                            preco=89.9,
                        ),
                    ],
                    persistir=True,
                )
        self.assertFalse(segundo.get("baseline"))
        self.assertEqual(segundo.get("n_novos"), 1)
        self.assertTrue(segundo.get("alertas"))
        self.assertIn("[novos-kits-impala]", segundo["alertas"][0])
        mock_i.assert_any_call("impala.novos_kits.ok")

    def test_nome_kit_e_saude(self):
        a = _kit(quantidade_vendida=400, nota=4.8, avaliacoes=25, preco=44.9)
        self.assertEqual(nk.nome_kit(a), "Kit 3 Impala Mimo + Carmed")
        saude = nk.saude_anuncio(a)
        self.assertGreaterEqual(saude["score"], 70)
        self.assertEqual(saude["faixa"], "boa")

    def test_ranking_ordena_por_saude(self):
        anuncios = [
            _kit(item_id="MLB111111111", titulo="Kit 3 Impala Mimo", qtd_kit=3, quantidade_vendida=5, preco=44.9),
            _kit(
                item_id="MLB222222222",
                titulo="Kit 8 Esmaltes Impala Sortidos",
                qtd_kit=8,
                quantidade_vendida=200,
                nota=4.9,
                avaliacoes=40,
                preco=52.0,
            ),
        ]
        rank = nk.montar_ranking(anuncios, limite=5)
        self.assertEqual(rank[0]["item_id"], "MLB222222222")
        self.assertIn("Kit 8 Impala", rank[0]["nome_kit"])
        nomes = nk.nomes_kits_a_venda(anuncios)
        self.assertTrue(any("Mimo" in n for n in nomes))
        self.assertTrue(any("Kit 8" in n for n in nomes))
        msg = nk.formatar_mensagem(
            novos=rank[:1],
            ranking=rank,
            nomes=nomes,
            n_amostra=2,
        )
        self.assertIn("Kits Impala no Mercado Livre", msg)
        self.assertIn("Ranking", msg)
        self.assertIn("Kits à venda", msg)
        self.assertIn("/100", msg)


if __name__ == "__main__":
    unittest.main()
