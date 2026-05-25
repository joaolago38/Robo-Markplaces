#!/usr/bin/env python3
"""
scripts/diagnostico_bling.py

Testa a conexão completa com o Bling ERP e guia
o usuário na correção de cada problema encontrado.

Uso:
    .venv\\Scripts\\python.exe scripts/diagnostico_bling.py

    Ou passando token diretamente (sem precisar editar):
    BLING_ACCESS_TOKEN=xxx python scripts/diagnostico_bling.py

Testa 6 pontos:
    1. Token de acesso — válido ou expirado?
    2. Produtos — quantos ativos no Bling?
    3. Dados da empresa — endereço bate com o CNPJ?
    4. Endpoint NF-e — App tem permissão para emitir?
    5. Refresh token — consegue renovar automaticamente?
    6. Escopos — App tem todas as permissões necessárias?
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import requests

# ── Carrega .env se existir ────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
env_path = ROOT / ".env"
if env_path.exists():
    for linha in env_path.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, _, valor = linha.partition("=")
            valor = valor.strip().strip('"').strip("'")
            if valor and valor != "...":
                os.environ.setdefault(chave.strip(), valor)

# ── Credenciais ────────────────────────────────────────────────
CLIENT_ID     = os.getenv("BLING_CLIENT_ID",     "").strip()
CLIENT_SECRET = os.getenv("BLING_CLIENT_SECRET", "").strip()
ACCESS_TOKEN  = os.getenv("BLING_ACCESS_TOKEN",  "").strip()
REFRESH_TOKEN = os.getenv("BLING_REFRESH_TOKEN", "").strip()

BASE    = "https://www.bling.com.br/Api/v3"
TIMEOUT = 15

OK    = "✓"
ERRO  = "✗"
AVISO = "⚠"


def _headers(token: str | None = None) -> dict:
    return {
        "Authorization": f"Bearer {token or ACCESS_TOKEN}",
        "Accept":        "application/json",
        "Content-Type":  "application/json",
    }


def _linha(ok: bool, descricao: str, detalhe: str = "") -> bool:
    icone = OK if ok else ERRO
    msg = f"  {icone} {descricao}"
    if detalhe:
        msg += f" — {detalhe}"
    print(msg)
    return ok


def _instrucao(linhas: list[str]) -> None:
    print()
    for l in linhas:
        print(f"     {l}")
    print()


# ══════════════════════════════════════════════════════════════
# Testes individuais
# ══════════════════════════════════════════════════════════════

def testar_token() -> dict:
    """Teste 1 — verifica se o access_token é válido."""
    if not ACCESS_TOKEN or ACCESS_TOKEN == "...":
        return {
            "ok": False,
            "status": 0,
            "msg": "BLING_ACCESS_TOKEN não configurado no .env ou Secrets",
        }
    try:
        r = requests.get(
            f"{BASE}/produtos",
            headers=_headers(),
            params={"situacao": "A", "limite": 1},
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            return {"ok": True, "status": 200, "msg": "autenticado com sucesso"}
        elif r.status_code == 401:
            return {"ok": False, "status": 401, "msg": "TOKEN EXPIRADO"}
        elif r.status_code == 403:
            return {"ok": False, "status": 403, "msg": "sem permissão — verifique escopos do App"}
        else:
            return {"ok": False, "status": r.status_code, "msg": r.text[:120]}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "status": 0, "msg": "sem conexão com a internet"}
    except Exception as exc:
        return {"ok": False, "status": 0, "msg": str(exc)}


def testar_produtos() -> dict:
    """Teste 2 — lista produtos ativos no Bling."""
    try:
        r = requests.get(
            f"{BASE}/produtos",
            headers=_headers(),
            params={"situacao": "A", "limite": 50},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return {"ok": False, "status": r.status_code, "produtos": [], "msg": r.text[:120]}
        dados = r.json().get("data", [])
        return {
            "ok":      True,
            "status":  200,
            "produtos": dados,
            "msg":     f"{len(dados)} produto(s) ativo(s)",
        }
    except Exception as exc:
        return {"ok": False, "status": 0, "produtos": [], "msg": str(exc)}


def testar_empresa() -> dict:
    """Teste 3 — verifica dados da empresa cadastrada no Bling."""
    try:
        r = requests.get(f"{BASE}/empresas", headers=_headers(), timeout=TIMEOUT)
        if r.status_code == 200:
            emp = r.json().get("data", {})
            return {
                "ok":     True,
                "status": 200,
                "razao":  emp.get("razaoSocial", ""),
                "cnpj":   emp.get("cnpj", ""),
                "cidade": emp.get("endereco", {}).get("municipio", ""),
                "msg":    emp.get("razaoSocial", ""),
            }
        return {"ok": False, "status": r.status_code, "msg": f"HTTP {r.status_code}"}
    except Exception as exc:
        return {"ok": False, "status": 0, "msg": str(exc)}


def testar_nfe() -> dict:
    """Teste 4 — verifica se o App tem acesso ao endpoint de NF-e."""
    try:
        r = requests.get(
            f"{BASE}/nfe",
            headers=_headers(),
            params={"limite": 1},
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            qtd = len(r.json().get("data", []))
            return {"ok": True, "status": 200, "msg": f"endpoint acessível — {qtd} nota(s)"}
        elif r.status_code == 403:
            return {"ok": False, "status": 403, "msg": "sem permissão — adicione escopo NF-e no App"}
        elif r.status_code == 401:
            return {"ok": False, "status": 401, "msg": "token expirado"}
        else:
            return {"ok": False, "status": r.status_code, "msg": r.text[:120]}
    except Exception as exc:
        return {"ok": False, "status": 0, "msg": str(exc)}


def testar_refresh() -> dict:
    """Teste 5 — tenta renovar o token usando o refresh_token."""
    if not CLIENT_ID or not CLIENT_SECRET or not REFRESH_TOKEN:
        return {
            "ok":  False,
            "status": 0,
            "msg": "CLIENT_ID, CLIENT_SECRET ou REFRESH_TOKEN ausentes",
        }
    try:
        credenciais = base64.b64encode(
            f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
        ).decode()
        r = requests.post(
            f"{BASE}/oauth/token",
            headers={
                "Authorization": f"Basic {credenciais}",
                "Content-Type":  "application/x-www-form-urlencoded",
            },
            data={
                "grant_type":    "refresh_token",
                "refresh_token": REFRESH_TOKEN,
            },
            timeout=TIMEOUT,
        )
        if r.status_code == 200 and "access_token" in r.json():
            dados = r.json()
            return {
                "ok":           True,
                "status":       200,
                "access_token":  dados["access_token"],
                "refresh_token": dados.get("refresh_token", REFRESH_TOKEN),
                "expires_in":    dados.get("expires_in", 21600),
                "msg":          f"token renovado — expira em {dados.get('expires_in',21600)//3600}h",
            }
        erro = r.json().get("error", {})
        if isinstance(erro, dict):
            motivo = erro.get("message", f"HTTP {r.status_code}")
        else:
            motivo = str(erro)
        return {"ok": False, "status": r.status_code, "msg": motivo}
    except Exception as exc:
        return {"ok": False, "status": 0, "msg": str(exc)}


def testar_escopos() -> dict:
    """Teste 6 — verifica escopos verificando endpoints chave."""
    escopos = {
        "Produtos":  (f"{BASE}/produtos",  {"limite": 1}),
        "NF-e":      (f"{BASE}/nfe",       {"limite": 1}),
        "Pedidos":   (f"{BASE}/pedidos/vendas", {"limite": 1}),
        "Contatos":  (f"{BASE}/contatos",  {"limite": 1}),
        "Financeiro":(f"{BASE}/contasreceber", {"limite": 1}),
    }
    resultados = {}
    for nome, (url, params) in escopos.items():
        try:
            r = requests.get(url, headers=_headers(), params=params, timeout=TIMEOUT)
            resultados[nome] = r.status_code in (200, 404)  # 404 = ok sem dados
        except Exception:
            resultados[nome] = False
    ok = all(resultados.values())
    faltando = [n for n, v in resultados.items() if not v]
    return {
        "ok":        ok,
        "status":    200 if ok else 403,
        "escopos":   resultados,
        "faltando":  faltando,
        "msg":       "todos os escopos ok" if ok else f"sem permissão: {', '.join(faltando)}",
    }


# ══════════════════════════════════════════════════════════════
# Execução principal
# ══════════════════════════════════════════════════════════════

def executar() -> dict:
    print()
    print("=" * 57)
    print("  Diagnóstico Bling — Comercial Lago Oliveira Ltda")
    print("  CNPJ: 52.668.583/0001-27")
    print("=" * 57)

    resultados = {}
    token_renovado = None

    # ── 1. Token ──────────────────────────────────────────────
    print("\n[1] Token de acesso")
    r1 = testar_token()
    resultados["token"] = r1
    _linha(r1["ok"], "Token válido", r1["msg"])
    if not r1["ok"] and r1["status"] == 401:
        _instrucao([
            "Token expirado. Para renovar:",
            "1. Abra no navegador:",
            "   https://www.bling.com.br/Api/v3/oauth/authorize?response_type=code",
            "   &client_id=db6853620b6e2f6f259b1cb972f64bf5579bd4d0",
            "   &redirect_uri=https%3A%2F%2Fgoogle.com&state=robo",
            "2. Autorize → copie o code da URL do Google",
            "3. Cole no pegar_token_bling.py e rode IMEDIATAMENTE",
        ])
        # Tenta renovar automaticamente com o refresh_token
        print("  Tentando renovar automaticamente...")
        r5 = testar_refresh()
        if r5["ok"]:
            print(f"  {OK} Token renovado com sucesso!")
            token_renovado = r5
            print(f"     Novo ACCESS_TOKEN: {r5['access_token'][:40]}...")
            print(f"     Novo REFRESH_TOKEN: {r5['refresh_token'][:40]}...")
            print()
            print("  AÇÃO NECESSÁRIA — atualize no GitHub Secrets:")
            print("  https://github.com/joaolago38/Robo-Markplaces/settings/secrets/actions")
            print(f"    BLING_ACCESS_TOKEN  → {r5['access_token']}")
            print(f"    BLING_REFRESH_TOKEN → {r5['refresh_token']}")
        else:
            print(f"  {ERRO} Renovação automática falhou: {r5['msg']}")

    # ── 2. Produtos ───────────────────────────────────────────
    print("\n[2] Produtos cadastrados")
    token_uso = token_renovado["access_token"] if token_renovado else None
    try:
        r2_raw = requests.get(
            f"{BASE}/produtos", headers=_headers(token_uso),
            params={"situacao": "A", "limite": 50}, timeout=TIMEOUT,
        )
        if r2_raw.status_code == 200:
            dados = r2_raw.json().get("data", [])
            r2 = {"ok": True, "produtos": dados, "msg": f"{len(dados)} produto(s) ativo(s)"}
            _linha(True, "Produtos listados", r2["msg"])
            for p in dados[:5]:
                nome    = p.get("nome", "?")[:35]
                codigo  = p.get("codigo", "?")
                preco   = p.get("preco", 0)
                est     = p.get("estoque", {})
                qtd     = est.get("saldoVirtualTotal", "?") if isinstance(est, dict) else "?"
                print(f"       {codigo}: {nome} | R$ {preco} | Est: {qtd}")
            if not dados:
                print(f"  {AVISO} Nenhum produto ativo — cadastre os kits Impala no Bling")
        else:
            r2 = {"ok": False, "produtos": [], "msg": f"HTTP {r2_raw.status_code}"}
            _linha(False, "Produtos listados", r2["msg"])
    except Exception as exc:
        r2 = {"ok": False, "produtos": [], "msg": str(exc)}
        _linha(False, "Produtos listados", r2["msg"])
    resultados["produtos"] = r2

    # ── 3. Empresa ────────────────────────────────────────────
    print("\n[3] Dados da empresa")
    r3 = testar_empresa()
    resultados["empresa"] = r3
    if r3["ok"]:
        _linha(True, "Empresa encontrada", r3.get("razao", ""))
        cidade = r3.get("cidade", "")
        ok_cidade = cidade.upper() == "CAMPINAS" if cidade else True
        _linha(ok_cidade,
               "Endereço correto (Campinas)",
               cidade if cidade else "não retornado — verifique no painel do Bling")
        if not ok_cidade:
            _instrucao([
                "O endereço no Bling deve ser Campinas (igual ao CNPJ).",
                "Bling → engrenagem → Meu Negócio → Dados da Empresa",
                "Endereço: R. Conceição, 233 — Anexo 9P Sala 916 — Centro — Campinas/SP",
                "CEP: 13.010-050",
            ])
    else:
        _linha(False, "Empresa", r3["msg"])

    # ── 4. NF-e ───────────────────────────────────────────────
    print("\n[4] Permissão para NF-e")
    r4 = testar_nfe()
    resultados["nfe"] = r4
    _linha(r4["ok"], "Endpoint NF-e acessível", r4["msg"])
    if not r4["ok"] and r4["status"] == 403:
        _instrucao([
            "O App do Bling não tem permissão para NF-e.",
            "Bling → Configurações → API → Aplicações → seu App",
            "→ Editar → marcar escopo 'Nota Fiscal (NF-e)'",
            "→ Salvar → gerar novo token com pegar_token_bling.py",
        ])

    # ── 5. Refresh ────────────────────────────────────────────
    print("\n[5] Renovação automática")
    if token_renovado:
        _linha(True, "Refresh token", "já testado e funcionando")
        resultados["refresh"] = {"ok": True}
    else:
        r5 = testar_refresh()
        resultados["refresh"] = r5
        _linha(r5["ok"], "Refresh token válido", r5["msg"])
        if r5["ok"]:
            print(f"  {AVISO} Token renovado — atualize o GitHub Secrets:")
            print(f"     BLING_ACCESS_TOKEN  → {r5['access_token'][:50]}...")
            print(f"     BLING_REFRESH_TOKEN → {r5['refresh_token'][:50]}...")

    # ── 6. Escopos ────────────────────────────────────────────
    print("\n[6] Escopos do App")
    r6 = testar_escopos()
    resultados["escopos"] = r6
    _linha(r6["ok"], "Todos os escopos", r6["msg"])
    for nome, ok in r6.get("escopos", {}).items():
        print(f"       {'✓' if ok else '✗'} {nome}")
    if r6.get("faltando"):
        _instrucao([
            f"Escopos faltando: {', '.join(r6['faltando'])}",
            "Bling → Configurações → API → Aplicações → seu App → Editar",
            "→ marque os escopos faltando → Salvar",
            "→ rode pegar_token_bling.py para gerar token com novos escopos",
        ])

    # ── RESULTADO FINAL ───────────────────────────────────────
    passou   = sum(1 for v in resultados.values() if v.get("ok"))
    total    = len(resultados)
    pct      = int(passou / total * 100) if total else 0
    emoji    = "🟢" if pct == 100 else "🟡" if pct >= 60 else "🔴"
    status   = "TUDO OK — Bling 100% operacional" if pct == 100 else \
               "ATENÇÃO — alguns pontos precisam de ajuste" if pct >= 60 else \
               "PROBLEMAS — verifique os itens marcados com ✗"

    print()
    print("=" * 57)
    print(f"  {emoji} {passou}/{total} testes ({pct}%)")
    print(f"  {status}")
    print("=" * 57)
    print()

    resultados["score_pct"] = pct
    return resultados


if __name__ == "__main__":
    executar()
