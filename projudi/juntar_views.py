"""Plano e execução de juntada/intimação da certidão."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render
from django.views import View

from projudi.juntar_service import (
    executar_juntada, executar_juntada_e_intimacao, montar_plano,
)
from projudi.models import PrazoDjenRecord


class CertidaoJuntarIntimarView(LoginRequiredMixin, View):
    template_name = 'projudi/certidao_juntar_intimar.html'

    def _contexto(self, registro, plano, **extra):
        acoes = [('simular', 'Simular plano')]
        if plano.get('pode_juntar', True):
            acoes.append(('juntar', 'Juntar certidão'))
        if plano.get('pode_intimar'):
            acoes.append(('juntar_intimar', 'Juntar + intimar'))
        embargos = registro.tipo_prazo == 'impugnacao_embargos_execucao'
        context = {
            'registro': registro,
            'plano': plano,
            'acoes': acoes,
            'polos': [
                ('autores', 'Embargado(a) / Exequente'
                 if embargos else 'Autoras/Autores'),
                ('res', 'Embargante / Executado(a)'
                 if embargos else 'Réus/Rés'),
            ],
            'prazos': (
                [('15', '15 dias úteis')]
                if embargos else [
                    ('5', '5 dias úteis'),
                    ('10', '10 dias úteis'),
                    ('15', '15 dias úteis'),
                ]
            ),
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

        if acao == 'juntar_intimar':
            if registro.tipo_prazo != 'impugnacao_embargos_execucao':
                messages.info(
                    request,
                    'A intimação será habilitada na próxima etapa. '
                    'Use "Juntar certidão" por enquanto. Nada foi enviado.',
                )
                return render(
                    request,
                    self.template_name,
                    self._contexto(
                        registro, plano, acao=acao,
                        processo_url=processo_url, polo=polo, prazo=prazo),
                )

            if not plano.get('pode_intimar'):
                messages.error(
                    request,
                    'A intimação do embargado só é feita quando os '
                    'embargos são TEMPESTIVOS e a certidão ainda não foi '
                    'juntada.',
                )
                return render(
                    request,
                    self.template_name,
                    self._contexto(
                        registro, plano, acao=acao,
                        processo_url=processo_url, polo=polo, prazo=prazo),
                )
            if plano.get('erros'):
                messages.error(request, '; '.join(plano['erros']))
                return render(
                    request,
                    self.template_name,
                    self._contexto(
                        registro, plano, acao=acao,
                        processo_url=processo_url, polo=polo, prazo=prazo),
                )

            try:
                ok, record, intimacao_ok, erro_intimacao = (
                    executar_juntada_e_intimacao(
                        registro, request.user, plano=plano))
            except Exception as exc:
                messages.error(
                    request, f'Erro ao juntar/intimar a certidão: {exc}')
                return render(
                    request,
                    self.template_name,
                    self._contexto(
                        registro, plano, acao=acao,
                        processo_url=processo_url, polo=polo, prazo=prazo),
                )

            if ok and intimacao_ok:
                messages.success(
                    request,
                    '✅ Certidão juntada e embargado(a) intimado(a) no '
                    f'Projudi (movimentação #{record.id}).',
                )
            elif ok:
                messages.warning(
                    request,
                    'A certidão foi juntada, mas a intimação do embargado '
                    'não foi confirmada. Confira o Projudi e os logs. '
                    f'{erro_intimacao}',
                )
            else:
                messages.error(
                    request,
                    'A juntada não foi confirmada. Confira a movimentação '
                    f'#{getattr(record, "id", "?")} e os logs.',
                )

            novo_plano = montar_plano(
                registro,
                request.user,
                processo_url=processo_url,
                polo=polo,
                prazo=prazo,
            )
            return render(
                request,
                self.template_name,
                self._contexto(
                    registro, novo_plano, acao=acao,
                    processo_url=processo_url, polo=polo, prazo=prazo),
            )

        if acao == 'juntar':
            if plano.get('ja_juntada'):
                messages.info(
                    request,
                    f'Certidão já juntada (movimentação '
                    f'#{plano.get("movimentacao_id")}). '
                    'Nada foi enviado novamente.',
                )
                return render(
                    request,
                    self.template_name,
                    self._contexto(
                        registro, plano, acao=acao,
                        processo_url=processo_url, polo=polo, prazo=prazo),
                )
            if plano.get('erros'):
                messages.error(request, '; '.join(plano['erros']))
                return render(
                    request,
                    self.template_name,
                    self._contexto(
                        registro, plano, acao=acao,
                        processo_url=processo_url, polo=polo, prazo=prazo),
                )
            try:
                ok, record = executar_juntada(
                    registro, request.user, plano=plano)
            except Exception as exc:
                messages.error(
                    request, f'Erro ao juntar a certidão: {exc}')
                return render(
                    request,
                    self.template_name,
                    self._contexto(
                        registro, plano, acao=acao,
                        processo_url=processo_url, polo=polo, prazo=prazo),
                )

            if ok:
                messages.success(
                    request,
                    f'✅ Juntada concluída no Projudi '
                    f'(movimentação #{record.id}).',
                )
            else:
                messages.error(
                    request,
                    f'A juntada não foi confirmada. Confira a movimentação '
                    f'#{record.id} e os logs.',
                )

            novo_plano = montar_plano(
                registro,
                request.user,
                processo_url=processo_url,
                polo=polo,
                prazo=prazo,
            )
            return render(
                request,
                self.template_name,
                self._contexto(
                    registro, novo_plano, acao=acao,
                    processo_url=processo_url, polo=polo, prazo=prazo),
            )

        messages.info(request, 'Ação não reconhecida. Nada foi enviado.')
        return render(
            request,
            self.template_name,
            self._contexto(
                registro, plano, acao='simular',
                processo_url=processo_url, polo=polo, prazo=prazo),
        )
