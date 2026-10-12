"""
tests/test_ssm_secrets.py — sync de tokens no SSM Parameter Store (moto).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from moto import mock_aws

from core.ssm_secrets import sync_secrets_ssm


@mock_aws
class TestSyncSecretsSsm(unittest.TestCase):
    def test_atualiza_access_e_refresh(self):
        self.assertTrue(
            sync_secrets_ssm("access-123", "refresh-456", prefix="BLING")
        )
        import boto3

        client = boto3.client("ssm", region_name="us-east-1")
        access = client.get_parameter(
            Name="/robo-markplaces/BLING_ACCESS_TOKEN", WithDecryption=True
        )
        refresh = client.get_parameter(
            Name="/robo-markplaces/BLING_REFRESH_TOKEN", WithDecryption=True
        )
        self.assertEqual(access["Parameter"]["Value"], "access-123")
        self.assertEqual(refresh["Parameter"]["Value"], "refresh-456")

    def test_sobrescreve_sem_duplicar(self):
        sync_secrets_ssm("v1", None, prefix="ML")
        sync_secrets_ssm("v2", None, prefix="ML")
        import boto3

        client = boto3.client("ssm", region_name="us-east-1")
        valor = client.get_parameter(
            Name="/robo-markplaces/ML_ACCESS_TOKEN", WithDecryption=True
        )["Parameter"]["Value"]
        self.assertEqual(valor, "v2")


if __name__ == "__main__":
    unittest.main()
