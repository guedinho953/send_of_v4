"""Dashboard de certidões/prazos DJEN (controle interno)."""

import json
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, TemplateView

from .certidao_layout import (
    html_certidao_decurso, html_certidao_padrao,
)
from .models import PrazoDjenRecord
from .prazo_service import TIPOS_PRAZO


def _status_registro(reg):
    if reg.tipo_prazo == 'decurso_pagamento':
        return 'decurso', 'DECURSO'
    if reg.tempestivo is True:
        return 'tempestivo', 'TEMPESTIVO'
    if reg.tempestivo is False:
        return 'intempestivo', 'INTEMPESTIVO'
    return 'sem_protocolo', 'SEM PROTOCOLO'


def _datas_br(valores):
    resultado = []
    for valor in valores or []:
        try:
            resultado.append(
                datetime.strptime(str(valor)[:10], '%Y-%m-%d')
                .strftime('%d/%m/%Y'))
        except ValueError:
            resultado.append(str(valor))
    return resultado


class CertidaoDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'projudi/certidao_dashboard.html'
    origem = ''
    url_name = 'projudi:certidao_dashboard'

    def get_origem(self):
        return self.origem or (self.request.GET.get('origem') or '')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        todos = PrazoDjenRecord.objects.all()
        origem = self.get_origem()
        base = todos
        if origem in ('peticao', 'movimentacao'):
            base = base.filter(origem=origem)

        busca = (self.request.GET.get('q') or '').strip()
        status = (self.request.GET.get('status') or '').strip()
        tipo = (self.request.GET.get('tipo') or '').strip()

        qs = base
        if busca:
            qs = qs.filter(
                Q(processo__icontains=busca)
                | Q(parte__icontains=busca)
                | Q(peticao_documento__icontains=busca)
                | Q(motivo__icontains=busca)
            )
        if status == 'tempestivo':
            qs = qs.filter(tempestivo=True)
        elif status == 'intempestivo':
            qs = qs.filter(tempestivo=False)
        elif status == 'sem_protocolo':
            qs = qs.filter(tempestivo__isnull=True)
        if tipo:
            qs = qs.filter(tipo_prazo=tipo)

        registros = list(qs.order_by('-created_at')[:200])
        for reg in registros:
            reg.status_classe, reg.status_label = _status_registro(reg)
            reg.tipo_label = TIPOS_PRAZO.get(
                reg.tipo_prazo, {}).get('label', reg.tipo_prazo)

        context.update({
            'registros': registros,
            'total': base.count(),
            'tempestivas': base.filter(tempestivo=True).count(),
            'intempestivas': base.filter(tempestivo=False).count(),
            'sem_protocolo': (
                base.filter(tempestivo__isnull=True)
                .exclude(tipo_prazo='decurso_pagamento').count()
            ),
            'decurso': base.filter(
                tipo_prazo='decurso_pagamento').count(),
            'total_geral': todos.count(),
            'total_peticoes': todos.filter(origem='peticao').count(),
            'total_movimentacoes': todos.filter(
                origem='movimentacao').count(),
            'origem_filtro': origem,
            'origem_label': {
                'peticao': 'Certidões de petições',
                'movimentacao': 'Certidões de movimentações',
            }.get(origem, 'Todas as certidões'),
            'mostrar_origem': not origem,
            'url_name': self.url_name,
            'busca': busca,
            'filtro_status': status,
            'filtro_tipo': tipo,
            'tipos': [
                {'valor': chave, **info}
                for chave, info in TIPOS_PRAZO.items()
            ],
        })
        return context


class CertidaoPeticaoView(CertidaoDashboardView):
    origem = 'peticao'
    url_name = 'projudi:certidao_peticoes'


class CertidaoMovimentacaoView(CertidaoDashboardView):
    origem = 'movimentacao'
    url_name = 'projudi:certidao_movimentacoes'


class CertidaoSugestaoMovimentacaoView(LoginRequiredMixin, View):
    """Sugere a certidão de uma movimentação a partir do match RAG."""

    def get(self, request):
        from projudi.certidao_sugestao import sugerir_certidao

        processo = (request.GET.get('processo') or '').strip()
        documento = (request.GET.get('documento') or '').strip()
        processo_url = (request.GET.get('url') or '').strip()
        if not processo:
            return JsonResponse(
                {'erro': 'Processo não informado.'}, status=400)
        return JsonResponse(sugerir_certidao(
            request.user, processo, documento, processo_url))


class CriarRagMovimentacaoView(LoginRequiredMixin, View):
    """Cria uma RAG a partir do documento/texto de uma movimentação."""

    def post(self, request):
        from base.utils import normalize_process_number
        from processes.models import DocumentTemplate, Process, RAGExample
        from projudi.certidao_sugestao import (
            _texto_documento, _tipo_por_texto, limpar_texto_despacho,
        )
        from projudi.services import ProjudiService

        processo = (request.POST.get('processo') or '').strip()
        tipo = (request.POST.get('tipo') or '').strip()
        data = (request.POST.get('data') or '').strip()
        link_processo = (request.POST.get('link_processo') or '').strip()
        link_documento = (request.POST.get('link_documento') or '').strip()
        texto_movimentacao = (
            request.POST.get('texto_movimentacao') or '').strip()
        forcar = request.POST.get('forcar') == '1'

        voltar = HttpResponseRedirect(reverse('projudi:movimentacoes'))
        if not processo:
            messages.error(
                request, 'Movimentação sem processo para gerar a RAG.')
            return voltar

        resultado = ProjudiService(request.user)._get_session_from_cookies()
        if not resultado:
            messages.error(request, 'Sessão do Projudi não disponível.')
            return voltar
        session, _ = resultado

        texto = (
            _texto_documento(session, link_documento)
            if link_documento else '')
        texto = limpar_texto_despacho(texto)
        usou_texto_movimentacao = False
        if len(texto.strip()) < 30 and texto_movimentacao:
            texto = limpar_texto_despacho(texto_movimentacao)
            usou_texto_movimentacao = True
        if not texto.strip():
            messages.error(
                request,
                'Não há documento nem texto da movimentação para gerar a RAG.',
            )
            return voltar

        numero = normalize_process_number(processo)
        proc = Process.objects.filter(number_normalized=numero).first()

        # O tenant é obrigatório em Process. Usuários antigos podem não ter
        # tenant vinculado; nesse caso reaproveita o tenant do processo ou,
        # por último, o tenant padrão do sistema.
        tenant = getattr(request.user, 'tenant', None)
        if tenant is None and proc is not None:
            tenant = proc.tenant
        if tenant is None:
            from accounts.models import Tenant
            tenant = Tenant.objects.first()
        if tenant is None:
            messages.error(
                request,
                'Nenhum tenant cadastrado para criar a RAG.',
            )
            return voltar

        if not proc:
            proc = Process.objects.create(
                number=processo,
                number_normalized=numero,
                tenant=tenant,
                status='analyzing',
                projudi_url=link_processo,
            )

        existente = None
        if not forcar:
            existente = RAGExample.objects.filter(
                process=proc,
                despacho_observacao=texto,
            ).first()
        if existente:
            messages.info(
                request,
                f'Essa movimentação já tem uma RAG cadastrada '
                f'(#{existente.id}).',
            )
            if request.user.is_staff:
                return HttpResponseRedirect(reverse(
                    'admin:processes_ragexample_change',
                    args=[existente.id],
                ))
            return voltar

        tipo_certidao = _tipo_por_texto(texto)
        documentos = []
        if link_documento:
            documentos.append({
                'nome': f'Documento — {data or tipo or "movimentação"}',
                'url': link_documento,
            })
        rag = RAGExample.objects.create(
            process=proc,
            tenant=tenant,
            despacho_ato=(tipo or 'Movimentação')[:200],
            despacho_observacao=texto,
            despacho_data=data,
            documentos=documentos,
            tipo_certidao=tipo_certidao,
            active=True,
        )
        template_por_tipo = {
            'inominado': 'Certidão de Recurso Inominado (COJE)',
            'decurso_pagamento': (
                'Certidão de Decurso de Prazo para Pagamento Voluntário'
            ),
            'cumprimento_sentenca': 'Certidão de Prazo — Modelo Base',
            'pagamento_impugnacao_penhora': 'Certidão de Prazo — Modelo Base',
            'impugnacao_embargos_execucao': 'Certidão de Prazo — Modelo Base',
            'contrarrazoes_inominado': 'Certidão de Prazo — Modelo Base',
        }
        template = DocumentTemplate.objects.filter(
            name=template_por_tipo.get(tipo_certidao, ''),
            template_type='certidao',
            active=True,
        ).first()
        if template:
            rag.suggested_templates.add(template)

        messages.success(
            request,
            f'✅ RAG #{rag.id} criada a partir '
            + (
                'do texto da movimentação'
                if usou_texto_movimentacao else 'do documento'
            )
            + (
                f' com template "{template.name}" vinculado.'
                if template else '.'
            )
            + ' Revise o tipo de certidão e os parâmetros no admin.',
        )
        if request.user.is_staff:
            return HttpResponseRedirect(reverse(
                'admin:processes_ragexample_change', args=[rag.id]))
        return voltar


def _texto_do_evento(user, processo, processo_url, evento):
    """Busca o texto do despacho/decisão de um evento no Projudi."""
    from projudi.certidao_sugestao import (
        _texto_documento, limpar_texto_despacho,
    )
    from projudi.services import ProjudiService
    from projudi.verificacao_inominado import data_mov
    from projudiProcessNavigator import ProcessoParser

    if not processo_url:
        from projudi.processo_lookup import localizar_processo
        achado = localizar_processo(user, processo)
        if achado:
            processo_url = achado['url']
    if not processo_url:
        return '', None

    sessao = ProjudiService(user)._get_session_from_cookies()
    if not sessao:
        return '', None
    session, _ = sessao
    resposta = session.get(processo_url, timeout=40)
    if resposta.status_code != 200:
        return '', None
    parser = ProcessoParser(resposta.text)
    movs, _ = parser.extrair_movimentacoes()
    mov = next(
        (m for m in movs if str(m.get('evento')) == str(evento)),
        None,
    )
    if not mov:
        return '', None

    data = data_mov(mov)
    documentos = mov.get('documentos') or []
    link = ''
    if documentos and isinstance(documentos[0], dict):
        link = documentos[0].get('url') or ''
    texto = _texto_documento(session, link) if link else ''
    if not texto.strip():
        texto = ' '.join(
            str(mov.get(k) or '') for k in
            ('ato', 'observacao', 'ato_normalizado', 'descricao')
        )
    return limpar_texto_despacho(texto), data


class RagCertidaoCreateView(LoginRequiredMixin, View):
    """Cadastro rápido de RAG + modelo de certidão em uma única tela."""

    template_name = 'projudi/certidao_rag_form.html'

    def _contexto(self, **extra):
        from processes.models import DocumentTemplate
        from projudi.peticoes_inominado import TIPOS_CERTIDAO

        context = {
            'tipos_certidao': TIPOS_CERTIDAO,
            'modelos_base': DocumentTemplate.objects.filter(
                template_type='certidao', active=True,
            ).order_by('name'),
            'modelo_base': '',
            'processo': '',
            'processo_url': '',
            'evento_despacho': '',
            'evento_peticao': '',
            'evento_intimacao': '',
            'data_protocolo': '',
            'seguranca_juizo': '',
            'calculo': None,
            'ato': 'DESPACHO',
            'texto_despacho': '',
            'tipo_certidao': '',
            'prazo_dias': '',
            'modo_saida': 'certidao',
            'observacao_tempestiva': '',
            'observacao_intempestiva': '',
            'nome_modelo': '',
            'texto_certidao': '',
            'tipo_localizador': '',
            'localizador': '',
            'tipo_conclusao': '18',
            'juiz_conclusao': '41201',
            'acoes_fluxo': [],
        }
        context.update(extra)
        return context

    def get(self, request):
        from processes.models import DocumentTemplate, RAGExample

        modelo_base = (request.GET.get('modelo_base') or '').strip()
        rag_base_id = (request.GET.get('rag_base') or '').strip()
        texto_certidao = (
            request.GET.get('texto_certidao') or '').strip()
        nome_modelo = ''
        dados = {
            'processo': (request.GET.get('processo') or '').strip(),
            'processo_url': (request.GET.get('url') or '').strip(),
            'evento_despacho': (
                request.GET.get('evento') or '').strip(),
            'texto_despacho': (
                request.GET.get('texto_despacho') or '').strip(),
            'tipo_certidao': (
                request.GET.get('tipo_certidao') or '').strip(),
            'texto_certidao': texto_certidao,
            'nome_modelo': nome_modelo,
            'modelo_base': modelo_base,
        }

        if modelo_base.isdigit():
            base = DocumentTemplate.objects.filter(
                pk=int(modelo_base), template_type='certidao', active=True,
            ).first()
            if base:
                dados['texto_certidao'] = base.html_template
                dados['nome_modelo'] = f'{base.name} (cópia)'

        if rag_base_id.isdigit():
            base_rag = (
                RAGExample.objects
                .select_related('process')
                .prefetch_related('suggested_templates')
                .filter(pk=int(rag_base_id), active=True)
                .first()
            )
            if base_rag:
                ato = (base_rag.despacho_ato or '').upper()
                if 'DECIS' in ato:
                    ato_form = 'DECISÃO'
                elif 'SENTEN' in ato:
                    ato_form = 'SENTENÇA'
                else:
                    ato_form = 'DESPACHO'
                template = base_rag.suggested_templates.filter(
                    template_type='certidao', active=True,
                ).first()
                dados.update({
                    'processo': (
                        base_rag.process.number
                        if base_rag.process else dados['processo']),
                    'processo_url': (
                        base_rag.process.projudi_url
                        if base_rag.process else dados['processo_url']),
                    'evento_despacho': base_rag.evento_despacho,
                    'evento_peticao': base_rag.evento_peticao,
                    'evento_intimacao': base_rag.evento_intimacao,
                    'ato': ato_form,
                    'texto_despacho': base_rag.despacho_observacao,
                    'tipo_certidao': base_rag.tipo_certidao,
                    'prazo_dias': (
                        base_rag.prazo_dias
                        if base_rag.prazo_dias else ''),
                    'modo_saida': base_rag.modo_saida or 'certidao',
                    'observacao_tempestiva': (
                        base_rag.observacao_tempestiva or ''),
                    'observacao_intempestiva': (
                        base_rag.observacao_intempestiva or ''),
                    'tipo_localizador': base_rag.tipo_localizador,
                    'localizador': base_rag.localizador,
                    'tipo_conclusao': base_rag.tipo_conclusao or '18',
                    'juiz_conclusao': base_rag.juiz_conclusao or '41201',
                    'acoes_fluxo': list(base_rag.acoes_fluxo or []),
                    'texto_certidao': (
                        template.html_template
                        if template else dados['texto_certidao']),
                    'nome_modelo': (
                        f'{template.name} (cópia)'
                        if template else dados['nome_modelo']),
                })
        return render(request, self.template_name, self._contexto(**dados))

    def post(self, request):
        from base.utils import normalize_process_number
        from processes.models import DocumentTemplate, Process, RAGExample

        processo = (request.POST.get('processo') or '').strip()
        processo_url = (request.POST.get('processo_url') or '').strip()
        evento_despacho = (
            request.POST.get('evento_despacho') or '').strip()
        evento_peticao = (
            request.POST.get('evento_peticao') or '').strip()
        evento_intimacao = (
            request.POST.get('evento_intimacao') or '').strip()
        data_protocolo_txt = (
            request.POST.get('data_protocolo') or '').strip()
        seguranca_juizo = (
            request.POST.get('seguranca_juizo') or '').strip()
        modelo_base = (request.POST.get('modelo_base') or '').strip()
        acao = (request.POST.get('acao') or 'salvar').strip()
        ato = (request.POST.get('ato') or 'DESPACHO').strip().upper()
        texto_despacho = (
            request.POST.get('texto_despacho') or '').strip()
        tipo_certidao = (
            request.POST.get('tipo_certidao') or '').strip()
        modo_saida = (
            request.POST.get('modo_saida') or 'certidao').strip()
        observacao_tempestiva = (
            request.POST.get('observacao_tempestiva') or '').strip()
        observacao_intempestiva = (
            request.POST.get('observacao_intempestiva') or '').strip()
        prazo_dias_txt = (
            request.POST.get('prazo_dias') or '').strip()
        prazo_dias = (
            int(prazo_dias_txt)
            if prazo_dias_txt.isdigit() and int(prazo_dias_txt) > 0
            else None)
        nome_modelo = (request.POST.get('nome_modelo') or '').strip()
        texto_certidao = (
            request.POST.get('texto_certidao') or '').strip()
        tipo_localizador = (
            request.POST.get('tipo_localizador') or '').strip()
        localizador = (request.POST.get('localizador') or '').strip()
        tipo_conclusao = (
            request.POST.get('tipo_conclusao') or '18').strip()
        juiz_conclusao = (
            request.POST.get('juiz_conclusao') or '41201').strip()
        acoes_fluxo = [
            nome for nome in (
                'juntar', 'intimar', 'localizador', 'contadoria',
                'conclusao', 'mp',
            )
            if request.POST.get(f'fluxo_{nome}') == 'on'
        ]

        from projudi.peticoes_inominado import TIPOS_CERTIDAO
        tipos = {t['valor']: t for t in TIPOS_CERTIDAO}

        if acao == 'carregar_modelo':
            base = None
            if modelo_base.isdigit():
                base = DocumentTemplate.objects.filter(
                    pk=int(modelo_base), template_type='certidao',
                    active=True,
                ).first()
            if base:
                texto_certidao = base.html_template
                nome_modelo = f'{base.name} (cópia)'
            else:
                messages.warning(
                    request, 'Escolha um modelo existente para copiar.')
            return render(request, self.template_name, self._contexto(
                processo=processo, processo_url=processo_url,
                evento_despacho=evento_despacho, ato=ato,
                texto_despacho=texto_despacho,
                tipo_certidao=tipo_certidao, nome_modelo=nome_modelo,
                texto_certidao=texto_certidao,
                evento_peticao=evento_peticao,
                evento_intimacao=evento_intimacao,
                data_protocolo=data_protocolo_txt,
                seguranca_juizo=seguranca_juizo,
                tipo_localizador=tipo_localizador,
                localizador=localizador,
                tipo_conclusao=tipo_conclusao,
                juiz_conclusao=juiz_conclusao,
                modelo_base=modelo_base,
                acoes_fluxo=acoes_fluxo,
            ))

        if evento_despacho and not evento_despacho.isdigit():
            messages.error(
                request, 'Evento do despacho inválido. Informe apenas o número.')
            return render(
                request, self.template_name,
                self._contexto(
                    processo=processo, processo_url=processo_url,
                    evento_despacho=evento_despacho, ato=ato,
                    texto_despacho=texto_despacho,
                    tipo_certidao=tipo_certidao, nome_modelo=nome_modelo,
                    texto_certidao=texto_certidao,
                    tipo_localizador=tipo_localizador,
                    localizador=localizador,
                    tipo_conclusao=tipo_conclusao,
                    juiz_conclusao=juiz_conclusao,
                    acoes_fluxo=acoes_fluxo,
                ),
            )

        data_evento = None
        if not texto_despacho and evento_despacho and processo:
            texto_despacho, data_evento = _texto_do_evento(
                request.user, processo, processo_url, evento_despacho)
            if not texto_despacho:
                messages.error(
                    request,
                    'Não localizei o texto do evento '
                    f'{evento_despacho}. Confira o número ou cole o texto '
                    'do despacho manualmente.')
                return render(
                    request, self.template_name,
                    self._contexto(
                        processo=processo, processo_url=processo_url,
                        evento_despacho=evento_despacho, ato=ato,
                        tipo_certidao=tipo_certidao,
                        nome_modelo=nome_modelo,
                        texto_certidao=texto_certidao,
                        tipo_localizador=tipo_localizador,
                        localizador=localizador,
                        tipo_conclusao=tipo_conclusao,
                        juiz_conclusao=juiz_conclusao,
                        acoes_fluxo=acoes_fluxo,
                    ),
                )

        if not processo or not texto_despacho:
            messages.error(
                request,
                'Informe o processo e o evento ou o texto do despacho.')
            return render(
                request, self.template_name,
                self._contexto(
                    processo=processo, processo_url=processo_url,
                    evento_despacho=evento_despacho, ato=ato,
                    texto_despacho=texto_despacho,
                    tipo_certidao=tipo_certidao, nome_modelo=nome_modelo,
                    texto_certidao=texto_certidao,
                    evento_peticao=evento_peticao,
                    evento_intimacao=evento_intimacao,
                    data_protocolo=data_protocolo_txt,
                    seguranca_juizo=seguranca_juizo,
                    tipo_localizador=tipo_localizador,
                    localizador=localizador,
                    tipo_conclusao=tipo_conclusao,
                    juiz_conclusao=juiz_conclusao,
                    acoes_fluxo=acoes_fluxo,
                ),
            )

        data_protocolo = None
        if data_protocolo_txt:
            try:
                data_protocolo = datetime.strptime(
                    data_protocolo_txt, '%d/%m/%Y').date()
            except ValueError:
                data_protocolo = None
        if not data_protocolo and evento_peticao and processo:
            if not evento_peticao.isdigit():
                messages.error(request, 'Evento da petição inválido.')
                return render(request, self.template_name, self._contexto(
                    processo=processo, processo_url=processo_url,
                    evento_despacho=evento_despacho, ato=ato,
                    texto_despacho=texto_despacho,
                    tipo_certidao=tipo_certidao, nome_modelo=nome_modelo,
                    texto_certidao=texto_certidao,
                    evento_peticao=evento_peticao,
                    evento_intimacao=evento_intimacao,
                    data_protocolo=data_protocolo_txt,
                    seguranca_juizo=seguranca_juizo,
                    acoes_fluxo=acoes_fluxo,
                ))
            from projudi.intimacao_service import data_evento_processo
            if not processo_url:
                from projudi.processo_lookup import localizar_processo
                achado = localizar_processo(request.user, processo)
                if achado:
                    processo_url = achado['url']
            if processo_url:
                data_protocolo = data_evento_processo(
                    request.user, processo_url, evento_peticao)

        if acao == 'calcular':
            if tipo_certidao != 'impugnacao_embargos_execucao':
                messages.info(
                    request,
                    'O cálculo de tempestividade está disponível para '
                    'Impugnação/Embargos à Execução.')
                return render(request, self.template_name, self._contexto(
                    processo=processo, processo_url=processo_url,
                    evento_despacho=evento_despacho, ato=ato,
                    texto_despacho=texto_despacho,
                    tipo_certidao=tipo_certidao, nome_modelo=nome_modelo,
                    texto_certidao=texto_certidao,
                    evento_peticao=evento_peticao,
                    evento_intimacao=evento_intimacao,
                    data_protocolo=data_protocolo_txt,
                    seguranca_juizo=seguranca_juizo,
                    acoes_fluxo=acoes_fluxo,
                ))
            if not data_protocolo:
                messages.error(
                    request,
                    'Informe a data do protocolo ou o evento da petição '
                    'para calcular a tempestividade.')
                return render(request, self.template_name, self._contexto(
                    processo=processo, processo_url=processo_url,
                    evento_despacho=evento_despacho, ato=ato,
                    texto_despacho=texto_despacho,
                    tipo_certidao=tipo_certidao, nome_modelo=nome_modelo,
                    texto_certidao=texto_certidao,
                    evento_peticao=evento_peticao,
                    evento_intimacao=evento_intimacao,
                    data_protocolo=data_protocolo_txt,
                    seguranca_juizo=seguranca_juizo,
                    acoes_fluxo=acoes_fluxo,
                ))
            from projudi.decurso_pagamento_service import (
                DecursoPagamentoService,
            )
            try:
                resultado = DecursoPagamentoService(request.user).analisar(
                    processo,
                    evento=evento_despacho,
                    url=processo_url or None,
                    evento_intimacao=evento_intimacao or None,
                    dias=prazo_dias or 15,
                )
            except Exception as exc:
                messages.error(request, f'Erro no cálculo: {exc}')
                return render(request, self.template_name, self._contexto(
                    processo=processo, processo_url=processo_url,
                    evento_despacho=evento_despacho, ato=ato,
                    texto_despacho=texto_despacho,
                    tipo_certidao=tipo_certidao, nome_modelo=nome_modelo,
                    texto_certidao=texto_certidao,
                    evento_peticao=evento_peticao,
                    evento_intimacao=evento_intimacao,
                    data_protocolo=data_protocolo_txt,
                    seguranca_juizo=seguranca_juizo,
                    acoes_fluxo=acoes_fluxo,
                ))
            if resultado.get('erro'):
                messages.error(request, resultado['erro'])
                return render(request, self.template_name, self._contexto(
                    processo=processo, processo_url=processo_url,
                    evento_despacho=evento_despacho, ato=ato,
                    texto_despacho=texto_despacho,
                    tipo_certidao=tipo_certidao, nome_modelo=nome_modelo,
                    texto_certidao=texto_certidao,
                    evento_peticao=evento_peticao,
                    evento_intimacao=evento_intimacao,
                    data_protocolo=data_protocolo_txt,
                    seguranca_juizo=seguranca_juizo,
                    acoes_fluxo=acoes_fluxo,
                ))
            tempestivo = data_protocolo <= resultado['ultimo_dia']
            calculo = {
                'tempestivo': tempestivo,
                'data_protocolo': data_protocolo,
                'ultimo_dia': resultado['ultimo_dia'],
                'data_decurso': resultado['data_decurso'],
                'data_intimacao': resultado.get('data_intimacao'),
                'evento_intimacao': resultado.get('evento_intimacao'),
                'meio_label': resultado.get('meio_label'),
                'data_publicacao': resultado.get('data_publicacao'),
                'data_inicio_contagem': resultado.get(
                    'data_inicio_contagem'),
            }
            return render(request, self.template_name, self._contexto(
                processo=processo, processo_url=processo_url,
                evento_despacho=evento_despacho, ato=ato,
                texto_despacho=texto_despacho,
                tipo_certidao=tipo_certidao, nome_modelo=nome_modelo,
                texto_certidao=texto_certidao,
                evento_peticao=evento_peticao,
                evento_intimacao=evento_intimacao,
                data_protocolo=data_protocolo_txt,
                seguranca_juizo=seguranca_juizo,
                calculo=calculo,
                acoes_fluxo=acoes_fluxo,
            ))

        if (modo_saida == 'certidao' and not texto_certidao):
            messages.error(request, 'Informe o texto da certidão.')
            return render(request, self.template_name, self._contexto(
                processo=processo, processo_url=processo_url,
                evento_despacho=evento_despacho, ato=ato,
                texto_despacho=texto_despacho,
                tipo_certidao=tipo_certidao, nome_modelo=nome_modelo,
                texto_certidao=texto_certidao,
                evento_peticao=evento_peticao,
                evento_intimacao=evento_intimacao,
                data_protocolo=data_protocolo_txt,
                seguranca_juizo=seguranca_juizo,
                modo_saida=modo_saida,
                observacao_tempestiva=observacao_tempestiva,
                observacao_intempestiva=observacao_intempestiva,
                acoes_fluxo=acoes_fluxo,
            ))
        if (modo_saida != 'certidao'
                and not observacao_tempestiva
                and not observacao_intempestiva):
            messages.error(
                request,
                'Informe a observação tempestiva e/ou a intempestiva.')
            return render(request, self.template_name, self._contexto(
                processo=processo, processo_url=processo_url,
                evento_despacho=evento_despacho, ato=ato,
                texto_despacho=texto_despacho,
                tipo_certidao=tipo_certidao, nome_modelo=nome_modelo,
                texto_certidao=texto_certidao,
                evento_peticao=evento_peticao,
                evento_intimacao=evento_intimacao,
                data_protocolo=data_protocolo_txt,
                seguranca_juizo=seguranca_juizo,
                modo_saida=modo_saida,
                observacao_tempestiva=observacao_tempestiva,
                observacao_intempestiva=observacao_intempestiva,
                acoes_fluxo=acoes_fluxo,
            ))
        if tipo_certidao not in tipos:
            messages.error(request, 'Escolha o tipo de certidão.')
            return render(
                request, self.template_name,
                self._contexto(
                    processo=processo, processo_url=processo_url,
                    ato=ato, texto_despacho=texto_despacho,
                    tipo_certidao=tipo_certidao, nome_modelo=nome_modelo,
                    texto_certidao=texto_certidao,
                    tipo_localizador=tipo_localizador,
                    localizador=localizador,
                    tipo_conclusao=tipo_conclusao,
                    juiz_conclusao=juiz_conclusao,
                    acoes_fluxo=acoes_fluxo,
                ),
            )

        numero = normalize_process_number(processo)
        if len(numero) < 15:
            messages.error(request, 'Número do processo inválido.')
            return render(
                request, self.template_name,
                self._contexto(
                    processo=processo, processo_url=processo_url,
                    ato=ato, texto_despacho=texto_despacho,
                    tipo_certidao=tipo_certidao, nome_modelo=nome_modelo,
                    texto_certidao=texto_certidao,
                    tipo_localizador=tipo_localizador,
                    localizador=localizador,
                    tipo_conclusao=tipo_conclusao,
                    juiz_conclusao=juiz_conclusao,
                    acoes_fluxo=acoes_fluxo,
                ),
            )
        numero = numero.zfill(20)

        proc = Process.objects.filter(number_normalized=numero).first()
        tenant = getattr(request.user, 'tenant', None)
        if tenant is None and proc is not None:
            tenant = proc.tenant
        if tenant is None:
            from accounts.models import Tenant
            tenant = Tenant.objects.first()
        if tenant is None:
            messages.error(request, 'Nenhum tenant cadastrado.')
            return render(request, self.template_name, self._contexto(
                processo=processo, texto_despacho=texto_despacho,
                texto_certidao=texto_certidao))
        if proc is None:
            proc = Process.objects.create(
                number=processo,
                number_normalized=numero,
                tenant=tenant,
                status='analyzing',
                projudi_url=processo_url,
            )
        elif processo_url and not proc.projudi_url:
            proc.projudi_url = processo_url
            proc.save(update_fields=['projudi_url'])

        if '<' in texto_certidao or '>' in texto_certidao:
            html_certidao = texto_certidao
        else:
            # Texto simples → aplica o cabeçalho/brasão padrão da certidão.
            # Decursos usam também a moldura com intimação, prazo e datas.
            if tipo_certidao in (
                    'decurso_pagamento',
                    'decurso_manifestacao_adjudicacao'):
                html_certidao = html_certidao_decurso(texto_certidao)
            else:
                html_certidao = html_certidao_padrao(texto_certidao)

        rag = RAGExample.objects.create(
            process=proc,
            tenant=tenant,
            evento_despacho=evento_despacho,
            evento_peticao=evento_peticao,
            evento_intimacao=evento_intimacao,
            despacho_ato=ato[:200],
            despacho_observacao=texto_despacho,
            despacho_data=(
                data_evento.strftime('%d/%m/%Y')
                if data_evento else datetime.now().strftime('%d/%m/%Y')
            ),
            tipo_certidao=tipo_certidao,
            prazo_dias=prazo_dias,
            modo_saida=modo_saida,
            observacao_tempestiva=observacao_tempestiva,
            observacao_intempestiva=observacao_intempestiva,
            tipo_localizador=tipo_localizador,
            localizador=localizador,
            tipo_conclusao=tipo_conclusao,
            juiz_conclusao=juiz_conclusao,
            acoes_fluxo=acoes_fluxo,
            active=True,
        )
        modelo = None
        if texto_certidao:
            modelo = DocumentTemplate.objects.create(
                name=(
                    nome_modelo
                    or f'Certidão RAG #{rag.id} — '
                       f'{tipos[tipo_certidao]["label"]}'
                ),
                template_type='certidao',
                description=texto_despacho[:500],
                html_template=html_certidao,
                active=True,
            )
            rag.suggested_templates.add(modelo)

        if modelo:
            messages.success(
                request,
                f'✅ RAG #{rag.id} e modelo "{modelo.name}" criados e '
                'vinculados. Revise na lista de RAGs.',
            )
        else:
            messages.success(
                request,
                f'✅ RAG #{rag.id} criada para saída '
                f'{rag.get_modo_saida_display()}. Revise na lista de RAGs.',
            )
        return HttpResponseRedirect(reverse('projudi:rag_certidoes'))


class RagCertidaoListView(LoginRequiredMixin, TemplateView):
    """Tabela das RAGs que geram certidão, separadas por origem."""

    template_name = 'projudi/rag_certidoes.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.db.models import Q
        from processes.models import RAGExample
        from projudi.certidao_sugestao import _normalizar, _tipo_por_texto
        from projudi.peticoes_inominado import TIPOS_CERTIDAO

        tipos_peticao = {'inominado', 'contrarrazoes_inominado'}
        labels = {t['valor']: t['label'] for t in TIPOS_CERTIDAO}

        busca = (self.request.GET.get('q') or '').strip()
        origem = (self.request.GET.get('origem') or '').strip()
        if origem not in ('peticao', 'movimentacao'):
            origem = ''

        qs = (
            RAGExample.objects
            .select_related('process')
            .prefetch_related('suggested_templates')
            .filter(active=True)
        )
        if busca:
            qs = qs.filter(
                Q(process__number__icontains=busca)
                | Q(despacho_ato__icontains=busca)
                | Q(despacho_observacao__icontains=busca)
            )

        registros = []
        contagem = {'peticao': 0, 'movimentacao': 0}
        for rag in qs.order_by('-created_at'):
            templates = [
                t.name for t in rag.suggested_templates.all()
                if t.template_type == 'certidao'
            ]
            tipo = rag.tipo_certidao or ''
            if not tipo:
                tipo = _tipo_por_texto(
                    f'{rag.despacho_ato or ""} '
                    f'{rag.despacho_observacao or ""}'
                )
            if not tipo and not templates:
                continue
            if tipo in tipos_peticao:
                origem_rag = 'peticao'
            elif tipo:
                origem_rag = 'movimentacao'
            else:
                nomes = _normalizar(' '.join(templates))
                origem_rag = (
                    'peticao'
                    if ('RECURSO INOMINADO' in nomes
                        or 'CONTRARRAZOES' in nomes)
                    else 'movimentacao'
                )

            rag.origem_certidao = origem_rag
            rag.origem_certidao_label = (
                'Petições' if origem_rag == 'peticao' else 'Movimentações'
            )
            rag.tipo_certidao_label = labels.get(
                tipo, templates[0] if templates else 'Sem certidão')
            rag.templates_nomes = templates
            contagem[origem_rag] += 1
            if origem and origem_rag != origem:
                continue
            registros.append(rag)

        context.update({
            'registros': registros,
            'busca': busca,
            'origem_filtro': origem,
            'total': contagem['peticao'] + contagem['movimentacao'],
            'total_peticoes': contagem['peticao'],
            'total_movimentacoes': contagem['movimentacao'],
            'is_staff': self.request.user.is_staff,
        })
        return context


class CertidaoDetailView(LoginRequiredMixin, DetailView):
    model = PrazoDjenRecord
    template_name = 'projudi/certidao_detail.html'
    context_object_name = 'registro'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        reg = self.object
        context['status_classe'], context['status_label'] = _status_registro(reg)
        context['tipo_label'] = TIPOS_PRAZO.get(
            reg.tipo_prazo, {}).get('label', reg.tipo_prazo)
        context['origem_label'] = reg.get_origem_display()
        info = reg.prazo_info or {}
        context['dias_contados_br'] = _datas_br(info.get('dias_contados'))
        context['dias_excluidos_br'] = _datas_br(info.get('dias_excluidos'))
        context['prazo_info_pretty'] = json.dumps(
            info, indent=2, ensure_ascii=False, default=str)
        context['preview_disponivel'] = bool(reg.certidao_path)
        return context


class CertidaoPreviewView(LoginRequiredMixin, View):
    """Serve o HTML do preview salvo em var/ (sem expor outros arquivos)."""

    def get(self, request, pk):
        reg = get_object_or_404(PrazoDjenRecord, pk=pk)
        if not reg.certidao_path:
            raise Http404('Esta certidão não tem preview salvo.')

        caminho = Path(reg.certidao_path).expanduser()
        try:
            caminho = caminho.resolve()
        except OSError:
            raise Http404('Caminho do preview inválido.')

        pasta_var = (Path(settings.BASE_DIR) / 'var').resolve()
        if pasta_var not in caminho.parents or not caminho.is_file():
            raise Http404(
                'Preview fora da pasta var/ ou arquivo inexistente.')

        from .arquivo_texto import ler_certidao
        html = ler_certidao(caminho)
        # O arquivo em disco é Latin-1; esta resposta é servida em UTF-8.
        html = html.replace(
            'charset="iso-8859-1"', 'charset="utf-8"'
        ).replace(
            "charset='iso-8859-1'", "charset='utf-8'"
        )
        return HttpResponse(
            html,
            content_type='text/html; charset=utf-8',
        )
