"""
agentes/sincronizar_estoque_marketplaces.py
Sincroniza estoque do Bling para marketplaces ativos em catalogo/produtos.json.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

from core.atomic_io import escrever_json_atomico
from core.config import SPEC
from core.datadog_metrics import incrementar
from core.notificador import alertar_critico, alertar_gestor
from integracoes.bling.bling_client import listar_produtos_por_sku_detalhado, probe_produtos
from integracoes.magalu.magalu_client import atualizar_estoque_item as atualizar_estoque_magalu
from integracoes.ml.ml_client import atualizar_estoque_item as atualizar_estoque_ml
from integracoes.ml.ml_client import pausar_anuncio
from integracoes.shopee.shopee_client import atualizar_estoque_item as atualizar_estoque_shopee

logger = logging.getLogger("sincronizar_estoque_marketplaces")

_MARKETPLACES_ATIVOS: set[str] = {
    m["id"] for m in SPEC.get("marketplaces", []) if m.get("ativo", False)
}

ROOT = Path(__file__).resolve().parent.parent
CATALOGO_PATH = ROOT / "catalogo" / "produtos.json"
HEARTBEAT_PATH = ROOT / "logs" / "estoque_ultima.json"

_CANAIS_ESTOQUE: dict[str, Callable[..., bool]] = {
    "mercadolivre": atualizar_estoque_ml,
    "shopee": atualizar_estoque_shopee,
}
if "magalu" in _MARKETPLACES_ATIVOS:
    _CANAIS_ESTOQUE["magalu"] = atualizar_estoque_magalu


def _carregar_catalogo() -> list[dict]:
    try:
        if not CATALOGO_PATH.is_file():
            logger.warning("catalogo/produtos.json não encontrado")
            return []
        with CATALOGO_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.error("Erro ao carregar catalogo: %s", exc)
        return []


def _salvar_catalogo(produtos: list[dict]) -> None:
    try:
        tmp = CATALOGO_PATH.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(produtos, f, ensure_ascii=False, indent=2)
            f.write("\n")
        tmp.replace(CATALOGO_PATH)
    except Exception as exc:
        logger.error("Erro ao salvar catalogo: %s", exc)


def _item_id_valido(valor: Any) -> bool:
    texto = str(valor or "").strip()
    if not texto or "PREENCHER" in texto.upper():
        return False
    return True


def _ref_estoque_canal(canal: str, sku: str, dados: dict) -> Any | None:
    if canal == "magalu":
        return str(dados.get("sku") or sku).strip() or None
    if canal == "shopee":
        raw = dados.get("item_id")
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    if canal == "mercadolivre":
        raw = dados.get("item_id")
        return str(raw).strip() if _item_id_valido(raw) else None
    return None


def _aplicar_estoque(canal: str, ref: Any, estoque: int, dados: dict) -> bool:
    fn = _CANAIS_ESTOQUE.get(canal)
    if not fn:
        return False
    try:
        if canal == "shopee":
            model_id = dados.get("model_id")
            if model_id is not None:
                return bool(fn(ref, estoque, model_id=int(model_id)))
            return bool(fn(ref, estoque))
        if canal == "magalu":
            return bool(fn(str(ref), estoque))
        return bool(fn(str(ref), estoque))
    except Exception as exc:
        logger.error("Erro ao aplicar estoque canal=%s ref=%s: %s", canal, ref, exc)
        return False


def executar(produtos: list[dict] | None = None, dry_run: bool = True) -> dict:
    if not dry_run:
        from core.guardrails import alertar_bloqueio_escrita_global, bloqueio_escrita_global

        if bloqueio := bloqueio_escrita_global():
            alertar_bloqueio_escrita_global()
            return {
                **bloqueio,
                "dry_run": False,
                "total_produtos": 0,
                "total_ajustes": 0,
                "ajustes": [],
                "produtos_sem_estoque_bling": [],
            }

    probe = probe_produtos()
    if not probe.get("ok"):
        msg = (
            f"⚠️ Sync estoque abortado — Bling indisponível "
            f"(HTTP {probe.get('status')}: {probe.get('msg')}). "
            "Não confundir com 'nada a sincronizar'."
        )
        try:
            alertar_critico(msg, chave="estoque:bling_indisponivel")
        except Exception as exc:
            logger.error("alertar_critico: %s", exc)
        try:
            from datetime import datetime, timezone

            escrever_json_atomico(
                HEARTBEAT_PATH,
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ok": False,
                    "dry_run": dry_run,
                    "erro": "bling_indisponivel",
                    "probe": probe,
                    "total_ajustes": 0,
                    "total_aplicados_sucesso": 0,
                    "total_falhas_aplicacao": 0,
                },
            )
        except Exception as exc:
            logger.warning("Estoque: falha ao gravar heartbeat: %s", exc)
        return {
            "ok": False,
            "erro": "bling_indisponivel",
            "probe": probe,
            "dry_run": dry_run,
            "total_produtos": 0,
            "total_ajustes": 0,
            "ajustes": [],
            "produtos_sem_estoque_bling": [],
        }

    catalogo = produtos if produtos is not None else _carregar_catalogo()
    produtos_bling, bling_ok = listar_produtos_por_sku_detalhado()
    if not bling_ok:
        try:
            alertar_critico(
                "⚠️ Sync estoque abortado — falha ao listar produtos no Bling "
                "(auth/API). Catálogo vazio não é tratado como sucesso.",
                chave="estoque:bling_lista_falhou",
            )
        except Exception as exc:
            logger.error("alertar_critico: %s", exc)
        return {
            "ok": False,
            "erro": "bling_lista_falhou",
            "dry_run": dry_run,
            "total_produtos": len(catalogo),
            "total_ajustes": 0,
            "ajustes": [],
            "produtos_sem_estoque_bling": [],
        }
    ajustes: list[dict] = []
    sem_estoque_bling: list[str] = []
    skipped_placeholder: list[str] = []
    falhas_pausa: list[str] = []
    catalogo_alterado = False
    zeros_ativos: list[str] = []

    for produto in catalogo:
        sku = str(produto.get("sku") or "").strip()
        if not sku:
            continue

        bling = produtos_bling.get(sku) or {}
        if not bling:
            logger.warning("SKU %s não encontrado no catálogo Bling — pulando", sku)
            sem_estoque_bling.append(sku)
            continue

        estoque_bling = bling.get("estoque")
        if estoque_bling is None:
            logger.warning("Estoque Bling desconhecido para sku=%s — pulando", sku)
            sem_estoque_bling.append(sku)
            continue

        estoque_bling = int(estoque_bling)
        canais = produto.get("canais") or {}
        if not isinstance(canais, dict):
            continue

        for canal, dados in canais.items():
            if not isinstance(dados, dict) or not dados.get("ativo"):
                continue

            if canal == "mercadolivre" and not _item_id_valido(dados.get("item_id")):
                skipped_placeholder.append(f"{sku}/{canal}")
                continue

            ref = _ref_estoque_canal(canal, sku, dados)
            if ref is None:
                continue

            try:
                estoque_anterior = int(dados.get("estoque", 0) or 0)
            except (TypeError, ValueError):
                estoque_anterior = 0

            if estoque_anterior == estoque_bling:
                continue

            aplicado = None
            falhou_aplicacao = False
            if not dry_run:
                aplicado = _aplicar_estoque(canal, ref, estoque_bling, dados)
                if aplicado:
                    dados["estoque"] = estoque_bling
                    catalogo_alterado = True
                    incrementar("estoque.aplicado", tags=[f"canal:{canal}"])
                    if estoque_bling == 0:
                        zeros_ativos.append(f"{sku}/{canal}")
                        if canal == "mercadolivre" and _item_id_valido(ref):
                            pausou = pausar_anuncio(str(ref), dry_run=False, confirmar=True)
                            if not (isinstance(pausou, dict) and pausou.get("ok")):
                                falhas_pausa.append(f"{sku}/{canal}")
                else:
                    falhou_aplicacao = True
                    incrementar("estoque.falha_aplicacao", tags=[f"canal:{canal}"])
                    logger.error(
                        "Sincronizar estoque: falha ao aplicar sku=%s canal=%s ref=%s estoque_bling=%s",
                        sku, canal, ref, estoque_bling,
                    )

            ajustes.append(
                {
                    "sku": sku,
                    "canal": canal,
                    "estoque_bling": estoque_bling,
                    "estoque_anterior_canal": estoque_anterior,
                    "aplicado": aplicado,
                    "falhou_aplicacao": falhou_aplicacao,
                }
            )

    if not dry_run and catalogo_alterado:
        _salvar_catalogo(catalogo)

    total_ajustes = len(ajustes)
    total_aplicados_sucesso = sum(1 for a in ajustes if not dry_run and a["aplicado"])
    total_falhas_aplicacao = sum(1 for a in ajustes if a["falhou_aplicacao"])

    if total_ajustes > 0:
        try:
            if dry_run:
                alertar_gestor(f"Estoque sincronizado: {total_ajustes} ajustes detectados (dry_run=True)")
            else:
                alertar_gestor(
                    f"Estoque sincronizado: {total_aplicados_sucesso}/{total_ajustes} "
                    f"ajustes aplicados com sucesso (dry_run=False)"
                )
        except Exception as exc:
            logger.error("alertar_gestor: %s", exc)

    if total_falhas_aplicacao > 0:
        skus_falha = sorted({a["sku"] for a in ajustes if a["falhou_aplicacao"]})
        try:
            alertar_critico(
                f"⚠️ Sincronização de estoque: {total_falhas_aplicacao} ajuste(s) FALHARAM ao aplicar "
                f"(estoque exibido no marketplace pode estar desatualizado/incorreto).\n"
                f"SKUs afetados: {', '.join(skus_falha[:10])}"
            )
        except Exception as exc:
            logger.error("alertar_critico: %s", exc)

    if zeros_ativos:
        try:
            alertar_critico(
                "Estoque zerado em canal ativo — revisar anúncios:\n"
                + "\n".join(f"• {z}" for z in zeros_ativos[:10])
            )
        except Exception as exc:
            logger.error("alertar_critico: %s", exc)

    if falhas_pausa:
        try:
            alertar_critico(
                "⚠️ Estoque zerado mas falha ao pausar anúncio ML:\n"
                + "\n".join(f"• {z}" for z in falhas_pausa[:10]),
                chave="estoque:falha_pausa_anuncio",
            )
        except Exception as exc:
            logger.error("alertar_critico: %s", exc)

    if skipped_placeholder:
        try:
            incrementar("estoque.skipped_placeholder_mlb")
            alertar_gestor(
                f"Estoque: {len(skipped_placeholder)} canal(is) ML com MLB_PREENCHER "
                f"pulados (sem sync real):\n"
                + "\n".join(f"• {s}" for s in skipped_placeholder[:8]),
                chave="estoque:skipped_placeholder",
                cooldown_segundos=86400,
            )
        except Exception as exc:
            logger.error("alerta placeholder: %s", exc)

    # Muitos SKUs sem saldo Bling = fonte de verdade cega (listagem sem estoque)
    pct_sem = (
        (100.0 * len(sem_estoque_bling) / len(catalogo)) if catalogo else 0.0
    )
    if catalogo and pct_sem >= 50.0:
        try:
            alertar_critico(
                f"⚠️ Sync estoque: {len(sem_estoque_bling)}/{len(catalogo)} SKUs "
                f"sem saldo Bling ({pct_sem:.0f}%). Listagem GET /produtos pode "
                "não trazer estoque — sync não moveu marketplace.",
                chave="estoque:bling_saldo_ausente",
            )
        except Exception as exc:
            logger.error("alertar_critico: %s", exc)

    ok_hb = total_falhas_aplicacao == 0 and not falhas_pausa and pct_sem < 80.0
    payload = {
        "ok": ok_hb,
        "dry_run": dry_run,
        "total_produtos": len(catalogo),
        "total_ajustes": total_ajustes,
        "total_aplicados_sucesso": total_aplicados_sucesso,
        "total_falhas_aplicacao": total_falhas_aplicacao,
        "skipped_placeholder_mlb": len(skipped_placeholder),
        "falhas_pausa_anuncio": len(falhas_pausa),
        "ajustes": ajustes,
        "produtos_sem_estoque_bling": sem_estoque_bling,
    }
    logger.info("Sincronizar estoque: %s", payload)
    try:
        from datetime import datetime, timezone

        escrever_json_atomico(
            HEARTBEAT_PATH,
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ok": ok_hb,
                "dry_run": dry_run,
                "total_ajustes": total_ajustes,
                "total_aplicados_sucesso": total_aplicados_sucesso,
                "total_falhas_aplicacao": total_falhas_aplicacao,
                "skipped_placeholder_mlb": len(skipped_placeholder),
                "produtos_sem_estoque_bling": len(sem_estoque_bling),
            },
        )
        incrementar("estoque.rodadas", tags=[f"dry_run:{str(bool(dry_run)).lower()}"])
    except Exception as exc:
        logger.warning("Estoque: falha ao gravar heartbeat: %s", exc)
    return payload


def main() -> int:
    dry = os.getenv("ESTOQUE_SYNC_DRY_RUN", "false").strip().lower() in ("1", "true", "yes")
    executar(dry_run=dry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
