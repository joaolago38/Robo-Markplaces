"""
agentes/social/agente_conversao_manicures.py
Conversão ativa + reativa de manicures → compra no Mercado Livre
(WhatsApp, Instagram, Facebook, chat ML) com Claude Haiku 4.5.

Uso:
  python -m agentes.social.agente_conversao_manicures
  python -m agentes.social.agente_conversao_manicures --sem-envio
  python -m agentes.social.agente_conversao_manicures --so-inbox
  python -m agentes.social.agente_conversao_manicures --so-ativo
  python -m agentes.social.agente_conversao_manicures --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.claude_client import MODELO_RAPIDO
from core.config import (
    ANTHROPIC_API_KEY,
    CONVERSAO_MANICURES_ALERTA,
    CONVERSAO_MANICURES_ATIVO,
    CONVERSAO_MANICURES_BLOQUEAR_SE_INSUSTENTAVEL,
    CONVERSAO_MANICURES_CHAT_ML,
    CONVERSAO_MANICURES_COOLDOWN_SEG,
    CONVERSAO_MANICURES_GASTO_MIN_AVALIAR,
    CONVERSAO_MANICURES_IMAGEM_IG_URL,
    CONVERSAO_MANICURES_PUBLICAR_FB,
    CONVERSAO_MANICURES_PUBLICAR_IG,
    CONVERSAO_MANICURES_REPLY_META,
    CONVERSAO_MANICURES_REPLY_WA,
    CONVERSAO_MANICURES_ROAS_MIN_REAL,
    CONVERSAO_MANICURES_SUST_DIAS,
    CONVERSAO_MANICURES_SUSTENTABILIDADE,
    META_ACCESS_TOKEN,
    META_INSTAGRAM_ID,
    META_PAGE_ID,
    ML_ACCESS_TOKEN,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import (
    alertar_gestor,
    chave_resumo_periodo,
    enviar_telegram_manicures,
    manicures_telegram_configurado,
)
from core.whatsapp import (
    buscar_mensagens_grupo_recentes,
    enviar_grupo_manicures,
    enviar_mensagem,
    whatsapp_grupo_manicures_configurado,
)
from integracoes.meta.meta_client import publicar_facebook, publicar_instagram
from integracoes.meta.meta_inbox import coletar_inbox_meta, responder_comentario
from integracoes.social.conversao_manicures import (
    append_lead,
    atualizar_lead,
    classificar_e_responder_lead,
    diagnosticar_canais,
    escolher_oferta_haiku,
    ids_leads_conhecidos,
    lead_id,
    montar_mensagem_gestor,
    pergunta_parece_manicure,
    resposta_chat_ml_haiku,
)
from integracoes.social.sustentabilidade_ads_ml import monitorar_venda_sustentavel
from integracoes.meta.meta_ads_client import listar_metricas_campanhas

logger = logging.getLogger("agente_conversao_manicures")

SNAPSHOT_PATH = ROOT / "logs" / "conversao_manicures_ultima.json"
HISTORICO_PATH = ROOT / "logs" / "conversao_manicures_historico.json"


def _sinal_ads() -> dict[str, Any]:
    """Meta pixel signal + (opcional) cruzamento sustentável com vendas ML."""
    try:
        from integracoes.meta.meta_ads_client import normalizar_metrica_campanha

        dias = max(1, CONVERSAO_MANICURES_SUST_DIAS)
        rows = listar_metricas_campanhas(periodo_dias=dias, limite=30) or []
        campanhas = [normalizar_metrica_campanha(r) for r in rows if isinstance(r, dict)]
        gasto = sum(float(r.get("gasto") or 0) for r in campanhas)
        compras = sum(float(r.get("compras") or 0) for r in campanhas)
        receita = sum(float(r.get("receita") or 0) for r in campanhas)
        roas = (receita / gasto) if gasto > 0 else 0.0
        base = {
            "campanhas": len(campanhas),
            "gasto": round(gasto, 2),
            "compras": round(compras, 2),
            "roas": round(roas, 2),
            "periodo_dias": dias,
        }
        if not CONVERSAO_MANICURES_SUSTENTABILIDADE:
            return base

        sust = monitorar_venda_sustentavel(
            periodo_dias=dias,
            roas_min_real=CONVERSAO_MANICURES_ROAS_MIN_REAL,
            gasto_minimo_avaliar=CONVERSAO_MANICURES_GASTO_MIN_AVALIAR,
        )
        avaliacao = sust.get("avaliacao") or {}
        base["sustentabilidade"] = avaliacao
        base["receita_ml"] = (sust.get("ml") or {}).get("receita_ml")
        base["pedidos_ml"] = (sust.get("ml") or {}).get("pedidos_ml")
        base["roas_real"] = avaliacao.get("roas_real")
        base["status_sustentavel"] = avaliacao.get("status")
        return base
    except Exception as exc:
        logger.info("sinal ads indisponível: %s", exc)
        return {"campanhas": 0, "gasto": 0, "compras": 0, "roas": 0, "erro": str(exc)[:120]}


def _pode_impulsionar_ativo(ads: dict[str, Any]) -> tuple[bool, str]:
    """False quando gasto Ads > vendas ML (modo sustentável — só status crítico)."""
    if not CONVERSAO_MANICURES_SUSTENTABILIDADE:
        return True, ""
    if not CONVERSAO_MANICURES_BLOQUEAR_SE_INSUSTENTAVEL:
        return True, ""
    sust = ads.get("sustentabilidade") or {}
    status = str(sust.get("status") or "")
    if status == "critico":
        return False, "bloqueado_sustentabilidade:critico"
    return True, ""

def _cooldown_ativo(historico: dict[str, Any]) -> tuple[bool, str]:
    ultimo = historico.get("ultimo_envio_ativo_em")
    if not ultimo:
        return False, ""
    try:
        dt = datetime.fromisoformat(str(ultimo).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        restante = CONVERSAO_MANICURES_COOLDOWN_SEG - (
            datetime.now(timezone.utc) - dt
        ).total_seconds()
        if restante > 0:
            return True, f"cooldown_ativo ({int(restante // 60)}min)"
    except Exception:
        return False, ""
    return False, ""


def _processar_inbox(
    oferta: dict[str, Any],
    *,
    enviar: bool,
) -> dict[str, Any]:
    conhecidos = ids_leads_conhecidos()
    coletados: list[dict[str, Any]] = []

    meta = coletar_inbox_meta()
    for c in meta.get("comentarios") or []:
        coletados.append(c)

    for m in buscar_mensagens_grupo_recentes(limite=40):
        coletados.append(m)

    novos = 0
    respondidos = 0
    enfileirados = 0
    detalhes: list[dict[str, Any]] = []

    link = str(oferta.get("link_ml") or "")
    nome = str(oferta.get("campanha_nome") or "")

    for item in coletados:
        canal = str(item.get("canal") or "social")
        ext = str(item.get("externo_id") or item.get("id") or "")
        texto = str(item.get("texto") or "")
        lid = lead_id(canal, ext, texto)
        if lid in conhecidos:
            continue
        conhecidos.add(lid)
        novos += 1

        classif = classificar_e_responder_lead(
            texto, canal=canal, link_ml=link, oferta_nome=nome
        )
        lead = append_lead(
            {
                "id": lid,
                "canal": canal,
                "externo_id": ext,
                "autor": item.get("autor"),
                "texto": texto,
                "post_id": item.get("post_id"),
                "intencao": classif.get("intencao"),
                "status": "novo",
                "resposta": classif.get("resposta") or "",
                "link_ml": link,
                "converter": bool(classif.get("converter")),
            }
        )

        enviou = False
        if (
            enviar
            and classif.get("converter")
            and classif.get("resposta")
        ):
            if canal in ("facebook", "instagram") and CONVERSAO_MANICURES_REPLY_META:
                out = responder_comentario(ext, str(classif.get("resposta")))
                enviou = bool(out.get("ok"))
            elif canal == "whatsapp" and CONVERSAO_MANICURES_REPLY_WA:
                autor = str(item.get("autor") or "").split("@")[0]
                # só DM se autor parecer número; senão responde no grupo
                if autor.isdigit() and len(autor) >= 10:
                    enviou = bool(enviar_mensagem(autor, str(classif.get("resposta"))))
                else:
                    enviou = bool(enviar_grupo_manicures(str(classif.get("resposta"))))

        if enviou:
            respondidos += 1
            atualizar_lead(lid, {"status": "respondido"})
        elif classif.get("converter"):
            enfileirados += 1
            atualizar_lead(lid, {"status": "fila"})
        else:
            atualizar_lead(lid, {"status": "ignorado"})

        detalhes.append(
            {
                "id": lead.get("id"),
                "canal": canal,
                "intencao": classif.get("intencao"),
                "enviou": enviou,
            }
        )

    return {
        "novos": novos,
        "respondidos": respondidos,
        "enfileirados": enfileirados,
        "meta_status": meta.get("status"),
        "detalhes": detalhes[:30],
    }


def _chat_ml_manicures(oferta: dict[str, Any], *, enviar: bool) -> dict[str, Any]:
    if not CONVERSAO_MANICURES_CHAT_ML or not ML_ACCESS_TOKEN:
        return {"respondidas": 0, "motivo": "chat_ml_desligado_ou_sem_token"}
    try:
        from integracoes.ml.ml_client import listar_perguntas_nao_respondidas, responder_pergunta
    except Exception as exc:
        return {"respondidas": 0, "erro": str(exc)[:120]}

    link = str(oferta.get("link_ml") or "")
    ok = 0
    vistos = 0
    try:
        perguntas = listar_perguntas_nao_respondidas() or []
    except Exception as exc:
        return {"respondidas": 0, "erro": str(exc)[:120]}

    for p in perguntas[:15]:
        texto = str(p.get("text") or "").strip()
        if not pergunta_parece_manicure(texto):
            continue
        vistos += 1
        resp = resposta_chat_ml_haiku(texto, link, produto_ctx=str(oferta.get("campanha_nome") or ""))
        if not resp:
            continue
        if enviar:
            if responder_pergunta(str(p.get("id") or ""), resp):
                ok += 1
                time.sleep(0.8)
        else:
            ok += 1  # dry-run conta como preparada
    return {"respondidas": ok, "candidatas": vistos, "dry_run": not enviar}


def _envios_ativos(
    oferta: dict[str, Any],
    *,
    enviar: bool,
    permitir_boost: bool = True,
    motivo_bloqueio: str = "",
) -> dict[str, Any]:
    out = {
        "whatsapp": False,
        "telegram": False,
        "facebook": False,
        "instagram": False,
        "adiado": False,
        "motivo": "",
    }
    if not enviar:
        out["motivo"] = "dry_run"
        return out

    if not permitir_boost:
        out["adiado"] = True
        out["motivo"] = motivo_bloqueio or "bloqueado_sustentabilidade"
        return out

    historico = ler_json(HISTORICO_PATH, default={})
    if not isinstance(historico, dict):
        historico = {}
    aguarda, motivo = _cooldown_ativo(historico)
    if aguarda:
        out["adiado"] = True
        out["motivo"] = motivo
        return out

    wa_txt = str(oferta.get("copy_whatsapp") or "")
    fb_txt = str(oferta.get("copy_facebook") or "")
    ig_txt = str(oferta.get("copy_instagram") or "")

    if whatsapp_grupo_manicures_configurado() and wa_txt:
        out["whatsapp"] = bool(enviar_grupo_manicures(wa_txt))

    if manicures_telegram_configurado() and wa_txt:
        # telegram aceita markdown leve — usa facebook copy
        out["telegram"] = bool(
            enviar_telegram_manicures(
                fb_txt or wa_txt,
                chave=f"conversao_manicures:tg:{oferta.get('campanha_id')}",
                cooldown_segundos=CONVERSAO_MANICURES_COOLDOWN_SEG,
            )
        )

    if CONVERSAO_MANICURES_PUBLICAR_FB and META_ACCESS_TOKEN and META_PAGE_ID and fb_txt:
        out["facebook"] = bool(publicar_facebook(fb_txt))

    img = (CONVERSAO_MANICURES_IMAGEM_IG_URL or "").strip()
    if (
        CONVERSAO_MANICURES_PUBLICAR_IG
        and META_ACCESS_TOKEN
        and META_INSTAGRAM_ID
        and img
        and ig_txt
    ):
        out["instagram"] = bool(publicar_instagram(ig_txt, img))

    if any([out["whatsapp"], out["telegram"], out["facebook"], out["instagram"]]):
        historico["ultimo_envio_ativo_em"] = datetime.now(timezone.utc).isoformat()
        historico["ultima_campanha_id"] = oferta.get("campanha_id")
        historico["modelo"] = MODELO_RAPIDO
        escrever_json_atomico(HISTORICO_PATH, historico)

    return out


def executar(
    *,
    enviar: bool = True,
    so_inbox: bool = False,
    so_ativo: bool = False,
    enviar_alerta: bool = True,
) -> dict[str, Any]:
    """Pipeline conversão manicures. Nunca lança."""
    try:
        if not CONVERSAO_MANICURES_ATIVO:
            return {"ok": False, "motivo": "agente_desligado", "alerta_enviado": False}

        historico = ler_json(HISTORICO_PATH, default={})
        if not isinstance(historico, dict):
            historico = {}

        diag = diagnosticar_canais(
            {
                "wa": whatsapp_grupo_manicures_configurado(),
                "tg_manicures": manicures_telegram_configurado(),
                "fb": bool(META_ACCESS_TOKEN and META_PAGE_ID),
                "ig": bool(META_ACCESS_TOKEN and META_INSTAGRAM_ID),
                "ig_imagem": bool((CONVERSAO_MANICURES_IMAGEM_IG_URL or "").strip()),
                "claude": bool(ANTHROPIC_API_KEY),
                "ml": bool(ML_ACCESS_TOKEN),
                "reply_meta": CONVERSAO_MANICURES_REPLY_META,
                "reply_wa": CONVERSAO_MANICURES_REPLY_WA,
                "publicar_fb": CONVERSAO_MANICURES_PUBLICAR_FB,
                "publicar_ig": CONVERSAO_MANICURES_PUBLICAR_IG,
            }
        )

        ads = _sinal_ads()
        oferta = escolher_oferta_haiku(
            sinal_ads=ads,
            ultimo_campanha_id=str(historico.get("ultima_campanha_id") or "") or None,
        )
        if not oferta.get("ok"):
            incrementar("conversao_manicures.sem_oferta")
            return {
                "ok": False,
                "motivo": oferta.get("motivo") or "sem_oferta",
                "diagnostico": diag,
                "alerta_enviado": False,
            }

        inbox: dict[str, Any] = {"novos": 0, "respondidos": 0, "enfileirados": 0}
        envios: dict[str, Any] = {}
        chat_ml: dict[str, Any] = {}

        fazer_inbox = not so_ativo
        fazer_ativo = not so_inbox
        permitir_boost, motivo_boost = _pode_impulsionar_ativo(ads)

        if fazer_inbox:
            inbox = _processar_inbox(oferta, enviar=enviar)
        if fazer_ativo:
            envios = _envios_ativos(
                oferta,
                enviar=enviar,
                permitir_boost=permitir_boost,
                motivo_bloqueio=motivo_boost,
            )
            # Chat ML continua mesmo se Ads estiver insustentável (fecha venda orgânica)
            chat_ml = _chat_ml_manicures(oferta, enviar=enviar)
        elif so_inbox:
            envios = {"motivo": "so_inbox"}
            chat_ml = {"respondidas": 0, "motivo": "so_inbox"}

        sust = ads.get("sustentabilidade") or {}
        payload = {
            "ok": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "modelo": MODELO_RAPIDO,
            "diagnostico": diag,
            "ads": ads,
            "sustentabilidade": sust,
            "oferta": {
                k: oferta.get(k)
                for k in (
                    "campanha_id",
                    "campanha_nome",
                    "sku",
                    "preco_brl",
                    "link_ml",
                    "angulo",
                    "motivo",
                    "fonte",
                    "cta_ml",
                    "copy_whatsapp",
                    "copy_facebook",
                    "copy_instagram",
                )
            },
            "envios": envios,
            "inbox": inbox,
            "chat_ml": chat_ml,
            "modo": "dry_run" if not enviar else "envio",
        }
        payload["mensagem"] = montar_mensagem_gestor(payload)
        escrever_json_atomico(SNAPSHOT_PATH, payload)

        gauge("conversao_manicures.leads_novos", float(inbox.get("novos") or 0))
        gauge("conversao_manicures.chat_ml", float(chat_ml.get("respondidas") or 0))
        if sust.get("roas_real") is not None:
            gauge("conversao_manicures.roas_real", float(sust.get("roas_real") or 0))
        if sust.get("status") == "critico":
            incrementar("conversao_manicures.insustentavel")

        enviado_alerta = False
        if enviar_alerta and CONVERSAO_MANICURES_ALERTA and payload.get("mensagem"):
            enviado_alerta = bool(
                alertar_gestor(
                    payload["mensagem"],
                    chave=chave_resumo_periodo("conversao_manicures", horas_por_bucket=4),
                    cooldown_segundos=CONVERSAO_MANICURES_COOLDOWN_SEG,
                    agente_id="conversao_manicures",
                )
            )

        incrementar("conversao_manicures.ok")
        return {
            "ok": True,
            "alerta_enviado": enviado_alerta,
            "campanha_id": oferta.get("campanha_id"),
            "envios": envios,
            "inbox": inbox,
            "chat_ml": chat_ml,
            "pendentes": diag.get("pendentes"),
            "sustentabilidade": sust.get("status"),
            "roas_real": sust.get("roas_real"),
        }
    except Exception as exc:
        logger.error("agente_conversao_manicures erro: %s", exc)
        incrementar("conversao_manicures.erro")
        return {"ok": False, "erro": str(exc), "alerta_enviado": False}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Conversão manicures WA/IG/FB/ML")
    parser.add_argument("--sem-envio", action="store_true", help="Dry-run (não posta/não responde)")
    parser.add_argument("--so-inbox", action="store_true")
    parser.add_argument("--so-ativo", action="store_true")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args()
    out = executar(
        enviar=not args.sem_envio,
        so_inbox=args.so_inbox,
        so_ativo=args.so_ativo,
        enviar_alerta=not args.sem_alerta,
    )
    print(
        {
            "ok": out.get("ok"),
            "erro": out.get("erro") or out.get("motivo"),
            "alerta_enviado": out.get("alerta_enviado"),
            "campanha_id": out.get("campanha_id"),
            "pendentes": out.get("pendentes"),
            "sustentabilidade": out.get("sustentabilidade"),
            "roas_real": out.get("roas_real"),
            "inbox": out.get("inbox"),
            "envios": out.get("envios"),
            "chat_ml": out.get("chat_ml"),
        }
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
