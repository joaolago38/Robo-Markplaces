"""
tests/test_atomic_io.py — escrita atômica + lock entre processos para JSON compartilhado.
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import atomic_io


class TestEscreverJsonAtomico(unittest.TestCase):
    def test_cria_arquivo_com_conteudo_correto(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "estado.json"
            atomic_io.escrever_json_atomico(caminho, {"a": 1})
            self.assertEqual(json.loads(caminho.read_text(encoding="utf-8")), {"a": 1})

    def test_cria_diretorios_intermediarios(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "sub" / "mais_um" / "estado.json"
            atomic_io.escrever_json_atomico(caminho, {"x": True})
            self.assertTrue(caminho.is_file())

    def test_nao_deixa_arquivo_temporario_apos_sucesso(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "estado.json"
            atomic_io.escrever_json_atomico(caminho, {"a": 1})
            restantes = list(Path(tmp).glob("*.tmp"))
            self.assertEqual(restantes, [])

    def test_sobrescreve_conteudo_anterior(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "estado.json"
            atomic_io.escrever_json_atomico(caminho, {"versao": 1})
            atomic_io.escrever_json_atomico(caminho, {"versao": 2})
            self.assertEqual(json.loads(caminho.read_text(encoding="utf-8"))["versao"], 2)


class TestLerJson(unittest.TestCase):
    def test_arquivo_inexistente_retorna_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "nao_existe.json"
            self.assertEqual(atomic_io.ler_json(caminho), {})
            self.assertEqual(atomic_io.ler_json(caminho, default=[]), [])

    def test_arquivo_corrompido_retorna_default_sem_lancar(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "corrompido.json"
            caminho.write_text("{ isso nao é json válido", encoding="utf-8")
            self.assertEqual(atomic_io.ler_json(caminho), {})


class TestLerEAtualizarJson(unittest.TestCase):
    def test_atualiza_e_persiste(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "estado.json"

            def _incrementar(dados):
                dados = dict(dados or {})
                dados["contador"] = dados.get("contador", 0) + 1
                return dados

            resultado1 = atomic_io.ler_e_atualizar_json(caminho, _incrementar, default={})
            resultado2 = atomic_io.ler_e_atualizar_json(caminho, _incrementar, default={})

            self.assertEqual(resultado1["contador"], 1)
            self.assertEqual(resultado2["contador"], 2)
            self.assertEqual(json.loads(caminho.read_text(encoding="utf-8"))["contador"], 2)

    def test_concorrencia_nao_perde_atualizacoes(self):
        """
        Simula múltiplas threads incrementando o mesmo contador
        concorrentemente. Sem o lock, é esperado perder atualizações
        (leitura-modificação-escrita sem proteção); com o lock, o
        contador final deve bater exatamente com o número de chamadas.
        """
        if not atomic_io._TEM_FLOCK:
            self.skipTest("fcntl indisponível — teste de concorrência só em POSIX")
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "contador.json"
            atomic_io.escrever_json_atomico(caminho, {"contador": 0})

            def _incrementar(dados):
                dados = dict(dados or {})
                # força uma janela de corrida: lê, espera um pouco, escreve
                valor_atual = dados.get("contador", 0)
                time.sleep(0.001)
                dados["contador"] = valor_atual + 1
                return dados

            def _trabalhar():
                atomic_io.ler_e_atualizar_json(caminho, _incrementar, default={})

            threads = [threading.Thread(target=_trabalhar) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            final = json.loads(caminho.read_text(encoding="utf-8"))
            self.assertEqual(final["contador"], 20)


class TestLockExclusivo(unittest.TestCase):
    def test_lock_e_liberado_apos_uso(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho_lock = Path(tmp) / "teste.lock"
            with atomic_io.lock_exclusivo(caminho_lock):
                pass
            # Conseguir adquirir de novo confirma que foi liberado.
            with atomic_io.lock_exclusivo(caminho_lock):
                pass

    def test_lock_funciona_mesmo_sem_diretorio_existente(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho_lock = Path(tmp) / "sub" / "teste.lock"
            with atomic_io.lock_exclusivo(caminho_lock):
                pass
            self.assertTrue(caminho_lock.parent.is_dir())


if __name__ == "__main__":
    unittest.main()
