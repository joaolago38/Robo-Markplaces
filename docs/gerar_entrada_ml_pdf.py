"""
PDF da entrada no Mercado Livre: kits com margem aceitável,
embalagem e custo de compra.

Uso (na raiz do repositório):
  python3 docs/gerar_entrada_ml_pdf.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "entrada-ml-kits-embalagem.pdf"
TAXA_ML = 0.18
PISO_PCT = 15.0
FRENTE_AGORA = ("IMP-MIMO-003", "IMP-PERL-004")
DEPOIS_PEDIDO = "IMP-JUPAES-006"


def _f(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _brl(val: float) -> str:
    return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _carregar() -> tuple[list[dict], dict, dict]:
    produtos = json.loads((ROOT / "catalogo" / "produtos.json").read_text(encoding="utf-8"))
    doutrina = json.loads(
        (ROOT / "catalogo" / "doutrina_guerra_impala.json").read_text(encoding="utf-8")
    )
    caixas = json.loads((ROOT / "catalogo" / "caixas_kits_impala.json").read_text(encoding="utf-8"))
    papéis = doutrina.get("kits") if isinstance(doutrina.get("kits"), dict) else {}
    por_sku = caixas.get("por_sku") if isinstance(caixas.get("por_sku"), dict) else {}
    linhas: list[dict] = []
    for p in produtos:
        if not isinstance(p, dict):
            continue
        sku = str(p.get("sku") or "").strip().upper()
        if not sku.startswith("IMP-"):
            continue
        ml = (p.get("canais") or {}).get("mercadolivre") or {}
        preco = _f(ml.get("preco") or p.get("preco"))
        custo = _f(p.get("custo_total"))
        liquida = preco * (1 - TAXA_ML)
        lucro = liquida - custo
        margem = (100.0 * lucro / preco) if preco else 0.0
        meta = papéis.get(sku) if isinstance(papéis.get(sku), dict) else {}
        caixa = por_sku.get(sku) if isinstance(por_sku.get(sku), dict) else {}
        if sku in FRENTE_AGORA:
            decisao = "entrar agora"
        elif sku == DEPOIS_PEDIDO and margem >= PISO_PCT:
            decisao = "depois do 1º pedido"
        elif margem >= PISO_PCT:
            decisao = "aceitável, fora da frente"
        elif margem >= 10:
            decisao = "abaixo do piso 15%"
        else:
            decisao = "não montar"
        linhas.append(
            {
                "sku": sku,
                "nome": str(p.get("nome") or ""),
                "papel": str(meta.get("papel") or "catálogo"),
                "preco": preco,
                "custo": custo,
                "esmaltes": _f(p.get("custo_esmaltes")),
                "complemento": _f(p.get("custo_complemento")),
                "embalagem": _f(p.get("custo_embalagem")),
                "caixa_rs": _f(p.get("custo_caixa")),
                "frete": _f(p.get("frete_estimado")),
                "sem_frete": _f(p.get("custo_total_sem_frete")),
                "liquida": liquida,
                "lucro": lucro,
                "margem": margem,
                "un": int(_f(p.get("valida_unidades") or 0)),
                "peso": int(_f(p.get("peso_gramas") or caixa.get("peso_g") or 0)),
                "caixa_cod": str(p.get("caixa_caixasnet") or caixa.get("codigo") or ""),
                "conteudo": str(caixa.get("conteudo") or ""),
                "layout": str(caixa.get("layout") or ""),
                "anunciar": str(caixa.get("anunciar_ml") or ""),
                "decisao": decisao,
            }
        )
    ordem = {"entrar agora": 0, "depois do 1º pedido": 1, "aceitável, fora da frente": 2, "abaixo do piso 15%": 3, "não montar": 4}
    linhas.sort(key=lambda r: (ordem.get(r["decisao"], 9), r["sku"]))
    return linhas, doutrina, caixas


def gerar(caminho: Path | None = None) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    linhas, doutrina, caixas = _carregar()
    dest = caminho or OUT
    hoje = date.today().strftime("%d/%m/%Y")
    font, font_b = "Helvetica", "Helvetica-Bold"
    ink = colors.HexColor("#1a1a1a")
    muted = colors.HexColor("#555555")
    head_bg = colors.HexColor("#1f2933")
    ok_bg = colors.HexColor("#e7f6ec")
    wait_bg = colors.HexColor("#fff6df")
    no_bg = colors.HexColor("#fdecec")
    alt = colors.HexColor("#f6f7f8")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("H", fontName=font_b, fontSize=16, leading=20, textColor=ink, spaceAfter=6))
    styles.add(ParagraphStyle("S", fontName=font, fontSize=9, leading=12, textColor=muted, spaceAfter=8))
    styles.add(ParagraphStyle("H1", fontName=font_b, fontSize=12, leading=15, textColor=ink, spaceBefore=12, spaceAfter=6))
    styles.add(ParagraphStyle("B", fontName=font, fontSize=9, leading=12.5, textColor=ink, alignment=TA_JUSTIFY, spaceAfter=6))
    styles.add(ParagraphStyle("Sm", fontName=font, fontSize=8, leading=10.5, textColor=muted, spaceAfter=4))
    styles.add(ParagraphStyle("Th", fontName=font_b, fontSize=7, leading=9, textColor=colors.white, alignment=TA_CENTER))
    styles.add(ParagraphStyle("Td", fontName=font, fontSize=7, leading=9, textColor=ink, alignment=TA_LEFT))
    styles.add(ParagraphStyle("TdC", fontName=font, fontSize=7, leading=9, textColor=ink, alignment=TA_CENTER))

    def P(text: str, style: str = "B"):
        return Paragraph(str(text), styles[style])

    def th(*cells):
        return [Paragraph(str(c), styles["Th"]) for c in cells]

    def td(*cells, center: bool = False):
        st = "TdC" if center else "Td"
        return [Paragraph(str(c), styles[st]) for c in cells]

    agora = [r for r in linhas if r["decisao"] == "entrar agora"]
    depois = [r for r in linhas if r["sku"] == DEPOIS_PEDIDO]
    compra = (caixas.get("envio_ml") or {}).get("comprar_caixas_pedido_validacao") or {}
    qtd_caixa = int(_f(compra.get("qtd"), 24))
    custo_caixa_un = _f(compra.get("custo_un_planilha"), 0.98)
    opex = _f((doutrina.get("opex") or {}).get("valor_brl"), 800)

    invest_kits = sum(r["custo"] * 10 for r in agora)
    invest_caixas = qtd_caixa * custo_caixa_un
    un_agora = sum(10 for _ in agora)

    story = [
        P("Entrada no Mercado Livre", "H"),
        P(
            f"Kits aceitáveis, embalagem e custo · Impala {doutrina.get('cnpj', '')} · {hoje}. "
            "Números lidos de catalogo/produtos.json, doutrina_guerra_impala.json e caixas_kits_impala.json.",
            "S",
        ),
        P(
            f"Aceitável para entrar é margem real de pelo menos {PISO_PCT:.0f}% "
            f"depois da taxa do Mercado Livre ({TAXA_ML * 100:.0f}%). "
            "Margem = (preço × 0,82 − custo total) / preço. "
            "Custo total já inclui esmalte, complemento, embalagem, caixa quando cadastrada e frete estimado.",
            "B",
        ),
        P(
            f"Entram agora {len(agora)} kits, {un_agora} unidades no ar "
            f"(10 de cada, estoque de validação da doutrina). "
            f"Dinheiro em produto: {_brl(invest_kits)}. "
            f"Caixas desta leva: {qtd_caixa} × {compra.get('modelo', 'S20')} a {_brl(custo_caixa_un)} = {_brl(invest_caixas)}. "
            f"O operacional único de {_brl(opex)} fica fora do custo do kit.",
            "B",
        ),
    ]

    story.append(P("O que montar", "H1"))
    cab = th("SKU", "Papel", "Preço", "Custo", "Lucro", "Margem", "Decisão")
    dados = [cab]
    for r in linhas:
        dados.append(
            td(
                r["sku"],
                r["papel"],
                _brl(r["preco"]),
                _brl(r["custo"]),
                _brl(r["lucro"]),
                f"{r['margem']:.1f}%",
                r["decisao"],
                center=True,
            )
        )
    tabela = Table(dados, colWidths=[3.1 * cm, 2.2 * cm, 2.0 * cm, 2.0 * cm, 2.0 * cm, 1.8 * cm, 3.6 * cm], repeatRows=1)
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), head_bg),
        ("FONTNAME", (0, 0), (-1, 0), font_b),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#d5d8dc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for i, r in enumerate(linhas, start=1):
        if r["decisao"] == "entrar agora":
            estilo.append(("BACKGROUND", (0, i), (-1, i), ok_bg))
        elif r["decisao"] == "depois do 1º pedido":
            estilo.append(("BACKGROUND", (0, i), (-1, i), wait_bg))
        elif r["decisao"] == "não montar":
            estilo.append(("BACKGROUND", (0, i), (-1, i), no_bg))
        elif i % 2 == 0:
            estilo.append(("BACKGROUND", (0, i), (-1, i), alt))
    tabela.setStyle(TableStyle(estilo))
    story.append(tabela)
    story.append(Spacer(1, 6))
    story.append(
        P(
            "Verde: publicar nesta entrada. Amarelo: só depois do primeiro pedido vencedor. "
            "Vermelho: margem negativa com a taxa de 18% — não comprar caixa nem esmalte para anunciar.",
            "Sm",
        )
    )

    story.append(P("Custo dos kits que passam do piso", "H1"))
    det = [
        th("Peça", "MIMO-003", "PERL-004", "JUPAES-006"),
    ]
    por = {r["sku"]: r for r in linhas}
    rotulos = [
        ("Preço no ML", "preco"),
        ("Esmaltes", "esmaltes"),
        ("Complemento", "complemento"),
        ("Embalagem", "embalagem"),
        ("Caixa no custo", "caixa_rs"),
        ("Frete estimado", "frete"),
        ("Custo total", "custo"),
        ("Líquido após 18%", "liquida"),
        ("Lucro por kit", "lucro"),
        ("Margem real", "margem"),
    ]
    for rotulo, chave in rotulos:
        linha = [Paragraph(rotulo, styles["Td"])]
        for sku in ("IMP-MIMO-003", "IMP-PERL-004", "IMP-JUPAES-006"):
            val = por[sku][chave]
            texto = f"{val:.1f}%" if chave == "margem" else _brl(val)
            linha.append(Paragraph(texto, styles["TdC"]))
        det.append(linha)
    t2 = Table(det, colWidths=[4.2 * cm, 4.0 * cm, 4.0 * cm, 4.0 * cm], repeatRows=1)
    t2.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), head_bg),
                ("BACKGROUND", (0, 7), (-1, 7), alt),
                ("GRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#d5d8dc")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(t2)
    story.append(Spacer(1, 6))
    mimo = por["IMP-MIMO-003"]
    story.append(
        P(
            f"O MIMO está com custo de caixa R$ 0 no produto e embalagem de {_brl(mimo['embalagem'])}. "
            f"O PERL já carrega a caixa S20 de {_brl(por['IMP-PERL-004']['caixa_rs'])} dentro do custo total. "
            "A compra de 24 caixas abaixo cobre os dois; não somar de novo os R$ 0,98 no PERL.",
            "Sm",
        )
    )

    story.append(P("Embalagem e quantidade aceitável", "H1"))
    story.append(
        P(
            f"Pedido de validação no catálogo de caixas: {qtd_caixa} unidades "
            f"{compra.get('modelo', 'S20-16x11x10')} ({compra.get('fornecedor', 'CaixasNet')}), "
            f"{compra.get('uso', '12 MIMO + 12 PERL')}. "
            f"Proteção: {compra.get('protecao', 'saco bolha, kraft e fita')}.",
            "B",
        )
    )
    emb_rows = [th("SKU", "No ar", "Caixa", "Peso", "Conteúdo", "Custo da leva")]
    leva = {"IMP-MIMO-003": 10, "IMP-PERL-004": 10, DEPOIS_PEDIDO: 0}
    for sku, qtd in leva.items():
        r = por[sku]
        nota_qtd = "10 agora" if qtd else "0 agora · 10 depois"
        emb_rows.append(
            td(
                r["sku"],
                nota_qtd,
                r["caixa_cod"] or "S20",
                f"{r['peso']} g",
                r["conteudo"] or r["nome"],
                _brl(r["custo"] * (qtd or 10)) + ("" if qtd else " depois"),
            )
        )
    t3 = Table(emb_rows, colWidths=[3.0 * cm, 2.8 * cm, 3.2 * cm, 1.6 * cm, 4.2 * cm, 2.4 * cm], repeatRows=1)
    t3.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), head_bg),
                ("BACKGROUND", (0, 1), (-1, 2), ok_bg),
                ("BACKGROUND", (0, 3), (-1, 3), wait_bg),
                ("GRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#d5d8dc")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(t3)
    story.append(Spacer(1, 8))

    modelos = caixas.get("modelos") or {}
    s20 = modelos.get("S20") or {}
    s03 = modelos.get("S03") or {}
    story.append(
        P(
            f"S20 {s20.get('codigo', '')}: {s20.get('uso', 'kits pequenos')}. "
            f"Anunciar MIMO 16 × 11 × 10 cm · 0,280 kg e PERL 16 × 11 × 10 cm · 0,380 kg. "
            f"S03 {s03.get('codigo', '')} fica para kits de 10 a 30 esmaltes — nenhum deles passa de {PISO_PCT:.0f}% nesta tabela, então não entra na compra.",
            "B",
        )
    )
    j = por[DEPOIS_PEDIDO]
    story.append(
        P(
            f"Depois do primeiro pedido: {j['un'] or 10} kits {j['sku']} ({j['nome']}), "
            f"margem {j['margem']:.1f}%, custo {_brl(j['custo'])} cada, "
            f"investimento {_brl(j['custo'] * (j['un'] or 10))}. Mesma caixa S20, mais 10 unidades.",
            "B",
        )
    )
    story.append(
        P(
            "Não anunciar Impala em Shopee, Magalu ou Amazon antes da fase 3 "
            "(20 avaliações e nota 4,8 no Mercado Livre). "
            "Não baixar o MIMO abaixo de R$ 41,99. Não tratar kit com margem negativa como estoque de entrada.",
            "B",
        )
    )
    story.append(
        P(
            "Fontes: catalogo/produtos.json, catalogo/doutrina_guerra_impala.json, catalogo/caixas_kits_impala.json.",
            "Sm",
        )
    )

    dest.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(dest),
        pagesize=A4,
        leftMargin=1.4 * cm,
        rightMargin=1.4 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
        title="Entrada no Mercado Livre — kits, embalagem e custo",
        author="Robo Markplaces",
    )
    doc.build(story)
    return dest


if __name__ == "__main__":
    caminho = gerar()
    print(caminho)
