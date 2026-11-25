"""Planilha de ofícios via Web App do Google Apps Script.

Vantagem: usa o próprio Gmail/conta Google que já tem acesso ao documento.
Não precisa de conta de serviço nem de chave JSON.

O Apps Script expõe um POST que responde a:
  {"action": "proximo_numero"}
  {"action": "registrar", "numero": "...", "data": "...",
   "processo": "...", "destinatario": "..."}
"""
import re
from datetime import date

import requests
from django.conf import settings


class OficioPlanilhaWebhookError(Exception):
    pass


class OficioPlanilhaWebhookService:
    def __init__(self, url=None, token=None):
        self.url = url or getattr(settings, 'GOOGLE_OFICIOS_WEBHOOK_URL', '')
        self.token = token or getattr(
            settings, 'GOOGLE_OFICIOS_WEBHOOK_TOKEN', ''
        )

    @property
    def configurado(self):
        return bool(self.url)

    def _post(self, payload):
        if not self.url:
            raise OficioPlanilhaWebhookError(
                'GOOGLE_OFICIOS_WEBHOOK_URL não configurada.'
            )

        corpo = dict(payload)
        if self.token:
            corpo['token'] = self.token

        try:
            resposta = requests.post(
                self.url, json=corpo, timeout=30
            )
            resposta.raise_for_status()
        except Exception as exc:
            raise OficioPlanilhaWebhookError(
                f'Falha ao chamar o Apps Script: {exc}'
            ) from exc

        try:
            dados = resposta.json()
        except Exception as exc:
            raise OficioPlanilhaWebhookError(
                f'Resposta inválida do Apps Script: {resposta.text[:200]}'
            ) from exc

        if not dados.get('ok'):
            raise OficioPlanilhaWebhookError(
                dados.get('erro') or 'Apps Script retornou ok=false.'
            )
        return dados

    def proximo_numero(self, hoje=None):
        dados = self._post({'action': 'proximo_numero'})
        numero = (dados.get('numero') or '').strip()

        if not re.match(r'^\d{1,5}/\d{4}$', numero):
            raise OficioPlanilhaWebhookError(
                f'O Apps Script não retornou um número válido: {numero!r}'
            )
        return numero

    def registrar(self, numero, processo, destinatario, data=None):
        data = data or date.today()
        return self._post({
            'action': 'registrar',
            'numero': numero,
            'data': data.strftime('%d/%m/%Y'),
            'processo': processo,
            'destinatario': destinatario,
        })
