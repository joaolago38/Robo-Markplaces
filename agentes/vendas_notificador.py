"""
agentes/vendas_notificador.py
Verifica novas vendas em todos os marketplaces e envia notificação WhatsApp.
Mantém controle de pedidos já notificados para não duplicar mensagens.
Nunca lança exceção.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from core.atomic_io import escrever_json_atomico, lock_exclusivo
from core.config import ROOT, SPEC
from core.datadog_metrics import incrementar
from core.log_opcional import erro_opcional, log_erros_pedidos_ativos
from core.notificador import alertar_critico
from core.whatsapp import notificar_venda

logger = logging.getLogger("vendas_notificador")

_MARKETPLACES_ATIVOS: set[str] = {
    m["id"] for m in SPEC.get("marketplaces", []) if m.get("ativo", False)
}

PEDIDOS_NOTIFICADOS_PATH: Path = ROOT / "dados" / "pedidos_notificados.json"
_LOCK_PATH: Path = PEDIDOS_NOTIFICADOS_PATH.with_name(PEDIDOS_NOTIFICADOS_PATH.name + ".lock")
HEARTBEAT_PATH: Path = ROOT / "logs" / "vendas_whatsapp_ultima.json"


def _carregar_notificados() -> set[str]:
    """Carrega IDs de pedidos já notificados do arquivo de controle."""
    try:
        PEDIDOS_NOTIFICADOS_PATH.parent.mkdir(parents=True, exist_ok=True)
        if PEDIDOS_NOTIFICADOS_PATH.exists():
            data = json.loads(PEDIDOS_NOTIFICADOS_PATH.read_text(encoding="utf-8"))
            return set(data.get("notificados", []))
    except Exception as exc:
        logger.error("Erro ao carregar pedidos notificados: %s", exc)
    return set()


def _salvar_notificados(ids: set[str]) -> None:
    """Salva IDs de pedidos já notificados no arquivo de controle (escrita atômica)."""
    try:
        lista = sorted(ids)[-1000:]
        escrever_json_atomico(PEDIDOS_NOTIFICADOS_PATH, {"notificados": lista})
    except Exception as exc:
        logger.error("Erro ao salvar pedidos notificados: %s", exc)


def _checar_busca_falhou(
    marketplace: str,
    ok: bool,
    *,
    auth_quebrada: bool = False,
) -> None:
    """
    Quando a chamada à API falhou de verdade (token expirado, API fora do
    ar, etc.), `pedidos` volta vazio igual a "sem venda nova" — sem isto,
    as duas situações são indistinguíveis e o time nunca saberia que está
    cego para vendas reais enquanto o problema persistir.

    Auth quebrada conhecida (ex.: Magalu invalid_grant) NÃO incrementa
    `vendas.busca_falhou` (P1) — vai para `vendas.busca_auth_quebrada` e
    alerta com cooldown longo, para não misturar com queda genérica da API.

    Religar ERROR no Datadog: LOG_ERROS_PEDIDOS=1
    """
    if ok:
        return

    mp_tag = marketplace.lower().replace(" ", "")
    if auth_quebrada:
        try:
            incrementar(
                "vendas.busca_auth_quebrada",
                tags=[f"marketplace:{mp_tag}"],
            )
        except Exception:
            pass
        erro_opcional(
            logger,
            log_erros_pedidos_ativos(),
            "%s: auth quebrada na busca de pedidos (fora do P1 vendas.busca_falhou).",
            marketplace,
            flag_hint="LOG_ERROS_PEDIDOS",
        )
        try:
            from core.notificador import alertar_gestor

            alertar_gestor(
                f"🔐 {marketplace}: OAuth/token inválido — vendas WhatsApp deste canal "
                "podem estar cegas.\nRenove o token nos secrets. "
                "(Não conta no monitor P1 de busca genérica.)",
                chave=f"falha_pedidos_auth:{marketplace}",
                cooldown_segundos=86400,
            )
        except Exception:
            pass
        return

    try:
        incrementar(
            "vendas.busca_falhou",
            tags=[f"marketplace:{mp_tag}"],
        )
    except Exception:
        pass
    erro_opcional(
        logger,
        log_erros_pedidos_ativos(),
        "%s: busca de pedidos FALHOU (não é 'sem vendas novas' — a chamada não completou).",
        marketplace,
        flag_hint="LOG_ERROS_PEDIDOS",
    )
    alertar_critico(
        f"⚠️ Não consegui buscar pedidos novos no {marketplace}.\n"
        "Isso pode significar que vendas reais não estão sendo notificadas. "
        "Verifique o token/credenciais e o status da API.",
        chave=f"falha_pedidos:{marketplace}",
    )


def _notificar_novos_pedidos(
    marketplace: str, pedidos: list[dict], notificados: set[str]
) -> set[str]:
    """
    Para cada pedido da lista, envia WhatsApp se ainda não foi notificado.
    Retorna conjunto com as chaves recém-notificadas (marketplace:order_id).
    """
    novos: set[str] = set()
    for pedido in pedidos:
        pedido_id = str(pedido.get("order_id", ""))
        chave = f"{marketplace}:{pedido_id}"

        if not pedido_id or chave in notificados:
            continue

        itens = pedido.get("itens", [])
        if itens:
            produto = (
                itens[0].get("sku", "Produto") if len(itens) == 1 else f"{len(itens)} itens"
            )
            quantidade = sum(int(i.get("quantidade", 1) or 1) for i in itens)
        else:
            produto = str(pedido.get("produto", "Produto"))
            quantidade = int(pedido.get("quantidade", 1) or 1)

        try:
            valor = float(pedido.get("total", 0) or 0)
        except (TypeError, ValueError):
            valor = 0.0

        ok = notificar_venda(
            marketplace=marketplace,
            pedido_id=pedido_id,
            produto=produto,
            valor=valor,
            quantidade=quantidade,
        )

        if ok:
            novos.add(chave)
            logger.info(
                "WhatsApp notificado: %s pedido %s valor R$ %.2f",
                marketplace,
                pedido_id,
                valor,
            )
            try:
                incrementar("vendas.notificadas", tags=[f"marketplace:{marketplace}"])
            except Exception:
                pass
        else:
            logger.warning("WhatsApp FALHOU: %s pedido %s", marketplace, pedido_id)
            try:
                incrementar("vendas.falha_whatsapp", tags=[f"marketplace:{marketplace}"])
            except Exception:
                pass

    return novos


def notificar_pedidos_novos_marketplace(marketplace: str) -> dict:
    """
    Processa apenas um marketplace (ex.: ao final de cada agente de chat).
    Retorna resumo com quantidade de notificações enviadas.
    """
    mp = (marketplace or "").strip().lower()
    novos: set[str] = set()
    res: dict = {"marketplace": mp, "notificacoes": 0}
    if mp == "magalu" and "magalu" not in _MARKETPLACES_ATIVOS:
        logger.info("Magalu inativo no spec — ignorando notificação")
        return res
    try:
        notificados = _carregar_notificados()
        pedidos: list[dict] = []
        if mp == "mercadolivre":
            from integracoes.ml.ml_client import listar_pedidos_detalhado as lp_detalhado

            pedidos, ok = lp_detalhado(dias=1)
            _checar_busca_falhou("Mercado Livre", ok)
        elif mp == "shopee":
            from integracoes.shopee.shopee_client import listar_pedidos_detalhado as lp_detalhado

            pedidos, ok = lp_detalhado(dias=1)
            _checar_busca_falhou("Shopee", ok)
        elif mp == "magalu":
            from integracoes.magalu import magalu_client as mag_cli

            pedidos, ok = mag_cli.listar_pedidos_detalhado(dias=1)
            _checar_busca_falhou(
                "Magalu",
                ok,
                auth_quebrada=(not ok) and mag_cli.ultima_listagem_auth_quebrada(),
            )
        elif mp == "amazon":
            from integracoes.amazon.amazon_client import listar_pedidos_detalhado as lp_detalhado

            pedidos, ok = lp_detalhado(dias=1)
            _checar_busca_falhou("Amazon", ok)
        else:
            logger.warning("Marketplace desconhecido para vendas WhatsApp: %s", marketplace)
            return res

        novos = _notificar_novos_pedidos(mp, pedidos, notificados)
        if novos:
            _salvar_notificados(notificados | novos)
    except Exception as exc:
        logger.error("notificar_pedidos_novos_marketplace %s: %s", mp, exc)
    res["notificacoes"] = len(novos)
    return res


def executar() -> dict:
    """
    Verifica novas vendas em todos os marketplaces e notifica via WhatsApp.
    Retorna resumo com total de notificações enviadas por marketplace.

    Todo o ciclo (ler quem já foi notificado → buscar pedidos novos →
    salvar quem foi notificado agora) roda dentro de um lock exclusivo
    entre processos: sem isso, duas execuções concorrentes (ex.: a API
    viva chamando isto ao mesmo tempo que um workflow agendado) podem
    ler o mesmo estado antigo e uma sobrescrever o "salvar" da outra —
    o que faria o WhatsApp notificar a mesma venda duas vezes.
    """
    with lock_exclusivo(_LOCK_PATH):
        notificados = _carregar_notificados()
        novos_total: set[str] = set()
        resumo: dict[str, int] = {}

        try:
            from integracoes.ml.ml_client import listar_pedidos_detalhado

            pedidos_ml, ok_ml = listar_pedidos_detalhado(dias=1)
            _checar_busca_falhou("Mercado Livre", ok_ml)
            novos_ml = _notificar_novos_pedidos("mercadolivre", pedidos_ml, notificados)
            resumo["mercadolivre"] = len(novos_ml)
            novos_total.update(novos_ml)
            notificados |= novos_ml
        except Exception as exc:
            logger.error("Erro ao buscar pedidos ML: %s", exc)
            resumo["mercadolivre"] = 0

        if "shopee" in _MARKETPLACES_ATIVOS:
            try:
                from integracoes.shopee.shopee_client import listar_pedidos_detalhado as shopee_pedidos_detalhado

                pedidos_shopee, ok_shopee = shopee_pedidos_detalhado(dias=1)
                _checar_busca_falhou("Shopee", ok_shopee)
                novos_shopee = _notificar_novos_pedidos("shopee", pedidos_shopee, notificados)
                resumo["shopee"] = len(novos_shopee)
                novos_total.update(novos_shopee)
                notificados |= novos_shopee
            except Exception as exc:
                logger.error("Erro ao buscar pedidos Shopee: %s", exc)
                resumo["shopee"] = 0

        if "magalu" in _MARKETPLACES_ATIVOS:
            try:
                from integracoes.magalu import magalu_client as mag_cli

                pedidos_magalu, ok_magalu = mag_cli.listar_pedidos_detalhado(dias=1)
                _checar_busca_falhou(
                    "Magalu",
                    ok_magalu,
                    auth_quebrada=(not ok_magalu)
                    and mag_cli.ultima_listagem_auth_quebrada(),
                )
                novos_magalu = _notificar_novos_pedidos("magalu", pedidos_magalu, notificados)
                resumo["magalu"] = len(novos_magalu)
                novos_total.update(novos_magalu)
                notificados |= novos_magalu
            except Exception as exc:
                logger.error("Erro ao buscar pedidos Magalu: %s", exc)
                resumo["magalu"] = 0

        if "amazon" in _MARKETPLACES_ATIVOS:
            try:
                from integracoes.amazon.amazon_client import listar_pedidos_detalhado as amazon_pedidos_detalhado

                pedidos_amazon, ok_amazon = amazon_pedidos_detalhado(dias=1)
                _checar_busca_falhou("Amazon", ok_amazon)
                novos_amazon = _notificar_novos_pedidos("amazon", pedidos_amazon, notificados)
                resumo["amazon"] = len(novos_amazon)
                novos_total.update(novos_amazon)
                notificados |= novos_amazon
            except Exception as exc:
                logger.error("Erro ao buscar pedidos Amazon: %s", exc)
                resumo["amazon"] = 0

        if novos_total:
            _salvar_notificados(notificados)

    total = sum(resumo.values())
    logger.info("Notificações WhatsApp enviadas: %d | Detalhe: %s", total, resumo)
    try:
        from datetime import datetime, timezone

        incrementar("vendas.rodadas")
        escrever_json_atomico(
            HEARTBEAT_PATH,
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ok": True,
                "total_notificacoes": total,
                "por_marketplace": resumo,
            },
        )
    except Exception as exc:
        logger.warning("Vendas WhatsApp heartbeat: %s", exc)
    return {"total_notificacoes": total, "por_marketplace": resumo}


if __name__ == "__main__":
    import pprint

    pprint.pprint(executar())
