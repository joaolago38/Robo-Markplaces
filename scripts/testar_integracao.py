#!/usr/bin/env python3
"""
scripts/testar_integracao.py

Testa a integracao completa Claude + Bling no GitHub Actions.
Roda via workflow_dispatch em testar_integracao.yml.

Testa:
  1. Configuracao — variaveis de ambiente presentes?
  2. Bling — token valido, lista produtos
  3. Claude — responde, latencia ok
  4. Integracao — Claude usa dados reais do Bling para responder
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OK   = "[OK]"
ERRO = "[ERRO]"
INFO = "[INFO]"

resultados = []


def log(icone: str, msg: str) -> None:
    print(f"{icone} {msg}", flush=True)


def checar(ok: bool, msg_ok: str, msg_erro: str = "") -> bool:
    if ok:
        log(OK, msg_ok)
    else:
        log(ERRO, msg_erro or msg_ok)
    resultados.append(ok)
    return ok


# ══════════════════════════════════════════════════════════════
# TESTE 1 — Configuracao
# ══════════════════════════════════════════════════════════════
print()
print("=" * 55)
print("TESTE 1 — Configuracao de variaveis")
print("=" * 55)

anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
bling_token   = os.getenv("BLING_ACCESS_TOKEN", "")
bling_refresh = os.getenv("BLING_REFRESH_TOKEN", "")
bling_id      = os.getenv("BLING_CLIENT_ID", "")
bling_secret  = os.getenv("BLING_CLIENT_SECRET", "")

checar(bool(anthropic_key) and anthropic_key != "...",
       f"ANTHROPIC_API_KEY configurada ({anthropic_key[:12]}...)",
       "ANTHROPIC_API_KEY ausente ou invalida")

checar(bool(bling_token) and bling_token != "...",
       f"BLING_ACCESS_TOKEN configurado ({bling_token[:8]}...)",
       "BLING_ACCESS_TOKEN ausente")

checar(bool(bling_refresh) and bling_refresh != "...",
       f"BLING_REFRESH_TOKEN configurado ({bling_refresh[:8]}...)",
       "BLING_REFRESH_TOKEN ausente")

checar(bool(bling_id),
       f"BLING_CLIENT_ID configurado",
       "BLING_CLIENT_ID ausente")

checar(bool(bling_secret) and bling_secret != "...",
       f"BLING_CLIENT_SECRET configurado ({bling_secret[:4]}...)",
       "BLING_CLIENT_SECRET ausente")


# ══════════════════════════════════════════════════════════════
# TESTE 2 — Bling
# ══════════════════════════════════════════════════════════════
print()
print("=" * 55)
print("TESTE 2 — Conexao com o Bling ERP")
print("=" * 55)

produtos = []
try:
    from integracoes.bling.bling_client import listar_produtos, estoques_criticos
    inicio = time.time()
    produtos = listar_produtos()
    latencia = round(time.time() - inicio, 2)

    checar(isinstance(produtos, list),
           f"listar_produtos() retornou lista",
           "listar_produtos() retornou tipo invalido")

    checar(len(produtos) > 0,
           f"Bling conectado — {len(produtos)} produto(s) encontrado(s) em {latencia}s",
           f"Bling retornou lista vazia — token pode estar expirado")

    if produtos:
        log(INFO, "Primeiros 3 produtos:")
        for p in produtos[:3]:
            nome   = p.get("nome", "?")[:40]
            codigo = p.get("codigo", "?")
            preco  = p.get("preco", 0)
            log(INFO, f"  {codigo}: {nome} | R$ {preco}")

    criticos = estoques_criticos()
    log(INFO, f"Estoque critico: {len(criticos)} produto(s)")

except Exception as exc:
    checar(False, "", f"Excecao ao conectar no Bling: {exc}")
    log(INFO, "Dica: o BLING_ACCESS_TOKEN pode ter expirado — rode pegar_token_bling.py")


# ══════════════════════════════════════════════════════════════
# TESTE 3 — Claude
# ══════════════════════════════════════════════════════════════
print()
print("=" * 55)
print("TESTE 3 — Claude IA")
print("=" * 55)

resposta_claude = ""
try:
    from core.claude_client import perguntar
    inicio = time.time()
    resposta_claude = perguntar("Responda apenas: OK")
    latencia = round(time.time() - inicio, 2)

    ok_resposta = bool(resposta_claude) and "API" not in resposta_claude
    checar(ok_resposta,
           f"Claude respondeu em {latencia}s: {resposta_claude[:50]}",
           f"Claude falhou: {resposta_claude[:100]}")

    checar(latencia < 10,
           f"Latencia aceitavel ({latencia}s < 10s)",
           f"Latencia alta ({latencia}s)")

except Exception as exc:
    checar(False, "", f"Excecao ao chamar Claude: {exc}")


# ══════════════════════════════════════════════════════════════
# TESTE 4 — Integracao Claude + Bling
# ══════════════════════════════════════════════════════════════
print()
print("=" * 55)
print("TESTE 4 — Integracao Claude + Bling")
print("=" * 55)

if produtos and resposta_claude and "API" not in resposta_claude:
    try:
        from core.claude_client import perguntar

        nomes = [p.get("nome", "?") for p in produtos[:5]]
        catalogo = ", ".join(nomes)

        contexto = (
            f"Voce e assistente de vendas da Comercial Lago Oliveira. "
            f"Vendemos esmaltes Impala. "
            f"Produtos disponiveis: {catalogo}."
        )
        pergunta = "Qual kit recomenda para uma manicure profissional que quer variedade de cores?"

        log(INFO, f"Pergunta: {pergunta}")
        inicio = time.time()
        resposta = perguntar(pergunta, contexto=contexto)
        latencia = round(time.time() - inicio, 2)

        ok_integracao = bool(resposta) and len(resposta) > 20 and "API" not in resposta
        checar(ok_integracao,
               f"Integracao ok em {latencia}s",
               f"Integracao falhou: {resposta[:100]}")

        if ok_integracao:
            log(INFO, f"Resposta do Claude ({len(resposta)} chars):")
            print()
            print(resposta[:500])
            print()

    except Exception as exc:
        checar(False, "", f"Excecao na integracao: {exc}")
else:
    log(INFO, "Integracao ignorada — Bling ou Claude nao estao funcionando")
    resultados.append(None)


# ══════════════════════════════════════════════════════════════
# RESULTADO FINAL
# ══════════════════════════════════════════════════════════════
print()
print("=" * 55)
passou   = sum(1 for r in resultados if r is True)
falhou   = sum(1 for r in resultados if r is False)
ignorado = sum(1 for r in resultados if r is None)
total    = len([r for r in resultados if r is not None])
pct      = int(passou / total * 100) if total else 0

emoji = "SUCESSO" if falhou == 0 else "FALHOU"
print(f"{emoji} — {passou}/{total} testes passaram ({pct}%)")
if falhou > 0:
    print(f"  {falhou} teste(s) falharam — veja os [ERRO] acima")
print("=" * 55)
print()

sys.exit(0 if falhou == 0 else 1)
