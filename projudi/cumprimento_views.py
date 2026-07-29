"""Views de Cumprimentos — Dashboard, listagem, detalhe, sincronização e execução.

Segue o mesmo padrão de mandado_views.py e oficio_views.py.
"""
from datetime import datetime
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views import View
from django.views.generic import ListView, DetailView, TemplateView
from django.contrib import messages
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import os

from .models import CumprimentoRecord, CumprimentoLog, ProjudiSession
from .cumprimento_service import CumprimentoService
from .services import ProjudiService


class CumprimentoDashboardView(LoginRequiredMixin, TemplateView):
    """Dashboard de Cumprimentos: cards de estatísticas + lista dos últimos."""
    template_name = 'projudi/cumprimento_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        qs = CumprimentoRecord.objects.filter(user=user)
        context['total'] = qs.count()
        context['pendentes'] = qs.filter(status='pendente').count()
        context['processando'] = qs.filter(status='processando').count()
        context['cumpridos'] = qs.filter(status='cumprido').count()
        context['falhas'] = qs.filter(status='falha').count()
        context['dispensados'] = qs.filter(status='dispensado').count()

        # Contagem por fluxo
        context['fluxos'] = {}
        for fluxo, label in CumprimentoRecord.FLUXO_CHOICES:
            count = qs.filter(fluxo=fluxo).count()
            if count:
                context['fluxos'][fluxo] = {'label': label, 'count': count}

        status_filter = self.request.GET.get('status', '')
        if status_filter:
            if status_filter in dict(CumprimentoRecord.STATUS_CHOICES):
                qs = qs.filter(status=status_filter)

        fluxo_filter = self.request.GET.get('fluxo', '')
        if fluxo_filter and fluxo_filter in dict(CumprimentoRecord.FLUXO_CHOICES):
            qs = qs.filter(fluxo=fluxo_filter)

        context['cumprimentos'] = qs.order_by('-created_at')[:50]
        context['session_active'] = self._session_ativa(user)
        context['auto_rastrear_ativo'] = os.path.exists('/tmp/auto_rastrear.pid')
        return context

    def _session_ativa(self, user):
        try:
            sessao = ProjudiSession.objects.filter(user=user, status='active').first()
            if sessao:
                return ProjudiService(user).check_session()
        except Exception:
            pass
        return False


class CumprimentoListView(LoginRequiredMixin, ListView):
    template_name = 'projudi/cumprimento_list.html'
    context_object_name = 'cumprimentos'
    paginate_by = 20

    def get_queryset(self):
        qs = CumprimentoRecord.objects.filter(user=self.request.user)
        fluxo = self.request.GET.get('fluxo', '')
        status = self.request.GET.get('status', '')
        if fluxo and fluxo in dict(CumprimentoRecord.FLUXO_CHOICES):
            qs = qs.filter(fluxo=fluxo)
        if status and status in dict(CumprimentoRecord.STATUS_CHOICES):
            qs = qs.filter(status=status)
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['session_active'] = self._session_ativa()
        return context

    def _session_ativa(self):
        try:
            sessao = ProjudiSession.objects.filter(user=self.request.user, status='active').first()
            if sessao:
                return ProjudiService(self.request.user).check_session()
        except Exception:
            pass
        return False


class CumprimentoDetailView(LoginRequiredMixin, DetailView):
    template_name = 'projudi/cumprimento_detail.html'
    model = CumprimentoRecord
    context_object_name = 'cumprimento'
    pk_url_kwarg = 'pk'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = CumprimentoService(self.request.user)
        context['logs'] = service.logs_humanizados(self.object)
        return context


@method_decorator(csrf_exempt, name='dispatch')
class CumprimentoSyncView(LoginRequiredMixin, View):
    """POST /projudi/cumprimentos/sync/
    Busca cumprimentos pendentes via RAG + classificação + decisão.
    """

    def post(self, request):
        from projudi_client import ProjudiClient
        from processes.models import DocumentTemplate
        from bs4 import BeautifulSoup

        service = CumprimentoService(request.user)
        try:
            # Captura sessão
            result = service.projudi_service._get_session_from_cookies()
            if not result:
                messages.error(request, 'Sessão do Projudi não disponível. Sincronize primeiro.')
                return HttpResponseRedirect(reverse('projudi:cumprimento_dashboard'))

            session, cookies_dict = result
            client = ProjudiClient()
            client.session = session
            client.cookies = cookies_dict

            # Varre movimentações
            pages = client.obter_paginas_finais_movimentacoes(quantidade=3)
            movs = []
            for p in pages:
                data = {'pagina': str(p), 'loginJuiz': ''}
                rp = session.post(client.URL_MOVIMENTACOES, data=data, timeout=15)
                if len(rp.text) > 1000:
                    sp = BeautifulSoup(rp.text, 'html.parser')
                    movs.extend(client.extrair_links_movimentacoes(sp))

            if not movs:
                messages.info(request, 'Nenhuma movimentação encontrada nas últimas páginas.')
                return HttpResponseRedirect(reverse('projudi:cumprimento_dashboard'))

            # Filtra templates que não são mandados nem ofícios (estes já têm fluxo próprio)
            templates_cumprimento = DocumentTemplate.objects.filter(
                active=True).exclude(template_type__in=['mandado', 'oficio'])

            # Busca decisões
            decisoes = service.buscar_cumprimentos_pendentes(
                movs, session, cookies_dict,
                templates_validos=templates_cumprimento
            )

            importados = 0
            for dec in decisoes:
                try:
                    service.importar_cumprimento(dec)
                    importados += 1
                except Exception as e:
                    print(f'[CumprimentoSync] Erro importando: {e}')

            msg = f'Sincronizado! {importados} cumprimento(s) identificado(s).'
            if importados == 0:
                msg += ' Nenhum novo cumprimento pendente encontrado.'
            messages.success(request, msg)

        except Exception as e:
            erro_str = str(e)
            if 'expirada' in erro_str.lower() or 'sessao' in erro_str.lower():
                messages.error(
                    request,
                    f'{erro_str} <a href="{reverse("projudi:sync_session")}">'
                    f'Clique aqui para sincronizar</a>'
                )
            else:
                messages.error(request, f'Erro ao sincronizar: {e}')

        return HttpResponseRedirect(reverse('projudi:cumprimento_dashboard'))


class CumprimentoExecutarView(LoginRequiredMixin, View):
    """POST /projudi/cumprimentos/<pk>/executar/
    Executa o cumprimento conforme o fluxo definido.
    """

    def post(self, request, pk):
        record = get_object_or_404(CumprimentoRecord, pk=pk, user=request.user)
        service = CumprimentoService(request.user)
        try:
            resultado = service.executar_cumprimento(record)
            if resultado.get('status') == 'cumprido':
                messages.success(request, f'Cumprimento {record.get_fluxo_display()} executado!')
            else:
                messages.info(request,
                              f'Cumprimento {record.get_fluxo_display()} '
                              f'iniciado ({resultado.get("status", "pendente")}).')
        except Exception as e:
            messages.error(request, f'Erro: {str(e)[:200]}')
        return HttpResponseRedirect(
            reverse('projudi:cumprimento_detail', kwargs={'pk': pk}))


class CumprimentoBatchView(LoginRequiredMixin, View):
    """POST /projudi/cumprimentos/executar-todos/
    Executa todos os cumprimentos pendentes em lote.
    """

    def post(self, request):
        service = CumprimentoService(request.user)
        pendentes = CumprimentoRecord.objects.filter(
            user=request.user, status__in=['pendente', 'falha'])
        try:
            resultado = service.processar_fila(list(pendentes))
            messages.success(
                request,
                f'Lote processado: {resultado["cumpridos"]} cumprido(s), '
                f'{resultado["falhas"]} falha(s).')
        except Exception as e:
            messages.error(request, f'Erro no lote: {str(e)[:200]}')
        return HttpResponseRedirect(reverse('projudi:cumprimento_dashboard'))


class CumprimentoDispensarView(LoginRequiredMixin, View):
    """POST /projudi/cumprimentos/<pk>/dispensar/"""

    def post(self, request, pk):
        record = get_object_or_404(CumprimentoRecord, pk=pk, user=request.user)
        service = CumprimentoService(request.user)
        try:
            service.dispensar_cumprimento(record)
            messages.success(request, f'Cumprimento {record.get_fluxo_display()} dispensado.')
        except Exception as e:
            messages.error(request, f'Erro: {str(e)[:200]}')
        return HttpResponseRedirect(reverse('projudi:cumprimento_dashboard'))


class CumprimentoExpedirRapidoView(LoginRequiredMixin, View):
    """POST /projudi/cumprimentos/<pk>/expedir-rapido/
    Executa o fluxo expedir_rapido (sequencia_cumprimento) para o processo do cumprimento.
    """
    
    def post(self, request, pk):
        record = get_object_or_404(CumprimentoRecord, pk=pk, user=request.user)
        proc = record.process
        if not proc:
            messages.error(request, 'Cumprimento sem processo vinculado.')
            return HttpResponseRedirect(reverse('projudi:cumprimento_dashboard'))
        
        try:
            import sys, os
            # Adiciona o diretório do projeto ao path (necessário para importar)
            project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if project_dir not in sys.path:
                sys.path.insert(0, project_dir)
            
            from expedir_rapido import expedir_processo_especifico
            expedir_processo_especifico(proc.number)
            messages.success(request, f'✅ Expedição concluída para {proc.number}')
        except Exception as e:
            import traceback
            traceback.print_exc()
            messages.error(request, f'❌ Erro: {str(e)[:300]}')
        
        return HttpResponseRedirect(reverse('projudi:cumprimento_dashboard'))


class CumprimentoLogsJsonView(LoginRequiredMixin, View):
    """GET /projudi/cumprimentos/<pk>/logs/json/"""

    def get(self, request, pk):
        record = get_object_or_404(CumprimentoRecord, pk=pk, user=request.user)
        service = CumprimentoService(request.user)
        logs = service.logs_humanizados(record)
        return JsonResponse({'logs': logs})
