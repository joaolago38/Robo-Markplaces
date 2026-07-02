"""
core/ssm_secrets.py
Sincroniza tokens renovados no AWS SSM Parameter Store (SecureString, tier Standard).

Equivalente a core/github_secrets.py, mas para o caminho Lambda/AWS.
Os workflows do GitHub Actions continuam usando github_secrets.py.
"""
from __future__ import annotations

import logging

from core.config import AWS_REGION, SSM_PARAMETER_PREFIX

logger = logging.getLogger("ssm_secrets")


def _nome_parametro(nome_secreto: str) -> str:
    base = (SSM_PARAMETER_PREFIX or "/robo-markplaces").rstrip("/")
    return f"{base}/{nome_secreto}"


def sync_secrets_ssm(
    access_token: str,
    refresh_token: str | None,
    prefix: str = "BLING",
) -> bool:
    """
    Atualiza {prefix}_ACCESS_TOKEN e opcionalmente {prefix}_REFRESH_TOKEN no SSM.
    Parâmetros SecureString, tier Standard (sem custo na cota Always Free).
    """
    try:
        import boto3
    except ImportError:
        logger.warning("boto3 não instalado — SSM %s_* não atualizado", prefix)
        return False

    client = boto3.client("ssm", region_name=AWS_REGION)
    pares: list[tuple[str, str]] = [(f"{prefix}_ACCESS_TOKEN", access_token)]
    if refresh_token:
        pares.append((f"{prefix}_REFRESH_TOKEN", refresh_token))

    ok = True
    for nome_secreto, valor in pares:
        nome = _nome_parametro(nome_secreto)
        try:
            client.put_parameter(
                Name=nome,
                Value=valor,
                Type="SecureString",
                Overwrite=True,
            )
            logger.info("SSM Parameter %s atualizado", nome)
        except Exception as exc:
            logger.error("Falha ao atualizar SSM %s: %s", nome, exc)
            ok = False
    return ok
