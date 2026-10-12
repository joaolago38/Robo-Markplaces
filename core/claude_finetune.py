"""
core/claude_finetune.py

Monta o JSONL de fine-tuning do Claude 3 Haiku no Amazon Bedrock.

O playbook (`montar_instrucoes`) vira o system de cada linha.
O roteador decide se a tarefa fica no Haiku. Propósito que sobe para o
Sonnet (preço, anúncio, Ads, ranking) fica de fora: o Bedrock só treina
o Haiku 3, e essas decisões continuam no modelo de vendas.

Este módulo não chama a AWS e não treina modelo. Ele só prepara o arquivo.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.claude_ml.playbooks import id_playbook, montar_instrucoes
from core.claude_roteador import proposito_exige_sonnet, resolver_modelo_vendas
from core.config import ROOT

logger = logging.getLogger("claude_finetune")

# Único Claude com fine-tuning no Bedrock (us-west-2). Não é o Haiku 4.5 da API.
BASE_BEDROCK = "anthropic.claude-3-haiku-20240307-v1:0"
LIMITE_TOKENS = 32_000
CANDIDATOS_PATH = ROOT / "logs" / "claude_finetune_candidatos.jsonl"
APROVADOS_PATH = ROOT / "catalogo" / "claude_finetune_aprovados.jsonl"
SAIDA_PATH = ROOT / "logs" / "claude_finetune_haiku.jsonl"


class FinetuneRecusado(ValueError):
    """A linha não entra no dataset. `motivo` explica a recusa."""

    def __init__(self, motivo: str):
        self.motivo = motivo
        super().__init__(motivo)


def _tokens(texto: str) -> int:
    n = len(texto or "")
    if n <= 0:
        return 0
    return max(1, (n + 3) // 4)


def elegivel(
    proposito: str | None,
    *,
    canal: str | None = None,
    texto: str | None = None,
    preco_produto: float | None = None,
    sinal_ads: dict[str, Any] | None = None,
    intencao: str | None = None,
    converter: bool | None = None,
    estoque: int | None = None,
    analise: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """
    True quando o playbook existe e o roteador deixa a chamada no Haiku.

    O segundo valor é o id do playbook, ou o motivo da recusa.
    """
    prop = (proposito or "").strip()
    if not prop:
        return False, "sem_proposito"
    if proposito_exige_sonnet(prop):
        return False, "complexidade_algoritmo_ml"
    pid = id_playbook(prop)
    if not pid:
        return False, "sem_playbook"
    rota = resolver_modelo_vendas(
        proposito=prop,
        canal=canal,
        texto=texto,
        preco_produto=preco_produto,
        sinal_ads=sinal_ads,
        intencao=intencao,
        converter=converter,
        estoque=estoque,
        analise=analise,
    )
    if rota.get("escalou"):
        return False, str(rota.get("motivo") or "escalou")
    return True, pid


def _mensagens_do_par(par: dict[str, Any]) -> list[dict[str, str]]:
    brutas = par.get("mensagens")
    if isinstance(brutas, list) and brutas:
        saida: list[dict[str, str]] = []
        for item in brutas:
            if not isinstance(item, dict):
                raise FinetuneRecusado("mensagem_invalida")
            papel = str(item.get("role") or "").strip()
            conteudo = str(item.get("content") or "").strip()
            if papel not in {"user", "assistant"} or not conteudo:
                raise FinetuneRecusado("mensagem_invalida")
            saida.append({"role": papel, "content": conteudo})
        return saida
    entrada = str(par.get("entrada") or "").strip()
    resposta = str(par.get("resposta") or "").strip()
    if not entrada or not resposta:
        raise FinetuneRecusado("par_vazio")
    return [
        {"role": "user", "content": entrada},
        {"role": "assistant", "content": resposta},
    ]


def validar_mensagens(mensagens: list[dict[str, str]]) -> None:
    if len(mensagens) < 2:
        raise FinetuneRecusado("conversa_curta")
    if mensagens[0]["role"] != "user" or mensagens[-1]["role"] != "assistant":
        raise FinetuneRecusado("conversa_mal_fechada")
    esperado = "user"
    for msg in mensagens:
        if msg["role"] != esperado:
            raise FinetuneRecusado("papeis_fora_de_ordem")
        esperado = "assistant" if esperado == "user" else "user"


def montar_linha(
    proposito: str | None,
    entrada: str | None = None,
    resposta: str | None = None,
    *,
    campos: dict[str, str] | None = None,
    mensagens: list[dict[str, Any]] | None = None,
    canal: str | None = None,
    texto: str | None = None,
    preco_produto: float | None = None,
    sinal_ads: dict[str, Any] | None = None,
    intencao: str | None = None,
    converter: bool | None = None,
    estoque: int | None = None,
    analise: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Uma linha no formato Bedrock: system do playbook + user/assistant."""
    ok, detalhe = elegivel(
        proposito,
        canal=canal,
        texto=texto if texto is not None else entrada,
        preco_produto=preco_produto,
        sinal_ads=sinal_ads,
        intencao=intencao,
        converter=converter,
        estoque=estoque,
        analise=analise,
    )
    if not ok:
        raise FinetuneRecusado(detalhe)
    msgs = _mensagens_do_par(
        {"entrada": entrada, "resposta": resposta, "mensagens": mensagens}
    )
    validar_mensagens(msgs)
    system = montar_instrucoes(detalhe, campos=campos)
    gasto = _tokens(system) + sum(_tokens(m["content"]) for m in msgs)
    if gasto > LIMITE_TOKENS:
        raise FinetuneRecusado("acima_de_32k")
    return {"system": system, "messages": msgs}


def _par_de_dict(par: dict[str, Any]) -> dict[str, Any]:
    campos = par.get("campos")
    if campos is not None and not isinstance(campos, dict):
        raise FinetuneRecusado("campos_invalidos")
    return {
        "proposito": par.get("proposito"),
        "entrada": par.get("entrada"),
        "resposta": par.get("resposta"),
        "mensagens": par.get("mensagens"),
        "campos": campos,
        "canal": par.get("canal"),
        "texto": par.get("texto"),
        "preco_produto": par.get("preco_produto"),
        "sinal_ads": par.get("sinal_ads") if isinstance(par.get("sinal_ads"), dict) else None,
        "intencao": par.get("intencao"),
        "converter": par.get("converter"),
        "estoque": par.get("estoque"),
        "analise": par.get("analise") if isinstance(par.get("analise"), dict) else None,
    }


def carregar_pares(caminho: Path | str) -> list[dict[str, Any]]:
    """Lê JSONL. Linha com aprovado=false fica na fila, fora do treino."""
    path = Path(caminho)
    if not path.is_file():
        return []
    pares: list[dict[str, Any]] = []
    for n, bruta in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        linha = bruta.strip()
        if not linha:
            continue
        try:
            par = json.loads(linha)
        except json.JSONDecodeError as exc:
            raise FinetuneRecusado(f"json_invalido:{n}") from exc
        if not isinstance(par, dict):
            raise FinetuneRecusado(f"linha_invalida:{n}")
        if par.get("aprovado") is False:
            continue
        pares.append(par)
    return pares


def exportar_jsonl(
    pares: list[dict[str, Any]],
    destino: Path | str = SAIDA_PATH,
) -> dict[str, Any]:
    """Grava só as linhas que o roteador aceita no Haiku."""
    path = Path(destino)
    path.parent.mkdir(parents=True, exist_ok=True)
    aceitas: list[dict[str, Any]] = []
    recusadas: list[dict[str, Any]] = []
    for i, par in enumerate(pares):
        try:
            if not isinstance(par, dict):
                raise FinetuneRecusado("linha_invalida")
            campos = _par_de_dict(par)
            aceitas.append(montar_linha(**campos))
        except FinetuneRecusado as exc:
            recusadas.append(
                {
                    "indice": i,
                    "proposito": (par or {}).get("proposito") if isinstance(par, dict) else None,
                    "motivo": exc.motivo,
                }
            )
    with path.open("w", encoding="utf-8") as arquivo:
        for linha in aceitas:
            arquivo.write(json.dumps(linha, ensure_ascii=False) + "\n")
    return {
        "gravadas": len(aceitas),
        "recusadas": recusadas,
        "destino": str(path),
        "base": BASE_BEDROCK,
    }


def talvez_capturar(
    *,
    proposito: str | None,
    entrada: str | None,
    resposta: str | None,
    origem: str | None = None,
) -> bool:
    """
    Com CLAUDE_FINETUNE_CAPTURAR=1, anexa um candidato (aprovado=false).

    Candidato não entra no JSONL de treino até alguém copiar a linha para
    catalogo/claude_finetune_aprovados.jsonl sem esse campo.
    """
    from core.config import CLAUDE_FINETUNE_CAPTURAR

    if not CLAUDE_FINETUNE_CAPTURAR:
        return False
    prop = (proposito or "").strip()
    texto_in = (entrada or "").strip()
    texto_out = (resposta or "").strip()
    if not prop or not texto_in or not texto_out or texto_out.startswith("⚠️"):
        return False
    ok, detalhe = elegivel(prop, texto=texto_in)
    if not ok:
        return False
    registro = {
        "aprovado": False,
        "proposito": prop,
        "playbook": detalhe,
        "entrada": texto_in,
        "resposta": texto_out,
        "origem": origem or "",
        "capturado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    try:
        CANDIDATOS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CANDIDATOS_PATH.open("a", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except OSError:
        logger.debug("nao gravou candidato de finetune", exc_info=True)
        return False
    return True
