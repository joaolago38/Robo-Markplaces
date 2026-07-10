from __future__ import annotations

import re

from core.ddg_lite import buscar as ddg
from core.http_client import request

rows = ddg(
    "site:produto.mercadolivre.com.br kit esmalte impala",
    max_resultados=8,
    contexto="probe",
)
print("ddg", len(rows))
for r in rows[:5]:
    print("-", (r.get("titulo") or "")[:70])
    print(" ", (r.get("url") or "")[:110])
    print(" ", (r.get("snippet") or "")[:140])

urls = [r.get("url") for r in rows if "produto.mercadolivre" in (r.get("url") or "")][:2]
if not urls:
    urls = [
        "https://produto.mercadolivre.com.br/MLB-4634823496-esmaltes-impala-kit-coleco-a-cor-da-sua-moda-5-lancamento-_JM"
    ]

for u in urls:
    try:
        rr = request(
            "GET",
            u,
            timeout=25,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"},
        )
        text = rr.text or ""
        print("html", rr.status_code, len(text), u[:90])
        for pat in ["R$", "og:title", "application/ld+json", "priceCurrency", "loginType"]:
            print(" ", pat, text.count(pat))
        precos = re.findall(r"R\$\s*([\d\.]+,\d{2})", text[:80000])
        print("  precos", precos[:8])
        m = re.search(r'"price"\s*:\s*"?([\d\.]+)"?', text)
        print("  json_price", m.group(1) if m else None)
        if "Olá! Para continuar" in text or "negative_traffic" in text:
            print("  BLOQUEIO_LOGIN")
    except Exception as exc:
        print("fail", u, exc)
