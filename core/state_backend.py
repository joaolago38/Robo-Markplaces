"""
core/state_backend.py
Camada plugável de persistência de estado (arquivo local ou DynamoDB).

A escolha do backend vem de STORAGE_BACKEND=file|dynamodb (padrão: file).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from abc import ABC, abstractmethod
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator

from core.config import AWS_REGION, DYNAMODB_TABLE_NAME, ROOT, STORAGE_BACKEND

logger = logging.getLogger("state_backend")

try:
    import fcntl

    _TEM_FLOCK = True
except ImportError:  # pragma: no cover - Windows não tem fcntl
    _TEM_FLOCK = False


def caminho_para_chave(caminho: Path | str, root: Path | None = None) -> str:
    """
    Converte um caminho de arquivo em chave lógica estável (ex. catalogo/produtos).
    Remove a extensão .json do último segmento, se houver.
    """
    base = (root or ROOT).resolve()
    caminho = Path(caminho)
    try:
        rel = caminho.resolve().relative_to(base)
    except ValueError:
        rel = caminho
    partes = list(rel.parts)
    if partes and partes[-1].endswith(".json"):
        partes[-1] = partes[-1][:-5]
    return "/".join(partes).replace("\\", "/")


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    raise TypeError(f"Objeto não serializável: {type(obj)}")


class StateBackend(ABC):
    @abstractmethod
    def ler_json(self, caminho: Path | str, default: Any = None) -> Any: ...

    @abstractmethod
    def escrever_json_atomico(self, caminho: Path | str, dados: Any) -> None: ...

    @abstractmethod
    def ler_e_atualizar_json(
        self,
        caminho: Path | str,
        funcao_atualizar: Callable[[Any], Any],
        default: Any = None,
    ) -> Any: ...

    @abstractmethod
    @contextmanager
    def lock_exclusivo(self, caminho_lock: Path | str) -> Iterator[None]: ...


class FileStateBackend(StateBackend):
    """Backend em disco — encapsula o comportamento original de atomic_io."""

    def ler_json(self, caminho: Path | str, default: Any = None) -> Any:
        caminho = Path(caminho)
        if not caminho.exists():
            return {} if default is None else default
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except Exception:
            return {} if default is None else default

    def escrever_json_atomico(self, caminho: Path | str, dados: Any) -> None:
        caminho = Path(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(caminho.parent), prefix=f".{caminho.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(dados, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, caminho)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def ler_e_atualizar_json(
        self,
        caminho: Path | str,
        funcao_atualizar: Callable[[Any], Any],
        default: Any = None,
    ) -> Any:
        caminho = Path(caminho)
        lock_path = caminho.with_name(caminho.name + ".lock")
        with self.lock_exclusivo(lock_path):
            dados = self.ler_json(caminho, default)
            dados_novos = funcao_atualizar(dados)
            self.escrever_json_atomico(caminho, dados_novos)
            return dados_novos

    @contextmanager
    def lock_exclusivo(self, caminho_lock: Path | str) -> Iterator[None]:
        caminho_lock = Path(caminho_lock)
        if not _TEM_FLOCK:
            caminho_lock.parent.mkdir(parents=True, exist_ok=True)
            yield
            return
        caminho_lock.parent.mkdir(parents=True, exist_ok=True)
        with open(caminho_lock, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)


class DynamoDBStateBackend(StateBackend):
    """Backend DynamoDB — chave = nome lógico do arquivo; valor em atributo `dados`."""

    def __init__(self, table_name: str | None = None, region: str | None = None) -> None:
        import boto3

        self._table_name = (table_name or DYNAMODB_TABLE_NAME).strip()
        if not self._table_name:
            raise ValueError("DYNAMODB_TABLE_NAME é obrigatório com STORAGE_BACKEND=dynamodb")
        self._client = boto3.client("dynamodb", region_name=region or AWS_REGION)
        self._resource = boto3.resource("dynamodb", region_name=region or AWS_REGION)
        self._table = self._resource.Table(self._table_name)

    def _chave(self, caminho: Path | str) -> str:
        return caminho_para_chave(caminho)

    def _item_para_dados(self, item: dict | None, default: Any) -> Any:
        if not item or "dados" not in item:
            return {} if default is None else default
        bruto = item["dados"]
        if isinstance(bruto, str):
            try:
                return json.loads(bruto)
            except json.JSONDecodeError:
                return {} if default is None else default
        return bruto

    def ler_json(self, caminho: Path | str, default: Any = None) -> Any:
        chave = self._chave(caminho)
        try:
            resp = self._table.get_item(Key={"chave": chave})
            return self._item_para_dados(resp.get("Item"), default)
        except Exception as exc:
            logger.error("DynamoDB ler_json falhou chave=%s: %s", chave, exc)
            return {} if default is None else default

    def escrever_json_atomico(self, caminho: Path | str, dados: Any) -> None:
        chave = self._chave(caminho)
        self._table.put_item(
            Item={
                "chave": chave,
                "dados": json.dumps(dados, ensure_ascii=False, default=_json_default),
            }
        )

    def ler_e_atualizar_json(
        self,
        caminho: Path | str,
        funcao_atualizar: Callable[[Any], Any],
        default: Any = None,
    ) -> Any:
        chave = self._chave(caminho)
        with self.lock_exclusivo(chave):
            dados = self.ler_json(caminho, default)
            dados_novos = funcao_atualizar(dados)
            self.escrever_json_atomico(caminho, dados_novos)
            return dados_novos

    @contextmanager
    def lock_exclusivo(self, caminho_lock: Path | str) -> Iterator[None]:
        # DynamoDB serializa por item; lock de arquivo não se aplica.
        yield


_backend: StateBackend | None = None


def get_state_backend() -> StateBackend:
    global _backend
    if _backend is not None:
        return _backend
    modo = (STORAGE_BACKEND or "file").strip().lower()
    if modo == "dynamodb":
        _backend = DynamoDBStateBackend()
        logger.info("State backend: DynamoDB (tabela=%s)", DYNAMODB_TABLE_NAME)
    else:
        _backend = FileStateBackend()
    return _backend


def reset_state_backend() -> None:
    """Útil em testes para trocar backend entre execuções."""
    global _backend
    _backend = None
