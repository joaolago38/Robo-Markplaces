"""
agentes/leilao/agente_leilao_veiculo.py
Monitor 24h de leilões de veículos **recuperados de furto ou pequena/média monta** em leiloeiros
e portais DETRAN (todos os estados). Por padrão varre veículos (ano configurável) com rotação
de fontes e alerta no Telegram o Top-N por margem FIPE (após taxas e haircut de sinistro).

Configuração: catalogo/leiloes_veiculos_monitorados.json (modo legado por modelo)
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
    LEILAO_ALERTA_TOP_N,
    LEILAO_ALERTAR_TODOS_ACHADOS,
    LEILAO_ANO_MAX,
    LEILAO_ANO_MIN,
    LEILAO_BUSCA_TODOS_VEICULOS,
    LEILAO_IA_AVALIAR_PARAMETROS,
    LEILAO_INCLUIR_COPART_DIRETO,
    LEILAO_INCLUIR_SODRE_DIRETO,
    LEILAO_INCLUIR_SUMARE_DIRETO,
    LEILAO_INCLUIR_SUPERBID_DIRETO,
    LEILAO_MARGEM_FIPE_MIN_PCT,
    LEILAO_MARGEM_FIPE_MIN_REAIS,
    LEILAO_PAUSA_ENTRE_FONTES_SEG,
    LEILAO_PRECO_MAX_LANCE,
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
from integracoes.leilao.busca import (
    buscar_veiculo_em_fontes,
    obter_lotes_diretos,
    obter_lotes_sumare,
)
from integracoes.leilao.comparacao_fipe import avaliar_achado_leilao, filtrar_vantajosos

logger = logging.getLogger("agente_leilao_veiculo")

HISTORY_PATH = ROOT / "logs" / "leilao_veiculos_history.json"
SNAPSHOT_PATH = ROOT / "logs" / "leilao_veiculos_ultima.json"


def _veiculo_busca_todos() -> dict[str, Any]:
    return {
        "id": "todos_veiculos",
        "ativo": True,
        "prioridade": 1,
        "busca_todos": True,
        "perfil": "recuperado_furto_pequena_monta",
        "ano_min": LEILAO_ANO_MIN,
        "ano_max": LEILAO_ANO_MAX,
        "margem_fipe_min_pct": LEILAO_MARGEM_FIPE_MIN_PCT,
        "margem_fipe_min_reais": LEILAO_MARGEM_FIPE_MIN_REAIS,
        "preco_max_lance": LEILAO_PRECO_MAX_LANCE,
        "notas": "Varredura ampla — todos os veículos no intervalo de ano",
    }


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
    lotes_diretos: dict[str, list[dict[str, Any]]] | None = None,
    diag_diretos: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    vid = str(veiculo.get("id") or "").strip()
    nome = (
        str(veiculo.get("veiculo") or "").strip()
        or f"{veiculo.get('marca', '')} {veiculo.get('modelo', '')}".strip()
        or vid
    )
    entrada_hist = historico.get(vid) if isinstance(historico.get(vid), dict) else {}
    vistos: dict[str, Any] = dict(entrada_hist.get("vistos") or {})

    busca = buscar_veiculo_em_fontes(
        veiculo,
        pausa_entre_fontes_seg=LEILAO_PAUSA_ENTRE_FONTES_SEG,
        lotes_sumare=lotes_sumare,
        diag_sumare=diag_sumare,
        lotes_diretos=lotes_diretos,
        diag_diretos=diag_diretos,
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
    if item.get("descricao_veiculo"):
        desc = str(item["descricao_veiculo"])
    else:
        marca = str(item.get("marca") or "").strip()
        modelo = str(item.get("modelo") or "").strip()
        partes = [p for p in (marca, modelo) if p]
        desc = " ".join(partes)
    ano = item.get("ano")
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


def _montar_alerta(resultados: list[dict[str, Any]], *, todos_achados: bool = False) -> str:
    """Alerta compacto: Top-N por margem FIPE (ou por ordem se sem FIPE)."""
    from core.telegram_explicacao import cabecalho_agente

    titulo = cabecalho_agente(
        "leilao",
        (
            "🚗 *Leilões — veículos encontrados*"
            if todos_achados
            else "🚗 *Leilões — vantagem FIPE (lance + taxas)*"
        ),
    )
    itens: list[dict[str, Any]] = []
    for r in resultados:
        novos = r.get("novos") if todos_achados else (r.get("novos_vantajosos") or [])
        for item in novos or []:
            if isinstance(item, dict):
                itens.append(item)

    if not itens:
        return ""

    def _chave_rank(item: dict[str, Any]) -> float:
        try:
            return float(item.get("margem_fipe_pct") or -9999)
        except (TypeError, ValueError):
            return -9999.0

    itens.sort(key=_chave_rank, reverse=True)
    top_n = max(1, LEILAO_ALERTA_TOP_N)
    top = itens[:top_n]

    linhas = [
        titulo,
        "",
        f"_{len(itens)} item(ns); mostrando Top {len(top)} por margem FIPE._",
        "",
    ]
    for i, item in enumerate(top, 1):
        pct = item.get("margem_fipe_pct")
        delta = f"+{pct:.0f}%" if isinstance(pct, (int, float)) else "n/d"
        veiculo = _formatar_veiculo_item(item)
        lance = _fmt_brl(item.get("lance_brl") or item.get("valor"))
        fipe = _fmt_brl(item.get("valor_fipe")) if item.get("valor_fipe") else "FIPE n/d"
        haircut = ""
        if item.get("fipe_sinistro") and item.get("fipe_haircut_pct"):
            haircut = f" (FIPE −{item.get('fipe_haircut_pct'):.0f}% sinistro)"
        linhas.append(
            f"`{i}. {delta}` | {veiculo} | lance {lance} | {fipe}{haircut}"
        )
        linhas.append(f"   📍 {_formatar_local_item(item)}")
        url = item.get("url_anuncio") or item.get("url") or ""
        if url:
            linhas.append(f"   🔗 {url}")
    if len(itens) > top_n:
        linhas.append("")
        linhas.append(f"_… +{len(itens) - top_n} outros (ver logs/histórico)_")
    return "\n".join(linhas).strip()


def _agregar_diagnostico(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    totais = {
        "ddg_queries": 0,
        "ddg_brutos": 0,
        "ddg_descartados_filtro": 0,
        "ddg_detran_queries": 0,
        "ddg_detran_brutos": 0,
        "ddg_fontes_puladas": 0,
        "sumare_candidatos": 0,
        "sumare_achados": 0,
        "sumare_detran_candidatos": 0,
        "sumare_detran_achados": 0,
        "copart_candidatos": 0,
        "copart_achados": 0,
        "superbid_candidatos": 0,
        "superbid_achados": 0,
        "sodre_candidatos": 0,
        "sodre_achados": 0,
        "diretos_candidatos": 0,
        "diretos_achados": 0,
        "fontes_consultadas": 0,
    }
    circuit_breaker = False
    circuit_msg = None
    ddg_status = "ok"
    ddg_nota = None
    sumare_coleta: dict[str, Any] = {}
    coletores_diretos: dict[str, Any] = {}
    achados_ddg_por_dominio: dict[str, int] = {}
    meta_fontes: dict[str, Any] = {}
    _status_prio = {"ok": 0, "vazio": 1, "pulado": 2, "breaker": 3, "desabilitado": 4}

    for r in resultados:
        d = r.get("diagnostico") or {}
        for chave in totais:
            totais[chave] += int(d.get(chave) or 0)
        if d.get("circuit_breaker_ativo"):
            circuit_breaker = True
        if d.get("circuit_breaker_msg"):
            circuit_msg = d["circuit_breaker_msg"]
        st = d.get("ddg_status")
        if st and _status_prio.get(str(st), 0) >= _status_prio.get(ddg_status, 0):
            ddg_status = str(st)
            if d.get("ddg_nota"):
                ddg_nota = d["ddg_nota"]
        elif d.get("ddg_nota") and ddg_nota is None:
            ddg_nota = d["ddg_nota"]
        if d.get("sumare_coleta"):
            sumare_coleta = d["sumare_coleta"]
        if d.get("coletores_diretos"):
            coletores_diretos = d["coletores_diretos"]
        for dom, n in (d.get("achados_ddg_por_dominio") or {}).items():
            achados_ddg_por_dominio[dom] = achados_ddg_por_dominio.get(dom, 0) + int(n or 0)
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
        "ddg_status": ddg_status,
        "ddg_nota": ddg_nota,
        "sumare_coleta": sumare_coleta,
        "coletores_diretos": coletores_diretos,
        "achados_ddg_por_dominio": achados_ddg_por_dominio,
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
    from core.telegram_explicacao import cabecalho_agente

    linhas = [
        cabecalho_agente("leilao", "🚗 *Leilões — resumo da varredura (FIPE × taxas)*"),
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
        coletores = diag.get("coletores_diretos") or {}
        for nome, flag, rotulo in (
            ("copart", LEILAO_INCLUIR_COPART_DIRETO, "Copart"),
            ("superbid", LEILAO_INCLUIR_SUPERBID_DIRETO, "Superbid"),
            ("sodre", LEILAO_INCLUIR_SODRE_DIRETO, "Sodré"),
        ):
            if not flag:
                continue
            c = coletores.get(nome) or {}
            linhas.append(
                f"{rotulo} direto: {c.get('lotes_veiculo', 0)} lotes "
                f"(modo={c.get('modo_coleta') or '?'}, "
                f"{c.get('leiloes_ok', 0)} OK / {c.get('leiloes_falha', 0)} falha)"
            )
        status = diag.get("ddg_status") or "ok"
        linhas.append(
            f"DDG ({status}): {diag.get('ddg_queries', 0)} queries, "
            f"{diag.get('ddg_brutos', 0)} brutos, "
            f"{diag.get('ddg_descartados_filtro', 0)} descartados no filtro"
            + (
                f", {diag.get('ddg_fontes_puladas', 0)} fonte(s) pulada(s)"
                if int(diag.get("ddg_fontes_puladas") or 0)
                else ""
            )
        )
        if int(diag.get("ddg_detran_queries") or 0) or int(diag.get("sumare_detran_candidatos") or 0):
            linhas.append(
                f"DETRAN: DDG {diag.get('ddg_detran_brutos', 0)} brutos "
                f"({diag.get('ddg_detran_queries', 0)} queries) | "
                f"Sumaré {diag.get('sumare_detran_achados', 0)} achado(s) de "
                f"{diag.get('sumare_detran_candidatos', 0)} lote(s) comitente DETRAN"
            )
        por_dom = diag.get("achados_ddg_por_dominio") or {}
        if por_dom:
            top_dom = sorted(por_dom.items(), key=lambda x: -x[1])[:5]
            linhas.append(
                "DDG por domínio: "
                + ", ".join(f"{dom}={n}" for dom, n in top_dom)
            )
        linhas.append(
            f"Diretos no veículo: {diag.get('diretos_achados', 0)} achados de "
            f"{diag.get('diretos_candidatos', 0)} candidatos "
            f"(Sumaré {diag.get('sumare_achados', 0)}, "
            f"Copart {diag.get('copart_achados', 0)}, "
            f"Superbid {diag.get('superbid_achados', 0)}, "
            f"Sodré {diag.get('sodre_achados', 0)})"
        )
        if diag.get("ddg_nota"):
            linhas.append(f"Nota DDG: {diag['ddg_nota']}")

    ddg = diag.get("circuit_breaker_msg") or mensagem_circuit_breaker("leilao")
    if ddg:
        linhas.extend(["", f"⚠️ {ddg}"])
    elif total_achados == 0:
        status = diag.get("ddg_status") or ""
        if status in ("breaker", "pulado", "desabilitado"):
            nota = (
                "_Nenhum anúncio: DDG indisponível nesta rodada; "
                "DETRAN depende de Sumaré/comitente DETRAN ou próxima rodada com DDG OK._"
            )
        elif status == "vazio":
            nota = (
                "_Nenhum anúncio: DDG sem resultados (rate limit/indexação); "
                "coletores diretos também sem match do veículo._"
            )
        else:
            nota = "_Nenhum anúncio encontrado nesta rodada (DDG/leiloeiros/coletores)._"
        linhas.extend(["", nota])
    elif total_vantajosos == 0:
        linhas.extend([
            "",
            "_Achados sem vantagem FIPE suficiente (lance + comissão + taxas vs tabela)._",
        ])
    secao_ia = formatar_secao_ia(ia)
    if secao_ia:
        linhas.append(secao_ia)
    return "\n".join(linhas).strip()


def _todos_novos(resultados: list[dict[str, Any]]) -> list[dict[str, Any]]:
    itens: list[dict[str, Any]] = []
    for r in resultados:
        itens.extend(r.get("novos") or [])
    return itens


def _todos_novos_vantajosos(resultados: list[dict[str, Any]]) -> list[dict[str, Any]]:
    itens: list[dict[str, Any]] = []
    for r in resultados:
        itens.extend(r.get("novos_vantajosos") or [])
    return itens


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    """
    Varre leiloeiros + DETRAN (todas as fontes por padrão) e notifica Telegram.
    Modo padrão: todos os veículos (ano 2000–2020), alerta de cada achado novo.
    """
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning(
                "Telegram gestor não configurado (TELEGRAM_TOKEN / TELEGRAM_GESTOR_CHAT_ID) — "
                "alertas de leilão não serão entregues"
            )

        if LEILAO_BUSCA_TODOS_VEICULOS:
            veiculos = [_veiculo_busca_todos()]
            veiculos[0]["veiculo"] = (
                f"Todos os veículos ({LEILAO_ANO_MIN}–{LEILAO_ANO_MAX})"
            )
        else:
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

        lotes_diretos: dict[str, list[dict[str, Any]]] = {}
        diag_diretos: dict[str, dict[str, Any]] = {}
        for nome, lots_diag in obter_lotes_diretos().items():
            lots, diag_c = lots_diag
            lotes_diretos[nome] = lots
            diag_diretos[nome] = diag_c

        for veiculo in veiculos:
            vid = str(veiculo.get("id") or "").strip()
            if not vid:
                continue
            nome = veiculo.get("veiculo") or f"{veiculo.get('marca', '')} {veiculo.get('modelo', '')}".strip()
            logger.info("Varrendo leilões: %s", nome or vid)
            resultado = _monitorar_veiculo(
                veiculo,
                historico,
                lotes_sumare=lotes_sumare,
                diag_sumare=diag_sumare,
                lotes_diretos=lotes_diretos,
                diag_diretos=diag_diretos,
            )
            if nome:
                resultado["veiculo"] = nome
            resultados.append(resultado)

        diagnostico_agregado = _agregar_diagnostico(resultados)

        _salvar_historico(historico)

        ia_parametros = None
        if LEILAO_IA_AVALIAR_PARAMETROS and not LEILAO_BUSCA_TODOS_VEICULOS:
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

        com_novos = [r for r in resultados if r.get("novos")]
        com_vantajosos = [r for r in resultados if r.get("novos_vantajosos")]
        alerta_novos_enviado = False
        alerta_resumo_enviado = False

        if enviar_alerta:
            if LEILAO_ALERTAR_TODOS_ACHADOS and com_novos:
                novos_itens = _todos_novos(com_novos)
                msg = _montar_alerta(com_novos, todos_achados=True)
                chave = chave_itens_novos("leilao:veiculos:todos", novos_itens)
            elif com_vantajosos:
                novos_itens = _todos_novos_vantajosos(com_vantajosos)
                msg = _montar_alerta(com_vantajosos, todos_achados=False)
                chave = chave_itens_novos("leilao:veiculos:vantagem_fipe", novos_itens)
            else:
                msg = ""
                novos_itens = []

            if msg:
                alerta_novos_enviado = bool(
                    alertar_gestor(
                        msg,
                        chave=chave,
                        cooldown_segundos=86400,
                        agente_id="leilao",
                    )
                )
                if not alerta_novos_enviado:
                    logger.warning(
                        "%s achado(s) novo(s) mas alerta não enviado (cooldown ou Telegram)",
                        len(novos_itens),
                    )

        if enviar_alerta and LEILAO_ALERTA_RESUMO:
            msg_resumo = _montar_resumo_varredura(resultados, ia_parametros, diagnostico_agregado)
            alerta_resumo_enviado = bool(
                alertar_gestor(
                    msg_resumo,
                    chave=chave_resumo_periodo("leilao", horas_por_bucket=1),
                    cooldown_segundos=LEILAO_ALERTA_RESUMO_COOLDOWN_SEG,
                    agente_id="leilao",
                )
            )
            if not alerta_resumo_enviado:
                logger.info("Leilão: resumo não enviado (cooldown ou Telegram indisponível)")

        return {
            "ok": True,
            "total_veiculos": len(resultados),
            "com_novos": len(com_novos),
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
        "Monitor leilões: %s veículo(s), %s com novos, %s com vantagem FIPE nova, alerta=%s",
        resultado.get("total_veiculos"),
        resultado.get("com_novos"),
        resultado.get("com_vantajosos"),
        resultado.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
