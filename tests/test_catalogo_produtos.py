import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import catalogo_produtos as cat


class CatalogoProdutosTests(unittest.TestCase):
    def test_carregar_vazio_quando_arquivo_ausente(self):
        with patch.object(cat, "CATALOGO_PATH", Path("/caminho/inexistente/produtos.json")):
            self.assertEqual(cat.carregar_produtos_catalogo(), [])

    def test_carregar_produtos_para_operacao_merge_bling(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "produtos.json"
            caminho.write_text(
                json.dumps(
                    [
                        {
                            "sku": "SKU-X",
                            "nome": "Kit X",
                            "custo_total": 25.0,
                            "canais": {"mercadolivre": {"ativo": True, "preco": 49.9}},
                        }
                    ]
                ),
                encoding="utf-8",
            )
            with patch.object(cat, "CATALOGO_PATH", caminho):
                with patch(
                    "integracoes.bling.bling_client.listar_produtos_por_sku",
                    return_value={"SKU-X": {"estoque": 5, "nome": "Kit X Bling"}},
                ):
                    produtos = cat.carregar_produtos_para_operacao()
            self.assertEqual(len(produtos), 1)
            self.assertEqual(produtos[0]["sku"], "SKU-X")
            self.assertEqual(produtos[0]["custo"], 25.0)
            self.assertEqual(produtos[0]["estoque_bling"], 5)

    def test_custo_do_bling_quando_catalogo_sem_custo(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "produtos.json"
            caminho.write_text(
                json.dumps([{"sku": "SKU-Y", "nome": "Kit Y", "canais": {}}]),
                encoding="utf-8",
            )
            with patch.object(cat, "CATALOGO_PATH", caminho):
                with patch(
                    "integracoes.bling.bling_client.listar_produtos_por_sku",
                    return_value={"SKU-Y": {"custo": 12.5}},
                ):
                    produtos = cat.carregar_produtos_para_operacao()
            self.assertEqual(produtos[0]["custo"], 12.5)

    def test_ignora_entrada_sem_sku(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "produtos.json"
            caminho.write_text(json.dumps([{"nome": "Sem SKU"}]), encoding="utf-8")
            with patch.object(cat, "CATALOGO_PATH", caminho):
                self.assertEqual(cat.carregar_produtos_para_operacao(), [])

    def test_json_invalido_retorna_lista_vazia(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "produtos.json"
            caminho.write_text("{nao-e-lista", encoding="utf-8")
            with patch.object(cat, "CATALOGO_PATH", caminho):
                self.assertEqual(cat.carregar_produtos_catalogo(), [])


if __name__ == "__main__":
    unittest.main()
