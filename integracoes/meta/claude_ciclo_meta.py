"""
Claude no ciclo IG/FB — síntese, não gate.

Momentos (crédito só aqui):
  1) flip ciclo.pronto 0→1 — briefing FAZER/NÃO FAZER (uma vez)
  2) copy IG/FB se pronto=1 e token Meta — 1×/dia, não publica
  3) eficiência alerta/crítico — 1×/dia ou na virada de status
  4) listing MIMO na fase 0 — título âncora, 1×/dia, não publica
  5) digest de bloqueio — 1×/dia enquanto pronto=0

Não inventa ROAS, não atribui pedido a IG vs FB, não liga Ads.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    CLAUDE_CICLO_META,
    CLAUDE_CICLO_META_COPY,
    CLAUDE_CICLO_META_COPY_SEG,
    CLAUDE_CICLO_META_DIGEST_SEG,
    CLAUDE_CICLO_META_EFIC,
    CLAUDE_CICLO_META_EFIC_SEG,
    CLAUDE_MIMO_LISTING,
    CLAUDE_MIMO_LISTING_SEG,
    META_ACCESS_TOKEN,
    META_AD_ACCOUNT_ID,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor

logger = logging.getLogger("claude_ciclo_meta")

ESTADO_PATH = ROOT / "logs" / "claude_ciclo_meta.json"
_STATUS_EFIC_ACIONA = frozenset({"alerta", "critico"})

# Esforço previsto (tokens ≈ prompt JSON curto + system). Preço: US$ / 1M tok.
# Haiku no volume; Sonnet só em 1 disparo ou dinheiro em risco.
PAPEIS_IA: dict[str, dict[str, Any]] = {
    "digest": {
        "familia": "haiku",
        "max_tokens": 200,
        "tokens_in": 800,
        "tokens_out": 200,
        "vezes_mes": 30,
        "cenario": "fase0",
        "motivo": "motivo já vem no JSON; 1×/dia enquanto bloqueado",
    },
    "mimo": {
        "familia": "haiku",
        "max_tokens": 260,
        "tokens_in": 900,
        "tokens_out": 260,
        "vezes_mes": 30,
        "cenario": "fase0",
        "motivo": "título âncora fixo; não reescreve doutrina",
    },
    "p0": {
        "familia": "haiku",
        "max_tokens": 180,
        "tokens_in": 600,
        "tokens_out": 180,
        "vezes_mes": 8,
        "cenario": "ambos",
        "motivo": "rascunho de pergunta; Sonnet só se texto de compra",
    },
    "efic_alerta": {
        "familia": "haiku",
        "max_tokens": 240,
        "tokens_in": 800,
        "tokens_out": 240,
        "vezes_mes": 8,
        "cenario": "pronto",
        "motivo": "números já calculados; Haiku interpreta",
    },
    "efic_critico": {
        "familia": "sonnet",
        "max_tokens": 240,
        "tokens_in": 800,
        "tokens_out": 240,
        "vezes_mes": 4,
        "cenario": "pronto",
        "motivo": "gasto real em risco — 1×/dia no máximo",
    },
    "flip": {
        "familia": "sonnet",
        "max_tokens": 360,
        "tokens_in": 1200,
        "tokens_out": 360,
        "vezes_mes": 1,
        "cenario": "pronto",
        "motivo": "um disparo na vida do ciclo: ligar IG/FB",
    },
    "copy": {
        "familia": "haiku",
        "max_tokens": 700,
        "tokens_in": 1500,
        "tokens_out": 700,
        "vezes_mes": 30,
        "cenario": "pronto",
        "motivo": "copy MIMO; Sonnet só se Ads alerta/crítico (roteador de vendas)",
    },
}


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ler() -> dict[str, Any]:
    data = ler_json(ESTADO_PATH, default={})
    return data if isinstance(data, dict) else {}


def _gravar(estado: dict[str, Any]) -> None:
    estado = dict(estado)
    estado["timestamp"] = _agora()
    try:
        escrever_json_atomico(ESTADO_PATH, estado)
    except Exception as exc:
        logger.warning("claude_ciclo_meta gravar: %s", exc)


def _passou(iso: str | None, segundos: int) -> bool:
    if not iso:
        return True
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - t).total_seconds() >= max(int(segundos), 0)


def _meta_token_ok() -> bool:
    return bool(META_ACCESS_TOKEN) and bool(META_AD_ACCOUNT_ID)


def detectar_flip_pronto(pronto: bool, estado: dict[str, Any] | None = None) -> dict[str, Any]:
    """Flip só com anterior explícito False → True (deploy com True não dispara)."""
    prev = estado if isinstance(estado, dict) else _ler()
    anterior = prev.get("pronto")
    flip = anterior is False and bool(pronto)
    return {"flip": flip, "anterior": anterior, "pronto": bool(pronto)}


def _pular_ia() -> bool:
    """Suíte pytest não gasta crédito (mesmo com ANTHROPIC_API_KEY no .env)."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _modelos() -> tuple[str, str]:
    from core.config import CLAUDE_MODELO_RAPIDO, CLAUDE_MODELO_VENDAS

    haiku = str(CLAUDE_MODELO_RAPIDO or "claude-haiku-4-5")
    sonnet = str(CLAUDE_MODELO_VENDAS or "claude-sonnet-4-5")
    return haiku, sonnet


def resolver_ia_ciclo_meta(
    papel: str,
    *,
    efic_status: str | None = None,
    texto: str | None = None,
) -> dict[str, Any]:
    """Haiku no volume; Sonnet no flip e na eficiência crítica (se orçamento cobrir)."""
    chave = (papel or "").strip().lower()
    if chave == "efic":
        chave = "efic_critico" if str(efic_status or "").lower() == "critico" else "efic_alerta"
    spec = PAPEIS_IA.get(chave) or PAPEIS_IA["digest"]
    haiku, sonnet = _modelos()
    familia = str(spec.get("familia") or "haiku")
    motivo = str(spec.get("motivo") or "")
    if chave == "p0" and texto:
        from core.claude_roteador import texto_indica_venda

        if texto_indica_venda(texto):
            familia = "sonnet"
            motivo = "p0_intencao_compra"
    if familia == "sonnet":
        from core.claude_roteador import restante_orcamento_usd

        from core.config import CLAUDE_ESCALONAR_RESTANTE_MIN_USD

        resta = restante_orcamento_usd()
        piso = float(CLAUDE_ESCALONAR_RESTANTE_MIN_USD or 1.5)
        if resta is not None and resta < piso:
            familia = "haiku"
            motivo = f"orcamento_baixo_cai_haiku:{resta:.2f}"
    modelo = sonnet if familia == "sonnet" else haiku
    from core.claude_orcamento import estimar_custo_usd

    usd = estimar_custo_usd(
        modelo,
        int(spec.get("tokens_in") or 0),
        int(spec.get("tokens_out") or 0),
    )
    return {
        "papel": chave,
        "familia": familia,
        "modelo": modelo,
        "forcar_modelo": True,
        "max_tokens": int(spec.get("max_tokens") or 200),
        "tokens_in": int(spec.get("tokens_in") or 0),
        "tokens_out": int(spec.get("tokens_out") or 0),
        "usd_chamada": usd,
        "motivo": motivo,
    }


def prever_esforco_ciclo_meta(cenario: str = "fase0") -> dict[str, Any]:
    """Previsão mensal de chamadas/US$ deste cenário (não é gasto real)."""
    c = (cenario or "fase0").strip().lower()
    if c == "pronto":
        papeis = ("flip", "copy", "efic_alerta", "efic_critico", "p0")
    elif c == "misto":
        papeis = tuple(PAPEIS_IA.keys())
    else:
        papeis = ("digest", "mimo", "p0")
    linhas = []
    usd_mes = 0.0
    for nome in papeis:
        spec = PAPEIS_IA[nome]
        rota = resolver_ia_ciclo_meta(nome)
        n = int(spec.get("vezes_mes") or 0)
        if nome == "flip" and c == "pronto":
            n = 1
        usd = round(float(rota["usd_chamada"]) * n, 4)
        usd_mes += usd
        linhas.append(
            {
                "papel": nome,
                "modelo": rota["modelo"],
                "familia": rota["familia"],
                "vezes_mes": n,
                "usd_chamada": rota["usd_chamada"],
                "usd_mes": usd,
                "motivo": rota["motivo"],
            }
        )
    return {
        "cenario": c if c in ("pronto", "misto") else "fase0",
        "usd_mes": round(usd_mes, 4),
        "chamadas": linhas,
    }


def _sintetizar(
    prompt: str,
    contexto: dict[str, Any],
    origem: str,
    *,
    papel: str,
    efic_status: str | None = None,
) -> str:
    if _pular_ia():
        return ""
    from core.claude_ml.dosagem import SYSTEM_RUPTURA
    from core.resumo_ia import sintetizar_claude

    rota = resolver_ia_ciclo_meta(papel, efic_status=efic_status)
    logger.info(
        "ciclo_meta IA %s → %s (usd≈%s) %s",
        rota["papel"],
        rota["modelo"],
        rota["usd_chamada"],
        rota["motivo"],
    )
    return sintetizar_claude(
        prompt,
        contexto,
        "",
        max_tokens=int(rota["max_tokens"]),
        origem=origem,
        enriquecer_ml=True,
        proposito="ciclo_meta_ig_fb",
        forcar_profundidade="minima" if rota["familia"] == "haiku" else "padrao",
        forcar_modelo=True,
        modelo=rota["modelo"],
        system=SYSTEM_RUPTURA,
        somente_ia=True,
    )


def _alertar(texto: str, chave: str, cooldown: int) -> bool:
    if not (texto or "").strip():
        return False
    return bool(
        alertar_gestor(
            texto.strip(),
            chave=chave,
            cooldown_segundos=cooldown,
            agente_id="meta_metricas",
        )
    )


def _briefing_flip(momento: dict[str, Any], eficiencia: dict[str, Any] | None) -> str:
    ctx = {
        "ciclo": {
            "pronto": True,
            "saude_conta_ok": bool(momento.get("saude_conta_ok")),
            "impala_ok": bool(momento.get("impala_ok")),
            "fase": momento.get("fase"),
            "motivo": momento.get("motivo"),
        },
        "eficiencia": eficiencia or {},
        "token_meta": _meta_token_ok(),
        "regra": (
            "Campanha só MIMO (Kit 3 Impala Mimo + Carmed Manicure). "
            "Não SORT/atacado/francesinha. Não atribuir pedido a IG vs FB."
        ),
    }
    return _sintetizar(
        "O ciclo IG/FB ACABOU DE LIBERAR (pronto=1). "
        "Em até 8 linhas, só com o JSON: "
        "(1) FAZER: criar campanha MIMO no Ads Manager se token_meta=true; "
        "senão FAZER configurar META_ACCESS_TOKEN / META_AD_ACCOUNT_ID. "
        "(2) NÃO FAZER SORT, atacado 10, Ads ML, 2º CNPJ. "
        "(3) OBSERVAR ROAS real (receita ML / gasto Meta) — pixel sozinho não decide. "
        "Não invente gasto, ROAS ou link. Não publique anúncio.",
        ctx,
        origem="ciclo_meta_flip_pronto",
        papel="flip",
    )


def _briefing_efic(eficiencia: dict[str, Any]) -> str:
    return _sintetizar(
        "Eficiência Ads×ML em alerta ou crítico. "
        "Em até 6 linhas cite SÓ o JSON: "
        "(1) se o buraco é criativo, listing ou público "
        "(ROAS real vs pixel — sem atribuir IG vs FB); "
        "(2) FAZER ajuste no que o JSON mostrar; "
        "(3) NÃO FAZER pausar por CTR; pausa só se o JSON disser crítico com gasto. "
        "Não invente pedido nem UTM.",
        {"eficiencia": eficiencia},
        origem="ciclo_meta_efic",
        papel="efic",
        efic_status=str(eficiencia.get("status") or ""),
    )


def _briefing_bloqueio(momento: dict[str, Any]) -> str:
    return _sintetizar(
        "IG/FB ainda NÃO entra no ciclo (pronto=0). "
        "Em até 5 linhas, só o JSON: "
        "FAZER o motivo (ex. publicar MIMO com o título do JSON); "
        "NÃO FAZER ligar Ads/IG/FB; OBSERVAR saúde da conta. "
        "Não invente MLB, estoque ou reviews.",
        {
            "pronto": False,
            "saude_conta_ok": bool(momento.get("saude_conta_ok")),
            "impala_ok": bool(momento.get("impala_ok")),
            "fase": momento.get("fase"),
            "motivo": momento.get("motivo"),
        },
        origem="ciclo_meta_bloqueio",
        papel="digest",
    )


def _briefing_mimo(condicoes: dict[str, Any]) -> str:
    from integracoes.esmaltes.doutrina_guerra_impala import TITULO_MIMO_ML

    checks = condicoes.get("checks") if isinstance(condicoes.get("checks"), dict) else {}
    return _sintetizar(
        "Fase 0 Impala: listing MIMO ainda não fecha o título de atração. "
        f"Título âncora (máx 60): `{TITULO_MIMO_ML}`. "
        "Em até 6 linhas: FAZER publicar/ajustar com esse título + estoque 10; "
        "NÃO FAZER francesinha, sortidas, ‘kit mais barato’, Ads. "
        "Uma linha de descrição (preview — o robô NÃO publica descrição). "
        "Cite só o JSON. CNPJ 52.668.583/0001-27.",
        {
            "fase": condicoes.get("fase"),
            "proximo": condicoes.get("proximo"),
            "mlb_mimo": checks.get("mlb_mimo"),
            "estoque_mimo": checks.get("estoque_mimo"),
            "titulo_atracao": checks.get("titulo_atracao"),
            "carmed_titulo": checks.get("carmed_titulo"),
            "titulo_ancora": TITULO_MIMO_ML,
        },
        origem="ciclo_meta_mimo_listing",
        papel="mimo",
    )


def auxiliar_ciclo_meta(
    momento: dict[str, Any] | None,
    *,
    eficiencia: dict[str, Any] | None = None,
    campanhas_total: int = 0,
) -> dict[str, Any]:
    """Chamado pelo agente meta_metricas após os gauges. Best-effort."""
    out: dict[str, Any] = {"ok": True, "flip": False, "efic": False, "copy": False}
    if not CLAUDE_CICLO_META:
        out["pulado"] = "off"
        return out
    mom = momento if isinstance(momento, dict) else {}
    efic = eficiencia if isinstance(eficiencia, dict) else (mom.get("eficiencia") or {})
    if not isinstance(efic, dict):
        efic = {}
    out["esforco"] = prever_esforco_ciclo_meta("pronto" if mom.get("pronto") else "fase0")
    try:
        gauge("meta.ciclo.claude_usd_previsto_mes", float(out["esforco"].get("usd_mes") or 0))
    except Exception:
        pass
    estado = _ler()
    try:
        det = detectar_flip_pronto(bool(mom.get("pronto")), estado)
        out["flip"] = bool(det["flip"])
        if det["flip"]:
            texto = _briefing_flip(mom, efic)
            enviado = _alertar(texto, "meta:ciclo:flip_pronto", 7 * 24 * 3600)
            out["flip_enviado"] = enviado
            out["flip_texto"] = texto
            if enviado:
                incrementar("meta.ciclo.claude_flip")
            estado["flip_em"] = _agora()
            gauge("meta.ciclo.claude_flip", 1.0 if enviado else 0.0)
        else:
            gauge("meta.ciclo.claude_flip", 0.0)

        estado["pronto"] = bool(mom.get("pronto"))

        if (
            CLAUDE_CICLO_META_EFIC
            and str(efic.get("status") or "") in _STATUS_EFIC_ACIONA
            and (
                str(estado.get("efic_status") or "") != str(efic.get("status"))
                or _passou(estado.get("efic_em"), CLAUDE_CICLO_META_EFIC_SEG)
            )
        ):
            texto_e = _briefing_efic(efic)
            env_e = _alertar(
                texto_e,
                f"meta:ciclo:efic:{efic.get('status')}",
                CLAUDE_CICLO_META_EFIC_SEG,
            )
            out["efic"] = True
            out["efic_enviado"] = env_e
            if env_e:
                incrementar("meta.ciclo.claude_efic")
            estado["efic_em"] = _agora()
            estado["efic_status"] = str(efic.get("status"))
            gauge("meta.ciclo.claude_efic", 1.0 if env_e else 0.0)
        else:
            gauge("meta.ciclo.claude_efic", 0.0)

        if (
            CLAUDE_CICLO_META_COPY
            and bool(mom.get("pronto"))
            and _meta_token_ok()
            and not _pular_ia()
            and _passou(estado.get("copy_em"), CLAUDE_CICLO_META_COPY_SEG)
        ):
            from integracoes.social.conversao_manicures import escolher_oferta_haiku

            oferta = escolher_oferta_haiku(
                sinal_ads={
                    "ciclo_pronto": True,
                    "campanhas_total": int(campanhas_total or 0),
                    "status": str(efic.get("status") or ""),
                    "sustentabilidade": {"status": efic.get("status")},
                    "eficiencia": {
                        "status": efic.get("status"),
                        "roas_real": efic.get("roas_real"),
                    },
                }
            )
            out["copy"] = True
            out["copy_ok"] = bool(oferta.get("ok"))
            if oferta.get("ok"):
                msg = (
                    "📣 *Copy IG/FB (ciclo pronto)*\n"
                    "_O robô não publicou. Colar no Ads Manager se for criar a campanha._\n\n"
                    f"Campanha: `{oferta.get('campanha_id')}` ({oferta.get('campanha_nome')})\n"
                    f"SKU: `{oferta.get('sku')}`\n\n"
                    f"*Facebook*\n{oferta.get('copy_facebook')}\n\n"
                    f"*Instagram*\n{oferta.get('copy_instagram')}\n\n"
                    f"CTA: {oferta.get('cta_ml')}"
                )
                env_c = _alertar(msg, "meta:ciclo:copy_ig_fb", CLAUDE_CICLO_META_COPY_SEG)
                out["copy_enviado"] = env_c
                if env_c:
                    incrementar("meta.ciclo.claude_copy")
                    estado["copy_em"] = _agora()
                gauge("meta.ciclo.claude_copy", 1.0 if env_c else 0.0)
            else:
                out["copy_motivo"] = oferta.get("motivo")
                gauge("meta.ciclo.claude_copy", 0.0)
        else:
            gauge("meta.ciclo.claude_copy", 0.0)

        _gravar(estado)
    except Exception as exc:
        logger.warning("auxiliar_ciclo_meta: %s", exc)
        out["ok"] = False
        out["erro"] = str(exc)
    return out


def auxiliar_digest_bloqueio(momento: dict[str, Any] | None = None) -> dict[str, Any]:
    """1×/dia enquanto IG/FB estiver bloqueado. Ponto: operação 24h (a cada 2h)."""
    out: dict[str, Any] = {"ok": True, "enviado": False}
    if not CLAUDE_CICLO_META:
        out["pulado"] = "off"
        return out
    try:
        from integracoes.meta.ciclo_campanhas import avaliar_momento_ciclo_meta

        mom = momento if isinstance(momento, dict) and "pronto" in momento else avaliar_momento_ciclo_meta()
        out["motivo"] = mom.get("motivo")
        out["pronto"] = bool(mom.get("pronto"))
        if mom.get("pronto"):
            out["pulado"] = "ja_pronto"
            return out
        estado = _ler()
        if not _passou(estado.get("digest_em"), CLAUDE_CICLO_META_DIGEST_SEG):
            out["pulado"] = "cooldown"
            return out
        texto = _briefing_bloqueio(mom)
        enviado = _alertar(texto, "meta:ciclo:bloqueio_digest", CLAUDE_CICLO_META_DIGEST_SEG)
        out["enviado"] = enviado
        out["texto"] = texto
        if enviado or texto:
            estado["digest_em"] = _agora()
            _gravar(estado)
        if enviado:
            incrementar("meta.ciclo.claude_digest")
        gauge("meta.ciclo.claude_digest", 1.0 if enviado else 0.0)
    except Exception as exc:
        logger.warning("auxiliar_digest_bloqueio: %s", exc)
        out["ok"] = False
        out["erro"] = str(exc)
    return out


def auxiliar_listing_mimo(condicoes: dict[str, Any] | None) -> dict[str, Any]:
    """Fase 0: título MIMO. 1×/dia. Não publica."""
    out: dict[str, Any] = {"ok": True, "enviado": False}
    if not CLAUDE_MIMO_LISTING:
        out["pulado"] = "off"
        return out
    cond = condicoes if isinstance(condicoes, dict) else {}
    try:
        fase = int(cond.get("fase") or 0)
    except (TypeError, ValueError):
        fase = 0
    checks = cond.get("checks") if isinstance(cond.get("checks"), dict) else {}
    precisa = fase < 3 and (not checks.get("mlb_mimo") or not checks.get("titulo_atracao"))
    if not precisa:
        out["pulado"] = "titulo_ok_ou_fase"
        return out
    estado = _ler()
    if not _passou(estado.get("mimo_listing_em"), CLAUDE_MIMO_LISTING_SEG):
        out["pulado"] = "cooldown"
        return out
    try:
        texto = _briefing_mimo(cond)
        enviado = _alertar(texto, "meta:ciclo:mimo_listing", CLAUDE_MIMO_LISTING_SEG)
        out["enviado"] = enviado
        out["texto"] = texto
        if enviado or texto:
            estado["mimo_listing_em"] = _agora()
            _gravar(estado)
        if enviado:
            incrementar("meta.ciclo.claude_mimo_listing")
        gauge("meta.ciclo.claude_mimo_listing", 1.0 if enviado else 0.0)
    except Exception as exc:
        logger.warning("auxiliar_listing_mimo: %s", exc)
        out["ok"] = False
        out["erro"] = str(exc)
    return out
