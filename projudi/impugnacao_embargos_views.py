"""Tela de certidão de tempestividade da impugnação/embargos à execução.

A certidão é gerada a partir da aba Movimentações, sem depender de uma
petição na fila JuntadaPeticao. O serviço localiza o despacho de pagamento
em 15 dias e a respectiva intimação; o usuário informa a data do protocolo
e a segurança do juízo.
"""

from __future__ import annotations

from datetime import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.management import call_command
from django.core.management.base import CommandError
from django.shortcuts import redirect, render
from django.views import View

from projudi.assinantes_certidao import (
    ASSINANTE_PADRAO, ASSINANTES, resolver_assinante,
)
from projudi.decurso_pagamento_service import DecursoPagamentoService
from projudi.models import PrazoDjenRecord

SEGURANCA_OPCOES = [
    ('integral', 'Integral'),
    ('parcial', 'Depósito parcial'),
    ('nenhuma', 'Não houve'),
]
SEGURANCA_VALORES = {valor for valor, _ in SEGURANCA_OPCOES}


def _data(texto):
    for formato in ('%d/%m/%Y', '%Y-%m-%d', '%d/%m/%y'):
        try:
            return datetime.strptime((texto or '').strip(), formato).date()
        except ValueError:
            continue
    return None


class CertidaoImpugnacaoEmbargosView(LoginRequiredMixin, View):
    template_name = 'projudi/certidao_impugnacao_embargos.html'

    def _contexto(self, **extra):
        context = {
            'assinante_padrao': ASSINANTE_PADRAO,
            'assinantes': [
                {'chave': chave, 'nome': dados[0], 'cargo': dados[1]}
                for chave, dados in ASSINANTES.items()
            ],
            'seguranca_opcoes': SEGURANCA_OPCOES,
            'processo': '',
            'processo_url': '',
            'evento': '',
            'executado': '',
            'data_protocolo': '',
            'evento_impugnacao': '',
            'seguranca_juizo': '',
            'data_intimacao_manual': '',
            'evento_intimacao_manual': '',
        }
        context.update(extra)
        return context

    def _render(self, request, **extra):
        return render(request, self.template_name, self._contexto(**extra))

    def get(self, request):
        return self._render(
            request,
            processo=(request.GET.get('processo') or '').strip(),
            processo_url=(request.GET.get('url') or '').strip(),
            evento=(request.GET.get('evento') or '').strip(),
        )

    def post(self, request):
        processo = (request.POST.get('processo') or '').strip()
        processo_url = (request.POST.get('processo_url') or '').strip()
        evento = (request.POST.get('evento') or '').strip()
        executado = (request.POST.get('executado') or '').strip()
        data_protocolo_txt = (
            request.POST.get('data_protocolo') or '').strip()
        evento_impugnacao = (
            request.POST.get('evento_impugnacao') or '').strip()
        seguranca_juizo = (
            request.POST.get('seguranca_juizo') or '').strip()
        data_intimacao_manual = (
            request.POST.get('data_intimacao_manual') or '').strip()
        evento_intimacao_manual = (
            request.POST.get('evento_intimacao_manual') or '').strip()

        dados = {
            'processo': processo,
            'processo_url': processo_url,
            'evento': evento,
            'executado': executado,
            'data_protocolo': data_protocolo_txt,
            'evento_impugnacao': evento_impugnacao,
            'seguranca_juizo': seguranca_juizo,
            'data_intimacao_manual': data_intimacao_manual,
            'evento_intimacao_manual': evento_intimacao_manual,
        }

        if not processo:
            messages.error(request, 'Informe o processo.')
            return self._render(request, **dados)

        data_protocolo = _data(data_protocolo_txt)
        if not data_protocolo:
            messages.error(
                request,
                'Informe a data do protocolo da impugnação/embargos '
                '(DD/MM/AAAA).',
            )
            return self._render(request, **dados)

        if seguranca_juizo not in SEGURANCA_VALORES:
            messages.error(
                request,
                'Informe a segurança do juízo: integral, depósito parcial '
                'ou não houve.',
            )
            return self._render(request, **dados)

        for rotulo, valor in (
            ('evento do despacho/pagamento', evento),
            ('evento da impugnação/embargos', evento_impugnacao),
            ('evento da intimação', evento_intimacao_manual),
        ):
            if valor and not valor.isdigit():
                messages.error(
                    request,
                    f'Informe apenas o número do {rotulo} ou deixe em branco.',
                )
                return self._render(request, **dados)

        if data_intimacao_manual and not _data(data_intimacao_manual):
            messages.error(
                request,
                'Data da intimação manual inválida. Use DD/MM/AAAA.',
            )
            return self._render(request, **dados)

        assinante = (
            request.POST.get('assinante') or ASSINANTE_PADRAO).strip()
        servidor, servidor_cargo = resolver_assinante(
            assinante,
            request.POST.get('assinante_nome') or '',
            request.POST.get('assinante_cargo') or '',
        )

        try:
            resultado = DecursoPagamentoService(request.user).analisar(
                processo,
                evento=evento,
                parte_nome=executado,
                url=processo_url or None,
                data_intimacao=data_intimacao_manual or None,
                evento_intimacao=evento_intimacao_manual or None,
            )
        except Exception as exc:
            messages.error(request, f'Erro ao analisar o processo: {exc}')
            return self._render(request, **dados)

        if resultado.get('erro'):
            messages.error(request, resultado['erro'])
            return self._render(request, **dados)

        data_intimacao = resultado.get('data_intimacao')
        if isinstance(data_intimacao, str):
            data_intimacao = _data(data_intimacao)
        if not data_intimacao:
            messages.error(
                request,
                'Não foi possível identificar a data da intimação. '
                'Informe a data/evento no fallback.',
            )
            return self._render(request, **dados)

        evento_intimacao = str(
            resultado.get('evento_intimacao') or '').strip()
        if not evento_intimacao.isdigit():
            evento_intimacao = ''

        try:
            call_command(
                'prazo_djen',
                tipo='impugnacao_embargos_execucao',
                disponibilizacao=data_intimacao.strftime('%d/%m/%Y'),
                protocolo=data_protocolo.strftime('%d/%m/%Y'),
                processo=processo,
                parte=resultado.get('executado') or executado,
                origem='movimentacao',
                evento_recurso=evento_impugnacao or '',
                evento_origem=(
                    resultado.get('evento_despacho') or evento or ''),
                evento_intimacao=evento_intimacao,
                seguranca_juizo=seguranca_juizo,
                servidor=servidor,
                servidor_cargo=servidor_cargo,
            )
        except CommandError as exc:
            messages.error(request, str(exc))
            return self._render(request, **dados)
        except Exception as exc:
            messages.error(
                request, f'Erro ao gerar a certidão: {exc}')
            return self._render(request, **dados)

        registro = (
            PrazoDjenRecord.objects
            .filter(processo=processo, origem='movimentacao')
            .order_by('-created_at')
            .first()
        )
        if registro:
            messages.success(
                request,
                'Certidão gerada e registrada em Movimentações '
                f'(#{registro.id}).',
            )
            return redirect('projudi:certidao_detail', pk=registro.id)

        messages.warning(
            request,
            'O comando foi executado, mas o registro não foi localizado. '
            'Confira a aba Movimentações.',
        )
        return redirect('projudi:certidao_movimentacoes')
