"""
tests/__init__.py
Garante que a suíte de testes NUNCA envia logs reais ao Datadog, mesmo
que DD_API_KEY esteja definida no ambiente (ex.: um workflow de CI que
herda secrets de produção para o job inteiro, incluindo o passo de
testes — foi exatamente isso que aconteceu antes desta correção: cada
`logger.error("boom")` usado como mock em testes virava um "erro de
produção" real no Datadog).

Isto roda ANTES de qualquer módulo de teste ser importado — e
portanto antes de core/config.py ser importado pela primeira vez
neste processo — garantindo que core.config.DD_API_KEY já nasce
vazia aqui, não importa o que esteja no ambiente real.

Isto é defesa em profundidade: o ajuste principal é não vazar
DD_API_KEY para o job de testes em .github/workflows/ci.yml. Esta
camada extra protege também quem rodar a suíte localmente com
DD_API_KEY exportada no shell, ou qualquer outro workflow futuro que
venha a incluir testes no mesmo job que tem acesso aos secrets.
"""
import os

os.environ["DD_API_KEY"] = ""
os.environ["DD_LOGS_ENABLED"] = "false"
