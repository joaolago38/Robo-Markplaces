"""
Gera o PDF de estratégias Impala (Flash, PERL, criativos, canais).

Uso (na raiz Robo-Markplaces):
  py -3 -m pip install reportlab
  py -3 docs/gerar_estrategias_pdf.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "estrategias.pdf"


def _fontes():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    arial = Path(r"C:\Windows\Fonts\arial.ttf")
    arial_b = Path(r"C:\Windows\Fonts\arialbd.ttf")
    if arial.exists():
        pdfmetrics.registerFont(TTFont("ArialDoc", str(arial)))
        pdfmetrics.registerFont(TTFont("ArialDoc-Bold", str(arial_b if arial_b.exists() else arial)))
        return "ArialDoc", "ArialDoc-Bold"
    return "Helvetica", "Helvetica-Bold"


def gerar(caminho: Path | None = None) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        ListFlowable,
        ListItem,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    dest = caminho or OUT
    font, font_b = _fontes()
    hoje = date.today().strftime("%d/%m/%Y")

    ink = colors.HexColor("#1a1a1a")
    muted = colors.HexColor("#5c5c5c")
    line = colors.HexColor("#d0d0d0")
    head_bg = colors.HexColor("#222222")
    alt = colors.HexColor("#f4f4f4")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("CapaH", fontName=font_b, fontSize=22, leading=28, textColor=ink, spaceAfter=8))
    styles.add(ParagraphStyle("CapaS", fontName=font, fontSize=11, leading=15, textColor=muted, spaceAfter=6))
    styles.add(ParagraphStyle("H1d", fontName=font_b, fontSize=13, leading=17, textColor=ink, spaceBefore=14, spaceAfter=8))
    styles.add(ParagraphStyle("H2d", fontName=font_b, fontSize=11, leading=14, textColor=ink, spaceBefore=10, spaceAfter=6))
    styles.add(ParagraphStyle("Bd", fontName=font, fontSize=9.5, leading=13, textColor=ink, alignment=TA_JUSTIFY, spaceAfter=6))
    styles.add(ParagraphStyle("Sm", fontName=font, fontSize=8, leading=11, textColor=muted, spaceAfter=4))
    styles.add(ParagraphStyle("Th", fontName=font_b, fontSize=7.5, leading=10, textColor=colors.white, alignment=TA_CENTER))
    styles.add(ParagraphStyle("Td", fontName=font, fontSize=7.5, leading=10, textColor=ink, alignment=TA_LEFT))
    styles.add(ParagraphStyle("TdC", fontName=font, fontSize=7.5, leading=10, textColor=ink, alignment=TA_CENTER))
    styles.add(ParagraphStyle("BulletBody", fontName=font, fontSize=9.5, leading=13, textColor=ink))

    def P(text: str, style="Bd"):
        return Paragraph(str(text).replace("&", "&amp;").replace("\n", "<br/>"), styles[style])

    def th(*cells):
        return [Paragraph(c, styles["Th"]) for c in cells]

    def td(*cells, center=False):
        st = styles["TdC"] if center else styles["Td"]
        return [Paragraph(str(c).replace("&", "&amp;"), st) for c in cells]

    def bullets(items: list[str]):
        return ListFlowable(
            [ListItem(Paragraph(str(i).replace("&", "&amp;"), styles["BulletBody"]), leftIndent=8) for i in items],
            bulletType="bullet",
            start="•",
            leftIndent=14,
            spaceAfter=8,
        )

    def tabela(header: list[str], rows: list, widths: list):
        data = [th(*header), *rows]
        t = Table(data, colWidths=widths, repeatRows=1)
        cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), head_bg),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.3, line),
        ]
        for i in range(1, len(data)):
            if i % 2 == 0:
                cmds.append(("BACKGROUND", (0, i), (-1, i), alt))
        t.setStyle(TableStyle(cmds))
        return t

    story = []
    story.append(P("Estratégias", "CapaH"))
    story.append(P("Kits Impala · Flash Secante · Mercado Livre e Shopee", "CapaS"))
    story.append(P(f"Robô Markplaces · CNPJ 52.668.583/0001-27 · {hoje}", "CapaS"))
    story.append(
        P(
            "Compilação da frente de validação: extra profissional é Flash Secante Impala "
            "(ref. 1009488, ~R$ 4,86). Carmed sai do criativo desta linha. Alicate não entra "
            "no kit de esmalte. Canal referente: Mercado Livre."
        )
    )

    story.append(P("1. Decisão central", "H1d"))
    story.append(
        bullets(
            [
                "Extra permitido: Flash Secante. Título alvo: Kit 3 Esmaltes Impala + Flash Secante Manicure.",
                "Extra proibido no mesmo MLB: alicate (777, 522-C), palito, algodão, lixa, acetona, Carmed.",
                "Dois anúncios na primeira onda: kit 3 + Flash (R$ 44,90) e PERL 4 perolados (R$ 39,90).",
                "Cores kit 3: Admire, Sutileza, Amor Profundo. PERL: Sonho, Polar, Lua, Dengo.",
                "SKU de referência do extra: IMP-FLASH-003 (pipeline onda 2; não publicar Flash+Carmed juntos).",
                "BUNDLE-777-5ESM fica legado — não publicar nesta etapa.",
            ]
        )
    )

    story.append(P("2. Quantos kits para validar", "H1d"))
    story.append(
        P(
            "Não é o plano antigo de 8 SKUs (~R$ 5.198). Validação = 2 anúncios, 10 unidades no ar cada."
        )
    )
    story.append(
        tabela(
            ["O quê", "Quantidade", "Por quê"],
            [
                td("SKUs agora", "2 — kit 3+Flash e IMP-PERL-004", "Entrada + preço no mesmo ciclo"),
                td("Estoque ML", "10 + 10", "estoque_validacao da doutrina"),
                td("Caixas S20", "24", "12+12 (10 no ar + folga)"),
                td("Depois, se vender", "30 por SKU", "estoque_ml_min — não é o lote inicial"),
                td("Flash/777/SORT no ar", "0 além do kit 3 combinado", "777 e sortido fora desta rodada"),
            ],
            [4.2 * cm, 5.8 * cm, 6.8 * cm],
        )
    )
    story.append(P("Meta depois da venda: 20 avaliações / nota 4,8 — isso é review, não quantidade a comprar agora.", "Sm"))

    story.append(P("3. Dois públicos — o que muda a vida delas", "H1d"))
    story.append(
        P(
            "Manicure e mulher não compram o mesmo argumento. Ferramenta de gaveta "
            "(palito, algodão, lixa, alicate no kit) não diferencia: as duas já têm."
        )
    )
    story.append(P("Manicure (trabalho)", "H2d"))
    story.append(
        P(
            "O dia dela é relógio + WhatsApp + cliente que compara preço. O que muda a vida: "
            "secar rápido (Flash = mais encaixe, menos borra), cores nomeadas sem comprar avulso "
            "(PERL: 4 por R$ 39,90 vs 4×R$ 12 = R$ 48), coleção que a cliente pede (Ju Paes só "
            "após o 1º pedido). Kit 3 + Flash não é oferta de economia de frasco — é extra de mesa."
        )
    )
    story.append(P("Mulher (presente ou eu mesma)", "H2d"))
    story.append(
        P(
            "Ela não monta estoque. Quer não errar a combinação e sair com a unha intacta. "
            "Três cores que já combinam + Flash (“pinta e segue o dia / não borra no bolso”). "
            "Perolado é outro desejo: PERL em anúncio separado. Palito e algodão não geram foto."
        )
    )

    story.append(P("4. Furar a bolha dos demais", "H1d"))
    story.append(
        P(
            "Sim — saindo da bolha, não furando por preço. Radar (amostra): 18 anúncios, "
            "0 comparáveis à frente; 8 francesinha, 5 tratamento, 0 Carmed, 0 alicate. "
            "A bolha é kit 3 sortido/francesinha a ~R$ 22–36."
        )
    )
    story.append(
        tabela(
            ["Kit", "Bolha que ignora", "Onde aparece"],
            [
                td("3 Impala + Flash", "3 Impala sortidas R$ 22", "Busca Flash/secante/manicure; foto de mesa"),
                td("PERL 4 perolados", "Kit 4 genérico / dump", "Cores nomeadas; economia vs avulso"),
                td("777 (depois)", "Kit presente e kit 3 barato", "Cutelaria; outro MLB"),
            ],
            [4.5 * cm, 5.5 * cm, 6.8 * cm],
        )
    )
    story.append(
        P(
            "Furam a bolha se o título leva Flash, as cores estão na foto e o preço não iguala R$ 22. "
            "Não furam se misturam 777/algodão/lixa no mesmo anúncio ou baixam o kit 3 para caber no dump."
        )
    )

    story.append(P("5. Como lidar com o preço", "H1d"))
    story.append(
        tabela(
            ["SKU", "No ar", "Mexe?", "Piso 15% ML", "Vs R$ 22"],
            [
                td("Kit 3 + Flash", "R$ 44,90", "Não (congelado)", "~R$ 38,79", "Ignora"),
                td("IMP-PERL-004", "R$ 39,90", "Sim, 3 regras", "~R$ 39,15", "Só kit 4 comparável"),
                td("777 bundle 5", "Fora", "Não publicar", "~R$ 86,90", "—"),
            ],
            [3.4 * cm, 2.8 * cm, 3.4 * cm, 3.2 * cm, 4.0 * cm],
        )
    )
    story.append(
        bullets(
            [
                "PERL só iguala se: rival ao vivo no mesmo tamanho, gap ≥ 3%, preço ≥ piso. Dump abaixo do piso = não perseguir.",
                "Chat kit 3: “R$ 44,90 com Flash incluso”. Nunca “mais barato que o outro”. Economia vs avulso só no PERL.",
                "Não copiar preço do ML para Shopee sem recálculo (taxa 14%). Não Ads para compensar preço.",
            ]
        )
    )

    story.append(P("6. Acetona na primeira onda", "H1d"))
    story.append(
        P(
            "Não vira kit nem vai na caixa do Flash. Copy: “para remover, use acetona Cruzeiro (não incluso).” "
            "Chat: não inventar combo nem preço. Publicar CRZ-KIT-001 (acetona 95 ml + amolecedor + esfoliante, "
            "R$ 39,90) só no 1º pedido vencedor. CRZ-KIT-002 depois, se houver recompra. 500 ml fora desta frente."
        )
    )

    story.append(P("7. Palito, algodão, lixa", "H1d"))
    story.append(
        P(
            "Como kit próprio no título: não. Commodity. Como extra no Flash/PERL: não (S20 já está ocupado). "
            "Onda 2, se quiser: 1 lixa Katy na caixa, fora do título (custo abaixo de R$ 1). IMP-BAIL-003 (3 Bailarina + lixa) "
            "só depois do 1º pedido. Completar mesa = acetona Cruzeiro em anúncio separado, não trio de descartável."
        )
    )

    story.append(PageBreak())
    story.append(P("8. Criativos — quando puder ligar", "H1d"))
    story.append(
        P(
            "Ads off até 20 reviews, nota 4,8, ACOS ≤ 20%, orçamento R$ 10/dia. Com essa verba: "
            "4 criativos, 1 SKU (kit 3 + Flash). Playbook: 4 variações, uma variável por vez. "
            "PERL orgânico até o Flash ter um vencedor."
        )
    )
    story.append(
        tabela(
            ["#", "Peça (8–15 s)", "Mulher", "Manicure"],
            [
                td("1", "Unboxing S20, Flash por último", "Sim — conjunto A", "Bancada ao fundo"),
                td("2", "Swatch + secou / não borrou", "Bolso, volante, teclado", "Próxima cliente sem espera"),
                td("3", "Mesa / relógio / fila", "Não", "Sim — conjunto B"),
                td("4", "Packshot + R$ 44,90", "Sim — conjunto A", "Copy de salão, outro anúncio"),
            ],
            [1.4 * cm, 5.2 * cm, 4.8 * cm, 5.4 * cm],
        )
    )
    story.append(P("Direcionar os públicos", "H2d"))
    story.append(
        bullets(
            [
                "Não misturar mulher e manicure no mesmo conjunto de Ads.",
                "Conjunto A mulher (~R$ 7): criativos 1 e 4. Interesse esmalte/beleza, não “salão”. CTA: pinta e segue o dia.",
                "Conjunto B manicure (~R$ 3 ou só orgânico/WA): criativo 3. CTA: extra de mesa, Flash Secante.",
                "Swatch: duas legendas, dois anúncios — nunca a mesma linha.",
                "Mulher: “Três cores que combinam. Flash para não borrar.”",
                "Manicure: “Mesmo kit da moda, com secante na mesa. Sem francesinha.”",
                "Carrossel ML (não conta como Ads): 6 fotos — packshot, cores, Flash visível, caixa, swatch, o que vai / não vai.",
                "Pausa os 2 piores em 3–5 dias; replica o melhor. Sem 777, lixa, acetona, Carmed no frame.",
            ]
        )
    )

    story.append(P("9. Alicate — estratégia (onda 3)", "H1d"))
    story.append(
        P(
            "Existe estratégia. É outra linha, outra hora, outro anúncio. Modelo: Mundial 777 Professional Inox "
            "(~R$ 23,75). 522-C e Flex Morango/Rosa não abrem a busca profissional."
        )
    )
    story.append(
        bullets(
            [
                "Quando: frente Flash+PERL no ar, pelo menos 1 pedido, Flash já testado. Lote 10 un. Ads off nesse SKU.",
                "Manicure: 777 sozinho ou 777 + 3 Impala clássicas (Vinho, Nude, Tomate). Título com Mundial 777.",
                "Mulher: não puxar 777 no Ads. Se perguntar no chat se vem alicate: não; aponta o Flash.",
                "Preço: bundle 5 a R$ 79,90 fura o piso (~9% op.). Só ≥ ~R$ 86,90 ou corta para 777+3.",
                "Criativo próprio (1–2 vídeos, só manicure): inox, corte. Não reutiliza os 4 do Flash.",
                "Proibido: kit completo (777+palito+algodão+lixa+acetona+esmalte) e 777 no título do Flash.",
            ]
        )
    )
    story.append(
        P(
            "Ordem: Flash diferencia a unha → PERL o preço do frasco → 777 a cutelaria, se a frente já vender."
        )
    )

    story.append(P("10. Shopee — mesma estratégia de kit, outra operação", "H1d"))
    story.append(
        P(
            "Kit + Flash + PERL vale nos dois canais. Não copia título, preço nem calendário. "
            "Shopee só na fase 3 (20 reviews e 4,8 no ML). Até lá, canais.shopee ativo = false."
        )
    )
    story.append(
        tabela(
            ["", "Mercado Livre", "Shopee"],
            [
                td("Quando", "Agora (10+10)", "Depois da reputação no ML"),
                td("Taxa", "18%", "14% — recalcula piso"),
                td("Piso 15% Flash", "~R$ 38,79", "~R$ 36,60 (custo 25,99)"),
                td("Bolha", "Kit 3 ~R$ 22", "Dump + frete grátis, ainda mais"),
                td("Público", "Manicure pesa mais", "Mais impulso / mulher"),
                td("Ads", "Meta → link ML, R$ 10", "Shopee Ads no item; vertical 9:16"),
            ],
            [3.4 * cm, 6.4 * cm, 7.0 * cm],
        )
    )
    story.append(
        P(
            "Na Shopee o preço pode ficar um pouco abaixo do ML por causa da taxa, nunca na francesinha. "
            "Frete Xpress muda o CMV — montar 1 kit físico antes de usar o piso do ML."
        )
    )

    story.append(P("11. Ordem prática", "H1d"))
    story.append(
        bullets(
            [
                "Fase 0–1: publicar kit 3 + Flash R$ 44,90 (estoque 10) e PERL R$ 39,90 (estoque 10). Ads off. Chat em dia.",
                "Não igualar francesinha. Não abrir 777, acetona, palito/algodão/lixa no mesmo MLB.",
                "1º pedido vencedor: JUPAES R$ 64,90; CRZ-KIT-001; combo removedor só no copy do Flash se couber.",
                "Subir estoque da frente para 30. Caixa S20 conferida no kit físico.",
                "20 reviews + 4,8: 4 criativos Flash, dois conjuntos (mulher / manicure), R$ 10/dia, ACOS ≤ 20%.",
                "Guerra de preço: só PERL vs kit 4 perolado ao vivo.",
                "Shopee: mesmos SKUs, piso 14%, depois da fase 3 do ML.",
                "Onda 3: validar 777 (10 un, ≥ piso), anúncio e criativo separados.",
            ]
        )
    )

    story.append(P("12. Catálogo vs esta sessão", "H1d"))
    story.append(
        P(
            "A doutrina em catalogo/doutrina_guerra_impala.json ainda lista IMP-MIMO-003 (Carmed) como sku_entrada. "
            "Esta compilação registra a decisão de produto/criativo: extra = Flash Secante, sem Carmed na peça. "
            "IMP-FLASH-003 permanece proposto no pipeline (não cadastrar em produtos.json só para publicar agora, "
            "salvo decisão de trocar o extra do kit 3 no ar). BUNDLE-777 não sobe de prioridade."
        )
    )
    story.append(Spacer(1, 0.35 * cm))
    story.append(
        P(
            "Arquivo: docs/estrategias.pdf · regenerar: py -3 docs/gerar_estrategias_pdf.py (reportlab).",
            "Sm",
        )
    )

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(muted)
        canvas.drawString(1.6 * cm, 1.1 * cm, "Robô Markplaces · Estratégias Impala · Flash Secante")
        canvas.drawRightString(A4[0] - 1.6 * cm, 1.1 * cm, f"{hoje}  ·  {canvas.getPageNumber()}")
        canvas.restoreState()

    dest.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(dest),
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.8 * cm,
        title="Estratégias",
        author="Robô Markplaces",
    )
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return dest


if __name__ == "__main__":
    print(gerar())
