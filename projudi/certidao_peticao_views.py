"""Fila de petições e geração de certidões de prazo."""
import logging
import re
from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from .assinantes import ASSINANTE_PADRAO, ASSINANTES
from .certidao_constants import NOME_CERTIDAO_CUSTAS
from .cumprimento_service import CumprimentoService
from .peticao_service import (
    MEIO_LABEL, TIPOS, TIPOS_PETICAO, PeticaoQueueService,
)


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


def _evento_recurso_certidao(html):
    """Extrai o número do evento do recurso do corpo da certidão."""
    m = re.search(r'evento\s+(\d+)', html or '', re.I)
    return m.group(1) if m else ''


def _texto_impugnacao_embargos(
        resultado, data_protocolo, evento_impugnacao='',
        evento_despacho='', evento_intimacao='', meio_label='DJEN',
        seguranca='nenhuma'):
    """Certidão de tempestividade + segurança do juízo (FONAJE 117)."""
    tempestivo = bool(
        data_protocolo and data_protocolo <= resultado.ultimo_dia
    )
    conclusao = 'TEMPESTIVIDADE' if tempestivo else 'INTEMPESTIVIDADE'

    def _evento(valor):
        return f' (evento {valor})' if str(valor or '').isdigit() else ''

    inicio = (
        resultado.dias_contados[0]
        if getattr(resultado, 'dias_contados', None)
        else resultado.data_inicio
    )
    texto = (
        'Certifico, para os devidos fins, a '
        f'{conclusao} da Impugnação/Embargos à Execução apresentada'
        f'{_evento(evento_impugnacao)} (prazo de 15 (quinze) dias), '
        f'referente ao despacho{_evento(evento_despacho)} e à '
        f'intimação {meio_label}{_evento(evento_intimacao)}. '
        f'Publicação em {resultado.data_inicio.strftime("%d/%m/%Y")}; '
        f'início do prazo em {inicio.strftime("%d/%m/%Y")}; '
        f'termo final em {resultado.ultimo_dia.strftime("%d/%m/%Y")}.'
    )
    if not tempestivo:
        return texto

    seguranca_txt = {
        'integral': 'a SEGURANÇA INTEGRAL DO JUÍZO',
        'parcial': (
            'que houve depósito PARCIAL, NÃO HAVENDO SEGURANÇA '
            'INTEGRAL DO JUÍZO'
        ),
        'nenhuma': 'que NÃO HOUVE SEGURANÇA DO JUÍZO',
    }.get(seguranca, 'que NÃO HOUVE SEGURANÇA DO JUÍZO')
    return (
        texto
        + f' Certifico ainda {seguranca_txt}, observados o valor '
        'executado (considerando o valor da execução) e o valor '
        'depositado/penhorado (Enunciado n. 117 do FONAJE).'
    )


def _texto_intimacao_decurso(resultado, modelo='voluntario'):
    """Texto único da observação da movimentação e da intimação."""
    if modelo == 'remanescente':
        objeto = 'pagamento do débito remanescente'
    else:
        objeto = 'pagamento voluntário do débito'
    data_intimacao = resultado['data_intimacao'].strftime('%d/%m/%Y')
    ultimo_dia = resultado['ultimo_dia'].strftime('%d/%m/%Y')
    data_decurso = resultado['data_decurso'].strftime('%d/%m/%Y')
    canal = (
        'DJEN' if resultado.get('meio') == 'eletronico'
        else (resultado.get('meio_label') or 'intimação')
    )
    return (
        f'Intime-se a parte autora: o prazo de 15 dias para {objeto} '
        f'(Despacho, evento {resultado["evento_despacho"]}), com intimação '
        f'em {data_intimacao} (evento {resultado["evento_intimacao"]} — '
        f'{canal}), ainda não decorreu. '
        f'Último dia: {ultimo_dia}. Decurso: {data_decurso}.'
    )


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
        contagem = {chave: 0 for chave in TIPOS_PETICAO}
        for item in itens:
            contagem[item['tipo']] = contagem.get(item['tipo'], 0) + 1

        context.update({
            'itens': itens,
            'erro': erro,
            'total': len(itens),
            'contagem': contagem,
            'tipos': TIPOS_PETICAO,
            'meios': MEIO_LABEL,
            'assinante_padrao': ASSINANTE_PADRAO,
            'assinantes': [
                {'chave': chave, 'nome': dados[0], 'cargo': dados[1]}
                for chave, dados in ASSINANTES.items()
            ],
        })
        return context


class CertidaoPeticaoGerarView(LoginRequiredMixin, View):
    """Gera a prévia da certidão e salva em GeneratedDocument."""

    origem = 'peticao'
    url_voltar = 'projudi:certidao_peticoes'
    rotulo_origem = 'Petição'

    def post(self, request):
        tipo = (request.POST.get('tipo') or '').strip()
        info = TIPOS.get(tipo)
        if not info:
            messages.error(
                request, f'Tipo de {self.rotulo_origem.lower()} inválido.'
            )
            return HttpResponseRedirect(reverse(self.url_voltar))

        processo = (request.POST.get('processo') or '').strip()
        processo_url = (request.POST.get('processo_url') or '').strip()
        if not processo:
            messages.error(request, 'Processo não informado.')
            return HttpResponseRedirect(reverse(self.url_voltar))

        evento_origem = (
            request.POST.get('evento_origem')
            or request.POST.get('evento_despacho')
            or ''
        ).strip()
        evento_intimacao = (
            request.POST.get('evento_intimacao') or ''
        ).strip()
        evento_requerimento = (
            request.POST.get('evento_requerimento') or ''
        ).strip()
        evento_impugnacao = (
            request.POST.get('evento_impugnacao') or ''
        ).strip()
        seguranca_juizo = (
            request.POST.get('seguranca_juizo') or ''
        ).strip()
        executado = (request.POST.get('executado') or '').strip()
        parte = (request.POST.get('parte') or '').strip()

        if tipo == 'decurso_pagamento':
            return CertidaoDecursoPagamentoView().processar(
                request, processo, evento=evento_origem,
                executado=executado,
                evento_requerimento=evento_requerimento,
            )
        if tipo == 'decurso_debito_remanescente':
            return CertidaoDecursoPagamentoView().processar(
                request, processo, evento=evento_origem,
                executado=executado,
                evento_requerimento=evento_requerimento,
                modelo='remanescente',
            )

        data_envio = _parse_data_br(request.POST.get('data_envio'))
        data_inicio = _parse_data_br(request.POST.get('data_inicio'))
        data_protocolo = data_envio
        intimacao_evento = None

        # Evento informado dispensa a data: busca no processo.
        evento_busca = (
            evento_intimacao
            or evento_origem
            or evento_impugnacao
            or (request.POST.get('evento_recurso') or '').strip()
        )
        precisa_consultar = (
            (not data_inicio and bool(evento_busca))
            or (tipo == 'impugnacao_embargos_execucao'
                and not data_protocolo and bool(evento_impugnacao))
        )
        if precisa_consultar and not processo_url:
            try:
                from .processo_lookup import localizar_processo
                achado = localizar_processo(request.user, processo)
                if achado:
                    processo_url = achado['url']
            except Exception:
                pass

        if tipo == 'impugnacao_embargos_execucao':
            if seguranca_juizo not in ('integral', 'parcial', 'nenhuma'):
                messages.error(
                    request,
                    'Informe a segurança do juízo: integral, depósito '
                    'parcial ou não houve.',
                )
                return HttpResponseRedirect(reverse(self.url_voltar))
            data_protocolo = _parse_data_br(
                request.POST.get('data_protocolo')
            )
            if not data_protocolo and evento_impugnacao and processo_url:
                from .evento_processo_service import data_evento_processo
                data_protocolo = data_evento_processo(
                    request.user, processo_url, evento_impugnacao,
                )
                if data_protocolo:
                    messages.info(
                        request,
                        'Data do protocolo obtida pelo evento '
                        f'{evento_impugnacao}: '
                        f'{data_protocolo.strftime("%d/%m/%Y")}.',
                    )
            if not data_protocolo:
                messages.error(
                    request,
                    'Informe a data do protocolo ou o evento da '
                    'impugnação/embargos para o sistema buscar a data.',
                )
                return HttpResponseRedirect(reverse(self.url_voltar))
            data_envio = data_protocolo

        if not data_inicio and evento_busca and processo_url:
            from .evento_processo_service import (
                localizar_intimacao_do_processo,
            )
            intimacao_evento = localizar_intimacao_do_processo(
                request.user, processo_url, evento_busca,
                parte=parte or executado or (
                    request.POST.get('recorrente') or ''
                ).strip(),
            )
            if intimacao_evento:
                data_inicio = intimacao_evento['data']

        if (not data_inicio
                and tipo == 'impugnacao_embargos_execucao'):
            messages.error(
                request,
                'Informe a data da intimação ou o evento do '
                'despacho/decisão para o sistema localizar a data.',
            )
            return HttpResponseRedirect(reverse(self.url_voltar))
        if not data_inicio:
            data_inicio = data_envio
        if not data_inicio:
            messages.error(
                request,
                'Informe a data da intimação ou o evento do '
                'despacho/decisão para o sistema localizar a data.',
            )
            return HttpResponseRedirect(reverse(self.url_voltar))

        meio = (request.POST.get('meio_intimacao') or 'intimacao').strip()
        meio_label = (request.POST.get('meio_label') or '').strip()
        if intimacao_evento and intimacao_evento.get('meio'):
            meio = intimacao_evento['meio']
            meio_label = ''
        origem_intimacao = (
            request.POST.get('origem_intimacao') or ''
        ).strip()
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
            return HttpResponseRedirect(reverse(self.url_voltar))

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
        if eh_recurso and situacao_recurso not in ('preparo', 'intempestivo'):
            situacao_recurso = 'gratuidade'
        evento_intimacao = (
            request.POST.get('evento_intimacao') or ''
        ).strip() or 'não informado'
        evento_recurso = (
            request.POST.get('evento_recurso')
            or evento_impugnacao
            or evento_origem
            or ''
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
        elif tipo == 'impugnacao_embargos_execucao':
            texto = _texto_impugnacao_embargos(
                resultado,
                data_protocolo,
                evento_impugnacao=evento_impugnacao,
                evento_despacho=evento_origem,
                evento_intimacao=(
                    request.POST.get('evento_intimacao') or ''
                ).strip(),
                meio_label=(
                    'eletrônica (DJEN)' if meio == 'eletronico'
                    else f'por {rotulo_meio}'
                ),
                seguranca=seguranca_juizo,
            )
            tempestivo_embargos = bool(
                data_protocolo <= resultado.ultimo_dia
            )
            if tempestivo_embargos:
                situacao_label = {
                    'integral': 'Tempestivo — segurança integral',
                    'parcial': 'Tempestivo — depósito parcial',
                    'nenhuma': 'Tempestivo — sem segurança do juízo',
                }.get(seguranca_juizo, 'Tempestivo')
            else:
                situacao_label = 'Intempestivo'
            template_name = 'Certidão de Impugnação/Embargos à Execução'
            ctx_extra = {'observacao_prazo': texto}
        else:
            situacao_label = ''
            if self.origem == 'movimentacao':
                texto = (
                    f'Certifico que, referente ao processo em epígrafe, foi '
                    f'identificada a movimentação "{info["label"]}"'
                )
            else:
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
        if tipo == 'impugnacao_embargos_execucao':
            status_temp = (
                'TEMPESTIVO'
                if data_envio and data_envio <= resultado.ultimo_dia
                else 'INTEMPESTIVO'
            )
        else:
            status_temp = (
                'movimentação registrada' if self.origem == 'movimentacao'
                else ('TEMPESTIVO' if tempestivo_calc else 'INTEMPESTIVO')
            )
        if self.origem == 'movimentacao':
            inicio_obs = (
                f'Certidão de {info["label"]} — movimentação de '
                f'{data_envio.strftime("%d/%m/%Y") if data_envio else "?"}; '
            )
        else:
            inicio_obs = (
                f'Certidão de {info["label"]} — recurso/protocolo no evento '
                f'{evento_recurso} em '
                f'{data_envio.strftime("%d/%m/%Y") if data_envio else "?"}; '
            )
        observacao_juntada = (
            inicio_obs
            + f'{status_temp}; último dia do prazo: '
            + f'{resultado.ultimo_dia.strftime("%d/%m/%Y")}; '
            + 'decurso do prazo: '
            + f'{resultado.data_decurso.strftime("%d/%m/%Y")}; intimação: '
            + f'{data_inicio.strftime("%d/%m/%Y")} ({rotulo_meio})'
        )
        if tipo == 'impugnacao_embargos_execucao':
            observacao_juntada += (
                f'; segurança do juízo: {seguranca_juizo}; '
                f'evento da impugnação/embargos: '
                f'{evento_impugnacao or "não informado"}'
            )
        if eh_recurso:
            origem_intimacao_label = (
                'Embargos de declaração'
                if origem_intimacao == 'embargos'
                else 'Sentença'
            )
            origem_obs = (
                'dos embargos de declaração'
                if origem_intimacao == 'embargos'
                else 'da sentença'
            )
            observacao_juntada += (
                f'; evento da intimação {origem_obs}: '
                f'{evento_intimacao}; '
                f'recorrente: {recorrente or "não identificado"}.'
            )
        else:
            observacao_juntada += '.'

        logging.getLogger('projudi.certidoes').info(
            'Certidão de %s gerada | processo=%s | tipo=%s | %s',
            self.rotulo_origem.lower(), processo, info['label'],
            observacao_juntada,
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
                    projudi_url=processo_url,
                )
            elif processo_url and not proc.projudi_url:
                # Guarda a URL do Projudi para a juntada encontrar o número
                # interno do processo (numeroProcesso=...).
                proc.projudi_url = processo_url
                proc.save(update_fields=['projudi_url'])

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
                recipient_name=f'{self.rotulo_origem}: {info["label"]}',
                html_content=html,
            )
            try:
                from .certidao_registro_service import registrar_documento
                prazo_info = resultado.to_dict()
                if tipo == 'impugnacao_embargos_execucao':
                    prazo_info.update({
                        'situacao_embargos': (
                            'tempestivo'
                            if data_envio <= resultado.ultimo_dia
                            else 'intempestivo'
                        ),
                        'evento_impugnacao': evento_impugnacao,
                        'seguranca_juizo': seguranca_juizo,
                    })
                registrar_documento(
                    request.user, doc,
                    tipo_prazo=tipo,
                    origem=self.origem,
                    parte=recorrente or parte or '',
                    status='gerada',
                    data_intimacao=data_inicio,
                    data_inicio=data_inicio,
                    data_protocolo=data_envio,
                    evento_despacho=evento_origem,
                    evento_intimacao=(
                        request.POST.get('evento_intimacao') or ''
                    ).strip(),
                    ultimo_dia=resultado.ultimo_dia,
                    data_decurso=resultado.data_decurso,
                    prazo_info=prazo_info,
                    servidor=servidor,
                    servidor_cargo=servidor_cargo,
                )
            except Exception:
                pass
        except Exception as exc:
            messages.error(request, f'Erro ao gerar a certidão: {exc}')
            return HttpResponseRedirect(reverse(self.url_voltar))

        # Polo do recorrente e polo a ser intimado:
        # - preparo integral e gratuidade: intima-se a parte contrária
        #   (recorrido) para contrarrazões;
        # - intempestivo: intima-se o próprio recorrente para ciência.
        polo_recorrente = ''
        if eh_recurso and recorrente:
            from processes.models import Party
            parte = (
                Party.objects
                .filter(process=proc, name__icontains=recorrente[:40])
                .first()
            )
            if parte and parte.is_author_side:
                polo_recorrente = 'autores'
            elif parte and parte.is_defendant_side:
                polo_recorrente = 'res'

        if situacao_recurso in ('preparo', 'gratuidade'):
            polo_sugerido = (
                'res' if polo_recorrente == 'autores' else 'autores'
            )
        else:
            polo_sugerido = polo_recorrente or 'autores'

        evento_recurso_numero = _evento_recurso_certidao(html)

        eh_embargos = tipo == 'impugnacao_embargos_execucao'
        situacao_embargos = ''
        if eh_embargos:
            situacao_embargos = (
                'tempestivo'
                if data_envio and data_envio <= resultado.ultimo_dia
                else 'intempestivo'
            )

        return render(request, 'projudi/certidao_peticao_preview.html', {
            'documento': doc,
            'html_content': html,
            'item': {
                'processo': processo,
                'processo_url': processo_url,
                'origem': self.origem,
                'origem_label': self.rotulo_origem,
                'url_voltar': self.url_voltar,
                'tipo': tipo,
                'eh_recurso': eh_recurso,
                'eh_embargos': eh_embargos,
                'situacao_recurso': situacao_recurso,
                'situacao_embargos': situacao_embargos,
                'evento_impugnacao': evento_impugnacao,
                'pode_intimar': (
                    (eh_recurso and situacao_recurso in (
                        'preparo', 'intempestivo', 'gratuidade',
                    ))
                    or (eh_embargos and situacao_embargos == 'tempestivo')
                ),
                'polo_recorrente': polo_recorrente,
                'tipo_label': info['label'],
                'situacao_label': situacao_label,
                'recorrente': recorrente,
                'evento_recurso': evento_recurso,
                'evento_recurso_numero': evento_recurso_numero,
                'evento_intimacao': evento_intimacao,
                'origem_intimacao': origem_intimacao,
                'origem_intimacao_label': (
                    'Embargos de declaração'
                    if origem_intimacao == 'embargos'
                    else 'Sentença'
                ) if eh_recurso else '',
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


class CertidaoMovimentacaoGerarView(CertidaoPeticaoGerarView):
    """Gera certidão a partir da fila de movimentações do Projudi.

    Reaproveita o fluxo das petições, mas registra a origem como
    movimentação e volta para a fila de movimentações.
    """

    origem = 'movimentacao'
    url_voltar = 'projudi:movimentacoes'
    rotulo_origem = 'Movimentação'


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
        eh_embargos = rotulo == 'Certidão de Impugnação/Embargos à Execução'
        origem = (
            'movimentacao'
            if (doc.recipient_name or '').startswith('Movimentação:')
            else 'peticao'
        )
        situacao = (
            _situacao_certidao_recurso(doc.html_content)
            if eh_recurso else ''
        )
        situacao_embargos = ''
        evento_impugnacao = ''
        if eh_embargos:
            from .models import CertidaoRegistro
            registro = (
                CertidaoRegistro.objects
                .filter(generated_document=doc)
                .order_by('-created_at')
                .first()
            )
            if registro:
                info = registro.prazo_info or {}
                situacao_embargos = info.get('situacao_embargos') or ''
                evento_impugnacao = str(
                    info.get('evento_impugnacao') or ''
                )
            if not situacao_embargos:
                texto = (doc.html_content or '').upper()
                if 'INTEMPESTIVIDADE' in texto:
                    situacao_embargos = 'intempestivo'
                elif 'TEMPESTIVIDADE' in texto:
                    situacao_embargos = 'tempestivo'
            if not evento_impugnacao:
                m_evento = re.search(
                    r'apresentada\s*\(evento\s+(\d+)\)',
                    doc.html_content or '', re.I,
                )
                if m_evento:
                    evento_impugnacao = m_evento.group(1)
        context.update({
            'documento': doc,
            'html_content': doc.html_content,
            'item': {
                'processo': doc.process.number if doc.process else '',
                'processo_url': (
                    doc.process.projudi_url if doc.process else ''
                ),
                'origem': origem,
                'origem_label': (
                    'Movimentação' if origem == 'movimentacao' else 'Petição'
                ),
                'url_voltar': (
                    'projudi:movimentacoes' if origem == 'movimentacao'
                    else 'projudi:certidao_peticoes'
                ),
                'tipo': '',
                'eh_recurso': eh_recurso,
                'eh_embargos': eh_embargos,
                'situacao_recurso': situacao,
                'situacao_embargos': situacao_embargos,
                'evento_impugnacao': evento_impugnacao,
                'pode_intimar': (
                    (eh_recurso and situacao in (
                        'preparo', 'intempestivo', 'gratuidade',
                    ))
                    or (eh_embargos and situacao_embargos == 'tempestivo')
                ),
                'polo_recorrente': '',
                'tipo_label': rotulo,
                'situacao_label': (
                    'Embargos tempestivos'
                    if eh_embargos and situacao_embargos == 'tempestivo'
                    else 'Embargos intempestivos'
                    if eh_embargos else ''
                ),
                'recorrente': '',
                'evento_recurso': '',
                'evento_recurso_numero': (
                    _evento_recurso_certidao(doc.html_content)
                    if eh_recurso else ''
                ),
                'evento_intimacao': '',
                'origem_intimacao': '',
                'origem_intimacao_label': '',
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
    é feita a intimação conforme a situação da certidão: parte contrária
    (contrarrazões) ou recorrente (ciência da intempestividade).

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
        eh_embargos = (
            rotulo_certidao == 'Certidão de Impugnação/Embargos à Execução'
        )
        acao = (request.POST.get('acao') or 'juntar_intimar').strip().lower()
        if acao not in ('juntar', 'intimar', 'juntar_intimar'):
            messages.error(request, 'Ação inválida.')
            return self._preview_redirect(doc)
        if acao in ('intimar', 'juntar_intimar') and not (
                eh_recurso or eh_embargos):
            messages.error(
                request,
                'A intimação só se aplica às certidões de recurso '
                'inominado e de impugnação/embargos à execução.'
            )
            return self._preview_redirect(doc)

        # Situação da certidão define a intimação:
        # - preparo ou gratuidade: parte contrária (recorrido), para
        #   contrarrazões em 10 dias;
        # - intempestivo: recorrente, para ciência da intempestividade;
        # - embargos tempestivos: embargado/exequente, 15 dias.
        situacao_recurso = (
            _situacao_certidao_recurso(doc.html_content)
            if eh_recurso else ''
        )
        situacao_embargos = ''
        evento_impugnacao = ''
        if eh_embargos:
            from .models import CertidaoRegistro
            registro = (
                CertidaoRegistro.objects
                .filter(generated_document=doc)
                .order_by('-created_at')
                .first()
            )
            if registro:
                info = registro.prazo_info or {}
                situacao_embargos = info.get('situacao_embargos') or ''
                evento_impugnacao = str(
                    info.get('evento_impugnacao') or ''
                )
            if not situacao_embargos:
                texto = (doc.html_content or '').upper()
                if 'INTEMPESTIVIDADE' in texto:
                    situacao_embargos = 'intempestivo'
                elif 'TEMPESTIVIDADE' in texto:
                    situacao_embargos = 'tempestivo'
            if not evento_impugnacao:
                m_evento = re.search(
                    r'apresentada\s*\(evento\s+(\d+)\)',
                    doc.html_content or '', re.I,
                )
                if m_evento:
                    evento_impugnacao = m_evento.group(1)

        if (acao in ('intimar', 'juntar_intimar')
                and eh_recurso
                and situacao_recurso not in (
                    'preparo', 'intempestivo', 'gratuidade',
                )):
            messages.warning(
                request,
                'Não foi possível identificar a situação da certidão '
                '(tempestivo e preparado, intempestivo ou sem preparo). '
                'É possível apenas juntar a certidão.'
            )
            return self._preview_redirect(doc)
        if (acao in ('intimar', 'juntar_intimar')
                and eh_embargos
                and situacao_embargos != 'tempestivo'):
            messages.warning(
                request,
                'A intimação do embargado só é feita quando os embargos '
                'são TEMPESTIVOS. Use “Apenas juntar certidão”.'
            )
            return self._preview_redirect(doc)

        polo = (request.POST.get('polo_intimacao') or 'autores').strip().lower()
        if polo not in ('autores', 'res', 'todos'):
            polo = 'autores'
        if eh_embargos:
            # O embargado é o exequente/credor (polo ativo).
            polo = 'autores'

        observacao = (
            request.POST.get('observacao_juntada') or ''
        ).strip()
        recorrente = (request.POST.get('recorrente') or '').strip()
        processo = doc.process.number
        url_processo = (
            doc.process.projudi_url
            or (request.POST.get('processo_url') or '').strip()
        )
        if url_processo and not doc.process.projudi_url:
            doc.process.projudi_url = url_processo
            doc.process.save(update_fields=['projudi_url'])

        # Número interno do Projudi (14 dígitos) — obrigatório para a
        # intimação no MovimentarProcesso. Vem da URL DadosProcesso.
        proc_projudi = ''
        m_proc = re.search(r'numeroProcesso=(\d+)', url_processo)
        if m_proc:
            proc_projudi = m_proc.group(1)

        logger = logging.getLogger('projudi.certidoes')
        service = MovimentacaoService(request.user)

        # A certidão da fila de petições nasce com recipient_name
        # "Petição: ...". A certidão específica de custas nasce como
        # "Certidão: ..." e pertence às movimentações.
        origem_certidao = (
            'peticao'
            if (rotulo_certidao != NOME_CERTIDAO_CUSTAS
                and (doc.recipient_name or '').startswith('Petição:'))
            else 'movimentacao'
        )

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
                    origem=origem_certidao,
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
                    try:
                        from .certidao_registro_service import (
                            sincronizar_documento,
                        )
                        sincronizar_documento(doc, status='juntada')
                    except Exception:
                        pass
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
                motivo = ''
                try:
                    ultimo_erro = (
                        record.logs.filter(tipo='erro')
                        .order_by('-created_at').first()
                    )
                    if ultimo_erro and ultimo_erro.mensagem:
                        motivo = f' Motivo: {ultimo_erro.mensagem}'
                except Exception:
                    pass
                messages.error(
                    request,
                    'A certidão não foi juntada.'
                    f'{motivo} A intimação não foi realizada.'
                )
                return self._preview_redirect(doc)

        if acao == 'intimar' and not certidao_juntada:
            messages.error(
                request,
                'Junte a certidão antes de realizar a intimação.'
            )
            return self._preview_redirect(doc)

        # ── 2. Intimação conforme a situação da certidão ────────────
        if acao in ('intimar', 'juntar_intimar'):
            if not proc_projudi:
                messages.error(
                    request,
                    'A URL interna do processo no Projudi não está '
                    'cadastrada. Gere a certidão novamente pela fila para '
                    'atualizar o cadastro antes de intimar.'
                )
                return self._preview_redirect(doc)

            evento_recurso = (
                evento_impugnacao if eh_embargos
                else _evento_recurso_certidao(doc.html_content)
            )
            texto_evento = (
                f' (evento {evento_recurso})' if evento_recurso else ''
            )

            if eh_embargos:
                observacao_intimacao = (
                    'Intime-se o(a) embargado(a) para, querendo, no prazo '
                    'de 15 (quinze) dias úteis, apresentar '
                    'impugnação/manifestação/contrarrazões aos embargos à '
                    f'execução{texto_evento}, conforme certidão em anexo.'
                )
                prazo_dias = '15'
                prazo_codigo = '4'
                rotulo_intimacao = (
                    'embargado(a) para manifestação em 15 dias úteis'
                )
            elif situacao_recurso in ('preparo', 'gratuidade'):
                observacao_intimacao = (
                    'Intime(m)-se o(s) recorrido(s) para que, querendo, '
                    'apresente(m) contrarrazões ao Recurso Inominado'
                    f'{texto_evento}, no prazo de 10 dias úteis.'
                )
                prazo_dias = '10'
                prazo_codigo = '3'
                rotulo_intimacao = (
                    'parte contrária (recorrido) para contrarrazões'
                )
            else:
                observacao_intimacao = (
                    'Intime-se o recorrente para ciência da '
                    'INTEMPESTIVIDADE do recurso interposto/apresentado, '
                    'conforme certidão em anexo.'
                )
                prazo_dias = (
                    (request.POST.get('prazo_intimacao') or '5').strip()
                )
                prazo_codigo = {
                    '5': '2', '10': '3', '15': '4',
                }.get(prazo_dias, '2')
                rotulo_intimacao = (
                    'recorrente para ciência da intempestividade'
                )

            try:
                ok_intimacao = service.executar_com_intimacao(
                    processo_numero=processo,
                    observacao=observacao_intimacao,
                    codigo_mov='581',
                    descricao_mov='Intimação',
                    proc_projudi=proc_projudi,
                    prazo_intimacao=prazo_codigo,
                    motivo_intimacao='3',
                    polo_intimacao=polo,
                    fallback_polo=polo,
                    natureza_override='civel',
                    tipo_intimacao='geral',
                )
            except Exception as exc:
                logger.exception(
                    'Erro ao intimar | situação=%s | processo=%s | '
                    'documento=%s', situacao_recurso, processo, doc.id,
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
                'Intimação realizada | situação=%s | processo=%s | '
                'documento=%s | polo=%s | prazo=%s dias úteis | %s',
                situacao_recurso, processo, doc.id, polo, prazo_dias,
                rotulo_intimacao,
            )

        if acao == 'juntar':
            messages.success(
                request,
                f'✅ {rotulo_certidao} juntada ao processo.'
            )
            return self._preview_redirect(doc)

        if eh_embargos:
            mensagem = (
                '✅ Certidão juntada e embargado(a) intimado(a) para '
                'manifestação sobre os embargos em 15 dias úteis.'
            )
        elif situacao_recurso in ('preparo', 'gratuidade'):
            mensagem = (
                '✅ Certidão juntada e parte contrária intimada para '
                'apresentar contrarrazões em 10 dias úteis.'
            )
        else:
            mensagem = (
                '✅ Certidão juntada e recorrente intimado para ciência '
                'da INTEMPESTIVIDADE do recurso.'
            )
        messages.success(request, mensagem)
        return HttpResponseRedirect(reverse('projudi:certidao_peticoes'))


class CertidaoMovimentacaoCustasView(LoginRequiredMixin, View):
    """Gera a Certidão de Inexistência de Custas da Execução.

    Pensada para o fluxo de movimentações: o usuário informa o processo,
    a parte (opcional), a movimentação (opcional) e a URL do Projudi para
    que a certidão possa ser juntada sem depender da busca por CNJ.
    """

    template_name = 'projudi/certidao_movimentacao_custas.html'
    nome_template = NOME_CERTIDAO_CUSTAS

    def _contexto(self, **extra):
        context = {
            'assinante_padrao': ASSINANTE_PADRAO,
            'assinantes': [
                {'chave': chave, 'nome': dados[0], 'cargo': dados[1]}
                for chave, dados in ASSINANTES.items()
            ],
        }
        context.update(extra)
        return context

    def get(self, request):
        return render(request, self.template_name, self._contexto(
            processo=(request.GET.get('processo') or '').strip(),
            parte=(request.GET.get('parte') or '').strip(),
            descricao_movimentacao=(
                request.GET.get('descricao_movimentacao') or ''
            ).strip(),
            processo_url=(request.GET.get('processo_url') or '').strip(),
        ))

    def post(self, request):
        from django.template import Context, Template
        from base.utils import normalize_process_number
        from processes.models import (
            DocumentTemplate, GeneratedDocument, Process,
        )

        processo = (request.POST.get('processo') or '').strip()
        parte = (request.POST.get('parte') or '').strip()
        descricao_movimentacao = (
            request.POST.get('descricao_movimentacao') or ''
        ).strip()
        processo_url = (request.POST.get('processo_url') or '').strip()

        if not processo:
            messages.error(request, 'Informe o número do processo.')
            return HttpResponseRedirect(
                reverse('projudi:certidao_movimentacao_custas')
            )

        assinante = (
            request.POST.get('assinante') or ASSINANTE_PADRAO
        ).strip()
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
            template = DocumentTemplate.objects.get(
                name=self.nome_template, active=True
            )
            proc = Process.objects.filter(number=processo).first()
            if not proc:
                proc = Process.objects.create(
                    number=processo,
                    number_normalized=normalize_process_number(processo),
                    tenant=request.user.tenant,
                    status='analyzing',
                    projudi_url=processo_url,
                )
            elif processo_url and not proc.projudi_url:
                proc.projudi_url = processo_url
                proc.save(update_fields=['projudi_url'])
            elif not processo_url and proc.projudi_url:
                processo_url = proc.projudi_url

            ctx = {
                'processo': processo,
                'parte': parte,
                'descricao_movimentacao': descricao_movimentacao,
                'data': date.today().strftime('%d/%m/%Y'),
                'servidor': servidor,
                'servidor_cargo': servidor_cargo,
            }
            html = Template(template.html_template).render(Context(ctx))

            seq = GeneratedDocument.proximo_numero(template)
            doc = GeneratedDocument.objects.create(
                tenant=request.user.tenant,
                process=proc,
                template=template,
                sequential_number=seq,
                year=date.today().year,
                recipient_name='Certidão: Inexistência de Custas da Execução',
                html_content=html,
            )
            try:
                from .certidao_registro_service import registrar_documento
                registrar_documento(
                    request.user, doc,
                    tipo_prazo='custas_execucao',
                    origem='movimentacao',
                    parte=(parte if 'parte' in locals() else ''),
                    status='gerada',
                    servidor=servidor,
                    servidor_cargo=servidor_cargo,
                )
            except Exception:
                pass
        except Exception as exc:
            messages.error(request, f'Erro ao gerar a certidão: {exc}')
            return HttpResponseRedirect(
                reverse('projudi:certidao_movimentacao_custas')
            )

        return render(request, 'projudi/certidao_peticao_preview.html', {
            'documento': doc,
            'html_content': html,
            'item': {
                'processo': processo,
                'processo_url': processo_url,
                'tipo': 'custas_execucao',
                'eh_recurso': False,
                'pode_intimar': False,
                'tipo_label': 'Inexistência de Custas da Execução',
                'situacao_recurso': '',
                'situacao_label': '',
                'recorrente': '',
                'evento_recurso': '',
                'evento_recurso_numero': '',
                'evento_intimacao': '',
                'origem_intimacao': '',
                'origem_intimacao_label': '',
                'observacao_juntada': '',
                'polo_sugerido': 'autores',
                'polo_recorrente': '',
                'dias': '',
                'data_envio': None,
                'data_inicio': None,
                'meio_label': '',
                'ultimo_dia': None,
                'data_decurso': None,
            },
        })


class CertidaoAcoesView(LoginRequiredMixin, View):
    """Ações adicionais para um documento gerado: juntar + localizador,
    conclusão ou contadoria."""

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
        user_tenant_id = getattr(request.user, 'tenant_id', None)
        if doc.tenant_id and user_tenant_id and doc.tenant_id != user_tenant_id:
            messages.error(request, 'Certidão não pertence ao seu órgão.')
            return self._preview_redirect(doc)
        if not doc.process:
            messages.error(request, 'A certidão não está vinculada a um processo.')
            return self._preview_redirect(doc)
        if not (doc.html_content or '').strip():
            messages.error(request, 'A certidão não possui conteúdo.')
            return self._preview_redirect(doc)

        acao = (request.POST.get('acao') or 'so_gerar').strip().lower()
        if acao not in (
            'so_gerar', 'juntar', 'juntar_localizador',
            'juntar_conclusao', 'juntar_contadoria',
        ):
            messages.error(request, 'Ação inválida.')
            return self._preview_redirect(doc)

        if acao == 'so_gerar':
            messages.info(
                request,
                'Certidão mantida apenas no sistema, sem juntada no Projudi.',
            )
            return self._preview_redirect(doc)

        rotulo = doc.template.name if doc.template else 'Certidão'
        origem = (
            'peticao'
            if (doc.recipient_name or '').startswith('Petição:')
            else 'movimentacao'
        )
        processo = doc.process.number
        url_processo = doc.process.projudi_url
        if not url_processo:
            messages.error(
                request,
                'A URL do processo no Projudi não está cadastrada.',
            )
            return self._preview_redirect(doc)

        tipo_localizador = (
            request.POST.get('tipo_localizador') or '').strip()
        localizador = (request.POST.get('localizador') or '').strip()
        tipo_conclusao = (
            request.POST.get('tipo_conclusao') or '18').strip()
        juiz_conclusao = (
            request.POST.get('juiz_conclusao') or '41201').strip()

        if acao == 'juntar_localizador' and not (
                tipo_localizador or localizador):
            messages.warning(
                request,
                'Informe o tipo/código do localizador para juntar com localizador.',
            )
            return self._preview_redirect(doc)

        service = MovimentacaoService(request.user)
        try:
            record = service.importar(
                processo_numero=processo,
                act_verb='certifique-se',
                observacao=f'Juntada da {rotulo}.',
                categoria='certidao',
                origem=origem,
                processo_cnj=processo,
                parte_nome=(
                    request.POST.get('parte_nome') or ''),
                url_processo=url_processo,
                codigo_movimentacao='581',
                descricao_movimentacao=rotulo,
                tipo_localizador=tipo_localizador,
                localizador=localizador,
            )
            juntou = service.executar_requests(
                record,
                certidao_html=doc.html_content,
                certidao_titulo=rotulo,
            )
            if not juntou:
                messages.error(
                    request,
                    'A juntada não foi confirmada. Confira os logs da '
                    f'movimentação #{record.id}.',
                )
                return self._preview_redirect(doc)

            doc.exported_to_projudi = True
            doc.save(update_fields=['exported_to_projudi'])
            try:
                from .certidao_registro_service import sincronizar_documento
                sincronizar_documento(
                    doc,
                    status=(
                        'concluida' if acao == 'juntar_conclusao'
                        else 'juntada'
                    ),
                    tipo_localizador=tipo_localizador,
                    localizador=localizador,
                    tipo_conclusao=tipo_conclusao,
                    juiz_conclusao=juiz_conclusao,
                )
            except Exception:
                pass

            if acao == 'juntar_localizador':
                messages.success(
                    request,
                    'Certidão juntada com localizador no Projudi '
                    f'(movimentação #{record.id}).',
                )
            elif acao == 'juntar_conclusao':
                extra = service.importar(
                    processo_numero=processo,
                    act_verb='conclusao',
                    observacao='Conclusão',
                    categoria='outro',
                    origem='movimentacao',
                    processo_cnj=processo,
                    url_processo=url_processo,
                    codigo_movimentacao='11383',
                    descricao_movimentacao='Conclusão',
                )
                extra_ok = service.executar_requests(
                    extra,
                    conclusao=tipo_conclusao,
                    login_conclusao_pessoal=juiz_conclusao,
                )
                if extra_ok:
                    messages.success(
                        request,
                        'Certidão juntada e conclusão ao Juiz registrada '
                        f'(movimentação #{extra.id}).',
                    )
                else:
                    messages.warning(
                        request,
                        'Certidão juntada, mas a conclusão não foi '
                        f'confirmada (movimentação #{extra.id}).',
                    )
            elif acao == 'juntar_contadoria':
                extra = service.importar(
                    processo_numero=processo,
                    act_verb='contadoria',
                    observacao='Remessa à contadoria.',
                    categoria='outro',
                    origem='movimentacao',
                    processo_cnj=processo,
                    url_processo=url_processo,
                    codigo_movimentacao='11383',
                    descricao_movimentacao='Remessa à Contadoria',
                )
                extra_ok = service.executar_requests(
                    extra, enviar_contador=True,
                )
                if extra_ok:
                    messages.success(
                        request,
                        'Certidão juntada e autos remetidos à contadoria '
                        f'(movimentação #{extra.id}).',
                    )
                else:
                    messages.warning(
                        request,
                        'Certidão juntada, mas a remessa à contadoria não '
                        f'foi confirmada (movimentação #{extra.id}).',
                    )
            else:
                messages.success(
                    request,
                    f'Certidão juntada no Projudi (movimentação #{record.id}).',
                )
        except Exception as exc:
            messages.error(
                request, f'Erro ao executar a ação da certidão: {exc}')
        return self._preview_redirect(doc)


class CertidaoDecursoPagamentoView(LoginRequiredMixin, View):
    """Gera a certidão de decurso do prazo de pagamento voluntário."""

    template_name = 'projudi/certidao_decurso_pagamento.html'
    nome_template = 'Certidão de Decurso de Prazo para Pagamento Voluntário'
    MODELOS = {
        'voluntario': {
            'template': (
                'Certidão de Decurso de Prazo para Pagamento Voluntário'
            ),
            'tipo': 'decurso_pagamento',
            'label': 'Decurso de Prazo para Pagamento Voluntário',
        },
        'remanescente': {
            'template': (
                'Certidão de Decurso de Prazo para Pagamento de '
                'Débito Remanescente'
            ),
            'tipo': 'decurso_debito_remanescente',
            'label': 'Decurso de Prazo para Pagamento de Débito Remanescente',
        },
    }

    def _contexto(self, **extra):
        context = {
            'assinante_padrao': ASSINANTE_PADRAO,
            'modelo': 'voluntario',
            'modelos': self.MODELOS,
            'assinantes': [
                {'chave': chave, 'nome': dados[0], 'cargo': dados[1]}
                for chave, dados in ASSINANTES.items()
            ],
        }
        context.update(extra)
        return context

    def get(self, request):
        return render(request, self.template_name, self._contexto(
            processo=(request.GET.get('processo') or '').strip(),
            evento=(request.GET.get('evento') or '').strip(),
            executado=(request.GET.get('executado') or '').strip(),
            modelo=(request.GET.get('modelo') or 'voluntario').strip(),
            evento_requerimento=(
                request.GET.get('evento_requerimento') or '').strip(),
        ))

    def post(self, request):
        processo = (request.POST.get('processo') or '').strip()
        evento = (request.POST.get('evento') or '').strip()
        executado = (request.POST.get('executado') or '').strip()
        modelo = (request.POST.get('modelo') or 'voluntario').strip()
        evento_requerimento = (
            request.POST.get('evento_requerimento') or '').strip()
        return self.processar(
            request, processo, evento, executado, evento_requerimento,
            modelo)

    def processar(self, request, processo, evento='', executado='',
                  evento_requerimento='', modelo='voluntario'):
        from django.template import Context, Template
        from base.utils import normalize_process_number
        from processes.models import (
            DocumentTemplate, GeneratedDocument, Process,
        )
        from .decurso_pagamento_service import DecursoPagamentoService

        info_modelo = self.MODELOS.get(modelo) or self.MODELOS['voluntario']
        modelo = next(
            (chave for chave, valor in self.MODELOS.items()
             if valor['template'] == info_modelo['template']),
            'voluntario',
        )

        if not processo:
            messages.error(request, 'Informe o processo.')
            return HttpResponseRedirect(
                reverse('projudi:certidao_decurso_pagamento')
            )
        if evento and not evento.isdigit():
            messages.error(
                request,
                'Evento inválido. Informe apenas o número do evento do '
                'despacho ou deixe em branco para busca automática.'
            )
            return render(request, self.template_name, self._contexto(
                processo=processo, evento=evento, executado=executado,
                evento_requerimento=evento_requerimento,
                modelo=modelo,
            ))
        if evento_requerimento and not evento_requerimento.isdigit():
            messages.error(
                request,
                'Evento do requerimento inválido. Informe apenas o número '
                'do evento ou deixe em branco para busca automática.'
            )
            return render(request, self.template_name, self._contexto(
                processo=processo, evento=evento, executado=executado,
                evento_requerimento=evento_requerimento,
                modelo=modelo,
            ))

        assinante = (
            request.POST.get('assinante') or ASSINANTE_PADRAO
        ).strip()
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

        resultado = DecursoPagamentoService(request.user).analisar(
            processo, evento, parte_nome=executado,
            evento_requerimento=evento_requerimento,
        )
        if resultado.get('erro'):
            messages.error(request, resultado['erro'])
            return render(request, self.template_name, self._contexto(
                processo=processo, evento=evento, executado=executado,
                evento_requerimento=evento_requerimento,
                modelo=modelo,
            ))

        # Enquanto o prazo não decorrer, não há certidão de decurso.
        # Mostra uma prévia do texto e só executa depois da confirmação:
        # movimentação 581 (Intimação) + intimação eletrônica da parte
        # autora. Nunca usa AR, mandado ou precatória.
        if date.today() < resultado['data_decurso']:
            from .movimentacao_service import MovimentacaoService

            observacao_decurso = _texto_intimacao_decurso(resultado, modelo)
            canais_autora = resultado.get('parte_autora_canais') or []
            pode_intimar = bool(
                resultado.get('parte_autora_canal_eletronico')
            )
            confirmar = (request.POST.get('confirmar') or '').strip()

            if confirmar == 'intimar' and not pode_intimar:
                messages.warning(
                    request,
                    'A parte autora não possui advogado, e-mail ou DJEN. '
                    'A intimação eletrônica não será feita e nenhum AR, '
                    'mandado ou precatória será gerado.'
                )
                previa = {
                    'texto': observacao_decurso,
                    'parte_autora': (
                        resultado.get('parte_autora') or 'parte autora'
                    ),
                    'canais': ', '.join(canais_autora),
                    'pode_intimar': pode_intimar,
                }
                return render(request, self.template_name, self._contexto(
                    processo=processo, evento=evento, executado=executado,
                    evento_requerimento=evento_requerimento,
                    modelo=modelo, previa=previa,
                ))

            if confirmar in ('intimar', 'so_11383'):
                service = MovimentacaoService(request.user)
                record = service.importar(
                    processo_numero=resultado['processo'],
                    act_verb=(
                        'intimar' if confirmar == 'intimar'
                        else 'certifique-se'
                    ),
                    observacao=observacao_decurso,
                    categoria=(
                        'intimacao' if confirmar == 'intimar'
                        else 'registro'
                    ),
                    origem='movimentacao',
                    processo_cnj=resultado['processo'],
                    parte_nome=resultado.get('parte_autora') or '',
                    parte_papel=resultado.get('parte_autora_papel') or '',
                    url_processo=resultado['url'],
                    codigo_movimentacao=(
                        '581' if confirmar == 'intimar' else '11383'
                    ),
                    descricao_movimentacao=(
                        'Intimação' if confirmar == 'intimar'
                        else 'Cumprimento de Ofício'
                    ),
                )
                logger = logging.getLogger('projudi.certidoes')
                logger.info(
                    'Decurso de pagamento ainda não ocorrido | '
                    'processo=%s | confirmar=%s | %s',
                    resultado['processo'], confirmar, observacao_decurso,
                )
                if confirmar == 'so_11383':
                    messages.info(
                        request,
                        '📝 Movimentação 11383 criada somente com a '
                        f'observação. O texto está no registro #{record.id}; '
                        'execute pela Fila de Movimentações.'
                    )
                    return HttpResponseRedirect(reverse(
                        'projudi:movimentacao_detail',
                        args=[record.pk],
                    ))

                sucesso = service.executar_intimacao_record(record)
                if sucesso:
                    messages.success(
                        request,
                        '✅ Movimentação 581 (Intimação) e intimação '
                        'eletrônica da parte autora executadas. O decurso '
                        'está previsto para '
                        f'{resultado["data_decurso"].strftime("%d/%m/%Y")}.'
                    )
                else:
                    messages.error(
                        request,
                        '❌ A movimentação 581 + intimação não foi '
                        'confirmada. Confira o registro e os logs; nenhum '
                        'AR, mandado ou precatória foi gerado.'
                    )
                return HttpResponseRedirect(reverse(
                    'projudi:movimentacao_detail',
                    args=[record.pk],
                ))

            previa = {
                'texto': observacao_decurso,
                'parte_autora': (
                    resultado.get('parte_autora') or 'parte autora'
                ),
                'canais': ', '.join(canais_autora),
                'pode_intimar': pode_intimar,
            }
            return render(request, self.template_name, self._contexto(
                processo=processo, evento=evento, executado=executado,
                evento_requerimento=evento_requerimento, modelo=modelo,
                previa=previa,
            ))

        try:
            template = DocumentTemplate.objects.get(
                name=info_modelo['template'], active=True
            )
            proc = Process.objects.filter(
                number_normalized=normalize_process_number(
                    resultado['processo']
                )
            ).first()
            if not proc:
                proc = Process.objects.filter(
                    number=resultado['processo']
                ).first()
            if not proc:
                proc = Process.objects.create(
                    number=resultado['processo'],
                    number_normalized=normalize_process_number(
                        resultado['processo']
                    ),
                    tenant=request.user.tenant,
                    status='analyzing',
                    projudi_url=resultado['url'],
                )
            elif not proc.projudi_url:
                proc.projudi_url = resultado['url']
                proc.save(update_fields=['projudi_url'])

            ctx = {
                'processo': resultado['processo'],
                'executado': resultado['executado'],
                'evento_despacho': resultado['evento_despacho'],
                'evento_intimacao': resultado['evento_intimacao'],
                'data_despacho': (
                    resultado['data_despacho'].strftime('%d/%m/%Y')
                    if resultado.get('data_despacho') else ''
                ),
                'meio_label': resultado.get('meio_label') or '',
                'evento_requerimento': (
                    resultado.get('evento_requerimento') or ''),
                'data_requerimento': (
                    resultado['data_requerimento'].strftime('%d/%m/%Y')
                    if resultado.get('data_requerimento') else ''
                ),
                'data_intimacao': resultado['data_intimacao'].strftime(
                    '%d/%m/%Y'
                ),
                'data_publicacao': resultado['data_intimacao'].strftime(
                    '%d/%m/%Y'
                ),
                'data_inicio_contagem': resultado['data_inicio'].strftime(
                    '%d/%m/%Y'
                ),
                'ultimo_dia': resultado['ultimo_dia'].strftime('%d/%m/%Y'),
                'data_decurso': resultado['data_decurso'].strftime(
                    '%d/%m/%Y'
                ),
                'data': date.today().strftime('%d/%m/%Y'),
                'servidor': servidor,
                'servidor_cargo': servidor_cargo,
            }
            html = Template(template.html_template).render(Context(ctx))
            seq = GeneratedDocument.proximo_numero(template)
            doc = GeneratedDocument.objects.create(
                tenant=request.user.tenant,
                process=proc,
                template=template,
                sequential_number=seq,
                year=date.today().year,
                recipient_name=(
                    f'Certidão: {info_modelo["label"]}'
                ),
                html_content=html,
            )
            try:
                from .certidao_registro_service import registrar_decurso
                registrar_decurso(
                    request.user, resultado, doc,
                    servidor=servidor, servidor_cargo=servidor_cargo,
                    tipo_prazo=info_modelo['tipo'],
                )
            except Exception:
                pass
        except Exception as exc:
            messages.error(request, f'Erro ao gerar a certidão: {exc}')
            return HttpResponseRedirect(
                reverse('projudi:certidao_decurso_pagamento')
            )

        observacao = (
            f'Certidão — {info_modelo["label"]} — '
            f'despacho evento {resultado["evento_despacho"]}'
            f'{origem_despacho}; '
            f'evento da intimação: {resultado["evento_intimacao"]}; '
            f'intimação em {ctx["data_intimacao"]}; '
            f'último dia {ctx["ultimo_dia"]}; '
            f'decurso {ctx["data_decurso"]}; '
            f'executado: {resultado["executado"]}.'
        )
        logging.getLogger('projudi.certidoes').info(
            'Certidão de decurso de pagamento gerada | processo=%s | %s',
            resultado['processo'], observacao,
        )

        return render(request, 'projudi/certidao_peticao_preview.html', {
            'documento': doc,
            'html_content': html,
            'item': {
                'processo': resultado['processo'],
                'processo_url': resultado['url'],
                'tipo': info_modelo['tipo'],
                'eh_recurso': False,
                'pode_intimar': False,
                'tipo_label': info_modelo['label'],
                'situacao_recurso': '',
                'situacao_label': '',
                'recorrente': '',
                'evento_recurso': '',
                'evento_recurso_numero': '',
                'evento_intimacao': resultado['evento_intimacao'],
                'origem_intimacao': 'despacho',
                'origem_intimacao_label': 'despacho',
                'observacao_juntada': observacao,
                'polo_sugerido': 'autores',
                'polo_recorrente': '',
                'dias': 15,
                'data_envio': None,
                'data_inicio': resultado['data_intimacao'],
                'meio_label': resultado['meio_label'],
                'ultimo_dia': resultado['ultimo_dia'],
                'data_decurso': resultado['data_decurso'],
            },
        })
