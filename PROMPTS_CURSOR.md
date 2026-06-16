# Tarefa: corrigir credenciais no arquivo errado — mover de `.env.exemplo` para `.env`

## Situação
Por engano, valores REAIS de credenciais foram preenchidos no arquivo **`.env.exemplo`** (que é versionado/commitado no Git). O correto é que eles fiquem no **`.env`** (que é ignorado pelo Git — já consta no `.gitignore`). O `.env.exemplo` deve voltar a ser só um template com placeholders.

Risco a evitar: se `.env.exemplo` for commitado com valores reais, o `client_secret` vaza no repositório. Esta tarefa precisa deixar o `.env.exemplo` limpo ANTES de qualquer commit.

## O que fazer (nesta ordem)

1. **Ler o `.env.exemplo`** e identificar TODAS as linhas onde o valor é real (qualquer `CHAVE=valor` cujo valor não seja `...`, vazio, ou um valor de configuração legítimo do template — ex.: `META_API_VERSION=v19.0`, `MARGEM_MINIMA=15.0`, URLs de exemplo já existiam no template e NÃO são segredo). Foco nas credenciais: `*_CLIENT_ID`, `*_CLIENT_SECRET`, `*_ACCESS_TOKEN`, `*_REFRESH_TOKEN`, `*_TOKEN`, `*_KEY`, `*_SECRET`, `*_SELLER_ID`, `*_MERCHANT_ID`, `*_SHOP_ID`, `*_PARTNER_*`, `ANTHROPIC_API_KEY`, `TELEGRAM_*`, etc.

2. **Garantir que o `.env` existe** na raiz (criar se não existir, copiando a estrutura do `.env.exemplo`).

3. **Copiar para o `.env`** os valores reais encontrados no `.env.exemplo`, em cada chave correspondente (sobrescrevendo o placeholder em branco que estiver no `.env`). Não apagar do `.env` valores que já estejam corretos lá.

4. **Resetar o `.env.exemplo`**: trocar de volta para placeholder (`...`) o valor de toda chave de credencial que tenha sido preenchida com valor real. Manter intactas as linhas de configuração legítimas do template (versões de API, margens, flags, redirect_uris de exemplo, comentários e a estrutura geral). O resultado: `.env.exemplo` idêntico a um template, sem nenhum segredo real.

5. **Conferir segurança**:
   - Confirmar que `.env` continua listado no `.gitignore` (não remover).
   - Confirmar que o `.env.exemplo`, após o reset, NÃO contém mais nenhum valor real de credencial (fazer um diff/grep mental pelas chaves sensíveis).
   - Rodar `pip show python-dotenv` no ambiente ativo (`.venv`); se faltar, `pip install -r requirements.txt`. (Os scripts de bootstrap ignoram silenciosamente o `.env` se o `python-dotenv` não estiver instalado.)

## NÃO fazer
- NÃO commitar nada. Apenas deixar os arquivos no estado correto; o commit fica a critério do usuário depois de revisar.
- NÃO incluir nenhum valor real em mensagens, logs ou arquivos versionados.
- NÃO alterar `pegar_token_bling.py`, `pegar_token_ml.py`, `core/config.py` nem qualquer outro código.

## Entregar
- Confirmação de quais chaves foram movidas para o `.env`.
- Confirmação de que o `.env.exemplo` voltou a ter só placeholders (sem segredo real) e está seguro para commit.
- Status do `python-dotenv` no `.venv`.