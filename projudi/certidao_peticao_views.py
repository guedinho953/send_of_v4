"""Fila de petições e geração de certidões de prazo."""
from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from .cumprimento_service import CumprimentoService
from .peticao_service import TIPOS, PeticaoQueueService


def _parse_data_br(valor):
    for fmt in ('%d/%m/%Y', '%d/%m/%y'):
        try:
            return datetime.strptime((valor or '').strip(), fmt).date()
        except ValueError:
            continue
    return None


class CertidaoPeticaoQueueView(LoginRequiredMixin, TemplateView):
    template_name = 'projudi/certidao_peticoes.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        erro = ''
        itens = []
        try:
            itens = PeticaoQueueService(self.request.user).listar()
        except Exception as exc:
            erro = str(exc)

        # Contagem por tipo.
        contagem = {chave: 0 for chave in TIPOS}
        for item in itens:
            contagem[item['tipo']] = contagem.get(item['tipo'], 0) + 1

        context.update({
            'itens': itens,
            'erro': erro,
            'total': len(itens),
            'contagem': contagem,
        })
        return context


class CertidaoPeticaoGerarView(LoginRequiredMixin, View):
    """Gera a prévia da certidão e salva em GeneratedDocument."""

    def post(self, request):
        tipo = (request.POST.get('tipo') or '').strip()
        info = TIPOS.get(tipo)
        if not info:
            messages.error(request, 'Tipo de petição inválido.')
            return HttpResponseRedirect(reverse('projudi:certidao_peticoes'))

        processo = (request.POST.get('processo') or '').strip()
        if not processo:
            messages.error(request, 'Processo não informado.')
            return HttpResponseRedirect(reverse('projudi:certidao_peticoes'))

        data_envio = _parse_data_br(request.POST.get('data_envio'))
        data_inicio = _parse_data_br(request.POST.get('data_inicio'))
        if not data_inicio:
            data_inicio = data_envio
        if not data_inicio:
            messages.error(request, 'Data de início da intimação não informada.')
            return HttpResponseRedirect(reverse('projudi:certidao_peticoes'))

        meio = (request.POST.get('meio_intimacao') or 'intimacao').strip()
        meio_label = (request.POST.get('meio_label') or '').strip()
        recorrente = (request.POST.get('recorrente') or '').strip()
        documento = (request.POST.get('documento_texto') or '').strip()

        try:
            resultado = CumprimentoService(request.user).contar_prazo_por_fluxo(
                meio,
                data_inicio,
                info['dias'],
                modo='uteis',
                tenant=getattr(request.user, 'tenant', None),
            )
        except Exception as exc:
            messages.error(request, f'Erro ao contar o prazo: {exc}')
            return HttpResponseRedirect(reverse('projudi:certidao_peticoes'))

        rotulo_meio = meio_label or {
            'eletronico': 'DJEN / domicílio eletrônico',
            'advogado': 'advogado constituído',
            'email': 'e-mail',
            'ar': 'AR / Correios',
            'mandado': 'mandado',
            'intimacao': 'intimação',
        }.get(meio, meio)

        texto = (
            f'Certifico que, referente ao processo em epígrafe, foi '
            f'juntado(a) {info["label"]}'
        )
        if data_envio:
            texto += f' em {data_envio.strftime("%d/%m/%Y")}'
        texto += (
            f'. A intimação foi realizada por {rotulo_meio} em '
            f'{data_inicio.strftime("%d/%m/%Y")}. O prazo de '
            f'{info["dias"]} ({info["dias"]} dias úteis) tem término em '
            f'{resultado.ultimo_dia.strftime("%d/%m/%Y")}, com decurso em '
            f'{resultado.data_decurso.strftime("%d/%m/%Y")}.'
        )
        if documento:
            texto += f' Documento: {documento}.'

        try:
            from django.template import Context, Template
            from base.utils import normalize_process_number
            from processes.models import DocumentTemplate, GeneratedDocument, Process

            template = DocumentTemplate.objects.get(
                name='Certidão de Prazo', active=True
            )
            proc = Process.objects.filter(number=processo).first()
            if not proc:
                proc = Process.objects.create(
                    number=processo,
                    number_normalized=normalize_process_number(processo),
                    tenant=request.user.tenant,
                    status='analyzing',
                )

            ctx = {
                'processo': processo,
                'parte': recorrente or 'parte',
                'recorrente': recorrente,
                'observacao_prazo': texto,
                'data': date.today().strftime('%d/%m/%Y'),
                'servidor': CumprimentoService._capitalizar_nome_proprio(
                    getattr(request.user, 'full_name', '')
                    or getattr(request.user, 'first_name', '') or '...'
                ),
            }
            html = Template(template.html_template).render(Context(ctx))

            seq = GeneratedDocument.proximo_numero(template)
            doc = GeneratedDocument.objects.create(
                tenant=request.user.tenant,
                process=proc,
                template=template,
                sequential_number=seq,
                year=date.today().year,
                recipient_name=f'Petição: {info["label"]}',
                html_content=html,
            )
        except Exception as exc:
            messages.error(request, f'Erro ao gerar a certidão: {exc}')
            return HttpResponseRedirect(reverse('projudi:certidao_peticoes'))

        return render(request, 'projudi/certidao_peticao_preview.html', {
            'documento': doc,
            'html_content': html,
            'item': {
                'processo': processo,
                'tipo_label': info['label'],
                'dias': info['dias'],
                'data_envio': data_envio,
                'data_inicio': data_inicio,
                'meio_label': rotulo_meio,
                'ultimo_dia': resultado.ultimo_dia,
                'data_decurso': resultado.data_decurso,
            },
        })
