"""
integracoes/meta/meta_inbox.py
Lista e responde comentários Facebook Page / Instagram (Graph API).
Falhas de permissão → status config_pendente (nunca derruba o agente).
"""
from __future__ import annotations

import logging
from typing import Any

from core.config import META_ACCESS_TOKEN, META_API_VERSION, META_INSTAGRAM_ID, META_PAGE_ID
from core.http_client import request

logger = logging.getLogger("meta_inbox")

BASE = f"https://graph.facebook.com/{META_API_VERSION}"


def _erro_graph(exc: Exception) -> dict[str, Any]:
    status = None
    body = ""
    resp = getattr(exc, "response", None)
    if resp is not None:
        status = getattr(resp, "status_code", None)
        try:
            body = (resp.text or "")[:300]
        except Exception:
            body = ""
    codigo = None
    texto = f"{exc} {body}".lower()
    if "190" in texto or "session has expired" in texto or "invalid oauth" in texto:
        codigo = 190
    elif "(#10)" in texto or "permission" in texto or " (#200)" in texto:
        codigo = 10
    return {
        "status": "config_pendente" if (status in (400, 403) or codigo in (10, 190, 200)) else "erro",
        "http": status,
        "codigo_meta": codigo,
        "detalhe": str(exc)[:200],
    }


def listar_comentarios_facebook(*, limite_posts: int = 5, limite_comentarios: int = 20) -> dict[str, Any]:
    """
    Busca posts recentes da Page e seus comentários.
    Retorna {ok, status, comentarios:[{id, texto, autor, post_id, canal}]}
    """
    if not META_ACCESS_TOKEN or not META_PAGE_ID:
        return {
            "ok": False,
            "status": "config_pendente",
            "comentarios": [],
            "motivo": "META_ACCESS_TOKEN/META_PAGE_ID ausentes",
        }
    comentarios: list[dict[str, Any]] = []
    try:
        r = request(
            "GET",
            f"{BASE}/{META_PAGE_ID}/feed",
            params={
                "access_token": META_ACCESS_TOKEN,
                "fields": "id,message,created_time",
                "limit": max(1, min(limite_posts, 10)),
            },
            timeout=20,
        )
        r.raise_for_status()
        posts = (r.json() or {}).get("data") or []
        for post in posts:
            pid = str(post.get("id") or "")
            if not pid:
                continue
            try:
                rc = request(
                    "GET",
                    f"{BASE}/{pid}/comments",
                    params={
                        "access_token": META_ACCESS_TOKEN,
                        "fields": "id,message,from,created_time",
                        "limit": max(1, min(limite_comentarios, 50)),
                        "filter": "stream",
                    },
                    timeout=20,
                )
                rc.raise_for_status()
                for c in (rc.json() or {}).get("data") or []:
                    texto = str(c.get("message") or "").strip()
                    if not texto:
                        continue
                    frm = c.get("from") or {}
                    comentarios.append(
                        {
                            "id": str(c.get("id") or ""),
                            "externo_id": str(c.get("id") or ""),
                            "post_id": pid,
                            "canal": "facebook",
                            "texto": texto,
                            "autor": str(frm.get("name") or frm.get("id") or ""),
                            "criado_em": c.get("created_time"),
                        }
                    )
            except Exception as exc:
                logger.warning("comentarios post %s: %s", pid, exc)
                continue
        return {"ok": True, "status": "ok", "comentarios": comentarios}
    except Exception as exc:
        info = _erro_graph(exc)
        logger.warning("listar_comentarios_facebook: %s", info)
        return {"ok": False, "comentarios": [], **info}


def listar_midias_instagram(*, limite: int = 5) -> list[dict[str, Any]]:
    if not META_ACCESS_TOKEN or not META_INSTAGRAM_ID:
        return []
    try:
        r = request(
            "GET",
            f"{BASE}/{META_INSTAGRAM_ID}/media",
            params={
                "access_token": META_ACCESS_TOKEN,
                "fields": "id,caption,timestamp,permalink",
                "limit": max(1, min(limite, 10)),
            },
            timeout=20,
        )
        r.raise_for_status()
        return list((r.json() or {}).get("data") or [])
    except Exception as exc:
        logger.warning("listar_midias_instagram: %s", exc)
        return []


def listar_comentarios_instagram(*, limite_midias: int = 5, limite_comentarios: int = 20) -> dict[str, Any]:
    if not META_ACCESS_TOKEN or not META_INSTAGRAM_ID:
        return {
            "ok": False,
            "status": "config_pendente",
            "comentarios": [],
            "motivo": "META_ACCESS_TOKEN/META_INSTAGRAM_ID ausentes",
        }
    comentarios: list[dict[str, Any]] = []
    try:
        midias = listar_midias_instagram(limite=limite_midias)
        if not midias:
            # pode ser sem permissão ou sem posts — não trata como hard fail
            return {
                "ok": True,
                "status": "ok",
                "comentarios": [],
                "nota": "sem midias ou sem permissao media",
            }
        for m in midias:
            mid = str(m.get("id") or "")
            if not mid:
                continue
            try:
                rc = request(
                    "GET",
                    f"{BASE}/{mid}/comments",
                    params={
                        "access_token": META_ACCESS_TOKEN,
                        "fields": "id,text,username,timestamp",
                        "limit": max(1, min(limite_comentarios, 50)),
                    },
                    timeout=20,
                )
                rc.raise_for_status()
                for c in (rc.json() or {}).get("data") or []:
                    texto = str(c.get("text") or "").strip()
                    if not texto:
                        continue
                    comentarios.append(
                        {
                            "id": str(c.get("id") or ""),
                            "externo_id": str(c.get("id") or ""),
                            "post_id": mid,
                            "canal": "instagram",
                            "texto": texto,
                            "autor": str(c.get("username") or ""),
                            "criado_em": c.get("timestamp"),
                        }
                    )
            except Exception as exc:
                logger.warning("comentarios ig media %s: %s", mid, exc)
                continue
        return {"ok": True, "status": "ok", "comentarios": comentarios}
    except Exception as exc:
        info = _erro_graph(exc)
        logger.warning("listar_comentarios_instagram: %s", info)
        return {"ok": False, "comentarios": [], **info}


def responder_comentario(comentario_id: str, mensagem: str) -> dict[str, Any]:
    """POST /{comment-id}/comments — reply em comentário FB/IG."""
    cid = (comentario_id or "").strip()
    msg = (mensagem or "").strip()
    if not cid or not msg:
        return {"ok": False, "status": "erro", "motivo": "id_ou_mensagem_vazia"}
    if not META_ACCESS_TOKEN:
        return {"ok": False, "status": "config_pendente", "motivo": "sem_token"}
    try:
        r = request(
            "POST",
            f"{BASE}/{cid}/comments",
            params={"access_token": META_ACCESS_TOKEN},
            json={"message": msg[:800]},
            timeout=20,
        )
        r.raise_for_status()
        return {"ok": True, "status": "ok", "resposta_id": (r.json() or {}).get("id")}
    except Exception as exc:
        info = _erro_graph(exc)
        logger.warning("responder_comentario %s: %s", cid, info)
        return {"ok": False, **info}


def coletar_inbox_meta() -> dict[str, Any]:
    """Agrega comentários FB + IG."""
    fb = listar_comentarios_facebook()
    ig = listar_comentarios_instagram()
    todos = list(fb.get("comentarios") or []) + list(ig.get("comentarios") or [])
    status = "ok"
    if fb.get("status") == "config_pendente" or ig.get("status") == "config_pendente":
        status = "config_pendente"
    return {
        "ok": bool(fb.get("ok") or ig.get("ok") or todos),
        "status": status,
        "facebook": fb,
        "instagram": ig,
        "comentarios": todos,
    }
