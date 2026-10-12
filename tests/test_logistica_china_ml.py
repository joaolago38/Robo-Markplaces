"""tests/test_logistica_china_ml.py"""
from __future__ import annotations

from unittest.mock import patch

from integracoes.importacao.logistica_china_ml import (
    formatar_logistica_telegram,
    inland_40hc_brl,
    ranquear_portos_ml,
)


def test_inland_piso_e_faixas():
    assert inland_40hc_brl(0) == 2200.0
    curto = inland_40hc_brl(95)
    longo = inland_40hc_brl(2450)
    assert curto < longo
    assert curto == round(2200 + 95 * 8.0, 2)


def test_cajamar_ganha_santos():
    with patch("integracoes.importacao.logistica_china_ml.escrever_json_atomico"), patch(
        "integracoes.importacao.logistica_china_ml.gauge"
    ), patch("integracoes.importacao.logistica_china_ml.incrementar"):
        out = ranquear_portos_ml(
            origem_id="szx",
            hub_id="cajamar",
            cambio_usd_brl=5.5,
            gravar=False,
        )
    assert out["ok"] is True
    assert out["melhor"]["codigo"] == "BRSSZ"
    ranking = {r["codigo"]: r for r in out["ranking"]}
    assert ranking["BRSSZ"]["total_logistico_brl"] < ranking["BRSUA"]["total_logistico_brl"]
    assert ranking["BRSSZ"]["total_logistico_brl"] < ranking["BRNVT"]["total_logistico_brl"]
    assert out["hub_ml"]["id"] == "cajamar"


def test_gcr_ganha_navegantes_ou_itapoa():
    with patch("integracoes.importacao.logistica_china_ml.escrever_json_atomico"), patch(
        "integracoes.importacao.logistica_china_ml.gauge"
    ), patch("integracoes.importacao.logistica_china_ml.incrementar"):
        out = ranquear_portos_ml(
            origem_id="szx",
            hub_id="gcr",
            cambio_usd_brl=5.5,
            gravar=False,
        )
    assert out["ok"] is True
    assert out["melhor"]["codigo"] in {"BRNVT", "BRITJ", "BRITP"}
    ranking = {r["codigo"]: r for r in out["ranking"]}
    assert ranking[out["melhor"]["codigo"]]["total_logistico_brl"] < ranking["BRSSZ"]["total_logistico_brl"]


def test_recife_ganha_suape():
    with patch("integracoes.importacao.logistica_china_ml.escrever_json_atomico"), patch(
        "integracoes.importacao.logistica_china_ml.gauge"
    ), patch("integracoes.importacao.logistica_china_ml.incrementar"):
        out = ranquear_portos_ml(
            origem_id="szx",
            hub_id="recife",
            cambio_usd_brl=5.5,
            gravar=False,
        )
    assert out["ok"] is True
    assert out["melhor"]["codigo"] == "BRSUA"


def test_telegram_desligado():
    msg = formatar_logistica_telegram({"ok": False, "motivo": "LOGISTICA_CHINA_ML_ATIVO=0"})
    assert "desligada" in msg.lower()
    assert "LOGISTICA_CHINA_ML_ATIVO=0" in msg


def test_agente_toggle_off_sem_forcar():
    from agentes.importacao.agente_logistica_china_ml import executar

    with patch("agentes.importacao.agente_logistica_china_ml.LOGISTICA_CHINA_ML_ATIVO", False), patch(
        "agentes.importacao.agente_logistica_china_ml.incrementar"
    ):
        out = executar(hub_id="cajamar")
    assert out["ok"] is False
    assert out["motivo"] == "LOGISTICA_CHINA_ML_ATIVO=0"
    assert out["toggle_ligado"] is False


def test_agente_forcar_ignora_toggle():
    from agentes.importacao.agente_logistica_china_ml import executar

    with patch("agentes.importacao.agente_logistica_china_ml.LOGISTICA_CHINA_ML_ATIVO", False), patch(
        "agentes.importacao.agente_logistica_china_ml.incrementar"
    ), patch("integracoes.importacao.logistica_china_ml.escrever_json_atomico"), patch(
        "integracoes.importacao.logistica_china_ml.gauge"
    ), patch("integracoes.importacao.logistica_china_ml.incrementar"):
        out = executar(origem_id="szx", hub_id="cajamar", cambio_usd_brl=5.5, forcar=True)
    assert out["ok"] is True
    assert out["forcado"] is True
    assert out["melhor"]["codigo"] == "BRSSZ"
    assert "Santos" in (out.get("mensagem") or "")
