"""
integracoes/esmaltes/migracao_marcas.py
Estrutura operacional Impala → Anita → demais marcas, com trilha paralela
do segundo CNPJ (Masterprint). Não publica anúncio.

A saúde de vendas Impala é o gate de tudo. Conta laranja/vermelha ou
taxa ≥5% congela a fila. Esmalte nunca migra para o CNPJ Masterprint.
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import ler_json
from core.config import ROOT
from core.datadog_metrics import gauge
from integracoes.empresa.ponto_ruptura_segundo_cnpj import _f, _i

logger = logging.getLogger("migracao_marcas")

CATALOGO_PATH = ROOT / "catalogo" / "migracao_marcas_esmalte.json"

_FASE_NUM = {"F0": 0.0, "F1": 1.0, "F1b": 1.5, "F2": 2.0}


def carregar_catalogo() -> dict[str, Any]:
    raw = ler_json(CATALOGO_PATH, default={})
    return raw if isinstance(raw, dict) else {}


def _check_ok(checks: list[Any], cid: str) -> bool:
    for c in checks or []:
        if isinstance(c, dict) and str(c.get("id") or "") == cid:
            return bool(c.get("ok"))
    return False


def _saude_conta_ok(ruptura_impala: dict[str, Any]) -> bool:
    checks = ruptura_impala.get("checks") if isinstance(ruptura_impala, dict) else []
    if any(isinstance(c, dict) and str(c.get("id") or "") == "saude_conta" for c in (checks or [])):
        return _check_ok(list(checks or []), "saude_conta")
    sinais = (ruptura_impala or {}).get("sinais") if isinstance(ruptura_impala, dict) else {}
    sinais = sinais if isinstance(sinais, dict) else {}
    from integracoes.empresa.ponto_ruptura_segundo_cnpj import _saude_conta_ok as _ok

    ok, _ = _ok(
        cor=str(sinais.get("reputacao_cor") or ""),
        atraso_rate=_f(sinais.get("atraso_rate")),
        cancelamentos_rate=_f(sinais.get("cancelamentos_rate")),
        claims_rate=_f(sinais.get("claims_rate")),
    )
    return ok


def _cnpj2_status(cnae: dict[str, Any] | None, impala_liberado: bool) -> dict[str, Any]:
    cnae = cnae if isinstance(cnae, dict) else {}
    pronto = bool(cnae.get("pronto"))
    gaps = list(cnae.get("gaps") or [])
    seller = str(cnae.get("seller_masterprint") or "").strip()
    if pronto and impala_liberado:
        veredito = "liberado_operar"
    elif pronto and not impala_liberado:
        veredito = "pronto_aguardar_impala"
    else:
        veredito = "preparar"
    return {
        "veredito": veredito,
        "pronto": pronto,
        "seller_preenchido": bool(seller),
        "gaps_n": len(gaps),
        "gap_ids": [str(g.get("id") or "") for g in gaps if isinstance(g, dict)],
        "pode_operar": pronto and impala_liberado,
        "nunca_esmalte": True,
    }


def _proxima_marca_fila(
    catalogo: dict[str, Any],
    candidatas: list[dict[str, Any]],
    *,
    pular_obrigatoria: bool = False,
) -> str:
    fila = catalogo.get("fila_marcas") if isinstance(catalogo.get("fila_marcas"), dict) else {}
    obrigatoria = str(fila.get("proxima_obrigatoria") or "anita").strip().lower() or "anita"
    depois = [str(x).strip().lower().replace(" ", "_") for x in (fila.get("candidatas_depois") or [])]
    por_slug = {
        str(c.get("slug") or "").strip().lower(): c
        for c in candidatas
        if isinstance(c, dict)
    }
    if obrigatoria and not pular_obrigatoria:
        return obrigatoria
    for slug in depois:
        row = por_slug.get(slug) or {}
        if row.get("elegivel") or _i(row.get("anuncios")) >= 2 or _i(row.get("score")) > 0:
            return slug
    return depois[0] if depois else obrigatoria


def avaliar_migracao(
    *,
    catalogo: dict[str, Any] | None = None,
    ruptura_impala: dict[str, Any] | None = None,
    ruptura_outra: dict[str, Any] | None = None,
    anita_nossa: bool = False,
    anita_pedido_proprio: bool = False,
) -> dict[str, Any]:
    """Monta o estado da fila de marcas. Nunca lança."""
    cat = catalogo if isinstance(catalogo, dict) and catalogo else carregar_catalogo()
    outra = ruptura_outra if isinstance(ruptura_outra, dict) else {}
    impala = ruptura_impala if isinstance(ruptura_impala, dict) else (outra.get("impala") or {})
    if not isinstance(impala, dict):
        impala = {}
    if "liberado" not in impala and "veredito" in impala:
        impala = {**impala, "liberado": str(impala.get("veredito") or "") == "liberado"}

    cnae = outra.get("cnae_preparacao") if isinstance(outra.get("cnae_preparacao"), dict) else None
    if cnae is None and isinstance(impala.get("cnae_preparacao"), dict):
        cnae = impala.get("cnae_preparacao")

    impala_liberado = bool(impala.get("liberado"))
    saude_ok = _saude_conta_ok(impala) if impala.get("checks") or impala.get("sinais") else True
    if outra.get("impala") and not (impala.get("checks") or impala.get("sinais")):
        # Snapshot compacto da outra marca: saude só trava se Impala ainda não liberou.
        saude_ok = True

    radar_cego = bool(outra.get("radar_cego"))
    guerra_fase = 0
    for c in outra.get("checks") or []:
        if isinstance(c, dict) and str(c.get("id") or "") == "fase_guerra":
            try:
                guerra_fase = int(c.get("atual") or 0)
            except (TypeError, ValueError):
                guerra_fase = 0
            break
    if guerra_fase == 0:
        try:
            from integracoes.esmaltes.doutrina_guerra_impala import avaliar_condicoes_guerra

            guerra_fase = int((avaliar_condicoes_guerra() or {}).get("fase") or 0)
        except Exception:
            guerra_fase = 0

    skus = cat.get("skus_entrada") if isinstance(cat.get("skus_entrada"), dict) else {}
    anita_cadastrada = bool(skus.get("anita")) or anita_nossa
    candidatas = list(outra.get("candidatas") or [])

    bloqueada = False
    motivo = ""
    if not saude_ok:
        bloqueada = True
        motivo = "saude_conta"
        fase = "F0"
    elif not impala_liberado:
        fase = "F0"
    elif not anita_cadastrada or not anita_nossa:
        fase = "F1"
        if radar_cego:
            bloqueada = True
            motivo = "radar_cego"
        elif guerra_fase < int(
            (cat.get("saude_vendas_impala") or {}).get("doutrina_guerra_fase_min_para_outra_marca") or 5
        ):
            bloqueada = True
            motivo = "guerra_fase"
    elif not anita_pedido_proprio:
        fase = "F1b"
    else:
        fase = "F2"

    cnpj2 = _cnpj2_status(cnae, impala_liberado)
    fases = {str(f.get("id")): f for f in (cat.get("fases") or []) if isinstance(f, dict)}
    meta = fases.get(fase) or {}
    proxima = _proxima_marca_fila(cat, candidatas, pular_obrigatoria=fase == "F2")
    return {
        "ok": True,
        "fase": fase,
        "fase_num": _FASE_NUM.get(fase, 0.0),
        "fase_nome": str(meta.get("nome") or fase),
        "bloqueada": bloqueada,
        "motivo_bloqueio": motivo,
        "impala_liberado": impala_liberado,
        "saude_conta_ok": saude_ok,
        "anita_nossa": bool(anita_nossa or anita_cadastrada),
        "proxima_marca": "anita" if fase in {"F0", "F1", "F1b"} else proxima,
        "radar_cego": radar_cego,
        "guerra_fase": guerra_fase,
        "cnpj2": cnpj2,
        "cnpj_esmaltes": ((cat.get("cnpjs") or {}).get("esmaltes") or {}).get("cnpj_formatado"),
        "cnpj_masterprint": ((cat.get("cnpjs") or {}).get("masterprint") or {}).get("cnpj_formatado"),
        "progresso_impala_pct": _f(impala.get("progresso_pct")),
        "progresso_outra_marca_pct": _f(outra.get("progresso_pct")),
    }


def emitir_metricas_migracao(estado: dict[str, Any]) -> None:
    """Gauges robo.migracao.* — baixa cardinalidade."""
    tags = [f"fase:{estado.get('fase') or 'F0'}"]
    marca = str(estado.get("proxima_marca") or "impala")
    tags.append(f"marca:{marca}")
    gauge("migracao.fase", float(estado.get("fase_num") or 0), tags=tags)
    gauge("migracao.bloqueada", 1.0 if estado.get("bloqueada") else 0.0, tags=tags)
    gauge("migracao.saude_conta", 1.0 if estado.get("saude_conta_ok") else 0.0, tags=tags)
    gauge("migracao.impala_liberado", 1.0 if estado.get("impala_liberado") else 0.0, tags=tags)
    cnpj2 = estado.get("cnpj2") if isinstance(estado.get("cnpj2"), dict) else {}
    gauge("migracao.cnpj2_pronto", 1.0 if cnpj2.get("pronto") else 0.0, tags=tags)
    gauge("migracao.cnpj2_pode_operar", 1.0 if cnpj2.get("pode_operar") else 0.0, tags=tags)
