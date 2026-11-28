"""Dashboard de certidões/prazos DJEN (controle interno)."""

import json
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, TemplateView

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
        from projudi.certidao_sugestao import _texto_documento, _tipo_por_texto
        from projudi.services import ProjudiService

        processo = (request.POST.get('processo') or '').strip()
        tipo = (request.POST.get('tipo') or '').strip()
        data = (request.POST.get('data') or '').strip()
        link_processo = (request.POST.get('link_processo') or '').strip()
        link_documento = (request.POST.get('link_documento') or '').strip()
        texto_movimentacao = (
            request.POST.get('texto_movimentacao') or '').strip()

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
        usou_texto_movimentacao = False
        if len(texto.strip()) < 30 and texto_movimentacao:
            texto = texto_movimentacao
            usou_texto_movimentacao = True
        if not texto.strip():
            messages.error(
                request,
                'Não há documento nem texto da movimentação para gerar a RAG.',
            )
            return voltar

        numero = normalize_process_number(processo)
        proc = Process.objects.filter(number_normalized=numero).first()
        if not proc:
            proc = Process.objects.create(
                number=processo,
                number_normalized=numero,
                tenant=getattr(request.user, 'tenant', None),
                status='analyzing',
                projudi_url=link_processo,
            )

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
            tenant=getattr(request.user, 'tenant', None),
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

        return HttpResponse(
            caminho.read_text(encoding='utf-8'),
            content_type='text/html; charset=utf-8',
        )
