"""
integracoes/mcp/servidor.py
MCP stdio para o Cursor consultar o robô (vigia, ciclo, erros Datadog).

Uso local (não roda no GitHub Actions):
  py -3 -m integracoes.mcp.servidor
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

from integracoes.mcp import ferramentas

logger = logging.getLogger("mcp_robo")

PROTOCOL = "2024-11-05"

_FERRAMENTAS: dict[str, dict[str, Any]] = {
    "vigia_saude": {
        "description": (
            "Diagnóstico local do vigia: inatividades, erros abertos e agentes "
            "com problema. Não envia Telegram."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "fn": lambda _args: ferramentas.vigia_saude(),
    },
    "ultimo_ciclo": {
        "description": "Último ciclo do orquestrador (heartbeat em logs/).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "fn": lambda _args: ferramentas.ultimo_ciclo(),
    },
    "datadog_erros": {
        "description": (
            "Busca logs status:error no Datadog (API REST, não o MCP OAuth do Cursor). "
            "Requer DD_APPLICATION_KEY."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "horas": {"type": "number", "description": "Janela em horas. Padrão 2."},
                "limite": {"type": "integer", "description": "Máximo de eventos. Padrão 30."},
            },
            "additionalProperties": False,
        },
        "fn": lambda args: ferramentas.datadog_erros(
            horas=float((args or {}).get("horas") or 2),
            limite=int((args or {}).get("limite") or 30),
        ),
    },
}


def _ok(id_: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _erro(id_: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def tratar_requisicao(req: dict[str, Any]) -> dict[str, Any] | None:
    """Processa um JSON-RPC. Notificações retornam None."""
    method = str(req.get("method") or "")
    id_ = req.get("id")
    params = req.get("params") if isinstance(req.get("params"), dict) else {}

    if method.startswith("notifications/"):
        return None

    if method == "initialize":
        versao = str(params.get("protocolVersion") or PROTOCOL)
        return _ok(
            id_,
            {
                "protocolVersion": versao or PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "robo-markplaces", "version": "1.0.0"},
            },
        )

    if method == "ping":
        return _ok(id_, {})

    if method == "tools/list":
        tools = [
            {"name": nome, "description": meta["description"], "inputSchema": meta["inputSchema"]}
            for nome, meta in _FERRAMENTAS.items()
        ]
        return _ok(id_, {"tools": tools})

    if method == "tools/call":
        nome = str(params.get("name") or "")
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        meta = _FERRAMENTAS.get(nome)
        if meta is None:
            return _erro(id_, -32601, f"ferramenta desconhecida: {nome}")
        try:
            resultado = meta["fn"](args)
            texto = json.dumps(resultado, ensure_ascii=False, default=str)
            return _ok(id_, {"content": [{"type": "text", "text": texto}], "isError": False})
        except Exception as exc:
            logger.exception("MCP tool %s falhou", nome)
            return _ok(
                id_,
                {
                    "content": [{"type": "text", "text": f"erro: {exc}"}],
                    "isError": True,
                },
            )

    if method in ("resources/list", "prompts/list"):
        chave = "resources" if method.startswith("resources") else "prompts"
        return _ok(id_, {chave: []})

    return _erro(id_, -32601, f"método desconhecido: {method}")


def _escrever(msg: dict[str, Any], out) -> None:
    corpo = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(corpo)}\r\n\r\n".encode("ascii")
    out.write(header)
    out.write(corpo)
    out.flush()


def _ler(inp) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        linha = inp.readline()
        if not linha:
            return None
        if linha in (b"\r\n", b"\n"):
            break
        texto = linha.decode("utf-8", errors="replace").strip()
        if not texto:
            break
        if texto.startswith("{") and not headers:
            return json.loads(texto)
        if ":" in texto:
            chave, valor = texto.split(":", 1)
            headers[chave.strip().lower()] = valor.strip()
    n = int(headers.get("content-length") or 0)
    if n <= 0:
        return None
    corpo = inp.read(n)
    if not corpo:
        return None
    return json.loads(corpo.decode("utf-8"))


def run_stdio() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    inp = sys.stdin.buffer
    out = sys.stdout.buffer
    while True:
        try:
            req = _ler(inp)
        except Exception:
            logger.exception("MCP: mensagem inválida")
            break
        if req is None:
            break
        if not isinstance(req, dict):
            continue
        resp = tratar_requisicao(req)
        if resp is not None:
            _escrever(resp, out)


if __name__ == "__main__":
    run_stdio()
