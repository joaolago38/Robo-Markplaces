"""
integracoes/licitacao/busca.py
Busca licitações por item do catálogo (PNCP + portais estaduais).
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
import unicodedata
from datetime import datetime
from typing import Any

from core.config import (
    LICITACOES_BUSCAR_PORTAIS_ESTADUAIS,
    LICITACOES_DIAS_PROPOSTA_FRENTE,
    LICITACOES_MAX_PAGINAS_PNCP,
    LICITACOES_PAUSA_ENTRE_FONTES_SEG,
    LICITACOES_TAMANHO_PAGINA_PNCP,
)
from core.ddg_lite import buscar as ddg_buscar
from integracoes.licitacao.fontes import MODALIDADES_PADRAO_BUSCA, PORTAIS_POR_ESTADO, TODAS_UFS
from integracoes.licitacao.pncp_client import buscar_detalhe_compra, buscar_propostas_abertas
from integracoes.licitacao.requisitos import montar_requisitos_participacao

logger = logging.getLogger("licitacao_busca")

_RE_VALOR = re.compile(
    r"(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2}|\d+(?:,\d{2})?)",
    re.IGNORECASE,
)


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def _hash_item(chave: str) -> str:
    return hashlib.sha256(chave.encode("utf-8")).hexdigest()[:16]


def _parse_valor_br(texto: str | float | int | None) -> float | None:
    if texto is None:
        return None
    if isinstance(texto, (int, float)):
        v = float(texto)
        return v if v > 0 else None
    m = _RE_VALOR.search(str(texto))
    if not m:
        return None
    bruto = m.group(1).replace(".", "").replace(",", ".")
    try:
        v = float(bruto)
        return v if v > 0 else None
    except ValueError:
        return None


def _formatar_valor_br(valor: float | None) -> str | None:
    if valor is None or valor <= 0:
        return None
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _formatar_data_iso(valor: Any) -> str | None:
    if not valor:
        return None
    texto = str(valor).strip()
    try:
        if "T" in texto:
            dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
            return dt.strftime("%d/%m/%Y %H:%M")
        if len(texto) == 8 and texto.isdigit():
            return datetime.strptime(texto, "%Y%m%d").strftime("%d/%m/%Y")
    except ValueError:
        pass
    return texto[:19]


def _termos_item(item_cat: dict[str, Any]) -> list[str]:
    brutos = item_cat.get("termos_busca") or []
    return [_normalizar(str(t)) for t in brutos if str(t).strip()]


def _excluir_item(item_cat: dict[str, Any]) -> list[str]:
    brutos = item_cat.get("excluir_termos") or []
    return [_normalizar(str(t)) for t in brutos if str(t).strip()]


def _ufs_item(item_cat: dict[str, Any]) -> list[str]:
    brutos = item_cat.get("ufs") or []
    ufs = [str(u).strip().upper()[:2] for u in brutos if str(u).strip()]
    return ufs or list(TODAS_UFS)


def _modalidades_item(item_cat: dict[str, Any]) -> list[int]:
    brutos = item_cat.get("modalidades") or MODALIDADES_PADRAO_BUSCA
    resultado: list[int] = []
    for m in brutos:
        try:
            resultado.append(int(m))
        except (TypeError, ValueError):
            continue
    return resultado or list(MODALIDADES_PADRAO_BUSCA)


def _bate_filtro_texto(item_cat: dict[str, Any], texto: str) -> bool:
    norm = _normalizar(texto)
    for ex in _excluir_item(item_cat):
        if ex and ex in norm:
            return False
    termos = _termos_item(item_cat)
    if not termos:
        return True
    return any(t in norm for t in termos)


def _valor_no_intervalo(item_cat: dict[str, Any], valor: float | None) -> bool:
    if valor is None:
        return True
    try:
        vmin = float(item_cat.get("valor_min") or 0)
    except (TypeError, ValueError):
        vmin = 0
    vmax_raw = item_cat.get("valor_max")
    try:
        vmax = float(vmax_raw) if vmax_raw not in (None, "") else None
    except (TypeError, ValueError):
        vmax = None
    if vmin > 0 and valor < vmin:
        return False
    if vmax is not None and vmax > 0 and valor > vmax:
        return False
    return True


def _normalizar_pncp(raw: dict[str, Any], *, detalhe: dict[str, Any] | None = None) -> dict[str, Any] | None:
    det = detalhe or {}
    orgao = raw.get("orgaoEntidade") or {}
    unidade = raw.get("unidadeOrgao") or {}
    numero = str(raw.get("numeroControlePNCP") or det.get("numeroControlePNCP") or "").strip()
    if not numero:
        cnpj = str(orgao.get("cnpj") or "")
        ano = raw.get("anoCompra") or det.get("anoCompra")
        seq = raw.get("sequencialCompra") or det.get("sequencialCompra")
        if cnpj and ano and seq:
            numero = f"{cnpj}-1-{int(seq):06d}/{ano}"

    objeto = str(det.get("objetoCompra") or raw.get("objetoCompra") or "").strip()
    if not objeto and not numero:
        return None

    valor_num = _parse_valor_br(det.get("valorTotalEstimado"))
    if valor_num is None:
        valor_num = _parse_valor_br(raw.get("valorTotalEstimado"))

    link = str(det.get("linkSistemaOrigem") or raw.get("linkSistemaOrigem") or "").strip()
    if not link and numero:
        link = f"https://pncp.gov.br/app/editais/{numero}"

    item = {
        "hash": _hash_item(numero or objeto[:120]),
        "numero_controle_pncp": numero or None,
        "titulo": objeto[:200] if objeto else numero,
        "produto": objeto,
        "orgao": str(orgao.get("razaoSocial") or "").strip(),
        "cnpj_orgao": str(orgao.get("cnpj") or "").strip(),
        "unidade": str(unidade.get("nomeUnidade") or "").strip(),
        "cidade": str(unidade.get("municipioNome") or "").strip(),
        "uf": str(unidade.get("ufSigla") or "").strip(),
        "modalidade": str(det.get("modalidadeNome") or raw.get("modalidadeNome") or "").strip(),
        "modalidade_id": det.get("modalidadeId") or raw.get("modalidadeId"),
        "valor_estimado": _formatar_valor_br(valor_num),
        "valor_estimado_num": valor_num,
        "data_abertura": _formatar_data_iso(det.get("dataAberturaProposta") or raw.get("dataAberturaProposta")),
        "data_encerramento": _formatar_data_iso(
            det.get("dataEncerramentoProposta") or raw.get("dataEncerramentoProposta")
        ),
        "processo": str(det.get("processo") or raw.get("processo") or "").strip(),
        "url": link,
        "link_sistema": link,
        "sistema_origem": str(det.get("usuarioNome") or raw.get("usuarioNome") or "PNCP").strip(),
        "fonte_tipo": "pncp",
        "fonte_id": "pncp",
        "fonte_nome": "PNCP",
        "srp": bool(det.get("srp") if det else raw.get("srp")),
        "orcamento_sigiloso": (det.get("orcamentoSigilosoCodigo") or 0) not in (0, None, 1)
        if det
        else False,
    }
    item["participacao"] = montar_requisitos_participacao(item)
    return item


def _buscar_pncp_item(item_cat: dict[str, Any]) -> list[dict[str, Any]]:
    achados: list[dict[str, Any]] = []
    vistos_hash: set[str] = set()
    ufs_filtro: set[str] | None = None
    if item_cat.get("ufs"):
        ufs_filtro = set(_ufs_item(item_cat))

    for modalidade in _modalidades_item(item_cat):
        for pagina in range(1, LICITACOES_MAX_PAGINAS_PNCP + 1):
            body = buscar_propostas_abertas(
                codigo_modalidade=modalidade,
                uf=None,
                pagina=pagina,
                tamanho_pagina=LICITACOES_TAMANHO_PAGINA_PNCP,
                dias_frente=LICITACOES_DIAS_PROPOSTA_FRENTE,
            )
            registros = body.get("data") or []
            if not registros:
                break

            for raw in registros:
                if not isinstance(raw, dict):
                    continue
                unidade = raw.get("unidadeOrgao") or {}
                uf_item = str(unidade.get("ufSigla") or "").upper()
                if ufs_filtro and uf_item and uf_item not in ufs_filtro:
                    continue

                texto = " ".join(
                    str(raw.get(k) or "")
                    for k in ("objetoCompra", "informacaoComplementar", "processo")
                )
                if not _bate_filtro_texto(item_cat, texto):
                    continue

                orgao = raw.get("orgaoEntidade") or {}
                detalhe: dict[str, Any] = {}
                cnpj = orgao.get("cnpj")
                ano = raw.get("anoCompra")
                seq = raw.get("sequencialCompra")
                if cnpj and ano and seq:
                    detalhe = buscar_detalhe_compra(str(cnpj), int(ano), int(seq))

                norm = _normalizar_pncp(raw, detalhe=detalhe)
                if not norm:
                    continue
                if not _valor_no_intervalo(item_cat, norm.get("valor_estimado_num")):
                    continue
                h = norm.get("hash") or ""
                if h in vistos_hash:
                    continue
                vistos_hash.add(h)
                achados.append(norm)

            if body.get("paginasRestantes", 0) == 0:
                break

    return achados


def _buscar_portal_estadual(
    item_cat: dict[str, Any],
    portal: dict[str, str],
    *,
    pausa_seg: float,
) -> list[dict[str, Any]]:
    dominio = str(portal.get("dominio") or "").strip()
    uf = str(portal.get("uf") or "").strip()
    if not dominio:
        return []
    ufs = _ufs_item(item_cat)
    if uf and uf not in ufs:
        return []

    termos = item_cat.get("termos_busca") or []
    termo = " ".join(str(t) for t in termos[:4] if t) or str(item_cat.get("nome") or "licitação")
    query = f'site:{dominio} {termo} pregão edital proposta'
    html = ddg_buscar(query, contexto="licitacao", max_resultados=6)
    if not html:
        return []

    from core.ddg_lite import extrair_resultados

    resultados = extrair_resultados(html)
    achados: list[dict[str, Any]] = []
    for r in resultados:
        url = str(r.get("url") or "").strip()
        titulo = str(r.get("title") or r.get("titulo") or "").strip()
        snippet = str(r.get("snippet") or "").strip()
        blob = f"{titulo} {snippet}"
        if dominio not in url:
            continue
        if not _bate_filtro_texto(item_cat, blob):
            continue
        valor_num = _parse_valor_br(blob)
        if not _valor_no_intervalo(item_cat, valor_num):
            continue
        item = {
            "hash": _hash_item(url),
            "titulo": titulo[:200],
            "produto": titulo,
            "orgao": str(portal.get("nome") or dominio),
            "uf": uf,
            "modalidade": "Portal estadual",
            "valor_estimado": _formatar_valor_br(valor_num),
            "valor_estimado_num": valor_num,
            "url": url,
            "link_sistema": url,
            "fonte_tipo": "estadual",
            "fonte_id": dominio,
            "fonte_nome": portal.get("nome") or dominio,
            "snippet": snippet[:300],
        }
        item["participacao"] = montar_requisitos_participacao(item)
        achados.append(item)

    if pausa_seg > 0:
        time.sleep(pausa_seg)
    return achados


def buscar_licitacoes_em_fontes(
    item_cat: dict[str, Any],
    *,
    pausa_entre_fontes_seg: float | None = None,
) -> list[dict[str, Any]]:
    """
    PNCP (todos os estados) + opcionalmente portais estaduais via DDG.
    """
    pausa = LICITACOES_PAUSA_ENTRE_FONTES_SEG if pausa_entre_fontes_seg is None else pausa_entre_fontes_seg
    achados = _buscar_pncp_item(item_cat)

    if LICITACOES_BUSCAR_PORTAIS_ESTADUAIS:
        ufs_alvo = set(_ufs_item(item_cat))
        for portal in PORTAIS_POR_ESTADO:
            if portal.get("uf") not in ufs_alvo:
                continue
            try:
                achados.extend(_buscar_portal_estadual(item_cat, portal, pausa_seg=pausa))
            except Exception as exc:
                logger.warning("Portal %s: %s", portal.get("dominio"), exc)

    # dedup final por hash
    unicos: dict[str, dict[str, Any]] = {}
    for a in achados:
        h = str(a.get("hash") or "")
        if h:
            unicos[h] = a
    return list(unicos.values())
