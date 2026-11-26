"""Prévia e criação da movimentação 848 — Trânsito em Julgado."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views import View

from .movimentacao_service import MovimentacaoService
from .transito_julgado_service import TransitoJulgadoService


def _contexto_form(processo=''):
    return {'processo': processo}


class TransitoJulgadoView(LoginRequiredMixin, View):
    template_name = 'projudi/transito_julgado.html'

    def get(self, request):
        return render(request, self.template_name, _contexto_form(
            request.GET.get('processo', '')
        ))

    def post(self, request):
        processo = (request.POST.get('processo') or '').strip()
        if not processo:
            messages.error(request, 'Informe o número do processo.')
            return redirect('projudi:transito_julgado')
        resultado = TransitoJulgadoService(request.user).analisar(processo)
        if resultado.get('erro'):
            messages.error(request, resultado['erro'])
            return render(
                request, self.template_name,
                _contexto_form(processo),
            )

        transited = {'TRANSITADO', 'RENÚNCIA/DISPENSA'}
        partes = resultado['partes']
        autores = [
            p for p in partes
            if 'PROMOVENTE' in (p.get('papel') or '').upper()
            or 'AUTOR' in (p.get('papel') or '').upper()
        ]
        reus = [
            p for p in partes
            if 'PROMOVIDO' in (p.get('papel') or '').upper()
            or 'REU' in (p.get('papel') or '').upper()
            or 'RÉU' in (p.get('papel') or '').upper()
        ]
        return render(
            request, 'projudi/transito_julgado_preview.html',
            {
                'resultado': resultado,
                'pode_todos': resultado['status_geral'] == 'TRANSITADO',
                'pode_autores': (
                    bool(autores)
                    and all(p['status'] in transited for p in autores)
                ),
                'pode_res': (
                    bool(reus)
                    and all(p['status'] in transited for p in reus)
                ),
                'partes_transitadas': [
                    p for p in partes if p['status'] in transited
                ],
            },
        )


class TransitoJulgadoCriarView(LoginRequiredMixin, View):
    """Cria a Mov848 na fila de movimentações, sem executar automaticamente."""

    def post(self, request):
        processo = (request.POST.get('processo') or '').strip()
        escopo = (request.POST.get('escopo') or 'todos').strip().lower()
        parte_nome = (request.POST.get('parte_nome') or '').strip()

        if not processo:
            messages.error(request, 'Processo não informado.')
            return redirect('projudi:transito_julgado')

        resultado = TransitoJulgadoService(request.user).analisar(processo)
        if resultado.get('erro'):
            messages.error(request, resultado['erro'])
            return redirect('projudi:transito_julgado')

        partes = resultado['partes']
        transited = {'TRANSITADO', 'RENÚNCIA/DISPENSA'}

        if escopo == 'todos':
            if resultado['status_geral'] != 'TRANSITADO':
                messages.error(
                    request,
                    'O processo não está transited para todas as partes.'
                )
                return redirect('projudi:transito_julgado')
            papel = 'todos'
            nomes = 'todas as partes'
        elif escopo in ('autores', 'res'):
            grupo = [
                p for p in partes
                if (papel := (p.get('papel') or '').upper())
                and (
                    ('PROMOVENTE' in papel or 'AUTOR' in papel)
                    if escopo == 'autores'
                    else ('PROMOVIDO' in papel or 'REU' in papel or 'RÉU' in papel)
                )
            ]
            if not grupo or any(p['status'] not in transited for p in grupo):
                messages.error(
                    request,
                    'Nem todas as partes desse polo estão transitadas.'
                )
                return redirect('projudi:transito_julgado')
            papel = escopo
            nomes = 'autores' if escopo == 'autores' else 'réus'
        elif escopo == 'parte':
            parte = next(
                (p for p in partes if p['nome'] == parte_nome), None
            )
            if not parte or parte['status'] not in transited:
                messages.error(
                    request,
                    'A parte selecionada não está transitada.'
                )
                return redirect('projudi:transito_julgado')
            papel = 'parte'
            nomes = parte['nome']
        else:
            messages.error(request, 'Escopo inválido.')
            return redirect('projudi:transito_julgado')

        record = MovimentacaoService(request.user).importar(
            processo_numero=resultado['processo'],
            act_verb='transitado em julgado',
            observacao=f'Transitado em julgado — {nomes}.',
            categoria='registro',
            origem='movimentacao',
            processo_cnj=resultado['processo'],
            parte_nome=parte_nome if escopo == 'parte' else '',
            parte_papel=papel,
            url_processo=resultado['url'],
            codigo_movimentacao='848',
            descricao_movimentacao='Transitado em Julgado',
        )
        messages.success(
            request,
            f'✅ Mov848 criada na fila (#{record.id}) para {nomes}. '
            'Confira e execute na Fila de Movimentações.'
        )
        return redirect('projudi:movimentacao_fila')
