"""
core/atomic_io.py
Helpers para leitura/escrita de arquivos JSON compartilhados entre
processos (a API viva + múltiplos workflows agendados do GitHub
Actions, todos podendo tocar nos mesmos arquivos de estado) sem risco
de "lost update" (dois processos lendo o mesmo estado, cada um
escrevendo por cima da escrita do outro) nem de corrupção por
escrita parcial.

A implementação concreta é delegada a core/state_backend.py
(STORAGE_BACKEND=file|dynamodb). O padrão continua sendo arquivo local.

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

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from core.state_backend import get_state_backend


@contextmanager
def lock_exclusivo(caminho_lock: Path | str) -> Iterator[None]:
    """
    Lock exclusivo entre processos baseado em arquivo (fcntl.flock,
    somente POSIX). Use para serializar todo o ciclo "ler estado →
    decidir o que mudar → escrever estado" quando isso abrange mais de
    uma operação (e por isso não pode usar só `ler_e_atualizar_json`).
    Em ambientes sem fcntl, vira um no-op (sem lock).
    """
    with get_state_backend().lock_exclusivo(caminho_lock):
        yield


def escrever_json_atomico(caminho: Path | str, dados: Any) -> None:
    """Grava `dados` como JSON em `caminho` de forma atômica (sem deixar
    o arquivo corrompido caso o processo seja interrompido no meio)."""
    get_state_backend().escrever_json_atomico(caminho, dados)


def ler_json(caminho: Path | str, default: Any = None) -> Any:
    return get_state_backend().ler_json(caminho, default=default)


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
    return get_state_backend().ler_e_atualizar_json(caminho, funcao_atualizar, default=default)
