"""Plano e execução de juntada/intimação da certidão."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render
from django.views import View

from projudi.acoes_agendadas import agendar_pos_intimacao
from projudi.juntar_service import (
    executar_juntada, executar_juntada_e_intimacao, montar_plano,
)
from projudi.models import PrazoDjenRecord

CONCLUSAO_OPCOES = [
    ('1', 'Despacho'),
    ('2', 'Decisão'),
    ('3', 'Sentença'),
    ('5', 'Decisão Urgente'),
    ('17', 'Embargos de Declaração'),
    ('18', 'Embargos de Execução'),
    ('19', 'Sentença Extintiva'),
    ('22', 'Exceção de Pré-executividade'),
]
JUIZ_CONCLUSAO_PADRAO = '41201'
JUIZES_CONCLUSAO = [
    ('41201', 'MARTINHO FERRAZ DA NOBREGA JUNIOR'),
    ('bsaraiva', 'BALTAZAR MIRANDA SARAIVA'),
    ('juiz.plantonista', 'JUIZ DESIGNADO'),
    ('37470', 'LEANDRO FERREIRA DE MORAES'),
    ('pachenaud', 'PAULO ALBERTO NUNES CHENAUD'),
    ('7946', 'PAULO EDUARDO DE MENEZES MOREIRA'),
    ('24575', 'REGINALDO COELHO CAVALCANTE'),
]


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
            'fazer_conclusao': plano.get('fazer_conclusao', False),
            'agendar_localizador': plano.get(
                'agendar_localizador', False),
            'agendar_contadoria': plano.get('agendar_contadoria', False),
            'tipo_conclusao': plano.get('tipo_conclusao', '18'),
            'conclusao_opcoes': CONCLUSAO_OPCOES,
            'juiz_conclusao': plano.get(
                'juiz_conclusao', JUIZ_CONCLUSAO_PADRAO),
            'juizes_conclusao': JUIZES_CONCLUSAO,
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
        fazer_conclusao = (
            request.POST.get('fazer_conclusao') == 'on'
            and registro.tipo_prazo == 'impugnacao_embargos_execucao'
        )
        agendar_localizador = (
            request.POST.get('agendar_localizador') == 'on'
            and registro.tipo_prazo == 'impugnacao_embargos_execucao'
        )
        agendar_contadoria = (
            request.POST.get('agendar_contadoria') == 'on'
            and registro.tipo_prazo == 'impugnacao_embargos_execucao'
        )
        tipo_conclusao = (
            request.POST.get('tipo_conclusao') or '18').strip()
        juiz_conclusao = (
            request.POST.get('juiz_conclusao')
            or JUIZ_CONCLUSAO_PADRAO).strip()

        plano = montar_plano(
            registro,
            request.user,
            processo_url=processo_url,
            polo=polo,
            prazo=prazo,
        )
        plano['fazer_conclusao'] = fazer_conclusao
        plano['tipo_conclusao'] = tipo_conclusao
        plano['juiz_conclusao'] = juiz_conclusao
        plano['agendar_localizador'] = agendar_localizador
        plano['agendar_contadoria'] = agendar_contadoria

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

            if ok and intimacao_ok:
                tipos = []
                if agendar_localizador:
                    if (plano.get('tipo_localizador')
                            or plano.get('localizador')):
                        tipos.append('localizador')
                    else:
                        messages.warning(
                            request,
                            'O localizador não foi agendado porque não há '
                            'código de localizador definido na RAG.',
                        )
                if agendar_contadoria:
                    tipos.append('contadoria')
                if fazer_conclusao:
                    tipos.append('conclusao')
                if tipos:
                    try:
                        data_ag, acoes = agendar_pos_intimacao(
                            registro,
                            request.user,
                            tipos,
                            tipo_localizador=plano.get(
                                'tipo_localizador') or '',
                            localizador=plano.get('localizador') or '',
                            tipo_conclusao=tipo_conclusao,
                            juiz_conclusao=juiz_conclusao,
                        )
                    except Exception as exc:
                        messages.warning(
                            request,
                            'A juntada/intimação foi feita, mas não foi '
                            f'possível agendar as ações: {exc}',
                        )
                    else:
                        messages.success(
                            request,
                            f'📅 {len(acoes)} ação(ões) agendada(s) para '
                            f'{data_ag.strftime("%d/%m/%Y")}: '
                            + ', '.join(
                                a.get_tipo_display() for a in acoes) + '.',
                        )

            novo_plano = montar_plano(
                registro,
                request.user,
                processo_url=processo_url,
                polo=polo,
                prazo=prazo,
            )
            novo_plano['fazer_conclusao'] = fazer_conclusao
            novo_plano['tipo_conclusao'] = tipo_conclusao
            novo_plano['juiz_conclusao'] = juiz_conclusao
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
                if (agendar_localizador or agendar_contadoria
                        or fazer_conclusao):
                    messages.info(
                        request,
                        'As ações pós-prazo só são agendadas na ação '
                        '"Juntar + intimar".',
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
            novo_plano['fazer_conclusao'] = fazer_conclusao
            novo_plano['tipo_conclusao'] = tipo_conclusao
            novo_plano['juiz_conclusao'] = juiz_conclusao
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
