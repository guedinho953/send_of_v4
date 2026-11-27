"""Tela de geração da certidão de decurso de pagamento voluntário."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views import View

from projudi.assinantes_certidao import (
    ASSINANTE_PADRAO, ASSINANTES, resolver_assinante,
)
from projudi.decurso_certidao import gerar_e_registrar
from projudi.decurso_pagamento_service import DecursoPagamentoService


class CertidaoDecursoPagamentoView(LoginRequiredMixin, View):
    template_name = 'projudi/certidao_decurso_pagamento.html'

    def _contexto(self, **extra):
        context = {
            'assinante_padrao': ASSINANTE_PADRAO,
            'assinantes': [
                {'chave': chave, 'nome': dados[0], 'cargo': dados[1]}
                for chave, dados in ASSINANTES.items()
            ],
            'processo': '',
            'evento': '',
            'executado': '',
        }
        context.update(extra)
        return context

    def get(self, request):
        return render(
            request,
            self.template_name,
            self._contexto(
                processo=(request.GET.get('processo') or '').strip(),
                evento=(request.GET.get('evento') or '').strip(),
                executado=(request.GET.get('executado') or '').strip(),
            ),
        )

    def post(self, request):
        processo = (request.POST.get('processo') or '').strip()
        evento = (request.POST.get('evento') or '').strip()
        executado = (request.POST.get('executado') or '').strip()

        if not processo:
            messages.error(request, 'Informe o processo.')
            return render(request, self.template_name, self._contexto())

        if evento and not evento.isdigit():
            messages.error(
                request,
                'Evento inválido. Informe apenas o número do despacho ou '
                'deixe em branco para busca automática.',
            )
            return render(request, self.template_name, self._contexto(
                processo=processo, evento=evento, executado=executado))

        assinante = (
            request.POST.get('assinante') or ASSINANTE_PADRAO
        ).strip()
        servidor, servidor_cargo = resolver_assinante(
            assinante,
            request.POST.get('assinante_nome') or '',
            request.POST.get('assinante_cargo') or '',
        )

        resultado = DecursoPagamentoService(request.user).analisar(
            processo, evento=evento, parte_nome=executado)
        if resultado.get('erro'):
            messages.error(request, resultado['erro'])
            return render(request, self.template_name, self._contexto(
                processo=processo, evento=evento, executado=executado))

        if not resultado['decorrido']:
            messages.info(
                request,
                'O prazo de 15 dias ainda não decorreu. '
                f'Último dia: {resultado["ultimo_dia"].strftime("%d/%m/%Y")}; '
                f'decurso: {resultado["data_decurso"].strftime("%d/%m/%Y")}. '
                'A certidão não foi gerada.',
            )
            return render(request, self.template_name, self._contexto(
                processo=processo, evento=evento, executado=executado))

        try:
            _html, _caminho, registro = gerar_e_registrar(
                resultado,
                servidor=servidor,
                servidor_cargo=servidor_cargo,
            )
        except Exception as exc:
            messages.error(
                request, f'Erro ao gerar a certidão: {exc}')
            return render(request, self.template_name, self._contexto(
                processo=processo, evento=evento, executado=executado))

        messages.success(
            request,
            'Certidão de decurso gerada e registrada em Movimentações '
            f'(#{registro.id}).',
        )
        return redirect('projudi:certidao_detail', pk=registro.id)
