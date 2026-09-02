"""core/claude_ml/enriquecedor.py — Facade que monta o contexto Claude."""
from __future__ import annotations

import logging
from typing import Any

from core.claude_ml.dosagem import dosar_analise_para_decisao
from core.claude_ml.numeros import cfg_bool
from core.claude_ml.stress import stress_produto

logger = logging.getLogger("claude_ml_enriquecedor")


def enriquecer_contexto_claude(
    contexto: dict[str, Any] | str | None,
    *,
    consolidado: dict[str, Any] | None = None,
    produto: dict[str, Any] | None = None,
    proposito: str = "analise_ml",
    ao_vivo: bool = False,
    forcar_profundidade: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Devolve (contexto_enriquecido, dosagem)."""
    if isinstance(contexto, str):
        base: dict[str, Any] = {"contexto_texto": contexto}
    elif isinstance(contexto, dict):
        base = dict(contexto)
    else:
        base = {}

    if not cfg_bool("CLAUDE_ML_CONTEXTO_ATIVO", True):
        dosagem = dosar_analise_para_decisao(
            proposito=proposito, forcar_profundidade=forcar_profundidade
        )
        return base, dosagem

    try:
        # Via Facade para @patch("core.claude_contexto_ml.carregar_estado_ml")
        from core import claude_contexto_ml as ccm

        estado = ccm.carregar_estado_ml(ao_vivo=ao_vivo)
    except Exception as exc:
        logger.warning("carregar_estado_ml falhou: %s", exc)
        estado = {"marketplace": "mercadolivre", "nivel": "desconhecido", "alertas": []}

    st = stress_produto(consolidado, produto=produto)
    dosagem = dosar_analise_para_decisao(
        estado_ml=estado,
        stress=st,
        proposito=proposito,
        forcar_profundidade=forcar_profundidade,
    )

    empresa_bloco: dict[str, Any] = {}
    dois_cnpjs: dict[str, Any] = {}
    try:
        from core.empresa_contexto import empresa_para_proposito, mapa_dois_cnpjs

        emp = empresa_para_proposito(proposito)
        dois_cnpjs = mapa_dois_cnpjs()
        if emp:
            empresa_bloco = {
                "id": emp.get("id"),
                "nome_fantasia": emp.get("nome_fantasia"),
                "cnpj": emp.get("cnpj"),
                "cnpj_formatado": emp.get("cnpj_formatado"),
                "cnae_principal": emp.get("cnae_principal"),
                "ramos": emp.get("ramos") or [],
                "prioriza_mercadolivre": emp.get("prioriza_mercadolivre", True),
            }
    except Exception as exc:
        logger.debug("empresa no contexto Claude: %s", exc)

    base["estado_ml"] = estado
    base["situacao_produto"] = st
    anuncios = estado.get("anuncios") if isinstance(estado.get("anuncios"), dict) else {}
    base["anuncios_ml"] = anuncios.get("itens") or []
    base["anuncios_ml_resumo"] = {
        "total": anuncios.get("total"),
        "publicados": anuncios.get("publicados"),
        "pendente_mlb": anuncios.get("pendente_mlb"),
        "fonte": anuncios.get("fonte"),
    }
    base["empresa_cnpj"] = empresa_bloco
    base["dois_cnpjs_operacao"] = dois_cnpjs
    base["dosagem_analise"] = {
        "profundidade": dosagem["profundidade"],
        "motivo": dosagem["motivo"],
        "foco_decisao": dosagem["foco_decisao"],
    }
    cnpj_txt = empresa_bloco.get("cnpj_formatado") or empresa_bloco.get("cnpj") or "?"
    base["orientacao_decisao"] = (
        f"CNPJ={cnpj_txt} | ML={dosagem.get('nivel_ml')} | "
        f"produto_stress={dosagem.get('stress_produto')} | "
        f"profundidade={dosagem['profundidade']} | foque em: "
        + ", ".join(dosagem["foco_decisao"][:4])
    )
    pid = dosagem.get("playbook_id")
    if pid:
        try:
            from core.claude_ml.playbooks import campos_do_json, montar_instrucoes

            campos = campos_do_json(
                contexto=base,
                consolidado=consolidado if isinstance(consolidado, dict) else None,
                produto=produto if isinstance(produto, dict) else None,
                estado_ml=estado if isinstance(estado, dict) else None,
                proposito=proposito,
            )
            base["playbook_ml"] = {
                "id": pid,
                "campos": campos,
                "instrucoes": montar_instrucoes(pid, campos=campos),
            }
        except Exception as exc:
            logger.debug("playbook_ml no contexto: %s", exc)
    return base, dosagem
