"""Redireciona stdout para evitar UnicodeEncodeError no console Windows (cp1252)."""
from __future__ import annotations

import io
import sys
from contextlib import contextmanager


@contextmanager
def capturar_stdout_utf8():
    """Usado em testes que executam scripts com print() de emoji/unicode."""
    buf = io.StringIO()
    anterior = sys.stdout
    sys.stdout = buf
    try:
        yield buf
    finally:
        sys.stdout = anterior
