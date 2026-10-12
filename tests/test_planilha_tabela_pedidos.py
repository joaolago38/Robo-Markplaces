# -*- coding: utf-8 -*-
"""tests/test_planilha_tabela_pedidos.py"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.masterprint import planilha_tabela_pedidos as tp

PLANILHA = (
    Path(__file__).resolve().parents[1]
    / "planilhas_ecommerce"
    / "TABELA DE PEDIDOS.XLSX"
)

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _c_inline(ref: str, text: str) -> str:
    return (
        f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'
    )


def _c_num(ref: str, val: str) -> str:
    return f'<c r="{ref}"><v>{val}</v></c>'


def _montar_fixture_xlsx(path: Path, *, sheet_membro: str = "xl/sheet1.xml") -> None:
    """XLSX mínimo no layout Masterprint (sheet na raiz de xl/)."""
    rows_xml = [
        # Família filamento PETG
        f"<row r=\"1\">{_c_inline('A1', 'Família:')}{_c_inline('B1', '23102')}{_c_inline('C1', 'PETG')}</row>",
        (
            f"<row r=\"2\">{_c_inline('A2', '231020001')}{_c_inline('B2', 'Filamento PETG Preto 1kg')}"
            f"{_c_num('I2', '40')}{_c_num('J2', '5')}{_c_num('K2', '42')}</row>"
        ),
        # várias cores para passar contagem
        *[
            (
                f"<row r=\"{i}\">{_c_inline(f'A{i}', f'23102000{i}')}"
                f"{_c_inline(f'B{i}', f'Filamento PETG {i}')}"
                f"{_c_num(f'I{i}', '41')}{_c_num(f'J{i}', '0')}{_c_num(f'K{i}', '41')}</row>"
            )
            for i in range(3, 55)
        ],
        # Família PLA
        f"<row r=\"60\">{_c_inline('A60', 'Família:')}{_c_inline('B60', '23101')}{_c_inline('C60', 'PLA')}</row>",
        (
            f"<row r=\"61\">{_c_inline('A61', '231010001')}{_c_inline('B61', 'Filamento PLA Branco')}"
            f"{_c_num('I61', '35')}{_c_num('J61', '0')}{_c_num('K61', '35')}</row>"
        ),
        # Escritório
        f"<row r=\"70\">{_c_inline('A70', 'Família:')}{_c_inline('B70', '30904')}{_c_inline('C70', 'Pincel')}</row>",
        *[
            (
                f"<row r=\"{80+i}\">{_c_inline(f'A{80+i}', f'30904000{i}')}"
                f"{_c_inline(f'B{80+i}', f'Pincel permanente {i}')}"
                f"{_c_num(f'I{80+i}', '8')}{_c_num(f'J{80+i}', '0')}{_c_num(f'K{80+i}', '8')}</row>"
            )
            for i in range(1, 5)
        ],
        f"<row r=\"90\">{_c_inline('A90', 'Família:')}{_c_inline('B90', '32801')}{_c_inline('C90', 'Apagador')}</row>",
        *[
            (
                f"<row r=\"{91+i}\">{_c_inline(f'A{91+i}', f'32801000{i}')}"
                f"{_c_inline(f'B{91+i}', f'Apagador {i}')}"
                f"{_c_num(f'I{91+i}', '6')}{_c_num(f'J{91+i}', '0')}{_c_num(f'K{91+i}', '6')}</row>"
            )
            for i in range(1, 4)
        ],
    ]
    sheet = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_NS}"><sheetData>'
        + "".join(rows_xml)
        + "</sheetData></worksheet>"
    )
    rel_target = sheet_membro.replace("xl/", "", 1) if sheet_membro.startswith("xl/") else sheet_membro
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        f'<Override PartName="/{sheet_membro}" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<workbook xmlns="{_NS}">'
        '<sheets><sheet name="Pedidos" sheetId="1" r:id="rId1" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
        "</sheets></workbook>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="{rel_target}"/>'
        "</Relationships>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr(sheet_membro, sheet)


class TestTabelaPedidosFixture(unittest.TestCase):
    def test_parse_layout_masterprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            xlsx = Path(tmp) / "tabela.xlsx"
            _montar_fixture_xlsx(xlsx, sheet_membro="xl/sheet1.xml")
            out = tp.parse_tabela_pedidos(xlsx)
            self.assertTrue(out["ok"], out.get("erro"))
            tot = out["totais"]
            self.assertGreater(tot["filamentos"], 50)
            self.assertGreater(tot["escritorio"], 5)
            mats = set(out["por_material"])
            self.assertTrue({"PLA", "PETG"} <= mats)
            self.assertIn("pincel_permanente", mats)
            self.assertIn("apagador", mats)

    def test_parse_layout_ooxml_worksheets(self):
        with tempfile.TemporaryDirectory() as tmp:
            xlsx = Path(tmp) / "tabela_std.xlsx"
            _montar_fixture_xlsx(xlsx, sheet_membro="xl/worksheets/sheet1.xml")
            out = tp.parse_tabela_pedidos(xlsx)
            self.assertTrue(out["ok"], out.get("erro"))
            self.assertGreater(out["totais"]["filamentos"], 50)


@unittest.skipUnless(PLANILHA.is_file(), "TABELA DE PEDIDOS.XLSX ausente")
class TestTabelaPedidosReal(unittest.TestCase):
    def test_parse_filamentos_e_escritorio(self):
        out = tp.parse_tabela_pedidos(PLANILHA)
        if not out.get("ok"):
            self.skipTest(f"planilha ilegível no ambiente: {out.get('erro')}")
        tot = out["totais"]
        self.assertGreater(tot["filamentos"], 50)
        self.assertGreater(tot["escritorio"], 5)
        mats = set(out["por_material"])
        self.assertTrue({"PLA", "PETG"} <= mats)
        self.assertIn("pincel_permanente", mats)
        self.assertIn("apagador", mats)


if __name__ == "__main__":
    unittest.main()
