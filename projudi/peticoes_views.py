"""Fila de petições com escolha manual da certidão e da ação.

O tipo detectado (nome/tipo do PDF) é apenas uma sugestão; o usuário pode
trocar a certidão, informar o preparo e escolher a ação.
"""

from __future__ import annotations

from datetime import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.management import call_command
from django.core.management.base import CommandError
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import TemplateView

from projudi.assinantes_certidao import (
    ASSINANTE_PADRAO, ASSINANTES, resolver_assinante,
)
from projudi.decurso_certidao import gerar_e_registrar
from projudi.decurso_pagamento_service import DecursoPagamentoService
from projudi.models import PrazoDjenRecord
from projudi.peticoes_inominado import TIPOS_CERTIDAO, carregar_fila

PREPAROS = [
    ('', 'Selecione o preparo...'),
    ('gratuidade', 'Gratuidade / assistência judiciária'),
    ('completo', 'Preparo completo'),
    ('incompleto', 'Preparo incompleto/insuficiente'),
    ('nao_pago', 'Não houve preparo'),
]

ACOES = [
    ('gerar', 'Gerar certidão'),
    ('juntar', 'Juntar certidão no Projudi (em breve)'),
    ('intimar', 'Juntar + intimar (em breve)'),
]

TIPOS_VALIDOS = {t['valor'] for t in TIPOS_CERTIDAO}


class CertidaoPeticaoFilaView(LoginRequiredMixin, TemplateView):
    template_name = 'projudi/certidao_peticoes_fila.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        erro = ''
        peticoes = []
        try:
            peticoes = carregar_fila(self.request.user)
        except Exception as exc:
            erro = str(exc)

        context.update({
            'peticoes': peticoes,
            'erro': erro,
            'tipos_certidao': TIPOS_CERTIDAO,
            'preparos': PREPAROS,
            'acoes': ACOES,
            'assinantes': [
                {'chave': chave, 'nome': dados[0], 'cargo': dados[1]}
                for chave, dados in ASSINANTES.items()
            ],
            'assinante_padrao': ASSINANTE_PADRAO,
        })
        return context


class CertidaoPeticaoFilaGerarView(LoginRequiredMixin, View):
    def post(self, request):
        processo = (request.POST.get('processo') or '').strip()
        tipo_prazo = (request.POST.get('tipo_prazo') or '').strip()
        acao = (request.POST.get('acao') or 'gerar').strip()
        preparo = (request.POST.get('preparo') or '').strip()
        data_envio = (request.POST.get('data_envio') or '').strip()
        data_intimacao = (request.POST.get('data_intimacao') or '').strip()
        evento_intimacao = (
            request.POST.get('evento_intimacao') or '').strip()
        parte = (request.POST.get('parte') or '').strip()
        processo_url = (request.POST.get('processo_url') or '').strip()
        peticao_url = (request.POST.get('peticao_url') or '').strip()
        peticao_documento = (
            request.POST.get('peticao_documento') or '').strip()
        evento_despacho = (
            request.POST.get('evento_despacho') or '').strip()
        executado = (request.POST.get('executado') or '').strip()
        assinante = (
            request.POST.get('assinante') or ASSINANTE_PADRAO).strip()
        assinante_nome = (
            request.POST.get('assinante_nome') or '').strip()
        assinante_cargo = (
            request.POST.get('assinante_cargo') or '').strip()

        voltar = redirect('projudi:certidao_peticoes_fila')

        if not processo:
            messages.error(request, 'Processo não informado.')
            return voltar
        if tipo_prazo not in TIPOS_VALIDOS:
            messages.error(request, 'Escolha a certidão que será gerada.')
            return voltar

        if acao != 'gerar':
            messages.info(
                request,
                'A ação escolhida ainda não está implementada nesta versão. '
                'Use "Gerar certidão" por enquanto.',
            )
            return voltar

        if tipo_prazo == 'decurso_pagamento':
            return self._gerar_decurso(
                request,
                processo=processo,
                processo_url=processo_url,
                evento=evento_despacho,
                executado=executado,
                assinante=assinante,
                assinante_nome=assinante_nome,
                assinante_cargo=assinante_cargo,
            )

        data_protocolo = self._data(data_envio)
        if not data_protocolo:
            messages.error(
                request,
                'A fila não informou a data de envio da petição.',
            )
            return voltar

        try:
            if tipo_prazo == 'inominado':
                if preparo not in ('gratuidade', 'completo', 'incompleto',
                                   'nao_pago'):
                    messages.error(
                        request,
                        'Para o recurso inominado, informe o preparo.',
                    )
                    return voltar
                call_command(
                    'certidao_inominado',
                    processo=processo,
                    preparo=preparo,
                    url=processo_url or None,
                    peticao_url=peticao_url or None,
                    peticao_documento=peticao_documento or None,
                    data_protocolo=data_protocolo.strftime('%d/%m/%Y'),
                    parte=parte,
                )
            else:
                if not data_intimacao:
                    messages.error(
                        request,
                        'Para esta certidão, informe a data da intimação '
                        'que abriu o prazo.',
                    )
                    return voltar
                if not self._data(data_intimacao):
                    messages.error(
                        request,
                        'Data da intimação inválida. Use DD/MM/AAAA.',
                    )
                    return voltar
                call_command(
                    'prazo_djen',
                    tipo=tipo_prazo,
                    disponibilizacao=data_intimacao,
                    protocolo=data_protocolo.strftime('%d/%m/%Y'),
                    processo=processo,
                    parte=parte,
                    origem='peticao',
                    peticao_documento=peticao_documento,
                    peticao_url=peticao_url,
                    evento_recurso='infra',
                    evento_intimacao=evento_intimacao,
                )
        except CommandError as exc:
            messages.error(request, str(exc))
            return voltar
        except Exception as exc:
            messages.error(request, f'Erro ao gerar a certidão: {exc}')
            return voltar

        registro = (
            PrazoDjenRecord.objects
            .filter(processo=processo, origem='peticao')
            .order_by('-created_at')
            .first()
        )
        if registro:
            messages.success(
                request,
                f'Certidão gerada e registrada em Petições (#{registro.id}).',
            )
            return redirect('projudi:certidao_detail', pk=registro.id)

        messages.warning(
            request,
            'O comando foi executado, mas o registro não foi localizado. '
            'Confira a aba Petições.',
        )
        return redirect('projudi:certidao_peticoes')

    def _gerar_decurso(self, request, *, processo, processo_url, evento,
                       executado, assinante, assinante_nome,
                       assinante_cargo):
        voltar = redirect('projudi:certidao_peticoes_fila')
        if evento and not evento.isdigit():
            messages.error(
                request,
                'Evento do despacho inválido. Informe apenas o número ou '
                'deixe em branco para busca automática.',
            )
            return voltar

        try:
            resultado = DecursoPagamentoService(request.user).analisar(
                processo,
                evento=evento,
                parte_nome=executado,
                url=processo_url or None,
            )
        except Exception as exc:
            messages.error(
                request, f'Erro ao analisar o decurso: {exc}')
            return voltar

        if resultado.get('erro'):
            messages.error(request, resultado['erro'])
            return voltar

        if not resultado['decorrido']:
            messages.info(
                request,
                'O prazo de 15 dias ainda não decorreu. '
                f'Último dia: '
                f'{resultado["ultimo_dia"].strftime("%d/%m/%Y")}; '
                f'decurso: '
                f'{resultado["data_decurso"].strftime("%d/%m/%Y")}. '
                'A certidão não foi gerada.',
            )
            return voltar

        servidor, servidor_cargo = resolver_assinante(
            assinante, assinante_nome, assinante_cargo)
        try:
            _html, _caminho, registro = gerar_e_registrar(
                resultado,
                servidor=servidor,
                servidor_cargo=servidor_cargo,
            )
        except Exception as exc:
            messages.error(
                request, f'Erro ao gerar a certidão de decurso: {exc}')
            return voltar

        messages.success(
            request,
            'Certidão de decurso gerada e registrada em Movimentações '
            f'(#{registro.id}).',
        )
        return redirect('projudi:certidao_detail', pk=registro.id)

    @staticmethod
    def _data(valor):
        for formato in ('%d/%m/%Y', '%d/%m/%y', '%Y-%m-%d'):
            try:
                return datetime.strptime(valor, formato).date()
            except (TypeError, ValueError):
                continue
        return None
