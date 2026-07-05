"""
integracoes/datadog/vigia_saude.py
Detecta inatividade e erros não verificados (espelho local + Datadog API).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from core.atomic_io import ler_json
from core.config import ROOT
from integracoes.datadog.buffer_erros import listar_erros_recentes
from integracoes.datadog.consulta_erros import buscar_erros_datadog

logger = logging.getLogger("vigia_saude_datadog")


def _parse_iso(valor: Any) -> datetime | None:
    if not valor:
        return None
    try:
        txt = str(valor).strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _horas_desde(dt: datetime) -> float:
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0


def _fmt_horas(horas: float) -> str:
    if horas < 1:
        return f"{int(horas * 60)}min"
    h = int(horas)
    m = int((horas - h) * 60)
    return f"{h}h{m:02d}m" if m else f"{h}h"


def _chave_mensagem(msg: str) -> str:
    return str(msg or "").strip().lower()[:80]


def _gravidade_relevante(gravidade: str | None) -> bool:
    return str(gravidade or "").lower() in {"critica", "alta"}


def carregar_filtros_erro(catalogo_relativo: str) -> dict[str, Any]:
    caminho = ROOT / catalogo_relativo
    data = ler_json(caminho, default={})
    return data if isinstance(data, dict) else {}


def _erro_relevante_para_vigia(erro: dict[str, Any], filtros: dict[str, Any]) -> bool:
    """
    Mantém alertas focados no Mercado Livre: ignora ruído de outros marketplaces
    e infraestrutura (Telegram, Claude, Panorama, etc.).
    """
    if not filtros:
        return True

    logger_name = str(erro.get("logger") or "")
    msg = str(erro.get("mensagem") or erro.get("error_message") or "")
    msg_lower = msg.lower()

    for ign in filtros.get("mensagens_ignorar") or []:
        if str(ign).lower() in msg_lower:
            return False

    if logger_name in set(filtros.get("loggers_ignorar") or []):
        return False

    loggers_ml = set(filtros.get("loggers_ml") or [])
    if not loggers_ml:
        return True

    if logger_name not in loggers_ml:
        return False

    loggers_multi = set(filtros.get("loggers_multi_ml") or [])
    if logger_name in loggers_multi:
        padroes = filtros.get("mensagens_ml_obrigatorias") or []
        return any(str(p).lower() in msg_lower for p in padroes)

    return True


def carregar_fontes(catalogo_relativo: str) -> list[dict[str, Any]]:
    caminho = ROOT / catalogo_relativo
    data = ler_json(caminho, default=[])
    if not isinstance(data, list):
        return []
    return [f for f in data if isinstance(f, dict) and f.get("ativo", True)]


def verificar_inatividade(
    fontes: list[dict[str, Any]],
    *,
    limite_horas_padrao: float = 2.0,
) -> list[dict[str, Any]]:
    alertas: list[dict[str, Any]] = []
    for fonte in fontes:
        fid = str(fonte.get("id") or "?")
        nome = str(fonte.get("nome") or fid)
        rel_path = str(fonte.get("path") or "").strip()
        campo = str(fonte.get("campo") or "timestamp").strip()
        max_horas = float(fonte.get("max_horas") or limite_horas_padrao)
        critico = bool(fonte.get("critico", True))

        caminho = ROOT / rel_path
        if not caminho.is_file():
            if bool(fonte.get("ignorar_ausente", False)):
                continue
            alertas.append(
                {
                    "tipo": "inatividade",
                    "gravidade": "alta" if critico else "media",
                    "fonte_id": fid,
                    "nome": nome,
                    "motivo": "arquivo_ausente",
                    "horas_sem_resposta": None,
                    "limite_horas": max_horas,
                    "texto": (
                        f"*{nome}*: nunca executou ou arquivo `{rel_path}` ausente — "
                        f"sem heartbeat registrado."
                    ),
                }
            )
            continue

        data = ler_json(caminho, default={})
        ts_raw = data.get(campo) if isinstance(data, dict) else None
        if ts_raw is None and isinstance(data, dict) and campo == "timestamp":
            ts_raw = data.get("ultima_varredura") or data.get("ultima_execucao")

        dt = _parse_iso(ts_raw)
        if dt is None:
            alertas.append(
                {
                    "tipo": "inatividade",
                    "gravidade": "alta" if critico else "media",
                    "fonte_id": fid,
                    "nome": nome,
                    "motivo": "timestamp_invalido",
                    "horas_sem_resposta": None,
                    "limite_horas": max_horas,
                    "texto": f"*{nome}*: heartbeat em `{rel_path}` sem timestamp válido.",
                }
            )
            continue

        horas = _horas_desde(dt)
        if horas > max_horas:
            alertas.append(
                {
                    "tipo": "inatividade",
                    "gravidade": "critica" if critico else "alta",
                    "fonte_id": fid,
                    "nome": nome,
                    "motivo": "sem_resposta",
                    "horas_sem_resposta": round(horas, 2),
                    "limite_horas": max_horas,
                    "ultimo_timestamp": dt.isoformat(),
                    "texto": (
                        f"*{nome}*: sem resposta há *{_fmt_horas(horas)}* "
                        f"(limite {_fmt_horas(max_horas)})."
                    ),
                }
            )
    return alertas


def verificar_erros_nao_tratados(
    *,
    limite_horas: float = 2.0,
    incluir_api_datadog: bool = True,
    filtros: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Erros ativos há mais de `limite_horas` sem desaparecer do buffer local.
    """
    agora = datetime.now(timezone.utc)
    limiar = timedelta(hours=max(0.1, limite_horas))
    alertas: list[dict[str, Any]] = []

    for erro in listar_erros_recentes():
        if filtros and not _erro_relevante_para_vigia(erro, filtros):
            continue
        primeira = _parse_iso(erro.get("primeira_vez"))
        ultima = _parse_iso(erro.get("ultima_vez")) or primeira
        if not primeira or not ultima:
            continue

        # Erro ainda "ativo" se visto dentro da janela de monitoramento
        janela_ativa = timedelta(hours=max(1.0, limite_horas))
        if agora - ultima > janela_ativa:
            continue

        if agora - primeira < limiar:
            continue

        horas_aberto = (agora - primeira).total_seconds() / 3600.0
        nome_logger = str(erro.get("logger") or "?")
        msg = str(erro.get("mensagem") or erro.get("error_message") or "?")[:180]
        fp = str(erro.get("fingerprint") or "")

        alertas.append(
            {
                "tipo": "erro_datadog",
                "gravidade": "critica",
                "fingerprint": fp,
                "logger": nome_logger,
                "horas_aberto": round(horas_aberto, 2),
                "ocorrencias": int(erro.get("ocorrencias") or 1),
                "texto": (
                    f"Erro em *{nome_logger}* aberto há *{_fmt_horas(horas_aberto)}* "
                    f"({int(erro.get('ocorrencias') or 1)} ocorr.): `{msg}`"
                ),
            }
        )

    if incluir_api_datadog:
        query = (filtros or {}).get("query_datadog")
        consulta = buscar_erros_datadog(horas=limite_horas, limite=30, query=query)
        if consulta.get("ok"):
            chaves_vistas = {
                _chave_mensagem(str(e.get("mensagem") or e.get("error_message") or ""))
                for e in listar_erros_recentes()
            }
            for alerta in alertas:
                chaves_vistas.add(_chave_mensagem(str(alerta.get("texto") or "")))
            for item in consulta.get("erros") or []:
                msg = str(item.get("mensagem") or "")[:180]
                if not msg:
                    continue
                chave = _chave_mensagem(msg)
                if chave in chaves_vistas:
                    continue
                chaves_vistas.add(chave)
                alertas.append(
                    {
                        "tipo": "erro_datadog_api",
                        "gravidade": "alta",
                        "fingerprint": f"ddapi:{chave}",
                        "logger": "datadog_api",
                        "texto": f"Erro recente no Datadog (API): `{msg}`",
                    }
                )

    return alertas


def montar_mensagem_critica(
    inatividades: list[dict[str, Any]],
    erros: list[dict[str, Any]],
) -> str:
    linhas = [
        "🚨 *VIGIA DATADOG — FALHA GRAVE NÃO VERIFICADA*",
        "",
        "_Inatividade ou erros sem resposta há 2h+ — risco de operação cega._",
        "",
    ]

    criticos_inat = [a for a in inatividades if a.get("gravidade") == "critica"]
    outros_inat = [a for a in inatividades if a.get("gravidade") != "critica"]
    erros_crit = [e for e in erros if e.get("gravidade") == "critica"]

    if criticos_inat:
        linhas.append("⏱ *Inatividade crítica (sem resposta)*")
        for a in criticos_inat:
            linhas.append(f"  • {a.get('texto', '')}")
        linhas.append("")

    if erros_crit:
        linhas.append("🔥 *Erros Datadog não tratados*")
        for e in erros_crit[:8]:
            linhas.append(f"  • {e.get('texto', '')}")
        linhas.append("")

    if outros_inat:
        linhas.append("⚠️ *Outros componentes sem heartbeat*")
        for a in outros_inat[:5]:
            linhas.append(f"  • {a.get('texto', '')}")
        linhas.append("")

    erros_altos = [e for e in erros if e.get("gravidade") != "critica"]
    if erros_altos:
        for e in erros_altos[:4]:
            linhas.append(f"  • {e.get('texto', '')}")
        linhas.append("")

    linhas.extend(
        [
            "⚠️ *Gravidade de não verificar:*",
            "  • Robô pode estar parado sem você saber",
            "  • Vendas, repricing e tokens degradam em silêncio",
            "  • Erros acumulam no Datadog até falha total",
            "",
            "*Ação imediata:*",
            "  1. GitHub Actions → workflows recentes",
            "  2. Datadog → Logs `service:robo-markplaces status:error`",
            "  3. Corrigir causa e confirmar próximo ciclo OK",
        ]
    )
    return "\n".join(linhas).strip()


def analisar_saude(
    fontes: list[dict[str, Any]],
    *,
    limite_horas_inatividade: float = 2.0,
    limite_horas_erro: float = 2.0,
    catalogo_filtros: str | None = None,
) -> dict[str, Any]:
    from core.config import DATADOG_VIGIA_CATALOGO_FILTROS

    filtros = carregar_filtros_erro(catalogo_filtros or DATADOG_VIGIA_CATALOGO_FILTROS)
    inatividades = verificar_inatividade(fontes, limite_horas_padrao=limite_horas_inatividade)
    erros = verificar_erros_nao_tratados(limite_horas=limite_horas_erro, filtros=filtros)

    tem_critico = any(
        a.get("gravidade") == "critica" for a in inatividades
    ) or any(e.get("gravidade") == "critica" for e in erros)

    inatividades_relevantes = [a for a in inatividades if _gravidade_relevante(a.get("gravidade"))]

    return {
        "ok": not inatividades_relevantes and not erros,
        "tem_critico": tem_critico,
        "inatividades": inatividades,
        "erros": erros,
        "total_inatividades": len(inatividades),
        "total_erros": len(erros),
        "mensagem_critica": montar_mensagem_critica(inatividades, erros)
        if (inatividades or erros)
        else "",
    }
