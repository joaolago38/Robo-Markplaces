"""
testar_claude_direto.py
Testa o Claude diretamente com requests
Rode: .venv\Scripts\python.exe testar_claude_direto.py
"""
import os
import sys
import requests
from pathlib import Path

# Carrega .env ou .env.exemplo
for nome in [".env", ".env.exemplo"]:
    env_path = Path(nome)
    if env_path.exists():
        print(f"Carregando: {nome}")
        for linha in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.startswith("#"):
                k, _, v = linha.partition("=")
                v = v.strip().strip('"').strip("'")
                if v and v != "..." and not v.startswith("sk-ant-..."):
                    os.environ.setdefault(k.strip(), v)
        break

key = os.getenv("ANTHROPIC_API_KEY", "")
print(f"API Key: {key[:20]}..." if key else "API Key: NAO ENCONTRADA")

print("\n=== Testando Claude direto ===")
if not key or key == "sk-ant-...":
    print("ERRO: ANTHROPIC_API_KEY nao configurada no .env")
    sys.exit(1)

r = requests.post(
    "https://api.anthropic.com/v1/messages",
    headers={
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    },
    json={
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "Responda apenas: OK"}],
    },
    timeout=15
)
print(f"Status: {r.status_code}")
print(f"Resposta: {r.text[:300]}")

print("\n=== Testando via claude_client ===")
try:
    from core.claude_client import perguntar
    resp = perguntar("Responda apenas: OK")
    print(f"Resultado: {resp}")
except Exception as e:
    print(f"Erro: {e}")
