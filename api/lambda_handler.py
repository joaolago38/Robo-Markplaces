"""
api/lambda_handler.py
Ponto de entrada AWS Lambda + Function URL para o Flask existente (api/app.py).

O servidor local continua via `python api/app.py` ou `flask run` — este módulo
só é usado quando deployado com SAM.
"""
from __future__ import annotations

import serverless_wsgi

from api.app import app


def handler(event, context):
    return serverless_wsgi.handle_request(app, event, context)
