"""
agentes/social/publicador.py
Publica promoções no Instagram e Facebook.
"""
import logging
from integracoes.bling.bling_client import listar_produtos
from integracoes.meta.meta_client import publicar_facebook, publicar_instagram
from core.claude_client import gerar_post
from core.config import ESTOQUE_CRITICO
from core.notificador import alertar

logger = logging.getLogger("publicador")

def selecionar_produto() -> dict | None:
    produtos = listar_produtos()
    elegiveis = [p for p in produtos if p["estoque"] >= ESTOQUE_CRITICO]
    if not elegiveis:
        return None

    def score(produto):
        preco = float(produto.get("preco", 0) or 0)
        custo = float(produto.get("custo", 0) or 0)
        margem_pct = ((preco - custo) / preco * 100) if preco > 0 else -999
        return (margem_pct, preco)

    return max(elegiveis, key=score)

def executar() -> bool:
    produto = selecionar_produto()
    if not produto:
        alertar("Nenhum produto elegível para post hoje.")
        return False
    texto_ig = gerar_post(produto, "Instagram")
    texto_fb = gerar_post(produto, "Facebook")
    ok_ig = publicar_instagram(texto_ig)
    ok_fb = publicar_facebook(texto_fb)
    logger.info(f"Post publicado: IG={ok_ig} FB={ok_fb}")
    return ok_ig and ok_fb
