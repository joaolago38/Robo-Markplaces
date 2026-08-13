"""
integracoes/social/conversao_manicures.py
Conversão de manicures → compra no Mercado Livre via WhatsApp/IG/FB.
Usa Claude (Haiku por padrão; Sonnet no ponto de venda/oferta via claude_roteador).
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_e_atualizar_json, ler_json
from core.claude_client import MODELO_RAPIDO, perguntar, perguntar_estruturado
from core.claude_roteador import resolver_modelo_vendas
from core.config import ANTHROPIC_API_KEY, ROOT
from integracoes.social.promocoes_manicures import (
    _para_whatsapp,
    carregar_campanhas,
    montar_mensagem_campanha,
)

logger = logging.getLogger("conversao_manicures")

LEADS_PATH = ROOT / "logs" / "leads_manicures.json"
MAX_LEADS = 500

_SYSTEM_CONV = (
    "Você apoia fechamento de compra no Mercado Livre (kits Impala/Anita). "
    "Tom neutro e factual, curto. "
    "NUNCA invente preço, estoque, frete, prazo, Full ou desconto. "
    "Para frete/prazo oriente a consultar o anúncio com o CEP. "
    "Pode citar o link do ML. Nunca peça dados sensíveis (senha/cartão)."
)

_SCHEMA_OFERTA = {
    "type": "object",
    "properties": {
        "campanha_id": {"type": "string"},
        "angulo": {
            "type": "string",
            "description": "Ex: atacado, tendencia, mimo, frete, estoque_salao",
        },
        "copy_whatsapp": {"type": "string"},
        "copy_facebook": {"type": "string"},
        "copy_instagram": {"type": "string"},
        "cta_ml": {"type": "string"},
        "motivo": {"type": "string"},
    },
    "required": [
        "campanha_id",
        "angulo",
        "copy_whatsapp",
        "copy_facebook",
        "copy_instagram",
        "cta_ml",
    ],
}

_SCHEMA_INTENCAO = {
    "type": "object",
    "properties": {
        "intencao": {
            "type": "string",
            "enum": ["interesse", "preco", "atacado", "duvida", "off_topic", "spam"],
        },
        "converter": {"type": "boolean"},
        "resposta": {"type": "string"},
        "motivo": {"type": "string"},
    },
    "required": ["intencao", "converter", "resposta"],
}

_KW_ML_CHAT = re.compile(
    r"manicure|kit|atacado|sal[aã]o|esmalte|impala|anita|revenda|profissional",
    re.IGNORECASE,
)


def lead_id(canal: str, externo_id: str, texto: str) -> str:
    base = f"{canal}|{externo_id}|{(texto or '')[:80]}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:20]


def carregar_leads() -> list[dict[str, Any]]:
    data = ler_json(LEADS_PATH, default={"leads": []})
    if isinstance(data, dict):
        leads = data.get("leads") or []
        return leads if isinstance(leads, list) else []
    if isinstance(data, list):
        return data
    return []


def ids_leads_conhecidos(leads: list[dict[str, Any]] | None = None) -> set[str]:
    itens = leads if leads is not None else carregar_leads()
    return {str(item.get("id") or "") for item in itens if item.get("id")}


def append_lead(lead: dict[str, Any]) -> dict[str, Any]:
    """Insere lead se id novo. Retorna o lead persistido (ou existente)."""
    lid = str(lead.get("id") or lead_id(
        str(lead.get("canal") or ""),
        str(lead.get("externo_id") or ""),
        str(lead.get("texto") or ""),
    ))
    lead = {**lead, "id": lid}
    if not lead.get("criado_em"):
        lead["criado_em"] = datetime.now(timezone.utc).isoformat()

    def _upd(estado: Any) -> Any:
        if not isinstance(estado, dict):
            estado = {"leads": []}
        lista = list(estado.get("leads") or [])
        for existente in lista:
            if str(existente.get("id") or "") == lid:
                return estado  # já existe
        lista.insert(0, lead)
        estado["leads"] = lista[:MAX_LEADS]
        estado["atualizado_em"] = datetime.now(timezone.utc).isoformat()
        return estado

    try:
        ler_e_atualizar_json(LEADS_PATH, _upd, default={"leads": []})
    except Exception:
        # fallback sem lock (Windows)
        atuais = carregar_leads()
        if lid not in ids_leads_conhecidos(atuais):
            atuais.insert(0, lead)
            escrever_json_atomico(
                LEADS_PATH,
                {
                    "leads": atuais[:MAX_LEADS],
                    "atualizado_em": datetime.now(timezone.utc).isoformat(),
                },
            )
    return lead


def atualizar_lead(lid: str, patch: dict[str, Any]) -> bool:
    def _upd(estado: Any) -> Any:
        if not isinstance(estado, dict):
            estado = {"leads": []}
        lista = list(estado.get("leads") or [])
        for i, item in enumerate(lista):
            if str(item.get("id") or "") == lid:
                lista[i] = {**item, **patch, "atualizado_em": datetime.now(timezone.utc).isoformat()}
                break
        estado["leads"] = lista
        return estado

    try:
        ler_e_atualizar_json(LEADS_PATH, _upd, default={"leads": []})
        return True
    except Exception as exc:
        logger.warning("atualizar_lead falhou: %s", exc)
        return False


def _resumo_campanhas() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in carregar_campanhas():
        montado = montar_mensagem_campanha(c)
        if not montado.get("ok"):
            continue
        out.append(
            {
                "id": c.get("id"),
                "nome": c.get("nome"),
                "sku": montado.get("sku"),
                "preco_brl": montado.get("preco_brl"),
                "link_ml": montado.get("link_ml"),
                "template_preview": str(montado.get("texto") or "")[:180],
            }
        )
    return out


def escolher_oferta_haiku(
    *,
    sinal_ads: dict[str, Any] | None = None,
    ultimo_campanha_id: str | None = None,
) -> dict[str, Any]:
    """
    Escolhe campanha + copies por canal via Haiku.
    Sempre retorna dict com ok/fallback mecânico se IA falhar.
    """
    campanhas = _resumo_campanhas()
    if not campanhas:
        return {"ok": False, "motivo": "sem_campanhas_montaveis"}

    fallback_id = campanhas[0]["id"]
    if ultimo_campanha_id:
        ids = [str(c["id"]) for c in campanhas]
        if ultimo_campanha_id in ids and len(ids) > 1:
            fallback_id = ids[(ids.index(ultimo_campanha_id) + 1) % len(ids)]

    def _montar_por_id(cid: str, copies: dict[str, Any] | None = None) -> dict[str, Any]:
        for c in carregar_campanhas():
            if str(c.get("id") or "") == str(cid):
                m = montar_mensagem_campanha(c)
                if not m.get("ok"):
                    return {"ok": False, "motivo": m.get("motivo")}
                base_txt = str(m.get("texto") or "")
                link = str(m.get("link_ml") or "")
                cta = (copies or {}).get("cta_ml") or f"Compre no Mercado Livre: {link}"
                wa = (copies or {}).get("copy_whatsapp") or _para_whatsapp(base_txt)
                fb = (copies or {}).get("copy_facebook") or base_txt
                ig = (copies or {}).get("copy_instagram") or _para_whatsapp(base_txt)
                # garante link no texto
                for nome, txt in (("wa", wa), ("fb", fb), ("ig", ig)):
                    if link and link not in txt:
                        if nome == "wa":
                            wa = f"{txt}\n\n{cta}".strip()
                        elif nome == "fb":
                            fb = f"{txt}\n\n{cta}".strip()
                        else:
                            ig = f"{txt}\n\n{cta}".strip()
                return {
                    "ok": True,
                    "fonte": "haiku" if copies else "fallback",
                    "campanha_id": cid,
                    "campanha_nome": m.get("campanha_nome"),
                    "sku": m.get("sku"),
                    "preco_brl": m.get("preco_brl"),
                    "link_ml": link,
                    "link_valido": bool(m.get("link_valido", True)),
                    "aviso_link": m.get("aviso_link") or "",
                    "item_id": m.get("item_id"),
                    "angulo": (copies or {}).get("angulo") or "rotacao",
                    "motivo": (copies or {}).get("motivo") or "sem_ia_ou_fallback",
                    "copy_whatsapp": wa.strip(),
                    "copy_facebook": fb.strip(),
                    "copy_instagram": ig.strip(),
                    "cta_ml": cta,
                    "texto_template": base_txt,
                }
        return {"ok": False, "motivo": f"campanha_nao_encontrada:{cid}"}

    if not ANTHROPIC_API_KEY:
        return _montar_por_id(str(fallback_id))

    ctx_ads = ""
    if sinal_ads:
        ctx_ads = f"Sinal Meta Ads (resumo): {sinal_ads}"

    prompt = (
        "Escolha a melhor campanha do catálogo para converter manicures AGORA "
        f"e gere textos curtos por canal.\n"
        f"Última campanha enviada: {ultimo_campanha_id or 'nenhuma'}\n"
        f"Campanhas disponíveis (JSON): {campanhas}\n"
        f"{ctx_ads}\n"
        "Regras: copy_whatsapp sem markdown pesado; facebook/instagram com emoji leve; "
        "inclua o link_ml da campanha escolhida no cta_ml; máximo ~500 caracteres por copy."
    )
    rota = resolver_modelo_vendas(
        proposito="oferta_conversao",
        canal="mercadolivre",
        sinal_ads=sinal_ads if isinstance(sinal_ads, dict) else None,
    )
    raw = perguntar_estruturado(
        prompt,
        _SCHEMA_OFERTA,
        "oferta_conversao_manicures",
        max_tokens=700,
        system=_SYSTEM_CONV,
        modelo=rota["modelo"],
        forcar_modelo=bool(rota.get("forcar_modelo")),
    )
    if not raw or not raw.get("campanha_id"):
        return _montar_por_id(str(fallback_id))

    cid = str(raw.get("campanha_id"))
    ids_ok = {str(c["id"]) for c in campanhas}
    if cid not in ids_ok:
        cid = str(fallback_id)
    out = _montar_por_id(cid, raw)
    if isinstance(out, dict):
        out["modelo_ia"] = rota["modelo"]
        out["escalou_ia"] = bool(rota.get("escalou"))
        out["motivo_escalonamento"] = rota.get("motivo")
    return out


def classificar_e_responder_lead(
    texto: str,
    *,
    canal: str,
    link_ml: str,
    oferta_nome: str = "",
    sinal_ads: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classifica intenção (Haiku). Sonnet só se calor alto — Meta captura, ML é o alvo."""
    texto = (texto or "").strip()
    if len(texto) < 2:
        return {
            "intencao": "off_topic",
            "converter": False,
            "resposta": "",
            "motivo": "texto_curto",
        }

    fallback = {
        "intencao": "interesse",
        "converter": True,
        "resposta": (
            f"Oi! Temos {oferta_nome or 'kits Impala para manicure'} no Mercado Livre "
            f"com frete Full. Confira e compre aqui: {link_ml}"
        ).strip(),
        "motivo": "fallback",
    }
    if not ANTHROPIC_API_KEY:
        return fallback

    prompt = (
        f"Canal de captação: {canal} (Instagram/Facebook/WhatsApp — NÃO é a venda ainda).\n"
        f"Objetivo: levar a manicure a COMPRAR no Mercado Livre.\n"
        f"Oferta ativa: {oferta_nome}\n"
        f"Link ML (fechamento): {link_ml}\n"
        f"Mensagem: {texto}\n\n"
        "Classifique a intenção e, se valer converter, escreva resposta curta "
        "(max 400 chars) com o link do ML. Se spam/off_topic, converter=false e resposta vazia."
    )
    raw = perguntar_estruturado(
        prompt,
        _SCHEMA_INTENCAO,
        "intencao_conversao_manicures",
        max_tokens=400,
        system=_SYSTEM_CONV,
        modelo=MODELO_RAPIDO,
    )
    if not raw:
        return fallback

    intencao = str(raw.get("intencao") or "interesse")
    converter = bool(raw.get("converter"))
    resp = str(raw.get("resposta") or "").strip()
    rota = resolver_modelo_vendas(
        proposito="resposta_lead",
        canal=canal,
        texto=texto,
        intencao=intencao,
        converter=converter,
        sinal_ads=sinal_ads,
    )
    if rota.get("escalou") and converter:
        rewrite = perguntar(
            (
                f"Canal de CAPTAÇÃO: {canal}. A venda fecha no MERCADO LIVRE.\n"
                f"Oferta: {oferta_nome}. Link ML: {link_ml}.\n"
                f"Intenção: {intencao}. Mensagem: {texto}\n\n"
                "Resposta curta (máx 400 chars) empurrando a compra no anúncio ML. "
                "Tom salão. Inclua o link."
            ),
            max_tokens=280,
            system=_SYSTEM_CONV,
            modelo=rota["modelo"],
            forcar_modelo=True,
        )
        if rewrite and not rewrite.startswith("⚠️"):
            resp = rewrite.strip()

    if converter and link_ml and link_ml not in resp:
        resp = f"{resp}\n{link_ml}".strip()
    return {
        "intencao": intencao,
        "converter": converter,
        "resposta": resp,
        "motivo": str(raw.get("motivo") or "haiku"),
        "modelo_ia": rota["modelo"] if rota.get("escalou") and converter else MODELO_RAPIDO,
        "escalou_ia": bool(rota.get("escalou") and converter),
        "analise": rota.get("analise"),
    }


def resposta_chat_ml_haiku(
    pergunta: str,
    link_ml: str,
    produto_ctx: str = "",
    *,
    produto: dict[str, Any] | None = None,
    sinal_ads: dict[str, Any] | None = None,
) -> str:
    """Fechamento no ML com travas: sem inventar frete/preço/desconto; sanitiza saída."""
    from core.chat_seguro_ml import sanitizar_resposta_chat_ml

    if not pergunta_parece_manicure(pergunta):
        return ""
    if ANTHROPIC_API_KEY:
        rota = resolver_modelo_vendas(
            proposito="resposta_chat_ml",
            canal="mercadolivre",
            texto=pergunta,
            sinal_ads=sinal_ads,
        )
        analise = rota.get("analise") or {}
        out = perguntar(
            (
                f"Cliente perguntou no Mercado Livre (FECHAMENTO DA VENDA): {pergunta}\n"
                f"Contexto produto: {produto_ctx or 'kit esmaltes Impala para manicures'}\n"
                f"Termômetro: {analise.get('resumo') or 'n/d'}\n"
                f"Captação Meta (se houver): {analise.get('captacao_meta') or {}}\n"
                f"CTA compra. Link: {link_ml}\n"
                "Resposta máx 300 chars, factual e neutra. "
                "Sem inventar frete, prazo, desconto ou preço."
            ),
            max_tokens=220,
            system=_SYSTEM_CONV,
            modelo=rota["modelo"],
            forcar_modelo=bool(rota.get("forcar_modelo")),
            origem="social.conversao_manicures.chat_ml",
        )
        if out and not out.startswith("⚠️"):
            if link_ml and link_ml not in out:
                out = f"{out} {link_ml}".strip()
            return sanitizar_resposta_chat_ml(out[:500], produto)
    return sanitizar_resposta_chat_ml(
        f"Sim, o kit é indicado para manicures profissionais. "
        f"Confira preço, frete e prazo no anúncio: {link_ml}",
        produto,
    )


def pergunta_parece_manicure(texto: str) -> bool:
    return bool(_KW_ML_CHAT.search(texto or ""))


def diagnosticar_canais(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Checklist de prontidão por canal.
    cfg keys esperadas: wa, tg_manicures, fb, ig, ig_imagem, claude, ml, reply_meta, reply_wa, publicar_fb, publicar_ig
    """
    canais = {
        "whatsapp": {
            "pronto": bool(cfg.get("wa")),
            "status": "ok" if cfg.get("wa") else "config_pendente",
            "nota": "WHATSAPP_* + GRUPO_MANICURES_ID" if not cfg.get("wa") else "grupo ok",
        },
        "telegram_manicures": {
            "pronto": bool(cfg.get("tg_manicures")),
            "status": "ok" if cfg.get("tg_manicures") else "config_pendente",
            "nota": "TELEGRAM_MANICURES_CHAT_ID" if not cfg.get("tg_manicures") else "ok",
        },
        "facebook": {
            "pronto": bool(cfg.get("fb")),
            "status": "ok" if cfg.get("fb") else "config_pendente",
            "nota": (
                "META_ACCESS_TOKEN + META_PAGE_ID (+ pages_manage_posts)"
                if not cfg.get("fb")
                else ("ligado" if cfg.get("publicar_fb") else "token ok — PUBLICAR_FB=0")
            ),
        },
        "instagram": {
            "pronto": bool(cfg.get("ig") and cfg.get("ig_imagem")),
            "status": "ok" if (cfg.get("ig") and cfg.get("ig_imagem")) else "config_pendente",
            "nota": (
                "META_INSTAGRAM_ID + CONVERSAO_MANICURES_IMAGEM_IG_URL "
                "(+ instagram_basic / instagram_content_publish)"
                if not (cfg.get("ig") and cfg.get("ig_imagem"))
                else ("ligado" if cfg.get("publicar_ig") else "ids ok — PUBLICAR_IG=0")
            ),
        },
        "claude_haiku": {
            "pronto": bool(cfg.get("claude")),
            "status": "ok" if cfg.get("claude") else "config_pendente",
            "nota": "ANTHROPIC_API_KEY" if not cfg.get("claude") else "claude-haiku-4-5",
        },
        "chat_ml": {
            "pronto": bool(cfg.get("ml")),
            "status": "ok" if cfg.get("ml") else "config_pendente",
            "nota": "token ML" if not cfg.get("ml") else "ok",
        },
        "reply_meta": {
            "pronto": bool(cfg.get("reply_meta") and cfg.get("fb")),
            "status": "ok" if cfg.get("reply_meta") else "desligado",
            "nota": "CONVERSAO_MANICURES_REPLY_META=1 quando permissões fecharem",
        },
        "reply_wa": {
            "pronto": bool(cfg.get("reply_wa") and cfg.get("wa")),
            "status": "ok" if cfg.get("reply_wa") else "desligado",
            "nota": "CONVERSAO_MANICURES_REPLY_WA=1",
        },
    }
    pendentes = [k for k, v in canais.items() if v.get("status") == "config_pendente"]
    return {"canais": canais, "pendentes": pendentes, "checklist_meta": [
        "Token long-lived Meta (META_ACCESS_TOKEN)",
        "META_PAGE_ID + pages_manage_posts / pages_read_engagement",
        "META_INSTAGRAM_ID + instagram_basic / instagram_content_publish",
        "pages_manage_engagement / instagram_manage_comments (para REPLY_META)",
        "CONVERSAO_MANICURES_IMAGEM_IG_URL (URL pública HTTPS da arte)",
    ]}


def montar_mensagem_gestor(payload: dict[str, Any]) -> str:
    from core.telegram_explicacao import cabecalho_agente

    diag = payload.get("diagnostico") or {}
    oferta = payload.get("oferta") or {}
    envios = payload.get("envios") or {}
    inbox = payload.get("inbox") or {}
    chat_ml = payload.get("chat_ml") or {}
    sust = payload.get("sustentabilidade") or (payload.get("ads") or {}).get("sustentabilidade") or {}

    linhas = [
        cabecalho_agente(
            "conversao_manicures",
            "💅 *Conversão manicures — WA / IG / FB / ML*",
        ),
        "",
        f"_Oferta: *{oferta.get('campanha_nome') or oferta.get('campanha_id') or 'n/d'}* "
        f"({oferta.get('fonte') or '-'}: {oferta.get('angulo') or '-'})_",
        f"_Link: {oferta.get('link_ml') or 'n/d'}_",
    ]
    if oferta.get("link_valido") is False:
        aviso = str(oferta.get("aviso_link") or "").strip()
        msg = (
            "⚠️ *Link ML inválido* (MLB_PREENCHER / genérico) — "
            "boost WA/TG/FB/IG bloqueado até você preencher o item_id real."
        )
        if aviso:
            msg = f"{msg} {aviso}"
        linhas.append(msg)
    linhas.extend(["", "*Sustentabilidade Ads × ML*"])
    if sust:
        emoji = {
            "sustentavel": "🟢",
            "alerta": "🟡",
            "critico": "🔴",
            "insuficiente_dados": "⚪",
        }.get(str(sust.get("status") or ""), "⚪")
        linhas.append(
            f"{emoji} *{sust.get('status') or 'n/d'}* — "
            f"gasto Ads R$ {float(sust.get('gasto_meta') or 0):.2f} | "
            f"vendas ML R$ {float(sust.get('receita_ml') or 0):.2f} "
            f"({int(sust.get('pedidos_ml') or 0)} ped.) | "
            f"ROAS real {float(sust.get('roas_real') or 0):.2f} "
            f"(pixel {float(sust.get('roas_pixel') or 0):.2f})"
        )
        if sust.get("recomendacao"):
            linhas.append(f"_Ação: {sust.get('recomendacao')}_")
    else:
        linhas.append("_Monitor Ads×ML desligado ou sem dados nesta rodada._")
    if envios.get("motivo") and str(envios.get("motivo")).startswith("bloqueado"):
        linhas.append(f"_Boost ativo bloqueado: {envios.get('motivo')}_")
    elif payload.get("boost_bloqueado") and payload.get("motivo_boost"):
        linhas.append(f"_Boost ativo bloqueado: {payload.get('motivo_boost')}_")

    linhas.extend(
        [
            "",
            "*Envios ativos*",
            f"• WhatsApp: {'✅' if envios.get('whatsapp') else '—'}",
            f"• Telegram manicures: {'✅' if envios.get('telegram') else '—'}",
            f"• Facebook: {'✅' if envios.get('facebook') else '—'} "
            f"| Instagram: {'✅' if envios.get('instagram') else '—'}",
            "",
            f"*Inbox:* {int(inbox.get('novos') or 0)} novos · "
            f"{int(inbox.get('respondidos') or 0)} respondidos · "
            f"{int(inbox.get('enfileirados') or 0)} na fila",
            f"*Chat ML manicure:* {int(chat_ml.get('respondidas') or 0)} respostas",
        ]
    )
    pend = diag.get("pendentes") or []
    if pend:
        linhas.extend(["", f"*Config pendente:* {', '.join(pend)}"])
        for item in (diag.get("checklist_meta") or [])[:4]:
            linhas.append(f"  · {item}")
    return "\n".join(linhas).strip()
