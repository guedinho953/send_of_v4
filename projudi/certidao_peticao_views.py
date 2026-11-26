"""Fila de petições e geração de certidões de prazo."""
import logging
from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
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


def _situacao_certidao_recurso(html):
    """Classifica a certidão de recurso inominado pelo corpo gerado.

    Retorna:
      - 'intempestivo' — certidão certifica a intempestividade;
      - 'preparo'      — tempestivo e regularmente preparado;
      - 'gratuidade'   — tempestivo, sem preparo por gratuidade;
      - ''             — não identificado.
    """
    texto = (html or '').upper()
    # "INTEMPESTIVO" contém "TEMPESTIVO": verifica primeiro.
    if 'INTEMPESTIVO' in texto:
        return 'intempestivo'
    if 'PREPARADO' in texto:
        return 'preparo'
    if ('GRATUIDADE' in texto
            or 'ASSISTÊNCIA JUDICIÁRIA GRATUITA' in texto
            or 'ASSISTENCIA JUDICIARIA GRATUITA' in texto):
        return 'gratuidade'
    return ''


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

        # Polo sugerido para a intimação de contrarrazões: se o recorrente
        # estiver cadastrado como autor, intima-se o polo réu; se estiver
        # cadastrado como réu, intima-se o polo autor. Sem cadastro, usa-se
        # "autores" como sugestão (caso mais comum: réu recorrente).
        polo_sugerido = 'autores'
        if eh_recurso and recorrente:
            from processes.models import Party
            parte = (
                Party.objects
                .filter(process=proc, name__icontains=recorrente[:40])
                .first()
            )
            if parte and parte.is_author_side:
                polo_sugerido = 'res'
            elif parte and parte.is_defendant_side:
                polo_sugerido = 'autores'

        return render(request, 'projudi/certidao_peticao_preview.html', {
            'documento': doc,
            'html_content': html,
            'item': {
                'processo': processo,
                'tipo': tipo,
                'eh_recurso': eh_recurso,
                'situacao_recurso': situacao_recurso,
                'pode_intimar': (
                    eh_recurso and situacao_recurso == 'preparo'
                ),
                'tipo_label': info['label'],
                'situacao_label': situacao_label,
                'recorrente': recorrente,
                'evento_recurso': evento_recurso,
                'evento_intimacao': evento_intimacao,
                'observacao_juntada': observacao_juntada,
                'polo_sugerido': polo_sugerido,
                'dias': info['dias'],
                'data_envio': data_envio,
                'data_inicio': data_inicio,
                'meio_label': rotulo_meio,
                'ultimo_dia': resultado.ultimo_dia,
                'data_decurso': resultado.data_decurso,
            },
        })


class CertidaoPeticaoPreviewView(LoginRequiredMixin, TemplateView):
    """Reabre a prévia de uma certidão já gerada.

    Permite voltar à certidão depois de uma juntada parcial (por exemplo,
    certidão juntada mas intimação falhou) e usar a ação "Apenas intimar".
    Os detalhes internos da geração não são recuperados nesta tela — só o
    corpo da certidão e as ações de juntada/intimação.
    """

    template_name = 'projudi/certidao_peticao_preview.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from processes.models import GeneratedDocument

        doc = get_object_or_404(GeneratedDocument, pk=self.kwargs['pk'])
        user_tenant_id = getattr(self.request.user, 'tenant_id', None)
        if doc.tenant_id and user_tenant_id and doc.tenant_id != user_tenant_id:
            raise Http404('Certidão não pertence ao seu órgão.')

        rotulo = doc.template.name if doc.template else 'Certidão'
        eh_recurso = rotulo == 'Certidão de Recurso Inominado'
        situacao = (
            _situacao_certidao_recurso(doc.html_content)
            if eh_recurso else ''
        )
        context.update({
            'documento': doc,
            'html_content': doc.html_content,
            'item': {
                'processo': doc.process.number if doc.process else '',
                'tipo': '',
                'eh_recurso': eh_recurso,
                'situacao_recurso': situacao,
                'pode_intimar': eh_recurso and situacao == 'preparo',
                'tipo_label': rotulo,
                'situacao_label': '',
                'recorrente': '',
                'evento_recurso': '',
                'evento_intimacao': '',
                'observacao_juntada': '',
                'polo_sugerido': 'autores',
                'dias': '',
                'data_envio': None,
                'data_inicio': None,
                'meio_label': '',
                'ultimo_dia': None,
                'data_decurso': None,
            },
        })
        return context


class CertidaoPeticaoJuntarIntimarView(LoginRequiredMixin, View):
    """Junta a certidão gerada no Projudi e/ou intima a parte contrária.

    A certidão é inserida na movimentação 581 (com assinatura) e, em seguida,
    é feita uma segunda movimentação 581 de intimação da parte contrária para
    apresentar contrarrazões no prazo de 10 dias úteis (código 3 do Projudi).

    Ações aceitas:
      - juntar: apenas junta a certidão;
      - intimar: apenas intima (exige certidão já juntada);
      - juntar_intimar: junta (se ainda não juntada) e intima.
    """

    @staticmethod
    def _preview_redirect(doc):
        return HttpResponseRedirect(
            reverse('projudi:certidao_peticao_preview', args=[doc.id])
        )

    def post(self, request):
        from processes.models import GeneratedDocument
        from .movimentacao_service import MovimentacaoService

        documento_id = (request.POST.get('documento_id') or '').strip()
        if not documento_id.isdigit():
            messages.error(request, 'Documento da certidão não informado.')
            return HttpResponseRedirect(reverse('projudi:certidao_peticoes'))

        doc = get_object_or_404(GeneratedDocument, pk=int(documento_id))

        # Isola por tenant quando ambos os lados têm tenant definido.
        user_tenant_id = getattr(request.user, 'tenant_id', None)
        if doc.tenant_id and user_tenant_id and doc.tenant_id != user_tenant_id:
            messages.error(request, 'Certidão não pertence ao seu órgão.')
            return self._preview_redirect(doc)

        if not doc.process:
            messages.error(request, 'A certidão não está vinculada a um processo.')
            return self._preview_redirect(doc)
        if not (doc.html_content or '').strip():
            messages.error(request, 'A certidão não possui conteúdo para juntar.')
            return self._preview_redirect(doc)

        rotulo_certidao = (
            doc.template.name if doc.template else 'Certidão'
        )
        eh_recurso = rotulo_certidao == 'Certidão de Recurso Inominado'
        acao = (request.POST.get('acao') or 'juntar_intimar').strip().lower()
        if acao not in ('juntar', 'intimar', 'juntar_intimar'):
            messages.error(request, 'Ação inválida.')
            return self._preview_redirect(doc)
        if acao in ('intimar', 'juntar_intimar') and not eh_recurso:
            messages.error(
                request,
                'A intimação para contrarrazões só se aplica à '
                'Certidão de Recurso Inominado.'
            )
            return self._preview_redirect(doc)

        # A intimação para contrarrazões do fluxo padrão só vale para
        # recurso TEMPESTIVO e PREPARADO. Intempestivo e sem preparo
        # (gratuidade) têm tratamento próprio.
        situacao_recurso = (
            _situacao_certidao_recurso(doc.html_content)
            if eh_recurso else ''
        )
        if (acao in ('intimar', 'juntar_intimar')
                and situacao_recurso != 'preparo'):
            messages.warning(
                request,
                'Esta certidão não é de recurso TEMPESTIVO e PREPARADO. '
                'A intimação de contrarrazões em 10 dias é exclusiva desse '
                'caso; para intempestivo ou sem preparo, use o fluxo próprio. '
                'A certidão pode ser apenas juntada.'
            )
            return self._preview_redirect(doc)

        polo = (request.POST.get('polo_intimacao') or 'autores').strip().lower()
        if polo not in ('autores', 'res', 'todos'):
            polo = 'autores'

        observacao = (
            request.POST.get('observacao_juntada') or ''
        ).strip()
        recorrente = (request.POST.get('recorrente') or '').strip()
        processo = doc.process.number
        url_processo = doc.process.projudi_url or ''

        logger = logging.getLogger('projudi.certidoes')
        service = MovimentacaoService(request.user)

        # ── 1. Juntada da certidão ──────────────────────────────────
        certidao_juntada = bool(doc.exported_to_projudi)
        if acao in ('juntar', 'juntar_intimar') and not certidao_juntada:
            try:
                record = service.importar(
                    processo_numero=processo,
                    act_verb='certifique-se',
                    observacao=(
                        f'Juntada da {rotulo_certidao}. ' + observacao
                    ).strip(),
                    categoria='certidao',
                    processo_cnj=processo,
                    parte_nome=recorrente,
                    url_processo=url_processo,
                    codigo_movimentacao='581',
                    descricao_movimentacao=rotulo_certidao,
                )
                if observacao:
                    # Dados privados também ficam no log interno da movimentação.
                    service.criar_log(
                        record, 'info',
                        f'Dados internos da certidão: {observacao}',
                        {'documento_id': doc.id,
                         'origem': 'certidao_recurso_inominado'},
                    )
                certidao_juntada = service.executar_requests(
                    record,
                    certidao_html=doc.html_content,
                    certidao_titulo=rotulo_certidao,
                )
                if certidao_juntada:
                    doc.exported_to_projudi = True
                    doc.save(update_fields=['exported_to_projudi'])
                    logger.info(
                        'Certidão juntada | tipo=%s | processo=%s | '
                        'documento=%s | %s',
                        rotulo_certidao, processo, doc.id, observacao,
                    )
            except Exception as exc:
                logger.exception(
                    'Erro ao juntar certidão | tipo=%s | processo=%s | '
                    'documento=%s', rotulo_certidao, processo, doc.id,
                )
                messages.error(request, f'Erro ao juntar a certidão: {exc}')
                return self._preview_redirect(doc)

            if not certidao_juntada:
                messages.error(
                    request,
                    'A certidão não foi juntada. A intimação não foi realizada.'
                )
                return self._preview_redirect(doc)

        if acao == 'intimar' and not certidao_juntada:
            messages.error(
                request,
                'Junte a certidão antes de intimar a parte contrária.'
            )
            return self._preview_redirect(doc)

        # ── 2. Intimação da parte contrária ─────────────────────────
        if acao in ('intimar', 'juntar_intimar'):
            observacao_intimacao = (
                'Intimem-se a parte contrária para apresentar contrarrazões '
                'ao recurso inominado, no prazo de 10 (dez) dias úteis.'
            )
            try:
                ok_intimacao = service.executar_com_intimacao(
                    processo_numero=processo,
                    observacao=observacao_intimacao,
                    codigo_mov='581',
                    descricao_mov='Intimação',
                    prazo_intimacao='3',   # código 3 = 10 dias úteis
                    motivo_intimacao='3',
                    polo_intimacao=polo,
                    natureza_override='civel',
                )
            except Exception as exc:
                logger.exception(
                    'Erro ao intimar contrarrazões | processo=%s | documento=%s',
                    processo, doc.id,
                )
                messages.error(
                    request,
                    'A certidão foi juntada, mas a intimação falhou: '
                    f'{exc}'
                )
                return self._preview_redirect(doc)

            if not ok_intimacao:
                messages.warning(
                    request,
                    'A certidão foi juntada, mas a intimação não foi '
                    'confirmada. Confira o processo no Projudi e, se '
                    'necessário, use o botão "Apenas intimar".'
                )
                return self._preview_redirect(doc)

            logger.info(
                'Intimação para contrarrazões realizada | processo=%s | '
                'documento=%s | polo=%s | prazo=10 dias úteis',
                processo, doc.id, polo,
            )

        if acao == 'juntar':
            messages.success(
                request,
                f'✅ {rotulo_certidao} juntada ao processo.'
            )
            return self._preview_redirect(doc)

        messages.success(
            request,
            '✅ Certidão juntada e parte contrária intimada para '
            'apresentar contrarrazões em 10 dias úteis.'
        )
        return HttpResponseRedirect(reverse('projudi:certidao_peticoes'))
