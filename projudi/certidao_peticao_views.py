"""Fila de petições e geração de certidões de prazo."""
from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from .assinantes import ASSINANTE_PADRAO, ASSINANTES
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
        forcar = self.request.GET.get('atualizar') == '1'
        try:
            itens = PeticaoQueueService(
                self.request.user
            ).listar(forcar=forcar)
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
            'assinante_padrao': ASSINANTE_PADRAO,
            'assinantes': [
                {'chave': chave, 'nome': dados[0], 'cargo': dados[1]}
                for chave, dados in ASSINANTES.items()
            ],
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

        assinante = (request.POST.get('assinante') or ASSINANTE_PADRAO).strip()
        if assinante == 'outro':
            servidor = (
                request.POST.get('assinante_nome') or ''
            ).strip() or 'Ivan Guedes da Silva'
            servidor_cargo = (
                request.POST.get('assinante_cargo') or ''
            ).strip() or 'Secretário em Substituição'
        else:
            servidor, servidor_cargo = ASSINANTES.get(
                assinante, ASSINANTES[ASSINANTE_PADRAO]
            )

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

        eh_recurso = tipo == 'recurso_inominado'
        situacao_recurso = (
            request.POST.get('situacao_recurso') or ''
        ).strip()
        evento_intimacao = (
            request.POST.get('evento_intimacao') or ''
        ).strip() or 'não informado'
        evento_recurso = (
            request.POST.get('evento_recurso') or ''
        ).strip() or 'não informado'

        if eh_recurso:
            cabecalho = (
                'Certifico, para os devidos fins, conforme as determinações '
                'do Ofício Circular nº 034/2015/COJE, de 10 de julho de 2015, '
                'que o recurso inominado interposto no evento '
                f'{evento_recurso} afigura-se '
            )
            if situacao_recurso == 'preparo':
                texto = (
                    cabecalho + '<strong>TEMPESTIVO</strong> e regularmente '
                    '<strong>PREPARADO</strong>. Certifico ainda a '
                    'regularidade da habilitação dos advogados das partes, '
                    'consoante pedidos realizados até a presente data, nos '
                    'termos do art. 17 do Provimento nº CGJ 03/2010.'
                )
                situacao_label = 'Tempestivo — preparo integral'
            elif situacao_recurso == 'intempestivo':
                texto = (
                    cabecalho + '<strong>INTEMPESTIVO</strong>, ficando '
                    'prejudicada a análise de preparo e gratuidade.'
                )
                situacao_label = 'Intempestivo'
            else:
                texto = (
                    cabecalho + '<strong>TEMPESTIVO</strong>. Não houve o '
                    '<strong>PREPARO</strong>, em razão do pedido de '
                    'assistência judiciária gratuita. Certifico ainda a '
                    'regularidade da habilitação dos advogados das partes, '
                    'consoante pedidos realizados até a presente data, nos '
                    'termos do art. 17 do Provimento nº CGJ 03/2010.'
                )
                situacao_label = 'Tempestivo — pedido de gratuidade'
            template_name = 'Certidão de Recurso Inominado'
            from django.utils.safestring import mark_safe
            ctx_extra = {'texto_certidao': mark_safe(texto)}
        else:
            situacao_label = ''
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
            template_name = 'Certidão de Prazo'
            ctx_extra = {'observacao_prazo': texto}

        # Dados internos/privados: ficam no log e na observação de juntada,
        # não no corpo público da certidão.
        tempestivo_calc = (
            bool(data_envio and data_envio <= resultado.ultimo_dia)
            if not (eh_recurso and situacao_recurso == 'intempestivo')
            else False
        )
        status_temp = 'TEMPESTIVO' if tempestivo_calc else 'INTEMPESTIVO'
        observacao_juntada = (
            f'Certidão de {info["label"]} — recurso/protocolo no evento '
            f'{evento_recurso} em '
            f'{data_envio.strftime("%d/%m/%Y") if data_envio else "?"}; '
            f'{status_temp}; último dia do prazo: '
            f'{resultado.ultimo_dia.strftime("%d/%m/%Y")}; decurso do prazo: '
            f'{resultado.data_decurso.strftime("%d/%m/%Y")}; intimação: '
            f'{data_inicio.strftime("%d/%m/%Y")} ({rotulo_meio})'
        )
        if eh_recurso:
            observacao_juntada += (
                f'; evento da intimação da sentença: {evento_intimacao}; '
                f'recorrente: {recorrente or "não identificado"}.'
            )
        else:
            observacao_juntada += '.'

        import logging
        logging.getLogger('projudi.certidoes').info(
            'Certidão de petição gerada | processo=%s | tipo=%s | %s',
            processo, info['label'], observacao_juntada,
        )

        try:
            from django.template import Context, Template
            from base.utils import normalize_process_number
            from processes.models import DocumentTemplate, GeneratedDocument, Process

            template = DocumentTemplate.objects.get(
                name=template_name, active=True
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
                'recorrente': recorrente or 'não identificado',
                'data': date.today().strftime('%d/%m/%Y'),
                'servidor': servidor,
                'servidor_cargo': servidor_cargo,
            }
            ctx.update(ctx_extra)
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
                'situacao_label': situacao_label,
                'recorrente': recorrente,
                'evento_recurso': evento_recurso,
                'evento_intimacao': evento_intimacao,
                'observacao_juntada': observacao_juntada,
                'dias': info['dias'],
                'data_envio': data_envio,
                'data_inicio': data_inicio,
                'meio_label': rotulo_meio,
                'ultimo_dia': resultado.ultimo_dia,
                'data_decurso': resultado.data_decurso,
            },
        })
