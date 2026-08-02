"""
integracoes/importacao/corredor_paraguai_terrestre.py
Importação / redistribuição via endereço comercial no Paraguai +
transporte terrestre até destino no Brasil (Mercosul).
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar
from core.horario import agora_brasil
from integracoes.importacao.portos_brasil import (
    calcular_frete_terrestre_py_br,
    cobertura_costa_brasil,
    corredores_terrestres_py_br,
    endereco_comercial_paraguai,
)

logger = logging.getLogger("corredor_paraguai_terrestre")

SNAPSHOT_PATH = ROOT / "logs" / "corredor_paraguai_terrestre_ultima.json"


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def montar_cenario_py_terrestre_br(
    *,
    valor_mercadoria_brl: float,
    quantidade: int = 1,
    cep_destino: str | None = None,
    fob_usd: float | None = None,
    cambio_usd_brl: float | None = None,
) -> dict[str, Any]:
    """
    Junta endereço comercial PY + custo terrestre até CEP BR.
    Se FOB+câmbio informados, estima valor da carga em BRL a partir do Alibaba.
    """
    end = endereco_comercial_paraguai()
    valor = float(valor_mercadoria_brl or 0)
    if valor <= 0 and fob_usd and cambio_usd_brl:
        valor = float(fob_usd) * max(1, int(quantidade)) * float(cambio_usd_brl)

    corredores = corredores_terrestres_py_br(cep_destino=cep_destino)
    cenarios = []
    for c in corredores:
        calc = calcular_frete_terrestre_py_br(
            c, valor_carga_brl=valor, quantidade=quantidade
        )
        # Custo total operação = mercadoria + terrestre (sem impostos aduaneiros marítimos)
        calc["valor_mercadoria_brl"] = round(valor, 2)
        calc["custo_operacao_total_brl"] = round(valor + _f(calc.get("custo_total_brl")), 2)
        calc["custo_operacao_unitario_brl"] = round(
            calc["custo_operacao_total_brl"] / max(1, int(quantidade)), 2
        )
        cenarios.append(calc)

    cenarios.sort(key=lambda x: _f(x.get("custo_total_brl"), 1e9))
    melhor = cenarios[0] if cenarios else None
    costa = cobertura_costa_brasil()

    out = {
        "ok": bool(end.get("ok") and cenarios),
        "gerado_em": agora_brasil().isoformat(),
        "modal": "terrestre",
        "referencia": "alibaba_ou_mercadoria_brl",
        "paraguai_endereco_comercial": end,
        "destino_cep": cep_destino,
        "cobertura_costa_brasil_pct": costa.get("cobertura_pct"),
        "cenarios_terrestres": cenarios,
        "melhor_corredor": melhor,
        "aviso": (
            "Transporte terrestre PY→BR (Mercosul). Não substitui assessoria fiscal/"
            "aduaneira na fronteira. Endereço PY padrão em Ciudad del Este — "
            "altere com IMPORTACAO_PY_ENDERECO / IMPORTACAO_PY_CIDADE."
        ),
    }

    tags = ["modal:terrestre", "origem:PY", "destino:BR"]
    gauge("portos_alibaba.cobertura_costa_pct", float(costa.get("cobertura_pct") or 0), tags)
    if melhor:
        gauge("py_terrestre.custo_total_brl", float(melhor.get("custo_total_brl") or 0), tags)
        gauge("py_terrestre.km_total", float(melhor.get("km_total") or 0), tags)
    incrementar("py_terrestre.cenario_ok" if out["ok"] else "py_terrestre.cenario_erro", tags=tags)
    escrever_json_atomico(SNAPSHOT_PATH, out)
    return out


def formatar_py_terrestre_telegram(resultado: dict[str, Any]) -> str:
    if not resultado.get("ok"):
        return "_Corredor PY terrestre indisponível._"
    end = (resultado.get("paraguai_endereco_comercial") or {}).get("endereco") or {}
    melhor = resultado.get("melhor_corredor") or {}
    linhas = [
        "🇵🇾➡️🇧🇷 *Paraguai terrestre → Brasil*",
        f"Endereço comercial PY: *{end.get('cidade')}* — {end.get('endereco')}",
        f"CEP destino BR: `{resultado.get('destino_cep') or melhor.get('destino_cep')}`",
        f"Cobertura costa BR (portos ref.): *{resultado.get('cobertura_costa_brasil_pct')}%*",
        f"✅ Corredor: *{melhor.get('corredor_id')}* · {melhor.get('origem')} → "
        f"{melhor.get('fronteira_br')} → CEP",
        f"  Km ~{melhor.get('km_total')} · frete R$ {melhor.get('frete_km_brl')} · "
        f"pedágio R$ {melhor.get('pedagios_brl')} · fronteira R$ {melhor.get('fixo_fronteira_brl')}",
        f"  Terrestre total: *R$ {melhor.get('custo_total_brl')}* · "
        f"operação (merc+frete) R$ {melhor.get('custo_operacao_total_brl')}",
    ]
    linhas.append(f"_{resultado.get('aviso')}_")
    return "\n".join(linhas)
