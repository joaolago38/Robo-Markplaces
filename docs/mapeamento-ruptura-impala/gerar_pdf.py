"""
Gera o PDF de mapeamento e o JSON com o processo completo
(kits, margem, caixas, fases, ruptura).

Uso (na raiz Robo-Markplaces):
  py -3 -m pip install reportlab
  py -3 docs/mapeamento-ruptura-impala/gerar_pdf.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent / "mapeamento-anuncios-ruptura-2o-cnpj.pdf"
PROCESSO_JSON = Path(__file__).resolve().parent / "processo_completo.json"
CAIXAS_PATH = ROOT / "catalogo" / "caixas_kits_impala.json"
TAXA_ML = 18.0
PISO_PCT = 15.0
FRENTE = ("IMP-MIMO-003", "IMP-PERL-004", "IMP-JUPAES-006")
CONGELADOS = ("IMP-MIMO-003", "IMP-JUPAES-006")


def _f(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _brl(val: float) -> str:
    return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def carregar_caixas() -> dict:
    if not CAIXAS_PATH.exists():
        return {}
    raw = json.loads(CAIXAS_PATH.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def carregar_kits() -> list[dict]:
    produtos = json.loads((ROOT / "catalogo" / "produtos.json").read_text(encoding="utf-8"))
    doutrina = json.loads(
        (ROOT / "catalogo" / "doutrina_guerra_impala.json").read_text(encoding="utf-8")
    )
    caixas = carregar_caixas()
    por_sku = caixas.get("por_sku") if isinstance(caixas.get("por_sku"), dict) else {}
    papéis = (doutrina.get("kits") or {}) if isinstance(doutrina, dict) else {}
    out: list[dict] = []
    for p in produtos:
        if not isinstance(p, dict):
            continue
        sku = str(p.get("sku") or "").strip().upper()
        if not sku.startswith("IMP-"):
            continue
        ml = p.get("canais", {}).get("mercadolivre") or {}
        preco = _f(ml.get("preco") or p.get("preco"))
        taxa = _f(ml.get("taxa_canal_pct"), TAXA_ML)
        custo = _f(p.get("custo_total"))
        liquida = preco * (1 - taxa / 100.0) if preco > 0 else 0.0
        lucro = liquida - custo
        margem = (100.0 * lucro / preco) if preco > 0 else 0.0
        denom = 1 - taxa / 100.0 - PISO_PCT / 100.0
        piso = round(custo / denom, 2) if denom > 0 and custo > 0 else 0.0
        fases = p.get("precos_por_fase") or {}
        cores = p.get("cores") or []
        nomes_cores = [
            str(c.get("nome") or "").strip()
            for c in cores
            if isinstance(c, dict) and str(c.get("nome") or "").strip() not in ("", "None")
        ]
        meta = papéis.get(sku) if isinstance(papéis.get(sku), dict) else {}
        mlb = str(ml.get("item_id") or p.get("item_id") or "")
        out.append(
            {
                "sku": sku,
                "nome": str(p.get("nome") or ""),
                "titulo": str(p.get("titulo_sugerido_ml") or ml.get("titulo_anuncio") or ""),
                "papel": str(meta.get("papel") or ("frente" if sku in FRENTE else "catalogo")),
                "arma": str(meta.get("arma") or "—"),
                "preco": preco,
                "custo": custo,
                "custo_esmaltes": _f(p.get("custo_esmaltes")),
                "custo_complemento": _f(p.get("custo_complemento")),
                "custo_embalagem": _f(p.get("custo_embalagem") or 0) + _f(p.get("custo_caixa") or 0),
                "frete": _f(p.get("frete_estimado")),
                "lucro": lucro,
                "margem_real": margem,
                "margem_trabalho": _f(p.get("margem_trabalho_pct")),
                "lucro_ref": _f(p.get("lucro_ref_ml")),
                "mercado": _f(p.get("preco_ml_mercado") or ml.get("preco_concorrente")),
                "piso": piso,
                "fase1": _f(fases.get("fase1"), preco),
                "fase2": _f(fases.get("fase2")),
                "fase3": _f(fases.get("fase3")),
                "mlb": mlb,
                "estoque": int(_f(ml.get("estoque") if mlb.startswith("MLB") and "PREENCHER" not in mlb.upper() else p.get("estoque_total"))),
                "valida_un": int(_f(p.get("valida_unidades") or 0)),
                "invest": _f(p.get("invest_validacao_reais")),
                "cores": nomes_cores,
                "acao_pos": str(p.get("acao_pos_validar") or ""),
                "segmento": str(p.get("segmento") or ""),
                "frente": sku in FRENTE,
                "congelado": sku in CONGELADOS,
                "acima_piso": margem >= PISO_PCT - 0.05,
                "peso_g": int(_f(p.get("peso_gramas"))),
                "caixa_codigo": str(p.get("caixa_caixasnet") or ""),
                "caixa": por_sku.get(sku) if isinstance(por_sku.get(sku), dict) else {},
            }
        )
    ordem = {s: i for i, s in enumerate(FRENTE)}
    out.sort(key=lambda r: (0 if r["frente"] else 1, ordem.get(r["sku"], 99), r["sku"]))
    return out


def _kit_dump(k: dict) -> dict:
    cx = k.get("caixa") if isinstance(k.get("caixa"), dict) else {}
    return {
        "sku": k["sku"],
        "nome": k["nome"],
        "titulo_ml": k["titulo"],
        "papel": k["papel"],
        "arma": k["arma"],
        "frente": k["frente"],
        "preco_congelado": k["congelado"],
        "mlb": k["mlb"] or "MLB_PREENCHER",
        "preco_fase1": round(k["preco"], 2),
        "preco_fase2": round(k["fase2"], 2),
        "preco_fase3": round(k["fase3"], 2),
        "custo_total": round(k["custo"], 2),
        "custo_esmaltes": round(k["custo_esmaltes"], 2),
        "custo_complemento": round(k["custo_complemento"], 2),
        "custo_embalagem_caixa": round(k["custo_embalagem"], 2),
        "frete_estimado": round(k["frete"], 2),
        "lucro_liquido": round(k["lucro"], 2),
        "margem_real_pct": round(k["margem_real"], 1),
        "margem_trabalho_pct_planilha": round(k["margem_trabalho"], 1),
        "lucro_ref_ml_planilha": round(k["lucro_ref"], 2),
        "piso_15_pct": round(k["piso"], 2),
        "preco_ml_mercado": round(k["mercado"], 2) if k["mercado"] else None,
        "acima_piso": k["acima_piso"],
        "estoque_json": k["estoque"],
        "valida_unidades": k["valida_un"],
        "invest_validacao_reais": round(k["invest"], 2),
        "cores": k["cores"],
        "acao_pos_validar": k["acao_pos"],
        "segmento": k["segmento"],
        "peso_gramas": k["peso_g"],
        "caixa": {
            "codigo": k.get("caixa_codigo") or cx.get("codigo") or "",
            "modelo": cx.get("modelo") or "",
            "cm": cx.get("cm") or "",
            "conteudo": cx.get("conteudo") or "",
            "layout": cx.get("layout") or "",
            "status": cx.get("status") or "",
            "cabe": cx.get("cabe"),
        },
    }


def montar_processo_completo(kits: list[dict] | None = None) -> dict:
    kits = kits if kits is not None else carregar_kits()
    doutrina = json.loads(
        (ROOT / "catalogo" / "doutrina_guerra_impala.json").read_text(encoding="utf-8")
    )
    caixas = carregar_caixas()
    frente = [_kit_dump(k) for k in kits if k["frente"]]
    catalogo = [_kit_dump(k) for k in kits if not k["frente"]]
    return {
        "gerado_em": date.today().isoformat(),
        "fonte": [
            "catalogo/produtos.json",
            "catalogo/doutrina_guerra_impala.json",
            "catalogo/caixas_kits_impala.json",
            "integracoes/empresa/ponto_ruptura_segundo_cnpj.py",
            "integracoes/ml/tipo_anuncio_ml.py",
        ],
        "conta": {
            "seller_id": "1651424153",
            "cnpj_impala": "52.668.583/0001-27",
            "cnae_impala": "4772500",
            "cnpj_masterprint": "23.811.261/0001-97",
            "segundo_cnpj": "só opera depois do veredito liberado",
            "anuncios_impala_live": 0,
            "vendas_completadas": 0,
            "reputacao_cor": "sem cor (0 vendas)",
        },
        "margem": {
            "taxa_ml_pct": TAXA_ML,
            "piso_guerra_pct": PISO_PCT,
            "formula_real": "(preco * 0.82 - custo_total) / preco",
            "nota": "margem_trabalho_pct no JSON é planilha; o robô usa margem real",
        },
        "frente_guerra": frente,
        "catalogo_fora_da_frente": catalogo,
        "caixas": caixas,
        "doutrina": doutrina,
        "tipo_anuncio": {
            "frente": "Premium (gold_pro). JSON assume taxa 18%.",
            "classico": "gold_special — não igualar preço Premium vs Clássico",
            "full": "logistic_type fulfillment — não é Mercado Líder (power_seller)",
            "taxa_estimada_pct": {"gold_special": 12.0, "gold_pro": 18.0, "gold_premium": 18.0},
        },
        "ruptura_segundo_cnpj": {
            "kits_validacao": ["IMP-MIMO-003", "IMP-PERL-004"],
            "fora": ["IMP-SORT-006"],
            "estoque_min": 30,
            "avaliacoes_min": 20,
            "avaliacoes_aproximando": 10,
            "nota_min": 4.8,
            "acos_max_pct": 20,
            "vereditos": ["ainda_nao", "aproximando", "liberado"],
            "checks": [
                {"id": "avaliacoes", "minimo": ">=20 com anúncio foco"},
                {"id": "nota", "minimo": ">=4,8 e >=1 review no foco"},
                {"id": "mlb", "minimo": "MLB reais MIMO e PERL"},
                {"id": "estoque", "minimo": ">=30 un. em cada kit de validação"},
                {"id": "pedidos", "minimo": ">=1 pedido próprio Impala"},
                {"id": "ads_acos", "minimo": "<=20% se snapshot Ads visível"},
                {"id": "claims", "minimo": "<2 se API visível"},
                {"id": "anuncios_foco", "minimo": ">=1 anúncio kit ativo"},
                {"id": "saude_conta", "minimo": "sem laranja/vermelho; taxas <5%"},
            ],
            "cnae_preparacao": {
                "impala_cosmetico": "4772-5/00",
                "masterprint_informatica": "4751-2/01",
                "masterprint_resinas": "4689-3/02",
                "masterprint_papelaria": "4761-0/03",
            },
        },
        "outra_marca_mesmo_cnpj": {
            "agente": "ponto_ruptura_outra_marca.py",
            "exige": "Impala liberado + doutrina fase 5 + anúncio foco + radar >=5 outras marcas",
        },
        "monitores": [
            {"agente": "resumo_conta_ml", "quando": "09:00 BRT"},
            {"agente": "monitor_ml", "quando": "a cada 2 h"},
            {"agente": "monitor_sem_venda_ml", "quando": "10:00 BRT"},
            {"agente": "monitor_concorrentes + radar + golpe", "quando": "a cada 4 h"},
            {"agente": "ads_gatilho", "quando": "08:00 BRT"},
            {"agente": "operacao_24h / repricing", "quando": "a cada 2 h"},
            {"agente": "ponto_ruptura_segundo_cnpj", "quando": "08:05 BRT"},
        ],
        "nao_fazer": doutrina.get("nao_fazer_global") or [],
    }


def salvar_processo_completo(kits: list[dict] | None = None) -> Path:
    dest = PROCESSO_JSON
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(montar_processo_completo(kits), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return dest


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


def gerar(caminho: Path | None = None) -> tuple[Path, Path]:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        KeepTogether,
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
    kits = carregar_kits()
    json_path = salvar_processo_completo(kits)
    frente = [k for k in kits if k["frente"]]
    catalogo = [k for k in kits if not k["frente"]]
    font, font_b = _fontes()
    hoje = date.today().strftime("%d/%m/%Y")

    ink = colors.HexColor("#1a1a1a")
    muted = colors.HexColor("#5c5c5c")
    line = colors.HexColor("#d0d0d0")
    head_bg = colors.HexColor("#222222")
    alt = colors.HexColor("#f4f4f4")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("CapaH", fontName=font_b, fontSize=20, leading=26, textColor=ink, spaceAfter=8))
    styles.add(ParagraphStyle("CapaS", fontName=font, fontSize=11, leading=15, textColor=muted, spaceAfter=6))
    styles.add(ParagraphStyle("H1d", fontName=font_b, fontSize=14, leading=18, textColor=ink, spaceBefore=14, spaceAfter=8))
    styles.add(ParagraphStyle("H2d", fontName=font_b, fontSize=11.5, leading=15, textColor=ink, spaceBefore=10, spaceAfter=6))
    styles.add(ParagraphStyle("Bd", fontName=font, fontSize=9.5, leading=13, textColor=ink, alignment=TA_JUSTIFY, spaceAfter=6))
    styles.add(ParagraphStyle("Sm", fontName=font, fontSize=8, leading=11, textColor=muted, spaceAfter=4))
    styles.add(ParagraphStyle("Th", fontName=font_b, fontSize=7.5, leading=10, textColor=colors.white, alignment=TA_CENTER))
    styles.add(ParagraphStyle("Td", fontName=font, fontSize=7.5, leading=10, textColor=ink, alignment=TA_LEFT))
    styles.add(ParagraphStyle("TdC", fontName=font, fontSize=7.5, leading=10, textColor=ink, alignment=TA_CENTER))
    styles.add(ParagraphStyle("KitN", fontName=font_b, fontSize=10.5, leading=14, textColor=ink, spaceAfter=2))
    styles.add(ParagraphStyle("BulletBody", fontName=font, fontSize=9.5, leading=13, textColor=ink))

    def P(text: str, style="Bd"):
        return Paragraph(text.replace("\n", "<br/>"), styles[style])

    def th(*cells):
        return [Paragraph(c, styles["Th"]) for c in cells]

    def td(*cells, center=False):
        st = styles["TdC"] if center else styles["Td"]
        return [Paragraph(str(c), st) for c in cells]

    def tabela(header, rows, widths):
        data = [th(*header)] + rows
        t = Table(data, colWidths=widths, repeatRows=1)
        cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), head_bg),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), font_b),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.3, line),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ]
        for i in range(1, len(data)):
            if i % 2 == 0:
                cmds.append(("BACKGROUND", (0, i), (-1, i), alt))
        t.setStyle(TableStyle(cmds))
        return t

    def bullets(items: list[str]):
        return ListFlowable(
            [ListItem(Paragraph(x, styles["BulletBody"]), leftIndent=8, bulletColor=ink) for x in items],
            bulletType="bullet",
            start="•",
            leftIndent=12,
            bulletFontName=font,
            bulletFontSize=9,
        )

    story = []
    story.append(P("Robô Markplaces · Impala", "CapaS"))
    story.append(P("Mapeamento: anúncios no ar até o 2º CNPJ", "CapaH"))
    story.append(
        P(
            f"Gerado em {hoje} a partir de catalogo/produtos.json, "
            "catalogo/doutrina_guerra_impala.json, catalogo/caixas_kits_impala.json e "
            "integracoes/empresa/ponto_ruptura_segundo_cnpj.py. "
            "Taxa ML 18%. Margem real = (preço × 0,82 − custo_total) / preço. "
            "Piso de guerra 15%. Processo completo também em processo_completo.json."
        )
    )
    story.append(
        P(
            "CNPJ Impala 52.668.583/0001-27 · seller 1651424153 · "
            "CNAE cosmético 4772-5/00. 2º CNPJ (Masterprint) 23.811.261/0001-97 — "
            "só opera depois do veredito <b>liberado</b>.",
            "Sm",
        )
    )

    story.append(P("1. Como usar este mapa", "H1d"))
    story.append(
        P(
            "Imprima ou abra ao lado do Telegram quando o MIMO/PERL estiver no ar. "
            "Cada bloco é o que o robô já mede ou o que você confere no painel. "
            "Não publica anúncio sozinho. Depois de criar o item com seller_sku "
            "do kit, rode <b>scripts/preencher_item_id_ml.py --aplicar</b>."
        )
    )

    story.append(P("2. Verificar no dia em que o anúncio existir", "H1d"))
    story.append(P("2.1 Ligação catálogo ↔ ML", "H2d"))
    story.append(
        bullets(
            [
                "seller_sku no anúncio = SKU do JSON (IMP-MIMO-003, IMP-PERL-004, IMP-JUPAES-006).",
                "item_id gravado em produtos.json → canais.mercadolivre (não deixar MLB_PREENCHER).",
                "Título MIMO: Kit 3 Esmaltes Impala Mimo + Carmed Manicure (sem francesinha).",
                "Tipo: Premium (gold_pro). JSON já assume taxa 18%. Clássico some sem ads/cor.",
                "Estoque no anúncio: 10 (validação) depois 30 (piso de ruptura). Ideal 60.",
                "Categoria MLB1430. Preço fase 1 no ar: MIMO 44,90 · PERL 39,90 · JUPAES 64,90.",
            ]
        )
    )
    story.append(P("2.2 Sinais que o robô passa a sentir sozinho", "H2d"))
    story.append(
        tabela(
            ["Sinal", "Onde", "Quando", "O que conferir"],
            [
                td("Anúncios foco 0 → 1+", "resumo_conta / Datadog ml.saude.anuncios_ativos", "09:00 BRT", "catalogo_foco_vazio some"),
                td("Exposição Premium/Clássico", "resumo_conta Telegram", "09:00 BRT", "MIMO deve contar em Premium"),
                td("Integridade GET /items", "monitor_ml + integridade", "a cada 2 h", "preço, estoque, sold_quantity, título"),
                td("Visitas 7d / 30d", "monitor_ml · /visits do NOSSO item", "a cada 2 h", "0 visita = não apareceu (tipo/ads), não ‘produto ruim’"),
                td("Sem venda 30d", "monitor_sem_venda", "10:00 BRT", "≥20 visitas sem pedido → listing; MIMO não baixa a R$ 22"),
                td("Perguntas / chat", "resumo_conta + chat_ml", "comercial", "responder no ciclo; converte quem já entrou"),
                td("Menor preço mesma prateleira", "monitor_ml / repricing", "2 h / 24h", "Premium vs Premium. Alerta ‘não igualar’ se o barato for Clássico"),
                td("Golpe de guerra", "golpe_guerra no radar", "monitor 4 h", "MIMO congelado. Só PERL iguala na faixa"),
            ],
            [3.4 * cm, 4.4 * cm, 2.6 * cm, 6.4 * cm],
        )
    )
    story.append(
        P(
            "Venda do rival a R$ 22 continua cega (sold_quantity/reviews 403). "
            "Busca /sites/MLB/search costuma 403 — não trate cache velho como rival ao vivo.",
            "Sm",
        )
    )

    story.append(P("2.3 Funil de 7 e 30 dias (quando estiver no ar)", "H2d"))
    story.append(
        tabela(
            ["Janela", "Se 0 visita", "Se visita e 0 pedido", "Se 1+ pedido"],
            [
                td("7 dias", "Conferir Premium, título, estoque, anúncio ativo", "Fotos/descrição/perguntas. Preço firme no MIMO", "PERL já pode estar no ar; JUPAES só depois"),
                td("30 dias", "republicar_ou_ads (ads ainda travados até 20 reviews)", "Não copiar francesinha. Piso MIMO R$ 41,99", "Conta para ruptura (pedido próprio no foco)"),
            ],
            [2.4 * cm, 4.8 * cm, 5.2 * cm, 4.4 * cm],
        )
    )

    story.append(PageBreak())
    story.append(P("3. Frente de guerra — kits (preço e margem)", "H1d"))
    story.append(
        P(
            "Só estes três entram na doutrina. Margem <b>real</b> é a que o robô usa "
            "(taxa 18% + custo com frete). Margem <b>trabalho</b> é planilha — no PERL "
            "42,8% não é caixa. Lucro líquido = preço × 0,82 − custo_total."
        )
    )

    for k in frente:
        cores = ", ".join(k["cores"]) if k["cores"] else "—"
        bloco = [
            P(f"{k['sku']} · {k['nome']}", "KitN"),
            P(
                f"Papel <b>{k['papel']}</b> · arma <b>{k['arma']}</b>"
                + (" · preço congelado" if k["congelado"] else " · único que iguala na faixa")
                + f" · MLB agora: {k['mlb'] or '—'}",
                "Sm",
            ),
            tabela(
                ["Preço fase 1", "Custo total", "Lucro líq.", "Margem real", "Piso 15%", "Trabalho JSON", "Ref. mercado"],
                [
                    td(
                        _brl(k["preco"]),
                        _brl(k["custo"]),
                        _brl(k["lucro"]),
                        f"{k['margem_real']:.1f}%",
                        _brl(k["piso"]),
                        f"{k['margem_trabalho']:.1f}%",
                        _brl(k["mercado"]) if k["mercado"] else "—",
                        center=True,
                    )
                ],
                [2.4 * cm, 2.4 * cm, 2.3 * cm, 2.4 * cm, 2.3 * cm, 2.5 * cm, 2.5 * cm],
            ),
            Spacer(1, 0.15 * cm),
            P(
                f"CMV: esmaltes {_brl(k['custo_esmaltes'])} + complemento {_brl(k['custo_complemento'])} "
                f"+ embalagem/caixa {_brl(k['custo_embalagem'])} + frete {_brl(k['frete'])}. "
                f"Fases 2/3: {_brl(k['fase2'])} / {_brl(k['fase3'])} (depois de validar, não na entrada). "
                f"Cores: {cores}. "
                f"Caixa: {k.get('caixa_codigo') or '—'} · {k.get('peso_g') or 0} g"
                + (
                    f" · {(k.get('caixa') or {}).get('layout')}"
                    if (k.get("caixa") or {}).get("layout")
                    else ""
                )
                + ".",
                "Sm",
            ),
        ]
        if k["valida_un"]:
            bloco.append(
                P(
                    f"Validação: {k['valida_un']} un. · CMV lote {_brl(k['invest'] or k['custo'] * k['valida_un'])}. "
                    + (k["acao_pos"] or ""),
                    "Sm",
                )
            )
        if k["titulo"]:
            bloco.append(P(f"Título ML: {k['titulo']}", "Sm"))
        story.append(KeepTogether(bloco + [Spacer(1, 0.25 * cm)]))

    story.append(P("Regras de preço da frente", "H2d"))
    story.append(
        bullets(
            [
                "MIMO: diferenciar (Carmed). Não igualar francesinha/tratamento. Não descer de R$ 41,99.",
                "PERL: igualar só kit 4 perolado ao vivo, mesma prateleira, gap ≥ 3% e preço ≥ R$ 39,15.",
                "JUPAES: listing; publicar só após 1º pedido vencedor de MIMO ou PERL. Preço firme R$ 64,90.",
                "Ads: off até 20 avaliações, nota 4,8, MLB da frente e ACOS ≤ 20%. Budget inicial R$ 10/dia.",
                "Outros canais (Shopee/Magalu/Amazon): só a partir da fase 3; recalcular piso pela taxa do canal.",
            ]
        )
    )

    story.append(P("3.1 Caixas de envio (cm e código)", "H2d"))
    story.append(
        P(
            "Dois modelos já usados no catálogo (família CaixasNet). "
            "S20 16×11×10 cm para kits 3–8. S03 31×20×11,5 cm para kits 10–30. "
            "Frasco Impala 7,5 ml estimado em 3,4×3,4×8,2 cm (com tampa) — "
            "montar 1 kit físico antes de comprar caixa em quantidade. "
            "POV-008 (8 frascos) fica justo no S20."
        )
    )
    rows_cx = []
    for k in kits:
        cx = k.get("caixa") if isinstance(k.get("caixa"), dict) else {}
        rows_cx.append(
            td(
                k["sku"],
                cx.get("codigo") or k.get("caixa_codigo") or "—",
                cx.get("cm") or "—",
                f"{k.get('peso_g') or 0} g",
                (cx.get("conteudo") or "—")[:36],
                "validar" if "validar" in str(cx.get("status") or "") else ("ok" if cx else "—"),
            )
        )
    story.append(
        tabela(
            ["SKU", "Código", "cm", "Peso", "Conteúdo", "Status"],
            rows_cx,
            [3.0 * cm, 3.4 * cm, 2.6 * cm, 1.6 * cm, 4.4 * cm, 1.8 * cm],
        )
    )
    story.append(
        P(
            "No anúncio ML: dimensões internas do modelo + peso_gramas do JSON. "
            "Definição: catalogo/caixas_kits_impala.json (gravada também no processo_completo.json).",
            "Sm",
        )
    )

    story.append(P("4. Catálogo Impala fora da frente (não confundir)", "H1d"))
    story.append(
        P(
            "Estão no produtos.json mas <b>não</b> são guerra nem ruptura. "
            "Kit 15 e sortidos grandes furam margem real. SORT-006 (~8%) fica para depois."
        )
    )
    rows_cat = []
    for k in catalogo:
        ver = "ok ≥15%" if k["acima_piso"] else "abaixo do piso / não lançar"
        rows_cat.append(
            td(
                k["sku"],
                k["nome"][:42],
                _brl(k["preco"]),
                _brl(k["custo"]),
                f"{k['margem_real']:.1f}%",
                ver,
            )
        )
    story.append(
        tabela(
            ["SKU", "Nome", "Preço", "Custo", "Margem real", "Uso"],
            rows_cat,
            [2.8 * cm, 5.6 * cm, 2.0 * cm, 2.0 * cm, 2.2 * cm, 3.2 * cm],
        )
    )

    story.append(PageBreak())
    story.append(P("5. Fases da doutrina (0 → 5)", "H1d"))
    story.append(
        P(
            "A fase sobe com fato no ML (anúncio, pedido, reviews, estoque, radar), "
            "não com data. Agentes listados são quem lê aquele degrau."
        )
    )
    fases = [
        (
            "0 · Abrir frente",
            "Publicar MIMO R$ 44,90 Premium, título Carmed, estoque 10 depois 30. "
            "SKU no anúncio. Preencher MLB no JSON.",
            "radar_diferencial, monitor_concorrentes, contrato_impulso, ads_gatilho (fail-closed)",
            "MLB MIMO · anúncios_ativos ≥ 1 · visitas começam a existir",
        ),
        (
            "1 · No ar",
            "PERL no mesmo ciclo a R$ 39,90. Ads off. Chat/perguntas em dia. MIMO congelado.",
            "golpe_guerra, monitor_concorrentes, resumo_conta_ml",
            "Dois MLB (MIMO+PERL) · Premium nos dois · estoque validação",
        ),
        (
            "2 · Primeiro pedido",
            "Com 1 pedido vencedor no foco: publicar JUPAES R$ 64,90. Combo removedor no copy.",
            "esmaltes_operacao, promocoes_manicures, crescimento",
            "Pedido próprio Impala (não bolsa/legado) · JUPAES só então",
        ),
        (
            "3 · Ads",
            "Ligar Product Ads só com 20 reviews, nota 4,8, MLB da frente, ACOS ≤ 20%. R$ 10/dia.",
            "ads_gatilho, contrato_impulso",
            "ads_gatilho decisão ≠ bloquear · ACOS no teto",
        ),
        (
            "4 · Guerra de preço",
            "Só PERL iguala se rival kit 4 perolado ao vivo, mesma prateleira, gap ≥ 3%, ≥ piso 15%.",
            "golpe_guerra, radar_diferencial, repricing_impala",
            "fonte_rival = ao_vivo · não cache STALE · não francesinha",
        ),
        (
            "5 · Ruptura",
            "Frente viva, reviews, estoque 30+, radar não cego. Aí 2º CNPJ / outra marca.",
            "ponto_ruptura_outra_marca, ponto_ruptura_segundo_cnpj",
            "veredito liberado nos dois agentes",
        ),
    ]
    story.append(
        tabela(
            ["Fase", "Fazer", "Agentes", "Verificar quando houver anúncio"],
            [td(a, b, c, d) for a, b, c, d in fases],
            [2.6 * cm, 5.0 * cm, 4.0 * cm, 5.2 * cm],
        )
    )
    story.append(P("Não fazer (global)", "H2d"))
    story.append(
        bullets(
            [
                "Igualar francesinha/tratamento ou kit 10/15 no prejuízo.",
                "Ligar Ads sem MLB da frente.",
                "Publicar JUPAES antes do 1º pedido.",
                "Baixar MIMO abaixo de R$ 41,99.",
                "Tratar cache STALE como rival ao vivo.",
                "Publicar Impala em Shopee/Magalu/Amazon antes da fase 3.",
                "Copiar preço do ML para outro canal sem recalcular o piso pela taxa.",
                "Confundir Mercado Líder (power_seller) com Full (logistic_type fulfillment).",
            ]
        )
    )

    story.append(P("6. Ponto de ruptura — 2º CNPJ (Masterprint)", "H1d"))
    story.append(
        P(
            "Código: integracoes/empresa/ponto_ruptura_segundo_cnpj.py. "
            "Kits de validação com margem ≥ piso: <b>IMP-MIMO-003</b> e <b>IMP-PERL-004</b> "
            "(SORT-006 fora). Estoque mínimo 30. Avaliações 20 (aproximando em 10, com anúncio foco). "
            "Nota 4,8. ACOS máximo 20%."
        )
    )
    story.append(
        P(
            "Vereditos: <b>ainda_nao</b> — Impala não passou; "
            "<b>aproximando</b> — há anúncio foco E (≥10 reviews da conta no foco OU MLB+estoque+maioria dos checks); "
            "<b>liberado</b> — todos os checks ok → segundo CNPJ pode entrar em ação."
        )
    )
    checks_2 = [
        ("avaliacoes", "Avaliações Impala com anúncio foco", "≥ 20", "Reviews de bolsa/legado não contam"),
        ("nota", "Nota média (≥1 review no foco)", "≥ 4,8", "Sem review no foco = não ok"),
        ("mlb", "MLB MIMO-003 e PERL-004", "ambos MLB reais", "MLB_PREENCHER não vale"),
        ("estoque", "Estoque nos dois kits", "≥ 30 un. cada", "Estoque do anúncio ML, não só JSON"),
        ("pedidos", "Pedido próprio Impala", "≥ 1", "Margem 24h ou venda da conta só com foco no ar"),
        ("ads_acos", "ACOS ≤ teto (snapshot Ads visível)", "≤ 20%", "Sem snapshot = n/d (não libera)"),
        ("claims", "Claims baixos (API visível)", "< 2", "API claims pode estar indisponível neste app"),
        ("anuncios_foco", "Há anúncio Impala (kit) ativo", "≥ 1", "Filtro de foco; bolsas ignoradas"),
        ("saude_conta", "Reputação", "sem laranja/vermelho; atraso/cancel/claims < 5%", "Sem cor no início passa; 10 vendas dão cor"),
    ]
    story.append(
        tabela(
            ["Check", "O que é", "Mínimo", "Quando tiver anúncio"],
            [td(*row) for row in checks_2],
            [2.6 * cm, 4.4 * cm, 4.2 * cm, 5.6 * cm],
        )
    )

    story.append(P("Preparação CNAE / KYC (pode fazer agora, sem esperar venda)", "H2d"))
    story.append(
        tabela(
            ["Item", "Mínimo", "Quem"],
            [
                td("CNAE cosmético neste CNPJ Impala", "4772-5/00 (4772500)", "Já ok no briefing"),
                td("Masterprint informática / filamento", "4751-2/01", "2º CNPJ"),
                td("Masterprint resinas / PETG", "4689-3/02", "2º CNPJ"),
                td("Masterprint papelaria / apagador", "4761-0/03", "2º CNPJ"),
                td("Seller ML do CNPJ 23.811.261/0001-97", "preenchido (KYC)", "Não usar o mesmo seller Impala"),
                td("Sellers Impala e Masterprint distintos", "IDs diferentes", "Evitar conta ambígua"),
            ],
            [6.5 * cm, 5.5 * cm, 4.8 * cm],
        )
    )
    story.append(
        P(
            "Telegram/Datadog: ponto_ruptura_segundo_cnpj (08:05 BRT). "
            "Não publicar anúncio automático. Não trocar de CNPJ antes do liberado.",
            "Sm",
        )
    )

    story.append(P("7. Outra marca no mesmo CNPJ (não é o 2º CNPJ)", "H1d"))
    story.append(
        P(
            "ponto_ruptura_outra_marca.py — Anita etc. no mesmo CNPJ Impala. "
            "Exige Impala já liberado + doutrina fase 5 + anúncio foco + radar com ≥5 anúncios de outras marcas. "
            "Radar cego (busca 403) impede ‘aproximando’ de verdade."
        )
    )
    story.append(
        tabela(
            ["Check", "Mínimo"],
            [
                td("Impala passou na checklist (reviews/MLB/estoque/pedido)", "veredito liberado do 2º CNPJ"),
                td("Doutrina guerra fase 5", "frente viva + reviews + estoque 30+ + radar não cego"),
                td("Anúncio Impala ativo no ML", "≥ 1"),
                td("CNPJ identificado no ML", "seller_id 1651424153"),
                td("CNAE 4772500 neste CNPJ", "ok"),
                td("Amostra ML para ranquear marcas", "≥ 5 anúncios de outras"),
                td("Marca candidata (não Impala)", "top1 elegível (ex.: Anita)"),
            ],
            [10.5 * cm, 6.3 * cm],
        )
    )

    story.append(P("8. Cron dos monitores (não estão no orquestrador 30 min)", "H1d"))
    story.append(
        tabela(
            ["Agente", "Quando", "Papel neste mapa"],
            [
                td("resumo_conta_ml", "todo dia 09:00 BRT", "Foco, Premium/Clássico, reputação, perguntas"),
                td("monitor_ml", "a cada 2 h", "Visitas, concorrente mesma prateleira, integridade"),
                td("monitor_sem_venda_ml", "todo dia 10:00 BRT", "30d sem pedido nos NOSSOS anúncios"),
                td("monitor_concorrentes + radar + golpe", "a cada 4 h", "Francesinha ≠ MIMO; PERL na faixa"),
                td("ads_gatilho", "todo dia 08:00 BRT", "Fail-closed até 20 reviews / nota 4,8 / MLB"),
                td("operacao_24h / repricing", "a cada 2 h (live na rotina de segurança)", "PERL pode mexer preço; MIMO congelado"),
                td("ponto_ruptura_segundo_cnpj", "todo dia 08:05 BRT", "Veredito ainda_nao / aproximando / liberado"),
            ],
            [4.8 * cm, 4.6 * cm, 7.4 * cm],
        )
    )

    story.append(P("9. Ordem prática no dia do ar", "H1d"))
    story.append(
        bullets(
            [
                "Publicar MIMO Premium R$ 44,90, estoque 10, seller_sku IMP-MIMO-003.",
                "preencher_item_id_ml.py --aplicar. Conferir Telegram 09:00: 1 ativo no foco, Exposição Premium.",
                "PERL no mesmo ciclo R$ 39,90. Não ligar Ads. Responder perguntas.",
                "7d: ler visitas. Zero → tipo/título, não cortar preço. Visita sem compra → listing.",
                "1º pedido no foco → JUPAES R$ 64,90. Subir estoque MIMO/PERL para 30 (depois 60).",
                "20 reviews + nota 4,8 → contrato de impulso / ads R$ 10. ACOS ≤ 20%.",
                "Guerra: só PERL vs kit 4 ao vivo. Radar francesinha = ignorar.",
                "Checks da secção 6 todos ok → 2º CNPJ Masterprint. Até lá, CNAE/KYC do 2º já pode estar pronto.",
            ]
        )
    )
    story.append(Spacer(1, 0.4 * cm))
    story.append(
        P(
            "Regenerar PDF + JSON: py -3 docs/mapeamento-ruptura-impala/gerar_pdf.py "
            "(depende de reportlab). Números de kit e caixa vêm do catálogo na hora da geração.",
            "Sm",
        )
    )

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(muted)
        canvas.drawString(1.6 * cm, 1.1 * cm, "Robô Markplaces · Impala · mapeamento até 2º CNPJ")
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
        title="Mapeamento anúncios Impala até 2º CNPJ",
        author="Robô Markplaces",
    )
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return dest, json_path


if __name__ == "__main__":
    pdf_path, json_path = gerar()
    print(pdf_path)
    print(json_path)
