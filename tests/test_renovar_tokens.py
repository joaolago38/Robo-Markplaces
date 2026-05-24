"""
tests/test_renovar_tokens.py — RT01–RT20

Cobre o script scripts/renovar_tokens.py (renovação automática + persistência
nos GitHub Secrets via PyNaCl). Garante que falhas no Actions não silenciem
e que o token novo do Bling realmente chegue ao Secret encriptado.
"""
from __future__ import annotations

import base64
import importlib
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _carregar_script_com_env(env: dict | None = None):
    """
    Recarrega o módulo scripts.renovar_tokens já com as variáveis de ambiente
    desejadas. Necessário porque GH_TOKEN/GH_REPO são lidas na importação.
    """
    env = env or {}
    base = {
        "GH_TOKEN":           "",
        "GITHUB_REPOSITORY":  "",
        "BLING_CLIENT_ID":    "",
        "BLING_CLIENT_SECRET": "",
        "BLING_REFRESH_TOKEN": "",
        "GITHUB_ENV":         "",
    }
    base.update(env)
    with patch.dict(os.environ, base, clear=False):
        if "scripts.renovar_tokens" in sys.modules:
            mod = importlib.reload(sys.modules["scripts.renovar_tokens"])
        else:
            import scripts.renovar_tokens as mod  # noqa: WPS433
        return mod


def _mock_resp(status: int = 200, body: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.raise_for_status = MagicMock()
    if status >= 400:
        r.raise_for_status.side_effect = Exception(f"HTTP {status}")
    r.json.return_value = body or {}
    return r


def _gerar_keypair_real():
    """Gera um keypair real do libsodium para validar encrypt/decrypt."""
    from nacl import public

    sk = public.PrivateKey.generate()
    pk_b64 = base64.b64encode(bytes(sk.public_key)).decode("utf-8")
    return sk, pk_b64


# ═══════════════════════════════════════════════════════════════════════════
# RT01–RT04 — _gh_headers / _get_public_key
# ═══════════════════════════════════════════════════════════════════════════

class TestGhHeadersEPublicKey(unittest.TestCase):
    def test_RT01_gh_headers_inclui_bearer_e_api_version(self):
        mod = _carregar_script_com_env({"GH_TOKEN": "tok_abc"})
        headers = mod._gh_headers()
        self.assertEqual(headers["Authorization"], "Bearer tok_abc")
        self.assertEqual(headers["Accept"], "application/vnd.github+json")
        self.assertEqual(headers["X-GitHub-Api-Version"], "2022-11-28")

    def test_RT02_get_public_key_chama_endpoint_correto(self):
        mod = _carregar_script_com_env(
            {"GH_TOKEN": "tok", "GITHUB_REPOSITORY": "joao/repo"}
        )
        with patch.object(mod.requests, "get") as mock_get:
            mock_get.return_value = _mock_resp(
                200, {"key_id": "kid-123", "key": "BASE64KEY=="}
            )
            out = mod._get_public_key()

        url = mock_get.call_args[0][0]
        self.assertEqual(
            url,
            "https://api.github.com/repos/joao/repo/actions/secrets/public-key",
        )
        self.assertEqual(out["key_id"], "kid-123")

    def test_RT03_get_public_key_propaga_erro_http(self):
        mod = _carregar_script_com_env(
            {"GH_TOKEN": "tok", "GITHUB_REPOSITORY": "joao/repo"}
        )
        with patch.object(mod.requests, "get") as mock_get:
            mock_get.return_value = _mock_resp(404, {"message": "Not Found"})
            with self.assertRaises(Exception):
                mod._get_public_key()


# ═══════════════════════════════════════════════════════════════════════════
# RT04–RT06 — _encrypt_secret (PyNaCl real)
# ═══════════════════════════════════════════════════════════════════════════

class TestEncryptSecret(unittest.TestCase):
    def test_RT04_encrypt_secret_pode_ser_decifrado_pela_chave_privada(self):
        """Usa keypair real para garantir que a criptografia é a esperada
        pelo GitHub (sealed box do libsodium)."""
        from nacl import public

        mod = _carregar_script_com_env()
        sk, pk_b64 = _gerar_keypair_real()

        ciphertext_b64 = mod._encrypt_secret(pk_b64, "meu_token_super_secreto")
        ciphertext = base64.b64decode(ciphertext_b64)

        clear = public.SealedBox(sk).decrypt(ciphertext)
        self.assertEqual(clear.decode(), "meu_token_super_secreto")

    def test_RT05_encrypt_secret_resultado_nao_eh_plain_text(self):
        mod = _carregar_script_com_env()
        _, pk_b64 = _gerar_keypair_real()
        out = mod._encrypt_secret(pk_b64, "valor-secreto")
        self.assertNotIn("valor-secreto", out)

    def test_RT06_encrypt_secret_invalida_chave_publica_lanca(self):
        mod = _carregar_script_com_env()
        with self.assertRaises(Exception):
            mod._encrypt_secret("nao-eh-base64-valido!!!", "x")


# ═══════════════════════════════════════════════════════════════════════════
# RT07–RT11 — _salvar_secret
# ═══════════════════════════════════════════════════════════════════════════

class TestSalvarSecret(unittest.TestCase):
    def test_RT07_salvar_secret_sem_gh_token_retorna_false(self):
        mod = _carregar_script_com_env({"GH_TOKEN": "", "GITHUB_REPOSITORY": ""})
        ok = mod._salvar_secret("BLING_ACCESS_TOKEN", "v", "kid", "pk")
        self.assertFalse(ok)

    def test_RT08_salvar_secret_valor_vazio_retorna_false(self):
        mod = _carregar_script_com_env(
            {"GH_TOKEN": "tok", "GITHUB_REPOSITORY": "joao/repo"}
        )
        _, pk_b64 = _gerar_keypair_real()
        ok = mod._salvar_secret("BLING_ACCESS_TOKEN", "", "kid", pk_b64)
        self.assertFalse(ok)

    def test_RT09_salvar_secret_put_endpoint_correto_e_payload(self):
        mod = _carregar_script_com_env(
            {"GH_TOKEN": "tok", "GITHUB_REPOSITORY": "joao/repo"}
        )
        _, pk_b64 = _gerar_keypair_real()

        with patch.object(mod.requests, "put") as mock_put:
            mock_put.return_value = _mock_resp(201)
            ok = mod._salvar_secret(
                "BLING_ACCESS_TOKEN", "novo_valor", "kid-xyz", pk_b64
            )

        self.assertTrue(ok)
        url = mock_put.call_args[0][0]
        self.assertEqual(
            url,
            "https://api.github.com/repos/joao/repo/actions/secrets/BLING_ACCESS_TOKEN",
        )
        payload = mock_put.call_args.kwargs["json"]
        self.assertEqual(payload["key_id"], "kid-xyz")
        self.assertIn("encrypted_value", payload)
        self.assertTrue(len(payload["encrypted_value"]) > 0)
        self.assertNotIn("novo_valor", payload["encrypted_value"])

    def test_RT10_salvar_secret_aceita_204(self):
        mod = _carregar_script_com_env(
            {"GH_TOKEN": "tok", "GITHUB_REPOSITORY": "joao/repo"}
        )
        _, pk_b64 = _gerar_keypair_real()
        with patch.object(mod.requests, "put") as mock_put:
            mock_put.return_value = _mock_resp(204)
            self.assertTrue(
                mod._salvar_secret("X", "v", "kid", pk_b64)
            )

    def test_RT11_salvar_secret_erro_http_retorna_false(self):
        mod = _carregar_script_com_env(
            {"GH_TOKEN": "tok", "GITHUB_REPOSITORY": "joao/repo"}
        )
        _, pk_b64 = _gerar_keypair_real()
        with patch.object(mod.requests, "put") as mock_put:
            mock_put.return_value = _mock_resp(422, {"message": "Validation"})
            self.assertFalse(
                mod._salvar_secret("X", "v", "kid", pk_b64)
            )

    def test_RT12_salvar_secret_excecao_retorna_false(self):
        mod = _carregar_script_com_env(
            {"GH_TOKEN": "tok", "GITHUB_REPOSITORY": "joao/repo"}
        )
        _, pk_b64 = _gerar_keypair_real()
        with patch.object(mod.requests, "put", side_effect=Exception("rede")):
            self.assertFalse(
                mod._salvar_secret("X", "v", "kid", pk_b64)
            )


# ═══════════════════════════════════════════════════════════════════════════
# RT13–RT14 — _atualizar_github_env
# ═══════════════════════════════════════════════════════════════════════════

class TestAtualizarGithubEnv(unittest.TestCase):
    def test_RT13_escreve_variaveis_no_arquivo_github_env(self):
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w+", delete=False, suffix=".env", encoding="utf-8"
        ) as fh:
            env_path = fh.name

        try:
            mod = _carregar_script_com_env({"GITHUB_ENV": env_path})
            mod._atualizar_github_env(
                BLING_ACCESS_TOKEN="abc", BLING_REFRESH_TOKEN="def"
            )
            with open(env_path, encoding="utf-8") as f:
                conteudo = f.read()
            self.assertIn("BLING_ACCESS_TOKEN=abc", conteudo)
            self.assertIn("BLING_REFRESH_TOKEN=def", conteudo)
        finally:
            os.unlink(env_path)

    def test_RT14_atualizar_github_env_sem_var_nao_levanta(self):
        mod = _carregar_script_com_env({"GITHUB_ENV": ""})
        mod._atualizar_github_env(X="y")  # não deve lançar nem escrever

    def test_RT15_atualizar_github_env_ignora_valores_vazios(self):
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w+", delete=False, suffix=".env", encoding="utf-8"
        ) as fh:
            env_path = fh.name
        try:
            mod = _carregar_script_com_env({"GITHUB_ENV": env_path})
            mod._atualizar_github_env(A="ok", B="")
            with open(env_path, encoding="utf-8") as f:
                conteudo = f.read()
            self.assertIn("A=ok", conteudo)
            self.assertNotIn("B=", conteudo)
        finally:
            os.unlink(env_path)


# ═══════════════════════════════════════════════════════════════════════════
# RT16–RT19 — _renovar_bling
# ═══════════════════════════════════════════════════════════════════════════

class TestRenovarBling(unittest.TestCase):
    def test_RT16_credenciais_ausentes_retorna_ok_false(self):
        mod = _carregar_script_com_env(
            {"BLING_CLIENT_ID": "", "BLING_CLIENT_SECRET": "", "BLING_REFRESH_TOKEN": ""}
        )
        res = mod._renovar_bling()
        self.assertFalse(res["ok"])
        self.assertIn("ausentes", res["motivo"])

    def test_RT17_refresh_ok_retorna_tokens_e_basic_auth(self):
        mod = _carregar_script_com_env(
            {
                "BLING_CLIENT_ID":     "cli_id",
                "BLING_CLIENT_SECRET": "cli_sec",
                "BLING_REFRESH_TOKEN": "ref_xyz",
            }
        )
        with patch.object(mod.requests, "post") as mock_post:
            mock_post.return_value = _mock_resp(
                200,
                {
                    "access_token":  "ACC_NOVO",
                    "refresh_token": "REF_NOVO",
                    "expires_in":    21600,
                },
            )
            res = mod._renovar_bling()

        self.assertTrue(res["ok"])
        self.assertEqual(res["access_token"],  "ACC_NOVO")
        self.assertEqual(res["refresh_token"], "REF_NOVO")
        self.assertEqual(res["expires_in"],    21600)

        # URL OAuth correta
        self.assertEqual(
            mock_post.call_args[0][0],
            "https://www.bling.com.br/Api/v3/oauth/token",
        )
        # Basic auth = base64(client_id:client_secret)
        headers = mock_post.call_args.kwargs["headers"]
        esperado = base64.b64encode(b"cli_id:cli_sec").decode()
        self.assertEqual(headers["Authorization"], f"Basic {esperado}")
        # body OAuth padrão
        body = mock_post.call_args.kwargs["data"]
        self.assertEqual(body["grant_type"], "refresh_token")
        self.assertEqual(body["refresh_token"], "ref_xyz")

    def test_RT18_resposta_sem_refresh_mantem_o_antigo(self):
        mod = _carregar_script_com_env(
            {
                "BLING_CLIENT_ID":     "id",
                "BLING_CLIENT_SECRET": "sec",
                "BLING_REFRESH_TOKEN": "ANTIGO",
            }
        )
        with patch.object(mod.requests, "post") as mock_post:
            mock_post.return_value = _mock_resp(
                200, {"access_token": "NOVO", "expires_in": 3600}
            )
            res = mod._renovar_bling()
        self.assertEqual(res["refresh_token"], "ANTIGO")

    def test_RT19_resposta_sem_access_token_retorna_ok_false(self):
        mod = _carregar_script_com_env(
            {
                "BLING_CLIENT_ID":     "id",
                "BLING_CLIENT_SECRET": "sec",
                "BLING_REFRESH_TOKEN": "x",
            }
        )
        with patch.object(mod.requests, "post") as mock_post:
            mock_post.return_value = _mock_resp(
                200, {"error": "invalid_grant"}
            )
            res = mod._renovar_bling()
        self.assertFalse(res["ok"])
        self.assertIn("invalid_grant", res["motivo"])

    def test_RT20_excecao_de_rede_retorna_ok_false(self):
        mod = _carregar_script_com_env(
            {
                "BLING_CLIENT_ID":     "id",
                "BLING_CLIENT_SECRET": "sec",
                "BLING_REFRESH_TOKEN": "x",
            }
        )
        with patch.object(mod.requests, "post", side_effect=Exception("timeout")):
            res = mod._renovar_bling()
        self.assertFalse(res["ok"])
        self.assertIn("timeout", res["motivo"])


# ═══════════════════════════════════════════════════════════════════════════
# RT21–RT24 — main(): orquestração completa (fluxo crítico do Actions)
# ═══════════════════════════════════════════════════════════════════════════

class TestMainOrquestracao(unittest.TestCase):
    def _patch_publica(self, mod):
        return patch.object(
            mod,
            "_get_public_key",
            return_value={"key_id": "kid-1", "key": "BASE64=="},
        )

    def test_RT21_sucesso_total_exit_code_0_e_salva_secrets(self):
        mod = _carregar_script_com_env(
            {
                "GH_TOKEN":            "ghp_xxx",
                "GITHUB_REPOSITORY":   "joao/repo",
                "BLING_CLIENT_ID":     "id",
                "BLING_CLIENT_SECRET": "sec",
                "BLING_REFRESH_TOKEN": "r",
            }
        )
        with self._patch_publica(mod), \
             patch.object(mod, "_renovar_bling", return_value={
                 "ok": True,
                 "access_token":  "AT",
                 "refresh_token": "RT",
                 "expires_in":    21600,
             }), \
             patch.object(mod, "_salvar_secret", return_value=True) as mock_save, \
             patch.object(mod, "_atualizar_github_env") as mock_env, \
             patch(
                 "core.token_manager.renovar_todos_tokens",
                 return_value={
                     "mercadolivre": {"ok": True, "access_token": "ml_at"},
                     "shopee":       {"ok": True, "access_token": "sp_at"},
                     "magalu":       {"ok": True, "access_token": "mg_at"},
                 },
             ):
            exit_code = mod.main()

        self.assertEqual(exit_code, 0)
        nomes_salvos = {c.args[0] for c in mock_save.call_args_list}
        self.assertIn("BLING_ACCESS_TOKEN",  nomes_salvos)
        self.assertIn("BLING_REFRESH_TOKEN", nomes_salvos)
        self.assertIn("ML_ACCESS_TOKEN",     nomes_salvos)
        self.assertIn("SHOPEE_ACCESS_TOKEN", nomes_salvos)
        self.assertIn("MAGALU_ACCESS_TOKEN", nomes_salvos)
        mock_env.assert_called_once_with(
            BLING_ACCESS_TOKEN="AT", BLING_REFRESH_TOKEN="RT"
        )

    def test_RT22_falha_bling_exit_code_1(self):
        mod = _carregar_script_com_env(
            {"GH_TOKEN": "g", "GITHUB_REPOSITORY": "j/r"}
        )
        with self._patch_publica(mod), \
             patch.object(mod, "_renovar_bling", return_value={
                 "ok": False, "motivo": "credenciais ausentes"
             }), \
             patch.object(mod, "_salvar_secret", return_value=True), \
             patch(
                 "core.token_manager.renovar_todos_tokens",
                 return_value={
                     "mercadolivre": {"ok": True},
                     "shopee":       {"ok": True},
                     "magalu":       {"ok": True},
                 },
             ):
            exit_code = mod.main()
        self.assertEqual(exit_code, 1)

    def test_RT23_falha_em_um_marketplace_exit_code_1(self):
        mod = _carregar_script_com_env(
            {"GH_TOKEN": "g", "GITHUB_REPOSITORY": "j/r"}
        )
        with self._patch_publica(mod), \
             patch.object(mod, "_renovar_bling", return_value={
                 "ok": True, "access_token": "a", "refresh_token": "b",
                 "expires_in": 21600,
             }), \
             patch.object(mod, "_salvar_secret", return_value=True), \
             patch(
                 "core.token_manager.renovar_todos_tokens",
                 return_value={
                     "mercadolivre": {"ok": True, "access_token": "x"},
                     "shopee":       {"ok": False},
                     "magalu":       {"ok": True, "access_token": "y"},
                 },
             ):
            exit_code = mod.main()
        self.assertEqual(exit_code, 1)

    def test_RT24_sem_gh_token_nao_quebra_e_so_renova_localmente(self):
        """Sem credenciais GitHub, deve renovar mas pular o save remoto."""
        mod = _carregar_script_com_env({"GH_TOKEN": "", "GITHUB_REPOSITORY": ""})
        with patch.object(mod, "_renovar_bling", return_value={
                "ok": True, "access_token": "a", "refresh_token": "b",
                "expires_in": 21600,
             }), \
             patch.object(mod, "_get_public_key") as mock_pk, \
             patch.object(mod, "_salvar_secret") as mock_save, \
             patch(
                 "core.token_manager.renovar_todos_tokens",
                 return_value={
                     "mercadolivre": {"ok": True},
                     "shopee":       {"ok": True},
                     "magalu":       {"ok": True},
                 },
             ):
            exit_code = mod.main()
        self.assertEqual(exit_code, 0)
        mock_pk.assert_not_called()
        mock_save.assert_not_called()

    def test_RT25_token_manager_lanca_excecao_exit_code_1(self):
        mod = _carregar_script_com_env(
            {"GH_TOKEN": "g", "GITHUB_REPOSITORY": "j/r"}
        )
        with self._patch_publica(mod), \
             patch.object(mod, "_renovar_bling", return_value={
                 "ok": True, "access_token": "a", "refresh_token": "b",
                 "expires_in": 21600,
             }), \
             patch.object(mod, "_salvar_secret", return_value=True), \
             patch(
                 "core.token_manager.renovar_todos_tokens",
                 side_effect=RuntimeError("crash"),
             ):
            exit_code = mod.main()
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
