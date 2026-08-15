"""
core/claude_orcamento.py
Orçamento local Claude (tokens → US$) + hard stop + alertas Telegram.
O saldo restante da console (Anthropic/OpenAI) NÃO vem pela API automaticamente.
Usamos orçamento local + sync manual via aplicar_saldo_console() / --creditos.
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_e_atualizar_json, ler_json
from core.config import ROOT

logger = logging.getLogger("claude_orcamento")

USO_PATH = ROOT / "logs" / "claude_uso_orcamento.json"
HIST_PATH = ROOT / "logs" / "claude_consumo_historico.json"
PAINEL_PATH = ROOT / "logs" / "claude_saldo_painel_ultima.json"
GRAFICO_AGENTES_PATH = ROOT / "logs" / "grafico_claude_por_agente.png"
GRAFICO_EVOLUCAO_PATH = ROOT / "logs" / "grafico_claude_evolucao.png"
MAX_EVENTOS = 200
MAX_HIST_PONTOS = 60

# Preços aproximados US$ / 1M tokens (Haiku 4.5 / Sonnet 4.5 — ajustáveis via env)
_PRECO_DEFAULT = {
    "haiku": {"in": 1.0, "out": 5.0},
    "sonnet": {"in": 3.0, "out": 15.0},
    "opus": {"in": 15.0, "out": 75.0},
}


def _cfg():
    from core import config as cfg

    return cfg


def _precos() -> dict[str, dict[str, float]]:
    c = _cfg()
    return {
        "haiku": {
            "in": float(getattr(c, "CLAUDE_PRECO_HAIKU_IN", 1.0) or 1.0),
            "out": float(getattr(c, "CLAUDE_PRECO_HAIKU_OUT", 5.0) or 5.0),
        },
        "sonnet": {
            "in": float(getattr(c, "CLAUDE_PRECO_SONNET_IN", 3.0) or 3.0),
            "out": float(getattr(c, "CLAUDE_PRECO_SONNET_OUT", 15.0) or 15.0),
        },
        "opus": _PRECO_DEFAULT["opus"],
    }


def _familia_modelo(modelo: str) -> str:
    m = (modelo or "").lower()
    if "haiku" in m:
        return "haiku"
    if "opus" in m:
        return "opus"
    return "sonnet"


def estimar_custo_usd(modelo: str, input_tokens: int, output_tokens: int) -> float:
    fam = _familia_modelo(modelo)
    p = _precos().get(fam) or _PRECO_DEFAULT["haiku"]
    custo = (max(0, input_tokens) / 1_000_000.0) * p["in"] + (
        max(0, output_tokens) / 1_000_000.0
    ) * p["out"]
    return round(custo, 6)


def detectar_origem() -> str:
    """Heurística: primeiro frame em agentes/ ou integracoes/ (Windows + Linux/Actions)."""
    skip_arquivos = (
        "claude_orcamento.py",
        "claude_client.py",
        "resumo_ia.py",
    )
    for fr in traceback.extract_stack():
        path = (fr.filename or "").replace("\\", "/")
        low = path.lower()
        if "/tests/" in low or "\\tests\\" in (fr.filename or "").lower():
            continue
        if any(low.endswith(nome) for nome in skip_arquivos):
            continue
        for marcador in ("agentes/", "integracoes/", "api/", "core/"):
            needle = "/" + marcador
            if needle in low:
                idx = low.index(needle) + 1
            elif low.startswith(marcador):
                idx = 0
            else:
                continue
            trecho = path[idx + len(marcador) :]
            return trecho.replace(".py", "").replace("/", ".")[:80]
    return "desconhecido"


def _row_origem_vazio() -> dict[str, Any]:
    return {
        "usd": 0.0,
        "chamadas": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "ok": 0,
        "falha": 0,
        "fallback": 0,
        "vazio": 0,
        "bloqueado": 0,
        "assertividade_pct": 0.0,
    }


def calcular_assertividade(stats: dict[str, Any]) -> float:
    """
    % de respostas úteis = ok / (ok + falha + fallback + vazio).
    Bloqueio por orçamento não entra no denominador (não é culpa do modelo).
    """
    ok = int(stats.get("ok") or 0)
    ruim = (
        int(stats.get("falha") or 0)
        + int(stats.get("fallback") or 0)
        + int(stats.get("vazio") or 0)
    )
    total = ok + ruim
    if total <= 0:
        return 0.0
    return round(100.0 * ok / total, 1)


def classificar_resultado_texto(texto: str | None) -> str:
    t = (texto or "").strip()
    if not t:
        return "vazio"
    if t.startswith("⚠️"):
        low = t.lower()
        if "pausado" in low or "orçamento" in low or "esgotado" in low:
            return "bloqueado"
        if "não configurada" in low or "falha" in low or "inválida" in low or "vazia" in low:
            return "falha"
        return "fallback"
    return "ok"


def _estado_vazio() -> dict[str, Any]:
    c = _cfg()
    orc = float(getattr(c, "CLAUDE_ORCAMENTO_USD", 8.99) or 8.99)
    return {
        "orcamento_usd": orc,
        "consumido_usd": 0.0,
        "chamadas": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "resultados": {"ok": 0, "falha": 0, "fallback": 0, "vazio": 0, "bloqueado": 0},
        "assertividade_pct": 0.0,
        "por_origem": {},
        "por_modelo": {},
        "eventos": [],
        "alertas_enviados": {},
        "bloqueado": False,
        "atualizado_em": None,
        "criado_em": datetime.now(timezone.utc).isoformat(),
    }


def carregar_estado() -> dict[str, Any]:
    data = ler_json(USO_PATH, default=None)
    if not isinstance(data, dict):
        return _estado_vazio()
    base = _estado_vazio()
    base.update(data)
    c = _cfg()
    # Saldo do painel Anthropic prevalece sobre CLAUDE_ORCAMENTO_USD do .env
    if str(base.get("fonte_saldo") or "") != "console_painel":
        base["orcamento_usd"] = float(
            getattr(c, "CLAUDE_ORCAMENTO_USD", base["orcamento_usd"]) or 8.99
        )
    if not isinstance(base.get("resultados"), dict):
        base["resultados"] = _estado_vazio()["resultados"]
    return base


def resumo(estado: dict[str, Any] | None = None) -> dict[str, Any]:
    e = estado or carregar_estado()
    orc = float(e.get("orcamento_usd") or 0)
    used = float(e.get("consumido_usd") or 0)
    resta = max(0.0, round(orc - used, 6))
    pct = round((used / orc) * 100, 1) if orc > 0 else 0.0
    resultados = dict(e.get("resultados") or {})
    assert_global = calcular_assertividade(resultados)
    por_origem = dict(e.get("por_origem") or {})
    # recalcula assertividade por origem (compatível com estado antigo)
    for nome, info in list(por_origem.items()):
        if not isinstance(info, dict):
            continue
        info = dict(info)
        info["assertividade_pct"] = calcular_assertividade(info)
        por_origem[nome] = info
    return {
        "orcamento_usd": round(orc, 4),
        "consumido_usd": round(used, 4),
        "restante_usd": round(resta, 4),
        "percentual_usado": pct,
        "fonte_saldo": e.get("fonte_saldo"),
        "chamadas": int(e.get("chamadas") or 0),
        "tokens_in": int(e.get("tokens_in") or 0),
        "tokens_out": int(e.get("tokens_out") or 0),
        "bloqueado": bool(e.get("bloqueado")) or (orc > 0 and used >= orc),
        "resultados": resultados,
        "assertividade_pct": assert_global,
        "por_origem": por_origem,
        "por_modelo": e.get("por_modelo") or {},
        "atualizado_em": e.get("atualizado_em"),
    }


def pode_chamar(*, origem: str | None = None, forcar: bool = False) -> tuple[bool, str]:
    """Fail-closed: qualquer erro no toggle/orçamento bloqueia a chamada.

    `forcar=True` ignora CLAUDE_ATIVO / toggle de arquivo (ruptura Impala).
    Orçamento esgotado continua bloqueando.
    """
    if not forcar:
        try:
            from core.claude_toggle import claude_esta_ativo

            ok_t, motivo_t = claude_esta_ativo()
            if not ok_t:
                return False, f"Claude desligado: {motivo_t}"
        except Exception as exc:
            logger.warning("toggle Claude indisponível — bloqueando chamadas: %s", exc)
            return False, f"Claude desligado: toggle_indisponivel ({exc})"
    elif origem:
        logger.info("Claude forçado na origem=%s (toggle ignorado)", origem)

    try:
        c = _cfg()
        if not getattr(c, "CLAUDE_ORCAMENTO_ATIVO", True):
            return True, ""
        r = resumo()
        if r["bloqueado"] or r["restante_usd"] <= 0:
            return False, (
                f"orçamento Claude esgotado "
                f"(US$ {r['consumido_usd']:.4f} / {r['orcamento_usd']:.2f})"
            )
        return True, ""
    except Exception as exc:
        logger.warning("orçamento Claude indisponível — bloqueando chamadas: %s", exc)
        return False, f"Claude desligado: orcamento_indisponivel ({exc})"


def _limiares_cruzados(antes_pct: float, depois_pct: float) -> list[int]:
    out = []
    for lim in (50, 75, 90, 100):
        if antes_pct < lim <= depois_pct:
            out.append(lim)
    return out


def registrar_uso(
    *,
    modelo: str,
    input_tokens: int,
    output_tokens: int,
    origem: str | None = None,
    tipo: str = "perguntar",
    resultado: str = "ok",
) -> dict[str, Any]:
    """
    Soma consumo estimado + resultado (ok/falha/fallback/vazio/bloqueado).
    Retorna resumo + limiares cruzados nesta chamada. Nunca lança.
    """
    try:
        c = _cfg()
        if not getattr(c, "CLAUDE_ORCAMENTO_ATIVO", True):
            return {"ok": True, "desligado": True}

        origem_n = (origem or detectar_origem() or "desconhecido")[:80]
        resultado_n = (resultado or "ok").strip().lower()
        if resultado_n not in ("ok", "falha", "fallback", "vazio", "bloqueado"):
            resultado_n = "falha"
        # chamadas bloqueadas antes da API não geram custo de tokens
        custo = (
            0.0
            if resultado_n == "bloqueado"
            else estimar_custo_usd(modelo, int(input_tokens or 0), int(output_tokens or 0))
        )
        antes = resumo()
        cruzados: list[int] = []

        def _upd(estado: Any) -> Any:
            nonlocal cruzados
            if not isinstance(estado, dict):
                estado = _estado_vazio()
            orc = float(getattr(c, "CLAUDE_ORCAMENTO_USD", 8.99) or 8.99)
            estado["orcamento_usd"] = orc
            used_antes = float(estado.get("consumido_usd") or 0)
            pct_antes = (used_antes / orc * 100) if orc > 0 else 0.0
            used = used_antes + custo
            estado["consumido_usd"] = round(used, 6)
            estado["chamadas"] = int(estado.get("chamadas") or 0) + 1
            estado["tokens_in"] = int(estado.get("tokens_in") or 0) + int(input_tokens or 0)
            estado["tokens_out"] = int(estado.get("tokens_out") or 0) + int(output_tokens or 0)

            glob = dict(estado.get("resultados") or _estado_vazio()["resultados"])
            glob[resultado_n] = int(glob.get(resultado_n) or 0) + 1
            estado["resultados"] = glob
            estado["assertividade_pct"] = calcular_assertividade(glob)

            po = dict(estado.get("por_origem") or {})
            row = dict(po.get(origem_n) or _row_origem_vazio())
            row["usd"] = round(float(row.get("usd") or 0) + custo, 6)
            row["chamadas"] = int(row.get("chamadas") or 0) + 1
            row["tokens_in"] = int(row.get("tokens_in") or 0) + int(input_tokens or 0)
            row["tokens_out"] = int(row.get("tokens_out") or 0) + int(output_tokens or 0)
            row[resultado_n] = int(row.get(resultado_n) or 0) + 1
            row["assertividade_pct"] = calcular_assertividade(row)
            po[origem_n] = row
            estado["por_origem"] = po

            pm = dict(estado.get("por_modelo") or {})
            mr = dict(pm.get(modelo) or {"usd": 0.0, "chamadas": 0, "ok": 0, "falha": 0})
            mr["usd"] = round(float(mr.get("usd") or 0) + custo, 6)
            mr["chamadas"] = int(mr.get("chamadas") or 0) + 1
            if resultado_n in ("ok", "falha", "fallback", "vazio", "bloqueado"):
                mr[resultado_n] = int(mr.get(resultado_n) or 0) + 1
            mr["assertividade_pct"] = calcular_assertividade(mr)
            pm[modelo] = mr
            estado["por_modelo"] = pm

            ev = list(estado.get("eventos") or [])
            ev.insert(
                0,
                {
                    "em": datetime.now(timezone.utc).isoformat(),
                    "origem": origem_n,
                    "modelo": modelo,
                    "tipo": tipo,
                    "resultado": resultado_n,
                    "in": int(input_tokens or 0),
                    "out": int(output_tokens or 0),
                    "usd": custo,
                },
            )
            estado["eventos"] = ev[:MAX_EVENTOS]
            pct_depois = (used / orc * 100) if orc > 0 else 0.0
            cruzados = _limiares_cruzados(pct_antes, pct_depois)
            estado["bloqueado"] = used >= orc
            estado["atualizado_em"] = datetime.now(timezone.utc).isoformat()
            return estado

        try:
            ler_e_atualizar_json(USO_PATH, _upd, default=_estado_vazio())
        except Exception:
            e = carregar_estado()
            e = _upd(e)
            escrever_json_atomico(USO_PATH, e)

        depois = resumo()
        out = {
            "ok": True,
            "custo_usd": custo,
            "origem": origem_n,
            "modelo": modelo,
            "resultado": resultado_n,
            "resumo": depois,
            "limiares": cruzados,
            "antes": antes,
        }
        _talvez_alertar(out)
        return out
    except Exception as exc:
        logger.warning("registrar_uso falhou: %s", exc)
        return {"ok": False, "erro": str(exc)[:120]}


def _talvez_alertar(reg: dict[str, Any]) -> None:
    c = _cfg()
    if not getattr(c, "CLAUDE_ORCAMENTO_ALERTA", True):
        return
    limiares = list(reg.get("limiares") or [])
    res = reg.get("resumo") or {}
    # alerta a cada chamada se flag verbose
    verbose = bool(getattr(c, "CLAUDE_ORCAMENTO_ALERTA_TODAS", True))
    deve = verbose or bool(limiares) or bool(res.get("bloqueado"))
    if not deve:
        return
    try:
        from core.notificador import alertar_gestor

        msg = montar_mensagem_telegram(
            res,
            evento=reg,
            titulo="Claude — consumo API",
        )
        # cooldown curto por limiar; verbose usa chave por minuto-bucket
        if limiares:
            chave = f"claude_orcamento:limiar:{max(limiares)}"
            cool = 3600
        elif res.get("bloqueado"):
            chave = "claude_orcamento:bloqueado"
            cool = 1800
        else:
            chave = f"claude_orcamento:uso:{datetime.now(timezone.utc):%Y%m%d%H%M}"
            cool = 50  # ~1 alerta/min no burst
        alertar_gestor(msg, chave=chave, cooldown_segundos=cool, agente_id="consumo_claude")
    except Exception as exc:
        logger.warning("alerta orçamento Claude: %s", exc)


def montar_mensagem_telegram(
    r: dict[str, Any] | None = None,
    *,
    evento: dict[str, Any] | None = None,
    titulo: str = "Claude — orçamento",
) -> str:
    from core.telegram_explicacao import cabecalho_agente

    r = r or resumo()
    emoji = "🔴" if r.get("bloqueado") else ("🟡" if float(r.get("percentual_usado") or 0) >= 75 else "🟢")
    assert_g = float(r.get("assertividade_pct") or 0)
    emoji_a = "🟢" if assert_g >= 80 else ("🟡" if assert_g >= 50 else "🔴")
    res = r.get("resultados") or {}
    linhas = [
        cabecalho_agente("consumo_claude", f"🤖 *{titulo}*"),
        "",
        f"{emoji} Orçamento: *US$ {float(r.get('orcamento_usd') or 0):.2f}*",
        f"• Consumido: *US$ {float(r.get('consumido_usd') or 0):.4f}* ({float(r.get('percentual_usado') or 0):.1f}%)",
        f"• Resta: *US$ {float(r.get('restante_usd') or 0):.4f}*",
        f"• Chamadas: {int(r.get('chamadas') or 0)} | "
        f"tokens in/out: {int(r.get('tokens_in') or 0)}/{int(r.get('tokens_out') or 0)}",
        "",
        f"{emoji_a} *Assertividade global: {assert_g:.1f}%*",
        f"• ok {int(res.get('ok') or 0)} · falha {int(res.get('falha') or 0)} · "
        f"fallback {int(res.get('fallback') or 0)} · vazio {int(res.get('vazio') or 0)} · "
        f"bloqueado {int(res.get('bloqueado') or 0)}",
        "_Score = ok / (ok+falha+fallback+vazio) nos agentes que usam Claude._",
    ]
    try:
        from core.claude_toggle import estado_toggle

        tg = estado_toggle()
        if not tg.get("ativo"):
            linhas.extend(
                [
                    "",
                    f"⏸ *Claude DESLIGADO* ({tg.get('fonte')}): {tg.get('motivo') or 'pausa'}",
                    "_Religar: `python scripts/toggle_claude.py on` ou CLAUDE_ATIVO=1_",
                ]
            )
        else:
            linhas.append("")
            linhas.append("▶️ Toggle Claude: *ligado* (pronto para operação)")
    except Exception:
        pass
    if r.get("bloqueado"):
        linhas.append("")
        linhas.append("🚫 *HARD STOP* — novas chamadas Claude bloqueadas até recarregar orçamento.")

    if evento and not evento.get("desligado"):
        linhas.extend(
            [
                "",
                "*Última chamada*",
                f"• Origem: `{evento.get('origem')}`",
                f"• Modelo: `{evento.get('modelo')}`",
                f"• Resultado: *{evento.get('resultado') or 'ok'}*",
                f"• Custo: US$ {float(evento.get('custo_usd') or 0):.6f}",
            ]
        )
        if evento.get("limiares"):
            linhas.append(f"• Limiar cruzado: {evento.get('limiares')}%")

    por = r.get("por_origem") or {}
    if por:
        top = sorted(
            por.items(),
            key=lambda kv: (
                float((kv[1] or {}).get("assertividade_pct") or 0),
                float((kv[1] or {}).get("usd") or 0),
            ),
            reverse=True,
        )[:10]
        linhas.extend(["", "*Assertividade por agente*"])
        for nome, info in top:
            info = info or {}
            linhas.append(
                f"• `{nome}` — *{float(info.get('assertividade_pct') or 0):.0f}%* "
                f"(ok {int(info.get('ok') or 0)}/"
                f"{int(info.get('chamadas') or 0)} · US$ {float(info.get('usd') or 0):.4f})"
            )

        top_usd = sorted(
            por.items(),
            key=lambda kv: (
                float((kv[1] or {}).get("usd") or 0),
                int((kv[1] or {}).get("chamadas") or 0),
            ),
            reverse=True,
        )[:12]
        linhas.extend(["", "*Consumo por agente (US$)*"])
        total_usd = float(r.get("consumido_usd") or 0) or sum(
            float((info or {}).get("usd") or 0) for _, info in top_usd
        )
        for nome, info in top_usd:
            usd = float((info or {}).get("usd") or 0)
            pct_agente = (usd / total_usd * 100) if total_usd > 0 else 0.0
            linhas.append(
                f"• `{nome}` — *US$ {usd:.4f}* "
                f"({pct_agente:.0f}% · {int((info or {}).get('chamadas') or 0)}×)"
            )

    pm = r.get("por_modelo") or {}
    if pm:
        linhas.extend(["", "*Por modelo*"])
        for modelo, info in sorted(pm.items(), key=lambda kv: float((kv[1] or {}).get("usd") or 0), reverse=True):
            linhas.append(
                f"• `{modelo}` — US$ {float((info or {}).get('usd') or 0):.4f} | "
                f"assert. {float((info or {}).get('assertividade_pct') or 0):.0f}%"
            )

    linhas.extend(
        [
            "",
            "_Estimativa local (preço/MTok). Saldo real: console.anthropic.com → Billing._",
        ]
    )
    return "\n".join(linhas).strip()


def resetar_consumo(*, manter_orcamento: bool = True) -> dict[str, Any]:
    """Zera contadores (útil após recarga)."""
    e = _estado_vazio() if not manter_orcamento else carregar_estado()
    orc = e.get("orcamento_usd")
    novo = _estado_vazio()
    if manter_orcamento and orc:
        novo["orcamento_usd"] = orc
    escrever_json_atomico(USO_PATH, novo)
    escrever_json_atomico(HIST_PATH, {"pontos": []})
    return resumo(novo)


def emitir_metricas_claude_datadog(
    r: dict[str, Any] | None = None,
    *,
    tokens_7d: float | None = None,
    tokens_7d_crescimento_pct: float | None = None,
    prompt_cache_ativo: bool | None = None,
    limite_mes_usd: float | None = None,
) -> dict[str, Any]:
    """Emite as métricas que o dashboard/monitores Claude já usam."""
    from core.datadog_metrics import gauge

    r = r or resumo()
    tags = ["fonte:consumo_claude"]
    if r.get("fonte_saldo"):
        tags.append(f"fonte_saldo:{r.get('fonte_saldo')}")
    gauge("claude.orcamento_consumido_usd", float(r.get("consumido_usd") or 0), tags=tags)
    gauge("claude.orcamento_restante_usd", float(r.get("restante_usd") or 0), tags=tags)
    gauge("claude.orcamento_usd", float(r.get("orcamento_usd") or 0), tags=tags)
    gauge("claude.assertividade_pct", float(r.get("assertividade_pct") or 0), tags=tags)
    if tokens_7d is not None:
        gauge("claude.tokens_7d", float(tokens_7d), tags=tags)
    if tokens_7d_crescimento_pct is not None:
        gauge("claude.tokens_7d_crescimento_pct", float(tokens_7d_crescimento_pct), tags=tags)
    if prompt_cache_ativo is not None:
        gauge("claude.prompt_cache_ativo", 1.0 if prompt_cache_ativo else 0.0, tags=tags)
    if limite_mes_usd is not None:
        gauge("claude.limite_mes_usd", float(limite_mes_usd), tags=tags)
    return r


def aplicar_saldo_console(
    creditos_usd: float,
    *,
    gasto_mes_usd: float | None = None,
    tokens_7d: float | None = None,
    tokens_7d_crescimento_pct: float | None = None,
    prompt_cache_ativo: bool | None = None,
    limite_mes_usd: float | None = None,
    emitir_datadog: bool = True,
) -> dict[str, Any]:
    """
    Alinha o orçamento local ao saldo do painel (print/console).
    restante = créditos; consumido = gasto do mês (se informado).
    """
    creditos = max(0.0, float(creditos_usd or 0))
    gasto = float(gasto_mes_usd) if gasto_mes_usd is not None else None

    def _patch(estado: dict[str, Any]) -> dict[str, Any]:
        used = float(gasto) if gasto is not None else float(estado.get("consumido_usd") or 0)
        # orçamento = consumido + créditos → restante bate com o painel
        estado["consumido_usd"] = round(max(0.0, used), 6)
        estado["orcamento_usd"] = round(max(0.0, used) + creditos, 6)
        estado["bloqueado"] = bool(
            estado["orcamento_usd"] > 0 and estado["consumido_usd"] >= estado["orcamento_usd"]
        )
        estado["fonte_saldo"] = "console_painel"
        estado["saldo_console_usd"] = round(creditos, 4)
        if gasto is not None:
            estado["gasto_mes_console_usd"] = round(gasto, 4)
        if tokens_7d is not None:
            estado["tokens_7d_console"] = float(tokens_7d)
        if tokens_7d_crescimento_pct is not None:
            estado["tokens_7d_crescimento_pct"] = float(tokens_7d_crescimento_pct)
        if prompt_cache_ativo is not None:
            estado["prompt_cache_ativo"] = bool(prompt_cache_ativo)
        if limite_mes_usd is not None:
            estado["limite_mes_console_usd"] = float(limite_mes_usd)
        estado["saldo_sincronizado_em"] = datetime.now(timezone.utc).isoformat()
        estado["atualizado_em"] = estado["saldo_sincronizado_em"]
        return estado

    estado = ler_e_atualizar_json(USO_PATH, _patch, default=_estado_vazio())
    r = resumo(estado if isinstance(estado, dict) else None)
    r["fonte_saldo"] = "console_painel"
    snap = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "creditos_usd": creditos,
        "gasto_mes_usd": gasto,
        "tokens_7d": tokens_7d,
        "tokens_7d_crescimento_pct": tokens_7d_crescimento_pct,
        "prompt_cache_ativo": prompt_cache_ativo,
        "limite_mes_usd": limite_mes_usd,
        "resumo": r,
    }
    escrever_json_atomico(PAINEL_PATH, snap)
    try:
        registrar_ponto_historico(r)
    except Exception as exc:
        logger.debug("historico claude apos sync painel: %s", exc)
    if emitir_datadog:
        emitir_metricas_claude_datadog(
            r,
            tokens_7d=tokens_7d,
            tokens_7d_crescimento_pct=tokens_7d_crescimento_pct,
            prompt_cache_ativo=prompt_cache_ativo,
            limite_mes_usd=limite_mes_usd,
        )
    return r


def _nome_agente_curto(origem: str, max_len: int = 40) -> str:
    nome = (origem or "desconhecido").strip() or "desconhecido"
    if len(nome) <= max_len:
        return nome
    return "…" + nome[-(max_len - 1) :]


def ranking_consumo_por_agente(
    r: dict[str, Any] | None = None,
    *,
    top: int = 15,
) -> list[dict[str, Any]]:
    """Lista agentes ordenados por US$ consumido (depois por chamadas)."""
    r = r or resumo()
    por = r.get("por_origem") or {}
    rows: list[dict[str, Any]] = []
    for nome, info in por.items():
        info = info or {}
        rows.append(
            {
                "agente": str(nome),
                "agente_curto": _nome_agente_curto(str(nome)),
                "usd": round(float(info.get("usd") or 0), 6),
                "chamadas": int(info.get("chamadas") or 0),
                "assertividade_pct": float(info.get("assertividade_pct") or 0),
                "ok": int(info.get("ok") or 0),
                "falha": int(info.get("falha") or 0),
            }
        )
    rows.sort(key=lambda x: (x["usd"], x["chamadas"]), reverse=True)
    return rows[: max(1, int(top))]


def carregar_historico() -> list[dict[str, Any]]:
    data = ler_json(HIST_PATH, default=None)
    if not isinstance(data, dict):
        return []
    pontos = data.get("pontos")
    return list(pontos) if isinstance(pontos, list) else []


def registrar_ponto_historico(r: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    Grava snapshot para o gráfico de andamento (consumido × tempo).
    Evita duplicar ponto idêntico no mesmo minuto UTC.
    """
    r = r or resumo()
    agora = datetime.now(timezone.utc)
    por = ranking_consumo_por_agente(r, top=20)
    ponto = {
        "ts": agora.isoformat(),
        "consumido_usd": float(r.get("consumido_usd") or 0),
        "restante_usd": float(r.get("restante_usd") or 0),
        "percentual_usado": float(r.get("percentual_usado") or 0),
        "chamadas": int(r.get("chamadas") or 0),
        "assertividade_pct": float(r.get("assertividade_pct") or 0),
        "por_agente_usd": {row["agente"]: row["usd"] for row in por},
    }
    pontos = carregar_historico()
    if pontos:
        ultimo = pontos[-1] or {}
        mesmo_minuto = str(ultimo.get("ts") or "")[:16] == ponto["ts"][:16]
        mesmo_consumo = abs(float(ultimo.get("consumido_usd") or 0) - ponto["consumido_usd"]) < 1e-9
        mesmas_chamadas = int(ultimo.get("chamadas") or 0) == ponto["chamadas"]
        if mesmo_minuto and mesmo_consumo and mesmas_chamadas:
            pontos[-1] = ponto
        else:
            pontos.append(ponto)
    else:
        pontos.append(ponto)
    pontos = pontos[-MAX_HIST_PONTOS:]
    escrever_json_atomico(HIST_PATH, {"pontos": pontos, "atualizado_em": agora.isoformat()})
    return pontos


def gerar_graficos_consumo(r: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Gera PNGs: barras US$ por agente + evolução temporal do consumido.
    Retorna caminhos (None se matplotlib indisponível / série curta).
    """
    from core import graficos

    r = r or resumo()
    pontos = registrar_ponto_historico(r)
    ranking = ranking_consumo_por_agente(r, top=15)
    out: dict[str, Any] = {
        "ranking": ranking,
        "historico_pontos": len(pontos),
        "por_agente": None,
        "evolucao": None,
    }
    if ranking:
        cats = [row["agente_curto"] for row in ranking]
        # Preferir US$; se todos zerados, mostrar chamadas para o painel não ficar vazio
        usos = [row["usd"] for row in ranking]
        usar_chamadas = all(u <= 0 for u in usos)
        if usar_chamadas:
            vals = [float(row["chamadas"]) for row in ranking]
            path = graficos.grafico_barras(
                cats,
                vals,
                GRAFICO_AGENTES_PATH,
                titulo="Claude — chamadas por agente (US$ ainda zerado)",
                rotulo_x="Chamadas",
                formato_valor=lambda v: f"{int(round(v))}×",
            )
        else:
            vals = usos
            path = graficos.grafico_barras(
                cats,
                vals,
                GRAFICO_AGENTES_PATH,
                titulo="Claude — consumo US$ por agente",
                rotulo_x="US$ consumido",
                formato_valor=lambda v: f"US$ {v:.4f}",
            )
        out["por_agente"] = str(path) if path else None
        out["metrica_barras"] = "chamadas" if usar_chamadas else "usd"

    if len(pontos) >= 2:
        path_ev = graficos.grafico_evolucao(
            pontos,
            [
                ("consumido_usd", "Consumido (US$)", "andamento do gasto"),
                ("restante_usd", "Restante (US$)", "saldo do orçamento"),
                ("percentual_usado", "% usado", "progresso do teto"),
            ],
            GRAFICO_EVOLUCAO_PATH,
            titulo="Claude — andamento do consumo",
            max_pontos=MAX_HIST_PONTOS,
            eixo_y_inteiro=False,
        )
        out["evolucao"] = str(path_ev) if path_ev else None
    return out
