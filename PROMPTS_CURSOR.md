Crie um script de diagnóstico do Telegram para o Robo-Markplaces, no mesmo
padrão dos diagnósticos já existentes (scripts/diagnostico_meta.py,
scripts/diagnostico_bling.py).

CONTEXTO:
Acabamos de criar um bot novo no Telegram (@robomarkeplace_bot) e já temos
TELEGRAM_TOKEN, TELEGRAM_CHAT_ID e TELEGRAM_GESTOR_CHAT_ID configurados no
.env local. O projeto já usa essas 3 variáveis em core/notificador.py
(funções alertar() e alertar_gestor(), que chamam
https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage). Não existe hoje
nenhum script que valide essa configuração de forma isolada — só descobrimos
se está certo quando algum agente tenta mandar alerta de verdade.

TAREFA:

1. Crie scripts/diagnostico_telegram.py seguindo o padrão visual e de
   imports dos outros scripts em scripts/ (sys.path.insert antes de importar
   core.*, sem expor token em nenhum print/log — mascare tipo
   "8935544842:AAHU...***" igual já faz core/http_errors.mascarar_url_telegram).

2. O script deve, em sequência:
   a) Confirmar que TELEGRAM_TOKEN, TELEGRAM_CHAT_ID e
      TELEGRAM_GESTOR_CHAT_ID estão definidos no ambiente (core.config) —
      se faltar algum, avisar exatamente qual e parar.
   b) Chamar GET https://api.telegram.org/bot{TOKEN}/getMe e confirmar que
      o token é válido, exibindo o username do bot retornado.
   c) Enviar uma mensagem de teste real via core.notificador.alertar()
      para TELEGRAM_CHAT_ID, com o texto
      "✅ Diagnóstico Robo-Markplaces — conexão Telegram OK".
   d) Enviar uma segunda mensagem de teste via
      core.notificador.alertar_gestor() para TELEGRAM_GESTOR_CHAT_ID
      (pode ser o mesmo chat_id, sem problema).
   e) Imprimir um resumo final tipo [OK]/[FALHA] por etapa, igual ao
      padrão de scripts/diagnostico_meta.py.

3. Nunca deixe a execução lançar exceção não tratada — qualquer erro de
   rede ou HTTP deve ser capturado e reportado como [FALHA] com a causa,
   sem interromper as demais etapas possíveis.

4. Adicione um teste em tests/test_diagnostico_telegram.py mockando
   requests (core.http_client.request) e core.notificador, cobrindo:
   token ausente, getMe com sucesso, getMe falhando (401), envio de
   alerta funcionando e falhando.

5. Rode ruff check . e python -m pytest -q ao final e confirme 0 erros
   de lint e cobertura >= 80% (limite já configurado no projeto).

6. Não altere a lógica de notificação existente em core/notificador.py —
   esta tarefa é só de diagnóstico/validação, não de funcionalidade nova.