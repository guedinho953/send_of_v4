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
from projudi.intimacao_service import localizar_intimacao_do_processo
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
    origem = 'peticao'
    origem_label = 'Petições'
    url_voltar = 'projudi:certidao_peticoes_fila'
    url_lista = 'projudi:certidao_peticoes'

    def _voltar(self):
        return redirect(self.url_voltar)

    def post(self, request):
        processo = (request.POST.get('processo') or '').strip()
        tipo_prazo = (request.POST.get('tipo_prazo') or '').strip()
        acao = (request.POST.get('acao') or 'gerar').strip()
        preparo = (request.POST.get('preparo') or '').strip()
        data_envio = (request.POST.get('data_envio') or '').strip()
        data_intimacao = (request.POST.get('data_intimacao') or '').strip()
        evento_intimacao = (
            request.POST.get('evento_intimacao') or '').strip()
        evento_origem = (
            request.POST.get('evento_origem') or '').strip()
        evento_impugnacao = (
            request.POST.get('evento_impugnacao') or '').strip()
        seguranca_juizo = (
            request.POST.get('seguranca_juizo') or '').strip()
        parte = (request.POST.get('parte') or '').strip()
        processo_url = (request.POST.get('processo_url') or '').strip()
        peticao_url = (request.POST.get('peticao_url') or '').strip()
        peticao_documento = (
            request.POST.get('peticao_documento') or '').strip()
        evento_despacho = (
            request.POST.get('evento_despacho') or '').strip()
        executado = (request.POST.get('executado') or '').strip()
        data_intimacao_manual = (
            request.POST.get('data_intimacao_manual') or '').strip()
        evento_intimacao_manual = (
            request.POST.get('evento_intimacao_manual') or '').strip()
        assinante = (
            request.POST.get('assinante') or ASSINANTE_PADRAO).strip()
        assinante_nome = (
            request.POST.get('assinante_nome') or '').strip()
        assinante_cargo = (
            request.POST.get('assinante_cargo') or '').strip()
        tipo_localizador = (
            request.POST.get('tipo_localizador') or '').strip()
        localizador = (request.POST.get('localizador') or '').strip()
        tipo_conclusao = (
            request.POST.get('tipo_conclusao') or '18').strip()
        juiz_conclusao = (
            request.POST.get('juiz_conclusao') or '41201').strip()
        template_id = (request.POST.get('template_id') or '').strip()
        template_id = int(template_id) if template_id.isdigit() else None
        prazo_dias_txt = (request.POST.get('prazo_dias') or '').strip()
        prazo_dias = (
            int(prazo_dias_txt)
            if prazo_dias_txt.isdigit() and int(prazo_dias_txt) > 0
            else None)
        modo_saida = (
            request.POST.get('modo_saida') or 'certidao').strip()
        observacao_tempestiva = (
            request.POST.get('observacao_tempestiva') or '').strip()
        observacao_intempestiva = (
            request.POST.get('observacao_intempestiva') or '').strip()
        rag_id = (request.POST.get('rag_id') or '').strip()
        rag_id = int(rag_id) if rag_id.isdigit() else None
        acoes_fluxo = [
            nome for nome in (
                'juntar', 'intimar', 'localizador', 'contadoria',
                'conclusao', 'mp',
            )
            if request.POST.get(f'fluxo_{nome}') == 'on'
        ]

        voltar = self._voltar()

        if not processo:
            messages.error(request, 'Processo não informado.')
            return voltar
        if tipo_prazo not in TIPOS_VALIDOS:
            messages.error(request, 'Escolha a certidão que será gerada.')
            return voltar
        if (tipo_prazo == 'impugnacao_embargos_execucao'
                and modo_saida == 'certidao'
                and seguranca_juizo not in ('integral', 'parcial', 'nenhuma')):
            messages.error(
                request,
                'Para a Impugnação/Embargos à Execução, informe a '
                'segurança do juízo: integral, depósito parcial ou não houve.',
            )
            return voltar
        if (tipo_prazo == 'impugnacao_embargos_execucao'
                and evento_impugnacao and not evento_impugnacao.isdigit()):
            messages.error(
                request,
                'Evento da impugnação/embargos inválido. Informe apenas o '
                'número do evento ou deixe em branco.',
            )
            return voltar

        if acao != 'gerar':
            messages.info(
                request,
                'A ação escolhida ainda não está implementada nesta versão. '
                'Use "Gerar certidão" por enquanto.',
            )
            return voltar

        if modo_saida in ('observacao_11383', 'intimacao_581'):
            return self._gerar_observacao(
                request,
                processo=processo,
                processo_url=processo_url,
                tipo_prazo=tipo_prazo,
                evento=evento_despacho or evento_origem,
                evento_intimacao=evento_intimacao,
                data_protocolo_txt=data_envio,
                parte=parte,
                modo_saida=modo_saida,
                observacao_tempestiva=observacao_tempestiva,
                observacao_intempestiva=observacao_intempestiva,
                prazo_dias=prazo_dias,
                rag_id=rag_id,
            )

        if tipo_prazo == 'decurso_pagamento':
            return self._gerar_decurso(
                request,
                processo=processo,
                processo_url=processo_url,
                evento=evento_despacho or evento_origem,
                executado=executado,
                data_intimacao_manual=(
                    data_intimacao_manual or data_intimacao),
                evento_intimacao_manual=(
                    evento_intimacao_manual or evento_intimacao),
                assinante=assinante,
                assinante_nome=assinante_nome,
                assinante_cargo=assinante_cargo,
            )

        data_protocolo = self._data(data_envio)
        if (not data_protocolo
                and tipo_prazo == 'impugnacao_embargos_execucao'
                and evento_impugnacao and processo_url):
            try:
                from projudi.intimacao_service import data_evento_processo
                data_protocolo = data_evento_processo(
                    request.user, processo_url, evento_impugnacao)
            except Exception:
                data_protocolo = None
        tipos_sem_protocolo = (
            'decurso_pagamento', 'decurso_manifestacao_adjudicacao')
        if not data_protocolo and tipo_prazo not in tipos_sem_protocolo:
            messages.error(
                request,
                'Informe a data do protocolo ou o evento da petição '
                'para que o sistema busque a data.',
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
                data_intimacao_final = self._data(data_intimacao)
                evento_intimacao_final = evento_intimacao
                evento_busca = evento_intimacao or evento_origem

                if evento_busca and not evento_busca.isdigit():
                    messages.error(
                        request,
                        'Evento inválido. Informe apenas o número do '
                        'evento da decisão/recurso ou da intimação.',
                    )
                    return voltar

                if evento_busca:
                    intima = localizar_intimacao_do_processo(
                        request.user,
                        processo_url,
                        evento_busca,
                        parte=parte,
                    )
                    if intima:
                        data_intimacao_final = intima['data']
                        evento_intimacao_final = intima['evento']
                        if intima.get('meio') not in (
                                'eletronico', 'intimacao'):
                            messages.warning(
                                request,
                                'A intimação foi localizada por '
                                f'{intima.get("meio")}. A contagem DJEN '
                                'pode precisar de ajuste; confira a prévia.',
                            )
                    elif not data_intimacao_final:
                        messages.error(
                            request,
                            'Não localizei a intimação pelo evento '
                            f'{evento_busca}. Informe a data manualmente '
                            'no campo de fallback.',
                        )
                        return voltar
                    else:
                        messages.warning(
                            request,
                            'Não localizei a intimação pelo evento '
                            f'{evento_busca}; usando a data manual '
                            f'{data_intimacao}.',
                        )

                if not data_intimacao_final:
                    messages.error(
                        request,
                        'Informe o evento da decisão/recurso para localizar '
                        'a intimação automaticamente ou a data da intimação '
                        'no fallback.',
                    )
                    return voltar

                call_command(
                    'prazo_djen',
                    tipo=tipo_prazo,
                    disponibilizacao=data_intimacao_final.strftime(
                        '%d/%m/%Y'),
                    protocolo=(
                        data_protocolo.strftime('%d/%m/%Y')
                        if data_protocolo else None),
                    processo=processo,
                    processo_url=processo_url or None,
                    parte=parte,
                    origem=self.origem,
                    peticao_documento=peticao_documento,
                    peticao_url=peticao_url,
                    evento_recurso=(
                        evento_impugnacao
                        if tipo_prazo == 'impugnacao_embargos_execucao'
                        else evento_origem or 'infra'
                    ),
                    evento_origem=evento_origem or '',
                    evento_intimacao=evento_intimacao_final,
                    seguranca_juizo=seguranca_juizo or None,
                    tipo_localizador=tipo_localizador,
                    localizador=localizador,
                    tipo_conclusao=tipo_conclusao,
                    juiz_conclusao=juiz_conclusao,
                    template_id=template_id,
                    prazo=prazo_dias,
                )
        except CommandError as exc:
            messages.error(request, str(exc))
            return voltar
        except Exception as exc:
            messages.error(request, f'Erro ao gerar a certidão: {exc}')
            return voltar

        registro = (
            PrazoDjenRecord.objects
            .filter(processo=processo, origem=self.origem)
            .order_by('-created_at')
            .first()
        )
        if registro:
            registro.acoes_fluxo = acoes_fluxo
            registro.save(update_fields=['acoes_fluxo'])
            messages.success(
                request,
                f'Certidão gerada e registrada em '
                f'{self.origem_label} (#{registro.id}).',
            )
            if request.POST.get('proximo') == 'juntar':
                return redirect(
                    'projudi:certidao_juntar_intimar', pk=registro.id)
            return redirect('projudi:certidao_detail', pk=registro.id)

        messages.warning(
            request,
            'O comando foi executado, mas o registro não foi localizado. '
            f'Confira a aba {self.origem_label}.',
        )
        return redirect(self.url_lista)

    def _gerar_observacao(
            self, request, *, processo, processo_url, tipo_prazo, evento,
            evento_intimacao, data_protocolo_txt, parte, modo_saida,
            observacao_tempestiva, observacao_intempestiva, prazo_dias,
            rag_id):
        """Cria a prévia da observação/intimação, sem executar no Projudi.

        A execução fica pendente na Fila de Movimentações. Na 581, o botão
        "Intimar" da tela de detalhe faz a confirmação explícita.
        """
        from processes.models import RAGExample
        from projudi.movimentacao_service import MovimentacaoService

        voltar = self._voltar()
        if not (observacao_tempestiva or observacao_intempestiva):
            messages.error(
                request, 'Informe a observação tempestiva e/ou intempestiva.')
            return voltar

        texto = observacao_tempestiva or observacao_intempestiva
        tempestivo = None
        # Quando as duas versões existem, tenta usar o mesmo cálculo de
        # tempestividade da certidão de impugnação/embargos.
        if observacao_tempestiva and observacao_intempestiva:
            data_protocolo = self._data(data_protocolo_txt)
            if data_protocolo:
                try:
                    resultado = DecursoPagamentoService(
                        request.user).analisar(
                            processo,
                            evento=evento or None,
                            url=processo_url or None,
                            evento_intimacao=evento_intimacao or None,
                            dias=prazo_dias or 15,
                        )
                    if not resultado.get('erro'):
                        tempestivo = (
                            data_protocolo <= resultado['ultimo_dia'])
                        texto = (
                            observacao_tempestiva if tempestivo
                            else observacao_intempestiva)
                except Exception:
                    pass

        rag = (
            RAGExample.objects.filter(pk=rag_id).first()
            if rag_id else None
        )
        try:
            record = MovimentacaoService(request.user).importar(
                processo_numero=processo,
                act_verb=(
                    'certifique-se' if modo_saida == 'observacao_11383'
                    else 'intimar'),
                observacao=texto,
                categoria=(
                    'registro' if modo_saida == 'observacao_11383'
                    else 'intimacao'),
                origem='movimentacao',
                processo_cnj=processo,
                parte_nome=parte,
                rag_example=rag,
                url_processo=processo_url,
                codigo_movimentacao=(
                    '11383' if modo_saida == 'observacao_11383' else '581'),
                descricao_movimentacao=(
                    'Cumprimento de Ofício'
                    if modo_saida == 'observacao_11383' else 'Intimação'),
            )
        except Exception as exc:
            messages.error(
                request, f'Erro ao criar a observação: {exc}')
            return voltar

        if tempestivo is not None:
            situacao = 'TEMPESTIVO' if tempestivo else 'INTEMPESTIVO'
            messages.info(request, f'Texto escolhido: {situacao}.')
        if modo_saida == 'observacao_11383':
            messages.success(
                request,
                f'Observação criada na movimentação #{record.id} '
                '(código 11383). Confira e execute na Fila de Movimentações.',
            )
        else:
            messages.success(
                request,
                f'Prévia de intimação criada na movimentação #{record.id} '
                '(código 581). Confira e clique em "Intimar" para confirmar '
                'a comunicação à parte.',
            )
        return redirect('projudi:movimentacao_detail', pk=record.id)

    def _gerar_decurso(self, request, *, processo, processo_url, evento,
                       executado, data_intimacao_manual,
                       evento_intimacao_manual, assinante, assinante_nome,
                       assinante_cargo):
        voltar = self._voltar()
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
                data_intimacao=data_intimacao_manual or None,
                evento_intimacao=evento_intimacao_manual or None,
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


class CertidaoMovimentacaoFilaGerarView(CertidaoPeticaoFilaGerarView):
    """Gera certidão a partir da fila de movimentações do Projudi."""

    origem = 'movimentacao'
    origem_label = 'Movimentações'
    url_voltar = 'projudi:movimentacoes'
    url_lista = 'projudi:certidao_movimentacoes'
