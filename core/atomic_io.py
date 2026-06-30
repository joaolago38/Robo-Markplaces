"""
core/atomic_io.py
Helpers para leitura/escrita de arquivos JSON compartilhados entre
processos (a API viva + múltiplos workflows agendados do GitHub
Actions, todos podendo tocar nos mesmos arquivos de estado) sem risco
de "lost update" (dois processos lendo o mesmo estado, cada um
escrevendo por cima da escrita do outro) nem de corrupção por
escrita parcial.

- Escrita atômica: grava num arquivo temporário no mesmo diretório e
  troca com os.replace() — no Linux/macOS isso é atômico, então o
  arquivo final nunca fica "pela metade" mesmo se o processo morrer
  no meio da escrita.
- Lock exclusivo (fcntl.flock, somente POSIX): serializa o ciclo
  leitura→modificação→escrita entre processos diferentes. Em
  ambientes sem fcntl (ex.: Windows), o lock é pulado silenciosamente
  — a escrita atômica ainda protege contra corrupção, só não contra
  "lost update" nesse caso específico.
"""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

try:
    import fcntl

    _TEM_FLOCK = True
except ImportError:  # pragma: no cover - Windows não tem fcntl
    _TEM_FLOCK = False


@contextmanager
def lock_exclusivo(caminho_lock: Path | str):
    """
    Lock exclusivo entre processos baseado em arquivo (fcntl.flock,
    somente POSIX). Use para serializar todo o ciclo "ler estado →
    decidir o que mudar → escrever estado" quando isso abrange mais de
    uma operação (e por isso não pode usar só `ler_e_atualizar_json`).
    Em ambientes sem fcntl, vira um no-op (sem lock).
    """
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


def escrever_json_atomico(caminho: Path | str, dados: Any) -> None:
    """Grava `dados` como JSON em `caminho` de forma atômica (sem deixar
    o arquivo corrompido caso o processo seja interrompido no meio)."""
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


def ler_json(caminho: Path | str, default: Any = None) -> Any:
    caminho = Path(caminho)
    if not caminho.exists():
        return {} if default is None else default
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def ler_e_atualizar_json(
    caminho: Path | str, funcao_atualizar: Callable[[Any], Any], default: Any = None
) -> Any:
    """
    Lê o JSON em `caminho` (ou `default`/{} se não existir/inválido),
    passa para `funcao_atualizar(dados) -> dados_novos`, e escreve o
    resultado de volta de forma atômica — tudo isso dentro de um lock
    exclusivo por arquivo, para nenhum outro processo conseguir
    ler/escrever no meio do ciclo.
    """
    caminho = Path(caminho)
    lock_path = caminho.with_name(caminho.name + ".lock")
    with lock_exclusivo(lock_path):
        dados = ler_json(caminho, default)
        dados_novos = funcao_atualizar(dados)
        escrever_json_atomico(caminho, dados_novos)
        return dados_novos
