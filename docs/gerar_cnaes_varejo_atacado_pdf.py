"""
PDF do resource robo://catalogo/cnaes-varejo-atacado.

Uso (na raiz do repositório):
  python3 -m pip install reportlab
  python3 docs/gerar_cnaes_varejo_atacado_pdf.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FONTE_JSON = ROOT / "catalogo" / "cnaes_varejo_atacado_produtos.json"
OUT = ROOT / "catalogo" / "cnaes_varejo_atacado.pdf"
URI = "robo://catalogo/cnaes-varejo-atacado"


def _xml(texto: str) -> str:
    return escape(str(texto or ""))


def gerar(caminho: Path | None = None) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    dados = json.loads(FONTE_JSON.read_text(encoding="utf-8"))
    dest = caminho or OUT
    ink = colors.HexColor("#1a1a1a")
    muted = colors.HexColor("#555555")
    head_bg = colors.HexColor("#1f2933")
    varejo_bg = colors.HexColor("#e7f6ec")
    atacado_bg = colors.HexColor("#e8f1fb")
    alt = colors.HexColor("#f6f7f8")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("H", fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=ink, spaceAfter=4))
    styles.add(ParagraphStyle("S", fontName="Helvetica", fontSize=9, leading=12, textColor=muted, spaceAfter=6))
    styles.add(ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=ink, spaceBefore=10, spaceAfter=4))
    styles.add(ParagraphStyle("B", fontName="Helvetica", fontSize=9, leading=12, textColor=ink, spaceAfter=4))
    styles.add(ParagraphStyle("Sm", fontName="Helvetica", fontSize=8, leading=10.5, textColor=muted, spaceAfter=2))
    styles.add(ParagraphStyle("Th", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white, alignment=TA_LEFT))
    styles.add(ParagraphStyle("Td", fontName="Helvetica", fontSize=8, leading=10.5, textColor=ink, alignment=TA_LEFT))
    styles.add(ParagraphStyle("TdB", fontName="Helvetica-Bold", fontSize=8, leading=10.5, textColor=ink, alignment=TA_LEFT))

    def P(texto: str, style: str = "B"):
        return Paragraph(_xml(texto), styles[style])

    story = [
        P("CNAEs de varejo e atacado", "H"),
        P(f"Resource: {URI}", "S"),
        P(
            f"Fonte: {dados.get('fonte', '')}. Consultado em {dados.get('consultado_em', '')}. "
            f"{dados.get('escopo', '')}",
            "B",
        ),
        P(str(dados.get("criterio") or ""), "Sm"),
    ]

    for produto in dados.get("produtos") or []:
        story.append(P(str(produto.get("nome") or produto.get("id")), "H1"))
        for canal, fundo in (("varejo", varejo_bg), ("atacado", atacado_bg)):
            itens = produto.get(canal) or []
            if not itens:
                continue
            story.append(P(canal.capitalize(), "B"))
            cab = [
                Paragraph("Código", styles["Th"]),
                Paragraph("Papel", styles["Th"]),
                Paragraph("Descrição e motivo", styles["Th"]),
            ]
            linhas = [cab]
            for item in itens:
                linhas.append(
                    [
                        Paragraph(_xml(item.get("codigo")), styles["TdB"]),
                        Paragraph(_xml(item.get("papel")), styles["Td"]),
                        Paragraph(
                            f"{_xml(item.get('descricao'))}<br/>{_xml(item.get('porque'))}",
                            styles["Td"],
                        ),
                    ]
                )
            tabela = Table(linhas, colWidths=[3.2 * cm, 2.4 * cm, 11.4 * cm])
            tabela.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), head_bg),
                        ("BACKGROUND", (0, 1), (-1, -1), fundo),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d0d5dd")),
                    ]
                )
            )
            story.append(tabela)
            story.append(Spacer(1, 4))

    story.append(P("Índice de códigos", "H1"))
    cab = [
        Paragraph("Código", styles["Th"]),
        Paragraph("Canal", styles["Th"]),
        Paragraph("Descrição", styles["Th"]),
        Paragraph("Produtos", styles["Th"]),
    ]
    linhas = [cab]
    for codigo in dados.get("codigos") or []:
        linhas.append(
            [
                Paragraph(_xml(codigo.get("codigo")), styles["TdB"]),
                Paragraph(_xml(codigo.get("canal")), styles["Td"]),
                Paragraph(_xml(codigo.get("descricao")), styles["Td"]),
                Paragraph(_xml(", ".join(codigo.get("produtos") or [])), styles["Td"]),
            ]
        )
    tabela = Table(linhas, colWidths=[3.2 * cm, 2.2 * cm, 7.4 * cm, 4.2 * cm])
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), head_bg),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d0d5dd")),
    ]
    for i in range(1, len(linhas)):
        if i % 2 == 0:
            estilo.append(("BACKGROUND", (0, i), (-1, i), alt))
    tabela.setStyle(TableStyle(estilo))
    story.append(tabela)

    dest.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(dest),
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
        title="CNAEs de varejo e atacado",
        author="Robo-Markplaces",
    )
    doc.build(story)
    return dest


if __name__ == "__main__":
    print(gerar())
