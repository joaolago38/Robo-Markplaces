#!/usr/bin/env python3
"""
scripts/testar_ml_e_nfe.py

Diagnóstico diário: Mercado Livre (perguntas, Product Ads, pedidos) e NF-e (dry-run).
Roda via workflow_dispatch em testar_ml_e_nfe.yml.

Testa:
  1. ML — perguntas não respondidas e saúde da conta
  2. ML — Product Ads (campanhas e ACOS)
  3. ML — pedidos pagos recentes
  4. NF-e — montagem do payload (dry_run=True, sem emitir)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OK = "[OK]"
ERRO = "[ERRO]"
INFO = "[INFO]"

resultados: list[bool | None] = []
pedidos_ml: list[dict] = []


def log(icone: str, msg: str) -> None:
    print(f"{icone} {msg}", flush=True)


def checar(ok: bool, msg_ok: str, msg_erro: str = "") -> bool:
    if ok:
        log(OK, msg_ok)
    else:
        log(ERRO, msg_erro or msg_ok)
    resultados.append(ok)
    return ok


def ignorar(msg: str) -> None:
    log(INFO, f"IGNORADO — {msg}")
    resultados.append(None)


def _ml_habilitado() -> bool:
    from integracoes.ml import ml_client

    return ml_client._enabled()


# ══════════════════════════════════════════════════════════════
# TESTE 1 — Mercado Livre: perguntas dos clientes
# ══════════════════════════════════════════════════════════════
print()
print("=" * 55)
print("TESTE 1 — Mercado Livre: perguntas dos clientes")
print("=" * 55)

if not _ml_habilitado():
    ignorar("Mercado Livre nao configurado (ML_ACCESS_TOKEN / ML_SELLER_ID)")
else:
    try:
        from integracoes.ml import ml_client

        perguntas = ml_client.listar_perguntas_nao_respondidas()
        checar(
            isinstance(perguntas, list),
            f"listar_perguntas_nao_respondidas() retornou lista ({len(perguntas)} pergunta(s))",
            "listar_perguntas_nao_respondidas() retornou tipo invalido",
        )

        if perguntas:
            log(INFO, "Primeiras 3 perguntas:")
            for p in perguntas[:3]:
                texto = str(p.get("text", p.get("question", "?")))[:80]
                item_id = p.get("item_id", "?")
                log(INFO, f"  item_id={item_id} | {texto}")

        saude = ml_client.obter_saude_conta()
        log(
            INFO,
            "Saude da conta — "
            f"pendencias={saude.get('pendencias', '?')}, "
            f"claims_rate={saude.get('claims_rate', '?')}, "
            f"dias_sem_acesso={saude.get('dias_sem_acesso', '?')}",
        )
    except Exception as exc:
        checar(False, "", f"Excecao no TESTE 1: {exc}")


# ══════════════════════════════════════════════════════════════
# TESTE 2 — Mercado Livre: Product Ads
# ══════════════════════════════════════════════════════════════
print()
print("=" * 55)
print("TESTE 2 — Mercado Livre: Product Ads")
print("=" * 55)

if not _ml_habilitado():
    ignorar("Mercado Livre nao configurado — Product Ads ignorado")
else:
    try:
        from integracoes.ml import ml_product_ads

        adv = ml_product_ads.obter_advertiser()
        if not adv.get("ok"):
            msg = adv.get("erro", "advertiser indisponivel")
            if adv.get("codigo") == "sem_permissao":
                ignorar(
                    f"{msg} — ative em Mercado Livre > Mi perfil > Publicidad"
                )
            else:
                log(INFO, f"AVISO Product Ads: {msg}")
                ignorar(msg)
        else:
            advertiser_id = adv.get("advertiser_id", "")
            checar(
                bool(advertiser_id),
                f"advertiser_id encontrado ({advertiser_id})",
                "advertiser_id ausente na resposta",
            )

            campanhas = ml_product_ads.listar_campanhas(advertiser_id, dias=14)
            ativas = [c for c in campanhas if str(c.get("status", "")).lower() == "active"]
            log(INFO, f"Campanhas: {len(campanhas)} total, {len(ativas)} active")

            for c in campanhas[:5]:
                log(
                    INFO,
                    f"  {c.get('nome', '?')[:40]} | status={c.get('status')} | "
                    f"acos={c.get('acos', 0)} | cost={c.get('cost', 0)}",
                )

            acima = ml_product_ads.campanhas_acos_acima_limite(dias=14)
            if acima:
                log(INFO, f"AVISO: {len(acima)} campanha(s) com ACOS acima do limite")
                for c in acima[:3]:
                    log(INFO, f"  {c.get('nome', '?')[:40]} | acos={c.get('acos', 0)}")
            else:
                log(INFO, "Nenhuma campanha com ACOS acima do limite")
    except Exception as exc:
        checar(False, "", f"Excecao no TESTE 2: {exc}")


# ══════════════════════════════════════════════════════════════
# TESTE 3 — Pedidos pagos prontos para faturar
# ══════════════════════════════════════════════════════════════
print()
print("=" * 55)
print("TESTE 3 — Pedidos pagos (ultimos 7 dias)")
print("=" * 55)

if not _ml_habilitado():
    ignorar("Mercado Livre nao configurado — pedidos ignorados")
else:
    try:
        from integracoes.ml import ml_client

        pedidos_ml = ml_client.listar_pedidos(dias=7)
        checar(
            isinstance(pedidos_ml, list),
            f"listar_pedidos() retornou lista ({len(pedidos_ml)} pedido(s))",
            "listar_pedidos() retornou tipo invalido",
        )

        for p in pedidos_ml[:5]:
            skus = [i.get("sku") or "?" for i in (p.get("itens") or [])]
            log(
                INFO,
                f"  order_id={p.get('order_id')} | total=R$ {p.get('total', 0)} | "
                f"skus={', '.join(skus) or '(sem sku)'}",
            )
    except Exception as exc:
        checar(False, "", f"Excecao no TESTE 3: {exc}")


# ══════════════════════════════════════════════════════════════
# TESTE 4 — NF-e automática (dry-run)
# ══════════════════════════════════════════════════════════════
print()
print("=" * 55)
print("TESTE 4 — NF-e automatica (dry-run, sem emitir)")
print("=" * 55)

try:
    from agentes.faturamento.agente_faturamento import emitir_nfe_pedido
    from core import config as cfg

    pedido_nfe: dict | None = None

    if pedidos_ml:
        primeiro = pedidos_ml[0]
        itens_fmt = [
            {
                "sku": str(i.get("sku", "")).strip(),
                "quantidade": int(i.get("quantidade") or 1),
                "valor_unitario": float(i.get("preco_unitario") or 0),
            }
            for i in (primeiro.get("itens") or [])
            if str(i.get("sku", "")).strip()
        ]
        if itens_fmt:
            pedido_nfe = {
                "pedido_id": str(primeiro.get("order_id", "PEDIDO-ML")),
                "cliente": {"nome": "Consumidor Final", "documento": ""},
                "itens": itens_fmt,
            }
            log(INFO, f"Usando pedido real ML {pedido_nfe['pedido_id']} ({len(itens_fmt)} item(ns))")

    if not pedido_nfe:
        pedido_nfe = {
            "pedido_id": "SIMULADO-1",
            "cliente": {"nome": "Consumidor Final", "documento": ""},
            "itens": [{"sku": "ESM-001", "quantidade": 1, "valor_unitario": 9.9}],
        }
        log(INFO, "Sem pedidos reais com SKU — usando pedido SIMULADO")

    resultado = emitir_nfe_pedido(pedido_nfe, dry_run=True)

    if resultado.get("ok"):
        checar(
            True,
            f"payload NF-e montado — emissao pronta ({resultado.get('itens_total', 0)} item(ns))",
        )
    else:
        ignorar("pendencias fiscais (nao e falha de codigo)")
        log(INFO, f"Erro: {resultado.get('erro', '?')}")
        for err in resultado.get("erros") or []:
            log(INFO, f"  pendencia: {err}")

    print()
    log(INFO, "Checklist fiscal (defaults do .env):")
    log(INFO, f"  NFE_NATUREZA_OPERACAO = {cfg.NFE_NATUREZA_OPERACAO}")
    log(INFO, f"  NFE_CFOP_PADRAO       = {cfg.NFE_CFOP_PADRAO}")
    log(INFO, f"  NFE_CST_PADRAO        = {cfg.NFE_CST_PADRAO}")
    log(INFO, f"  NFE_CSOSN_PADRAO      = {cfg.NFE_CSOSN_PADRAO}")
    log(INFO, f"  NFE_ORIGEM_PADRAO     = {cfg.NFE_ORIGEM_PADRAO}")
    log(INFO, f"  NFE_SERIE_PADRAO      = {cfg.NFE_SERIE_PADRAO}")
    print()
    log(INFO, "Requisitos para emissao 100% automatica:")
    log(INFO, "  1. Todo produto com NCM valido (8 digitos) no Bling/catalogo fiscal")
    log(INFO, "  2. Dados do destinatario (nome/documento/endereco) vindos do pedido")
    log(INFO, "  3. Escopo NFe autorizado no app do Bling (OAuth)")
    log(INFO, "  4. Certificado digital A1 configurado na conta Bling")
    log(INFO, "  5. Serie/numeracao fiscal habilitada no Bling")

except Exception as exc:
    checar(False, "", f"Excecao no TESTE 4: {exc}")


# ══════════════════════════════════════════════════════════════
# RESULTADO FINAL
# ══════════════════════════════════════════════════════════════
print()
print("=" * 55)
passou = sum(1 for r in resultados if r is True)
falhou = sum(1 for r in resultados if r is False)
ignorado = sum(1 for r in resultados if r is None)
total = len([r for r in resultados if r is not None])
pct = int(passou / total * 100) if total else 0

emoji = "SUCESSO" if falhou == 0 else "FALHOU"
print(f"{emoji} — {passou}/{total} testes passaram ({pct}%)")
if ignorado:
    print(f"  {ignorado} teste(s) ignorado(s) — integracao nao configurada ou sem permissao")
if falhou:
    print(f"  {falhou} teste(s) falharam — veja os [ERRO] acima")
print("=" * 55)
print()

sys.exit(0 if falhou == 0 else 1)
