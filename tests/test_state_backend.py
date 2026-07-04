"""
tests/test_state_backend.py — backends file e DynamoDB (moto).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from moto import mock_aws

from core import atomic_io
from core.state_backend import (
    DynamoDBStateBackend,
    FileStateBackend,
    caminho_para_chave,
    get_state_backend,
    reset_state_backend,
)


class TestCaminhoParaChave(unittest.TestCase):
    def test_remove_extensao_json(self):
        root = Path("/proj")
        chave = caminho_para_chave("/proj/catalogo/produtos.json", root=root)
        self.assertEqual(chave, "catalogo/produtos")

    def test_logs_marketplace_keepalive(self):
        root = Path("/proj")
        chave = caminho_para_chave("/proj/logs/marketplace_keepalive.json", root=root)
        self.assertEqual(chave, "logs/marketplace_keepalive")


class TestFileStateBackend(unittest.TestCase):
    def setUp(self):
        reset_state_backend()

    def tearDown(self):
        reset_state_backend()

    def test_ler_escrever_roundtrip(self):
        backend = FileStateBackend()
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "estado.json"
            backend.escrever_json_atomico(caminho, {"a": 1})
            self.assertEqual(backend.ler_json(caminho), {"a": 1})


@mock_aws
class TestDynamoDBStateBackend(unittest.TestCase):
    TABLE = "robo-markplaces-teste"

    def setUp(self):
        reset_state_backend()
        import boto3

        boto3.resource("dynamodb", region_name="us-east-1").create_table(
            TableName=self.TABLE,
            KeySchema=[{"AttributeName": "chave", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "chave", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        self.backend = DynamoDBStateBackend(table_name=self.TABLE, region="us-east-1")

    def tearDown(self):
        reset_state_backend()

    def test_escrever_ler_por_chave_logica(self):
        caminho = "catalogo/produtos.json"
        self.backend.escrever_json_atomico(caminho, [{"sku": "A"}])
        self.assertEqual(self.backend.ler_json(caminho), [{"sku": "A"}])

    def test_ler_inexistente_retorna_default(self):
        self.assertEqual(self.backend.ler_json("dados/inexistente.json"), {})

    def test_ler_e_atualizar_incrementa(self):
        caminho = "dados/contador.json"

        def _inc(dados):
            dados = dict(dados or {})
            dados["n"] = dados.get("n", 0) + 1
            return dados

        self.backend.ler_e_atualizar_json(caminho, _inc, default={})
        out = self.backend.ler_e_atualizar_json(caminho, _inc, default={})
        self.assertEqual(out["n"], 2)

    def test_idempotente_sobrescreve(self):
        caminho = "catalogo/produtos.json"
        self.backend.escrever_json_atomico(caminho, {"v": 1})
        self.backend.escrever_json_atomico(caminho, {"v": 2})
        self.assertEqual(self.backend.ler_json(caminho)["v"], 2)


class TestAtomicIoDelegacao(unittest.TestCase):
    def setUp(self):
        reset_state_backend()

    def tearDown(self):
        reset_state_backend()

    def test_padrao_file_backend(self):
        self.assertIsInstance(get_state_backend(), FileStateBackend)

    @mock_aws
    def test_dynamodb_via_env(self):
        import boto3

        table = "robo-markplaces-delegacao"
        boto3.resource("dynamodb", region_name="us-east-1").create_table(
            TableName=table,
            KeySchema=[{"AttributeName": "chave", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "chave", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        with patch("core.state_backend.STORAGE_BACKEND", "dynamodb"), patch(
            "core.state_backend.DYNAMODB_TABLE_NAME", table
        ):
            reset_state_backend()
            with tempfile.TemporaryDirectory() as tmp:
                caminho = Path(tmp) / "catalogo" / "produtos.json"
                atomic_io.escrever_json_atomico(caminho, {"ok": True})
                self.assertEqual(atomic_io.ler_json(caminho), {"ok": True})


if __name__ == "__main__":
    unittest.main()
