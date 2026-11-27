"""Plano de juntada/intimação da certidão (dry-run)."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render
from django.views import View

from projudi.juntar_service import montar_plano
from projudi.models import PrazoDjenRecord


class CertidaoJuntarIntimarView(LoginRequiredMixin, View):
    template_name = 'projudi/certidao_juntar_intimar.html'

    def _contexto(self, registro, plano, **extra):
        acoes = [('simular', 'Simular plano')]
        if plano.get('pode_juntar', True):
            acoes.append(('juntar', 'Juntar certidão'))
        if plano.get('pode_intimar'):
            acoes.append(('juntar_intimar', 'Juntar + intimar'))
        context = {
            'registro': registro,
            'plano': plano,
            'acoes': acoes,
            'polos': [
                ('autores', 'Autoras/Autores'),
                ('res', 'Réus/Rés'),
            ],
            'prazos': [
                ('5', '5 dias úteis'),
                ('10', '10 dias úteis'),
                ('15', '15 dias úteis'),
            ],
            'processo_url': plano.get('processo_url', ''),
            'polo': plano.get('polo', 'autores'),
            'prazo': plano.get('prazo', '10'),
            'acao': 'simular',
        }
        context.update(extra)
        return context

    def get(self, request, pk):
        registro = get_object_or_404(PrazoDjenRecord, pk=pk)
        plano = montar_plano(registro, request.user)
        return render(
            request, self.template_name, self._contexto(registro, plano))

    def post(self, request, pk):
        registro = get_object_or_404(PrazoDjenRecord, pk=pk)
        acao = (request.POST.get('acao') or 'simular').strip()
        processo_url = (request.POST.get('processo_url') or '').strip()
        polo = (request.POST.get('polo') or '').strip()
        prazo = (request.POST.get('prazo') or '').strip()
        confirmo = request.POST.get('confirmo') == 'on'

        plano = montar_plano(
            registro,
            request.user,
            processo_url=processo_url,
            polo=polo,
            prazo=prazo,
        )

        if acao == 'simular':
            messages.info(
                request,
                'Simulação gerada. Nada foi enviado ao Projudi.',
            )
            return render(
                request,
                self.template_name,
                self._contexto(
                    registro, plano, acao=acao,
                    processo_url=processo_url, polo=polo, prazo=prazo),
            )

        if not confirmo:
            messages.warning(
                request,
                'Marque a confirmação para executar. Nada foi enviado.',
            )
            return render(
                request,
                self.template_name,
                self._contexto(
                    registro, plano, acao=acao,
                    processo_url=processo_url, polo=polo, prazo=prazo),
            )

        # A execução real será habilitada na próxima etapa, após validar o
        # plano com um processo de teste.
        messages.warning(
            request,
            'Execução real ainda não habilitada nesta etapa. '
            'O plano está validado; nada foi enviado ao Projudi.',
        )
        return render(
            request,
            self.template_name,
            self._contexto(
                registro, plano, acao=acao,
                processo_url=processo_url, polo=polo, prazo=prazo),
        )
