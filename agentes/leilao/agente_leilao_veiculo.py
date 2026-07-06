"""
agentes/leilao/agente_leilao_veiculo.py
Monitor 24h de leilões de veículos **recuperados de furto ou pequena/média monta** em leiloeiros
e portais DETRAN (todos os estados). Modelos prioritários no catálogo padrão:
Fiorino Furgão → Gol → Civic → City → Fit.

Configuração: catalogo/leiloes_veiculos_monitorados.json
Somente leitura + alertas — não participa de leilões.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    LEILAO_ALERTA_RESUMO,
    LEILAO_ALERTA_RESUMO_COOLDOWN_SEG,
    LEILAO_IA_AVALIAR_PARAMETROS,
    LEILAO_INCLUIR_SUMARE_DIRETO,
    LEILAO_PAUSA_ENTRE_FONTES_SEG,
    LEILAO_VEICULOS_CATALOGO,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.ddg_lite import mensagem_circuit_breaker
from core.notificador import alertar_gestor, chave_itens_novos, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.leilao.avaliacao_ia_parametros import (
    avaliar_parametros_leilao_veiculos,
    formatar_secao_ia,
)
from integracoes.leilao.busca import buscar_veiculo_em_fontes, obter_lotes_sumare
from integracoes.leilao.comparacao_fipe import avaliar_achado_leilao, filtrar_vantajosos

logger = logging.getLogger("agente_leilao_veiculo")

HISTORY_PATH = ROOT / "logs" / "leilao_veiculos_history.json"
SNAPSHOT_PATH = ROOT / "logs" / "leilao_veiculos_ultima.json"


def _carregar_veiculos() -> list[dict[str, Any]]:
    caminho = ROOT / LEILAO_VEICULOS_CATALOGO
    try:
        if not caminho.is_file():
            logger.warning("Catálogo de leilões não encontrado: %s", caminho)
            return []
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        return [v for v in data if isinstance(v, dict) and v.get("ativo")]
    except Exception as exc:
        logger.error("Erro ao carregar catálogo de leilões: %s", exc)
        return []


def _carregar_historico() -> dict[str, Any]:
    return ler_json(HISTORY_PATH, default={})


def _salvar_historico(historico: dict[str, Any]) -> None:
    try:
        escrever_json_atomico(HISTORY_PATH, historico)
    except Exception as exc:
        logger.error("Erro ao salvar histórico de leilões: %s", exc)


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def _params_fipe_veiculo(veiculo: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for chave_src, chave_dst in (
        ("margem_fipe_min_pct", "margem_min_pct"),
        ("margem_fipe_min_reais", "margem_min_reais"),
        ("preco_max_lance", "preco_max_lance"),
    ):
        val = veiculo.get(chave_src)
        if val is not None:
            try:
                out[chave_dst] = float(val)
            except (TypeError, ValueError):
                pass
    return out


def _analisar_achados(veiculo: dict[str, Any], achados: list[dict[str, Any]]) -> list[dict[str, Any]]:
    params = _params_fipe_veiculo(veiculo)
    return [avaliar_achado_leilao(item, veiculo, **params) for item in achados]


def _monitorar_veiculo(
    veiculo: dict[str, Any],
    historico: dict[str, Any],
    *,
    lotes_sumare: list[dict[str, Any]] | None = None,
    diag_sumare: dict[str, Any] | None = None,
) -> dict[str, Any]:
    vid = str(veiculo.get("id") or "").strip()
    nome = f"{veiculo.get('marca', '')} {veiculo.get('modelo', '')}".strip()
    entrada_hist = historico.get(vid) if isinstance(historico.get(vid), dict) else {}
    vistos: dict[str, Any] = dict(entrada_hist.get("vistos") or {})

    busca = buscar_veiculo_em_fontes(
        veiculo,
        pausa_entre_fontes_seg=LEILAO_PAUSA_ENTRE_FONTES_SEG,
        lotes_sumare=lotes_sumare,
        diag_sumare=diag_sumare,
    )
    brutos = busca.get("achados") or []
    diagnostico = busca.get("diagnostico") or {}
    achados = _analisar_achados(veiculo, brutos)
    vantajosos = filtrar_vantajosos(achados)
    novos: list[dict[str, Any]] = []
    novos_vantajosos: list[dict[str, Any]] = []
    agora = datetime.now(timezone.utc).isoformat()

    for item in achados:
        h = item.get("hash") or ""
        if not h:
            continue
        if h not in vistos:
            registro = {**item, "visto_em": agora}
            vistos[h] = registro
            novos.append(registro)
            if item.get("vantajoso"):
                novos_vantajosos.append(registro)

    historico[vid] = {
        "veiculo": nome,
        "vistos": vistos,
        "ultima_varredura": agora,
        "total_achados_rodada": len(achados),
        "total_vantajosos_rodada": len(vantajosos),
    }

    gauge("leilao.achados_por_veiculo", len(achados), tags=[f"veiculo:{vid}"])
    gauge("leilao.vantajosos_por_veiculo", len(vantajosos), tags=[f"veiculo:{vid}"])
    incrementar("leilao.novos", len(novos), tags=[f"veiculo:{vid}"])
    incrementar("leilao.vantajosos", len(vantajosos), tags=[f"veiculo:{vid}"])
    _logar_achados(veiculo, achados, novos)

    return {
        "id": vid,
        "veiculo": nome,
        "prioridade": int(veiculo.get("prioridade") or 99),
        "achados_total": len(achados),
        "vantajosos_total": len(vantajosos),
        "novos": novos,
        "novos_vantajosos": novos_vantajosos,
        "diagnostico": diagnostico,
        "ok": True,
    }


def _formatar_local_item(item: dict[str, Any]) -> str:
    cidade = str(item.get("cidade") or "").strip()
    uf = str(item.get("uf") or "").strip()
    if item.get("fonte_tipo") == "detran":
        detran = str(item.get("detran_nome") or item.get("fonte_nome") or "").strip()
        if cidade and detran:
            return f"{cidade} — {detran}"
        if cidade and uf:
            return f"{cidade} — DETRAN {uf}"
        return detran or (f"DETRAN {uf}" if uf else str(item.get("fonte_nome") or "?"))
    partes: list[str] = []
    if cidade and uf:
        partes.append(f"{cidade}/{uf}")
    elif cidade:
        partes.append(cidade)
    fonte = str(item.get("fonte_nome") or item.get("fonte_id") or "").strip()
    if fonte:
        partes.append(fonte)
    return " — ".join(partes) if partes else "?"


def _formatar_veiculo_item(item: dict[str, Any]) -> str:
    marca = str(item.get("marca") or "").strip()
    modelo = str(item.get("modelo") or "").strip()
    ano = item.get("ano")
    partes = [p for p in (marca, modelo) if p]
    desc = " ".join(partes)
    if ano:
        desc = f"{desc} {ano}".strip()
    return desc or str(item.get("titulo") or "Veículo")[:60]


def _formatar_valor_item(item: dict[str, Any]) -> str:
    return str(item.get("valor") or "valor n/d")


def _formatar_data_item(item: dict[str, Any]) -> str:
    return str(item.get("data_leilao") or "data n/d")


def _formatar_cadastro_item(item: dict[str, Any]) -> str:
    return str(item.get("url_cadastro") or "cadastro n/d")


def _formatar_analise_fipe(item: dict[str, Any]) -> str:
    if not item.get("valor_fipe"):
        motivo = (item.get("analise_fipe") or {}).get("motivo") or "FIPE n/d"
        return f"FIPE: {motivo}"
    custo = item.get("custo_total_brl")
    margem = item.get("margem_fipe_reais")
    pct = item.get("margem_fipe_pct")
    emoji = "✅" if item.get("vantajoso") else "⚠️"
    return (
        f"{emoji} FIPE {_fmt_brl(item.get('valor_fipe'))} | "
        f"custo leilão {_fmt_brl(custo)} | "
        f"vantagem {_fmt_brl(margem)} ({pct}%)"
    )


def _logar_linha_item(item: dict[str, Any], *, prefix: str) -> None:
    logger.info(
        "%s %s | %s | %s | %s | %s | cadastro: %s | %s",
        prefix,
        _formatar_local_item(item),
        _formatar_veiculo_item(item),
        _formatar_valor_item(item),
        _formatar_analise_fipe(item),
        _formatar_data_item(item),
        _formatar_cadastro_item(item),
        item.get("url_anuncio") or item.get("url", ""),
    )


def _logar_achados(
    veiculo: dict[str, Any],
    achados: list[dict[str, Any]],
    novos: list[dict[str, Any]],
) -> None:
    nome = f"{veiculo.get('marca', '')} {veiculo.get('modelo', '')}".strip() or str(
        veiculo.get("id") or "?"
    )

    if not achados:
        logger.info("Leilão %s: nenhum achado nesta rodada", nome)
        ddg = mensagem_circuit_breaker("leilao")
        if ddg:
            logger.warning("Leilão %s: %s", nome, ddg)
        return

    logger.info("Leilão %s: %s achado(s) nesta rodada", nome, len(achados))
    for item in achados[:8]:
        _logar_linha_item(item, prefix="  •")
    if len(achados) > 8:
        logger.info("  … e mais %s achado(s) nesta rodada", len(achados) - 8)

    if novos:
        logger.info("Leilão %s: %s achado(s) NOVO(S)", nome, len(novos))
        for item in novos[:5]:
            _logar_linha_item(item, prefix="  ★ NOVO:")
        if len(novos) > 5:
            logger.info("  … e mais %s novo(s)", len(novos) - 5)


def _montar_alerta(resultados: list[dict[str, Any]]) -> str:
    linhas = ["🚗 *Leilões — vantagem FIPE (lance + taxas)*", ""]
    ordenados = sorted(resultados, key=lambda r: int(r.get("prioridade") or 99))
    tem_item = False
    for r in ordenados:
        novos = r.get("novos_vantajosos") or []
        if not novos:
            continue
        tem_item = True
        linhas.append(f"*{r.get('veiculo', r.get('id', ''))}* ({len(novos)} com vantagem FIPE):")
        for item in novos[:8]:
            linhas.append(f"📍 {_formatar_local_item(item)}")
            linhas.append(f"🚙 {_formatar_veiculo_item(item)}")
            if item.get("valor") or item.get("lance_brl"):
                linhas.append(f"💰 Lance {_fmt_brl(item.get('lance_brl') or item.get('valor'))}")
            if item.get("valor_fipe"):
                linhas.append(f"📊 FIPE {_fmt_brl(item['valor_fipe'])} ({item.get('modelo_fipe', '')})")
                linhas.append(
                    f"💸 Custo total leilão {_fmt_brl(item.get('custo_total_brl'))} "
                    f"(+{_fmt_brl(item.get('comissao_leiloeiro_brl'))} comissão + taxas)"
                )
                linhas.append(
                    f"✅ Vantagem {_fmt_brl(item.get('margem_fipe_reais'))} "
                    f"({item.get('margem_fipe_pct')}% abaixo FIPE)"
                )
            if item.get("data_leilao"):
                linhas.append(f"📅 {item['data_leilao']}")
            if item.get("url_cadastro"):
                linhas.append(f"📝 Cadastro: {item['url_cadastro']}")
            linhas.append(f"🔗 {item.get('url_anuncio') or item.get('url', '')}")
            linhas.append("")
        if len(novos) > 8:
            linhas.append(f"… e mais {len(novos) - 8}")
        linhas.append("")
    if not tem_item:
        return ""
    return "\n".join(linhas).strip()


def _agregar_diagnostico(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    totais = {
        "ddg_queries": 0,
        "ddg_brutos": 0,
        "ddg_descartados_filtro": 0,
        "sumare_candidatos": 0,
        "sumare_achados": 0,
        "fontes_consultadas": 0,
    }
    circuit_breaker = False
    circuit_msg = None
    sumare_coleta: dict[str, Any] = {}
    meta_fontes: dict[str, Any] = {}

    for r in resultados:
        d = r.get("diagnostico") or {}
        for chave in totais:
            totais[chave] += int(d.get(chave) or 0)
        if d.get("circuit_breaker_ativo"):
            circuit_breaker = True
        if d.get("circuit_breaker_msg"):
            circuit_msg = d["circuit_breaker_msg"]
        if d.get("sumare_coleta"):
            sumare_coleta = d["sumare_coleta"]
        if d.get("leiloeiros_na_rodada") and not meta_fontes:
            meta_fontes = {
                "hora_utc": d.get("hora_utc"),
                "leiloeiros_na_rodada": d.get("leiloeiros_na_rodada"),
                "detrans_na_rodada": d.get("detrans_na_rodada"),
                "leiloeiros_ids": d.get("leiloeiros_ids"),
                "detrans_ufs": d.get("detrans_ufs"),
            }

    return {
        **totais,
        "circuit_breaker_ativo": circuit_breaker,
        "circuit_breaker_msg": circuit_msg,
        "sumare_coleta": sumare_coleta,
        "meta_fontes": meta_fontes,
    }


def _montar_resumo_varredura(
    resultados: list[dict[str, Any]],
    ia: dict[str, Any] | None = None,
    diagnostico_agregado: dict[str, Any] | None = None,
) -> str:
    total_achados = sum(int(r.get("achados_total") or 0) for r in resultados)
    total_novos = sum(len(r.get("novos") or []) for r in resultados)
    total_vantajosos = sum(int(r.get("vantajosos_total") or 0) for r in resultados)
    total_novos_vantajosos = sum(len(r.get("novos_vantajosos") or []) for r in resultados)
    linhas = [
        "🚗 *Leilões — resumo da varredura (FIPE × taxas)*",
        "",
        f"Veículos monitorados: {len(resultados)}",
        f"Achados nesta rodada: {total_achados}",
        f"Com vantagem FIPE: {total_vantajosos}",
        f"Novos: {total_novos} | Novos com vantagem: {total_novos_vantajosos}",
        "",
    ]
    for r in sorted(resultados, key=lambda x: int(x.get("prioridade") or 99)):
        achados = int(r.get("achados_total") or 0)
        vant = int(r.get("vantajosos_total") or 0)
        novos = len(r.get("novos") or [])
        novos_v = len(r.get("novos_vantajosos") or [])
        linhas.append(
            f"• {r.get('veiculo', r.get('id', '?'))}: "
            f"{achados} achado(s), {vant} vantagem FIPE, {novos} novo(s), {novos_v} novo(s) vantajoso(s)"
        )

    diag = diagnostico_agregado or _agregar_diagnostico(resultados)
    if diag:
        linhas.extend(["", "*Diagnóstico da coleta*"])
        meta = diag.get("meta_fontes") or {}
        if meta:
            ufs = ", ".join(meta.get("detrans_ufs") or []) or "n/d"
            leil = ", ".join(meta.get("leiloeiros_ids") or []) or "n/d"
            linhas.append(
                f"Fontes DDG: {meta.get('leiloeiros_na_rodada', 0)} leiloeiros ({leil}) + "
                f"{meta.get('detrans_na_rodada', 0)} DETRAN ({ufs})"
            )
        sumare = diag.get("sumare_coleta") or {}
        if LEILAO_INCLUIR_SUMARE_DIRETO:
            linhas.append(
                f"Sumaré direto: {sumare.get('lotes_veiculo', 0)} lotes catálogo "
                f"({sumare.get('leiloes_ok', 0)} leilões OK, {sumare.get('leiloes_falha', 0)} falhas)"
            )
        linhas.append(
            f"DDG: {diag.get('ddg_queries', 0)} queries, {diag.get('ddg_brutos', 0)} brutos, "
            f"{diag.get('ddg_descartados_filtro', 0)} descartados no filtro"
        )
        linhas.append(
            f"Sumaré no veículo: {diag.get('sumare_achados', 0)} achados de "
            f"{diag.get('sumare_candidatos', 0)} candidatos"
        )

    ddg = diag.get("circuit_breaker_msg") or mensagem_circuit_breaker("leilao")
    if ddg:
        linhas.extend(["", f"⚠️ {ddg}"])
    elif total_achados == 0:
        linhas.extend(["", "_Nenhum anúncio encontrado nesta rodada (DDG/leiloeiros)._"])
    elif total_vantajosos == 0:
        linhas.extend([
            "",
            "_Achados sem vantagem FIPE suficiente (lance + comissão + taxas vs tabela)._",
        ])
    secao_ia = formatar_secao_ia(ia)
    if secao_ia:
        linhas.append(secao_ia)
    return "\n".join(linhas).strip()


def _todos_novos_vantajosos(resultados: list[dict[str, Any]]) -> list[dict[str, Any]]:
    itens: list[dict[str, Any]] = []
    for r in resultados:
        itens.extend(r.get("novos_vantajosos") or [])
    return itens


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    """
    Varre leiloeiros + DETRAN (27 UFs) para cada veículo ativo no catálogo.
    Alerta apenas achados novos (não repetidos). Nunca lança exceção.
    """
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning(
                "Telegram gestor não configurado (TELEGRAM_TOKEN / TELEGRAM_GESTOR_CHAT_ID) — "
                "alertas de leilão não serão entregues"
            )

        veiculos = _carregar_veiculos()
        if not veiculos:
            logger.info("Nenhum veículo ativo em %s", LEILAO_VEICULOS_CATALOGO)
            return {"ok": True, "total_veiculos": 0, "resultados": [], "alerta_enviado": False}

        veiculos = sorted(veiculos, key=lambda v: int(v.get("prioridade") or 99))
        historico = _carregar_historico()
        resultados: list[dict[str, Any]] = []

        lotes_sumare: list[dict[str, Any]] = []
        diag_sumare: dict[str, Any] = {}
        if LEILAO_INCLUIR_SUMARE_DIRETO:
            lotes_sumare, diag_sumare = obter_lotes_sumare()

        for veiculo in veiculos:
            vid = str(veiculo.get("id") or "").strip()
            if not vid:
                continue
            logger.info("Varrendo leilões: %s %s", veiculo.get("marca"), veiculo.get("modelo"))
            resultados.append(
                _monitorar_veiculo(
                    veiculo,
                    historico,
                    lotes_sumare=lotes_sumare,
                    diag_sumare=diag_sumare,
                )
            )

        diagnostico_agregado = _agregar_diagnostico(resultados)

        _salvar_historico(historico)

        ia_parametros = None
        if LEILAO_IA_AVALIAR_PARAMETROS:
            ia_parametros = avaliar_parametros_leilao_veiculos(
                veiculos_catalogo=veiculos,
                resultados=resultados,
            )

        agora = datetime.now(timezone.utc).isoformat()
        escrever_json_atomico(
            SNAPSHOT_PATH,
            {
                "timestamp": agora,
                "resultados": resultados,
                "avaliacao_ia_parametros": ia_parametros,
                "diagnostico_agregado": diagnostico_agregado,
            },
        )

        com_vantajosos = [r for r in resultados if r.get("novos_vantajosos")]
        alerta_novos_enviado = False
        alerta_resumo_enviado = False

        if enviar_alerta and com_vantajosos:
            novos_itens = _todos_novos_vantajosos(com_vantajosos)
            msg = _montar_alerta(com_vantajosos)
            if msg:
                alerta_novos_enviado = bool(
                    alertar_gestor(
                        msg,
                        chave=chave_itens_novos("leilao:veiculos:vantagem_fipe", novos_itens),
                        cooldown_segundos=86400,
                    )
                )
                if not alerta_novos_enviado:
                    logger.warning(
                        "%s achado(s) com vantagem FIPE mas alerta não enviado (cooldown ou Telegram)",
                        len(novos_itens),
                    )

        if enviar_alerta and LEILAO_ALERTA_RESUMO:
            msg_resumo = _montar_resumo_varredura(resultados, ia_parametros, diagnostico_agregado)
            alerta_resumo_enviado = bool(
                alertar_gestor(
                    msg_resumo,
                    chave=chave_resumo_periodo("leilao", horas_por_bucket=1),
                    cooldown_segundos=LEILAO_ALERTA_RESUMO_COOLDOWN_SEG,
                )
            )
            if not alerta_resumo_enviado:
                logger.info("Leilão: resumo não enviado (cooldown ou Telegram indisponível)")

        return {
            "ok": True,
            "total_veiculos": len(resultados),
            "com_vantajosos": len(com_vantajosos),
            "alerta_enviado": alerta_novos_enviado or alerta_resumo_enviado,
            "alerta_novos_enviado": alerta_novos_enviado,
            "alerta_resumo_enviado": alerta_resumo_enviado,
            "avaliacao_ia_parametros": ia_parametros,
            "diagnostico_agregado": diagnostico_agregado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Agente leilão veículos erro: %s", exc)
        return {"ok": False, "erro": str(exc), "resultados": []}


def main() -> int:
    logger.info("=== Monitor de leilões de veículos (24h) ===")
    resultado = executar(enviar_alerta=True)
    if not resultado.get("ok"):
        logger.error("Monitor leilões falhou: %s", resultado.get("erro"))
        return 1
    logger.info(
        "Monitor leilões: %s veículo(s), %s com vantagem FIPE nova, alerta=%s",
        resultado.get("total_veiculos"),
        resultado.get("com_vantajosos"),
        resultado.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
