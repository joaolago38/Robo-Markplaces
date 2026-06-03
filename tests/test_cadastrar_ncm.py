"""
tests/test_cadastrar_ncm.py
Testes (mockados, sem rede) do script de cadastro de NCM no Bling.
"""
import gc
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import integracoes.bling.bling_client as bc  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "cadastrar_ncm_bling", os.path.join(ROOT, "scripts", "cadastrar_ncm_bling.py")
)
cad = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cad)


def _xlsx_exemplo(path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Produtos NCM"
    ws.append(["PRODUTOS — NCM"])              # título (linha 1)
    ws.append([])                              # linha 2
    ws.append(["SKU (código no Bling)", "EAN", "Descrição", "NCM (sugerido)", "Validar c/ contador?"])
    ws.append(["7890000000001", "7890000000001", "Esmalte X", "33043000", "Nao"])
    ws.append(["7890000000002", "7890000000002", "Acetona Y", "33043000", "Sim"])
    wb.save(path)
    wb.close()


class TestLeitura(unittest.TestCase):
    def test_ler_xlsx(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ncm.xlsx"
            _xlsx_exemplo(p)
            itens = cad.carregar_itens(p)
            self.assertEqual(len(itens), 2)
            self.assertEqual(itens[0], {"sku": "7890000000001", "ncm": "33043000", "validar": False})
            self.assertTrue(itens[1]["validar"])
            gc.collect()

    def test_so_digitos(self):
        self.assertEqual(cad._so_digitos("3304.30.00"), "33043000")


class TestExecutar(unittest.TestCase):
    def test_idempotente_pula_ja_correto(self):
        itens = [{"sku": "S1", "ncm": "33043000", "validar": False}]
        with patch.object(bc, "buscar_produto", return_value={"ncm": "33043000"}), \
             patch.object(bc, "definir_ncm_por_sku") as dn:
            res = cad.executar(itens, aplicar=True, incluir_validar=False)
        dn.assert_not_called()
        self.assertEqual(res["ja_corretos"], 1)
        self.assertEqual(res["atualizados"], 0)

    def test_aplica_quando_diferente(self):
        itens = [{"sku": "S1", "ncm": "82142000", "validar": False}]
        with patch.object(bc, "buscar_produto", return_value={"ncm": "33043000"}), \
             patch.object(bc, "definir_ncm_por_sku", return_value={"ok": True}) as dn:
            res = cad.executar(itens, aplicar=True, incluir_validar=False)
        dn.assert_called_once_with("S1", "82142000")
        self.assertEqual(res["atualizados"], 1)

    def test_dry_run_nao_grava(self):
        itens = [{"sku": "S1", "ncm": "82142000", "validar": False}]
        with patch.object(bc, "buscar_produto", return_value={"ncm": "33043000"}), \
             patch.object(bc, "definir_ncm_por_sku") as dn:
            res = cad.executar(itens, aplicar=False, incluir_validar=False)
        dn.assert_not_called()
        self.assertEqual(res["atualizados"], 0)

    def test_pula_validar_por_padrao(self):
        itens = [{"sku": "S1", "ncm": "33043000", "validar": True}]
        with patch.object(bc, "buscar_produto") as bp, \
             patch.object(bc, "definir_ncm_por_sku") as dn:
            res = cad.executar(itens, aplicar=True, incluir_validar=False)
        bp.assert_not_called()
        dn.assert_not_called()
        self.assertEqual(res["pulados_validar"], 1)

    def test_inclui_validar_quando_flag(self):
        itens = [{"sku": "S1", "ncm": "33043000", "validar": True}]
        with patch.object(bc, "buscar_produto", return_value={"ncm": ""}), \
             patch.object(bc, "definir_ncm_por_sku", return_value={"ok": True}) as dn:
            res = cad.executar(itens, aplicar=True, incluir_validar=True)
        dn.assert_called_once()
        self.assertEqual(res["atualizados"], 1)

    def test_sku_nao_encontrado(self):
        itens = [{"sku": "X", "ncm": "33043000", "validar": False}]
        with patch.object(bc, "buscar_produto", return_value=None), \
             patch.object(bc, "definir_ncm_por_sku") as dn:
            res = cad.executar(itens, aplicar=True, incluir_validar=False)
        dn.assert_not_called()
        self.assertEqual(res["nao_encontrados"], 1)


if __name__ == "__main__":
    unittest.main()
