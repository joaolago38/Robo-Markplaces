# -*- coding: utf-8 -*-
"""
integracoes/masterprint/planilha_tabela_pedidos.py

Lê planilhas_ecommerce/TABELA DE PEDIDOS.XLSX (MA-MASTER Revenda 06)
focando em:
  - Filamentos 3D (famílias 23101–23106)
  - Pincel permanente / quadro branco (30904–30905)
  - Apagador (32801)

Gera catalogo/masterprint_tabela_pedidos.json + métricas Datadog.
"""
from __future__ import annotations

import logging
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar

logger = logging.getLogger("planilha_tabela_pedidos")

PLANILHA_DEFAULT = ROOT / "planilhas_ecommerce" / "TABELA DE PEDIDOS.XLSX"
CAT_OUT = ROOT / "catalogo" / "masterprint_tabela_pedidos.json"
SNAP_OUT = ROOT / "logs" / "masterprint_tabela_pedidos_ultima.json"

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# Famílias de interesse (código → linha/material)
_FAMILIAS = {
    "23101": ("filamento", "PLA"),
    "23102": ("filamento", "PETG"),
    "23103": ("filamento", "ABS"),
    "23104": ("filamento", "TPR"),
    "23105": ("filamento", "TPU"),
    "23106": ("filamento", "ASA"),
    "30904": ("escritorio", "pincel_permanente"),
    "30905": ("escritorio", "pincel_quadro_branco"),
    "32801": ("escritorio", "apagador"),
}


def _f(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or val == "":
            return default
        return float(str(val).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _cell_map(row: ET.Element) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in row.findall("m:c", _NS):
        ref = c.get("r") or ""
        col = re.sub(r"\d+", "", ref)
        is_el = c.find("m:is/m:t", _NS)
        v = c.find("m:v", _NS)
        if is_el is not None and is_el.text:
            out[col] = is_el.text
        elif v is not None and v.text is not None:
            out[col] = v.text
        else:
            out[col] = ""
    return out


def _linha_de_sku(sku: str) -> tuple[str, str] | None:
    for fam, meta in _FAMILIAS.items():
        if sku.startswith(fam):
            return meta
    return None


def _candidatos_sheet(z: zipfile.ZipFile) -> list[str]:
    """Resolve caminho(s) da worksheet no XLSX (layout Masterprint ou OOXML padrão)."""
    nomes = list(z.namelist())
    out: list[str] = []
    # Preferência: rels do workbook → Target relativo a xl/
    try:
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        for rel in rels:
            if "worksheet" not in (rel.get("Type") or ""):
                continue
            target = (rel.get("Target") or "").replace("\\", "/").lstrip("/")
            if not target:
                continue
            cand = target if target.startswith("xl/") else f"xl/{target}"
            if cand in nomes and cand not in out:
                out.append(cand)
    except Exception:
        pass
    for cand in (
        "xl/sheet1.xml",
        "xl/worksheets/sheet1.xml",
        "xl/worksheets/sheet.xml",
    ):
        if cand in nomes and cand not in out:
            out.append(cand)
    for n in nomes:
        low = n.lower().replace("\\", "/")
        if "/worksheets/sheet" in low and low.endswith(".xml") and n not in out:
            out.append(n)
        elif re.search(r"/sheet\d*\.xml$", low) and n not in out:
            out.append(n)
    return out


def _ler_sheet_rows(z: zipfile.ZipFile) -> list[ET.Element]:
    candidatos = _candidatos_sheet(z)
    erros: list[str] = []
    for cand in candidatos:
        try:
            root = ET.fromstring(z.read(cand))
            rows = root.findall(".//m:sheetData/m:row", _NS)
            if rows:
                return rows
            # Namespace às vezes ausente / diferente — fallback sem NS
            rows = root.findall(
                ".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"
            )
            if rows:
                return rows
            rows = root.findall(".//row")
            if rows:
                return rows
            erros.append(f"{cand}: sem rows")
        except Exception as exc:
            erros.append(f"{cand}: {exc}")
    amostra = ",".join(z.namelist()[:12])
    detalhe = "; ".join(erros[:3]) if erros else f"candidatos vazios; zip=[{amostra}]"
    raise FileNotFoundError(f"worksheet XML não encontrado no XLSX ({detalhe})")


def parse_tabela_pedidos(path: Path | None = None) -> dict[str, Any]:
    """
    Parse via zip/xml (openpyxl quebra no stylesheet deste xlsx).
    Retorna itens filtrados + agregados.
    """
    p = path or PLANILHA_DEFAULT
    if not p.is_file():
        return {"ok": False, "erro": f"planilha ausente: {p}", "itens": []}

    try:
        with zipfile.ZipFile(p) as z:
            rows = _ler_sheet_rows(z)
    except Exception as exc:
        return {"ok": False, "erro": str(exc), "itens": []}

    familia_atual = ""
    familia_nome = ""
    itens: list[dict[str, Any]] = []
    for row in rows:
        m = _cell_map(row)
        a = (m.get("A") or "").strip()
        b = (m.get("B") or "").strip()
        c = (m.get("C") or "").strip()
        if a.lower().startswith("fam") or a == "Família:":
            familia_atual = b
            familia_nome = c
            continue
        if not re.match(r"^\d{6,}$", a):
            continue
        meta = _linha_de_sku(a)
        if not meta:
            continue
        linha, material = meta
        preco = _f(m.get("I"))
        ipi = _f(m.get("J"))
        preco_ipi = _f(m.get("K"))
        if preco_ipi <= 0 and preco > 0:
            preco_ipi = round(preco * (1 + ipi / 100.0), 2) if ipi else preco
        itens.append(
            {
                "sku": a,
                "descricao": b,
                "familia": familia_atual or a[:5],
                "familia_nome": familia_nome,
                "linha": linha,
                "material": material,
                "categoria_fiscal": (m.get("G") or "").strip(),
                "preco_base_brl": round(preco, 2),
                "ipi_pct": round(ipi, 2),
                "custo_unitario_brl": round(preco_ipi, 2),
                "fonte": p.name,
            }
        )

    por_material: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"qtd": 0, "custo_medio": 0.0, "custo_min": 0.0, "custo_max": 0.0, "custos": []}
    )
    for it in itens:
        key = str(it["material"])
        bucket = por_material[key]
        bucket["qtd"] += 1
        bucket["custos"].append(float(it["custo_unitario_brl"]))
    for key, bucket in por_material.items():
        custos = bucket.pop("custos")
        bucket["custo_medio"] = round(sum(custos) / len(custos), 2) if custos else 0.0
        bucket["custo_min"] = round(min(custos), 2) if custos else 0.0
        bucket["custo_max"] = round(max(custos), 2) if custos else 0.0
        bucket["linha"] = "filamento" if key in {"PLA", "PETG", "ABS", "TPR", "TPU", "ASA"} else "escritorio"

    filamentos = [i for i in itens if i["linha"] == "filamento"]
    escritorio = [i for i in itens if i["linha"] == "escritorio"]
    return {
        "ok": True,
        "fonte": p.name,
        "tabela": "MA-MASTER - MATRIZ Revenda 06",
        "itens": itens,
        "filamentos": filamentos,
        "escritorio": escritorio,
        "por_material": dict(por_material),
        "totais": {
            "skus": len(itens),
            "filamentos": len(filamentos),
            "escritorio": len(escritorio),
            "custo_investido_filamentos": round(
                sum(float(i["custo_unitario_brl"]) for i in filamentos), 2
            ),
            "custo_investido_escritorio": round(
                sum(float(i["custo_unitario_brl"]) for i in escritorio), 2
            ),
        },
    }


def emitir_metricas_tabela_pedidos(snap: dict[str, Any] | None = None) -> dict[str, Any]:
    data = snap if snap and snap.get("ok") else parse_tabela_pedidos()
    if not data.get("ok"):
        incrementar("masterprint.tabela_pedidos_erro")
        return {"ok": False, "erro": data.get("erro")}

    totais = data.get("totais") or {}
    gauge("masterprint.tabela.skus", float(totais.get("skus") or 0))
    gauge("masterprint.tabela.filamentos_skus", float(totais.get("filamentos") or 0))
    gauge("masterprint.tabela.escritorio_skus", float(totais.get("escritorio") or 0))
    gauge(
        "masterprint.tabela.custo_investido_filamentos",
        float(totais.get("custo_investido_filamentos") or 0),
    )
    gauge(
        "masterprint.tabela.custo_investido_escritorio",
        float(totais.get("custo_investido_escritorio") or 0),
    )

    for material, bucket in (data.get("por_material") or {}).items():
        mat = re.sub(r"[^a-z0-9_]+", "_", str(material).lower())[:24] or "x"
        tags = [f"material:{mat}", f"linha:{bucket.get('linha') or 'x'}"]
        gauge("masterprint.tabela.skus_material", float(bucket.get("qtd") or 0), tags=tags)
        gauge("masterprint.tabela.custo_medio", float(bucket.get("custo_medio") or 0), tags=tags)
        gauge("masterprint.tabela.custo_min", float(bucket.get("custo_min") or 0), tags=tags)
        gauge("masterprint.tabela.custo_max", float(bucket.get("custo_max") or 0), tags=tags)

    incrementar("masterprint.tabela_pedidos_sync")
    return {"ok": True, **totais}


def sincronizar_tabela_pedidos(*, emitir_metricas: bool = True) -> dict[str, Any]:
    snap = parse_tabela_pedidos()
    if not snap.get("ok"):
        return snap
    ts = datetime.now(timezone.utc).isoformat()
    out_cat = {
        "timestamp": ts,
        "fonte": snap.get("fonte"),
        "tabela": snap.get("tabela"),
        "totais": snap.get("totais"),
        "por_material": snap.get("por_material"),
        "itens": snap.get("itens"),
    }
    escrever_json_atomico(CAT_OUT, out_cat)
    met = emitir_metricas_tabela_pedidos(snap) if emitir_metricas else {"ok": True, "skip": True}
    result = {
        "ok": True,
        "timestamp": ts,
        "totais": snap.get("totais"),
        "por_material": snap.get("por_material"),
        "metricas": met,
        "catalogo": str(CAT_OUT),
    }
    escrever_json_atomico(SNAP_OUT, result)
    return result


def carregar_tabela_pedidos_cache() -> dict[str, Any]:
    data = ler_json(CAT_OUT, default={})
    return data if isinstance(data, dict) else {}
