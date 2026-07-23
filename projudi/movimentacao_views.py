"""Views de Movimentações — Dashboard, listagem, sincronização e execução.

Segue o mesmo padrão de mandado_views.py e oficio_views.py.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views import View
from django.views.generic import ListView, DetailView, TemplateView
from django.contrib import messages
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .models import MovimentacaoRecord, MovimentacaoLog, ProjudiSession
from .movimentacao_service import MovimentacaoService
from .services import ProjudiService


class MovimentacaoDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'projudi/movimentacao_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        qs = MovimentacaoRecord.objects.filter(user=user)

        context['total'] = qs.count()
        context['pendentes'] = qs.filter(status='pendente').count()
        context['processando'] = qs.filter(status='processando').count()
        context['cumpridos'] = qs.filter(status='cumprido').count()
        context['falhas'] = qs.filter(status='falha').count()
        context['dispensados'] = qs.filter(status='dispensado').count()

        context['categorias'] = {}
        for cat, label in MovimentacaoRecord.CATEGORIA_CHOICES:
            count = qs.filter(categoria=cat).count()
            if count:
                context['categorias'][cat] = {'label': label, 'count': count}

        filtro_status = self.request.GET.get('status', '')
        if filtro_status and filtro_status in dict(MovimentacaoRecord.STATUS_CHOICES):
            qs = qs.filter(status=filtro_status)

        filtro_cat = self.request.GET.get('categoria', '')
        if filtro_cat and filtro_cat in dict(MovimentacaoRecord.CATEGORIA_CHOICES):
            qs = qs.filter(categoria=filtro_cat)

        context['movimentacoes'] = qs.order_by('-created_at')[:50]
        context['session_active'] = self._session_ativa(user)
        return context

    def _session_ativa(self, user):
        try:
            sessao = ProjudiSession.objects.filter(user=user, status='active').first()
            if sessao:
                return ProjudiService(user).check_session()
        except Exception:
            pass
        return False


class MovimentacaoListView(LoginRequiredMixin, ListView):
    template_name = 'projudi/movimentacao_list.html'
    context_object_name = 'movimentacoes'
    paginate_by = 20

    def get_queryset(self):
        qs = MovimentacaoRecord.objects.filter(user=self.request.user)
        status = self.request.GET.get('status', '')
        cat = self.request.GET.get('categoria', '')
        if status and status in dict(MovimentacaoRecord.STATUS_CHOICES):
            qs = qs.filter(status=status)
        if cat and cat in dict(MovimentacaoRecord.CATEGORIA_CHOICES):
            qs = qs.filter(categoria=cat)
        return qs.order_by('-created_at')


class MovimentacaoDetailView(LoginRequiredMixin, DetailView):
    template_name = 'projudi/movimentacao_detail.html'
    model = MovimentacaoRecord
    context_object_name = 'movimentacao'
    pk_url_kwarg = 'pk'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = MovimentacaoService(self.request.user)
        context['logs'] = service.logs_humanizados(self.object)
        return context


@method_decorator(csrf_exempt, name='dispatch')
class MovimentacaoSyncView(LoginRequiredMixin, View):
    """POST — Busca movimentações no Projudi, RAG match, importa."""

    def post(self, request):
        from projudi_client import ProjudiClient
        from bs4 import BeautifulSoup

        service = MovimentacaoService(request.user)
        try:
            result = service.projudi_service._get_session_from_cookies()
            if not result:
                messages.error(request, 'Sessão do Projudi não disponível.')
                return HttpResponseRedirect(reverse('projudi:movimentacao_dashboard'))

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
                messages.info(request, 'Nenhuma movimentação encontrada.')
                return HttpResponseRedirect(reverse('projudi:movimentacao_dashboard'))

            # Processa cada mov com CommandAnalyzer
            from projudi_command_analyzer_new import CommandAnalyzer
            from processes.models import Process

            importados = 0
            for mov in movs:
                proc_num = mov.get('processo', '')
                doc_url = mov.get('link_documento', '')
                if not proc_num or not doc_url:
                    continue

                try:
                    r_doc = session.get(doc_url, timeout=30)
                    if r_doc.status_code != 200:
                        continue
                    texto = BeautifulSoup(r_doc.text, 'html.parser').get_text(' ', strip=True)
                    if len(texto) < 50:
                        continue

                    # Analisa comando
                    analyzer = CommandAnalyzer()
                    item = {'processo': proc_num, 'tipo': mov.get('tipo', '')}
                    comandos = analyzer.processar_texto(texto, item=item)

                    # Verifica se algum comando é movimentação
                    for cmd in comandos:
                        tipo_cmd = self._classificar_tipo_cumprimento(cmd)
                        if tipo_cmd != 'movimentacao':
                            continue

                        # Cria MovimentacaoRecord
                        record = service.importar(
                            processo_numero=proc_num,
                            act_verb=cmd['ato'],
                            observacao=cmd['trecho'][:500],
                            categoria=self._mapear_categoria(cmd['ato']),
                            processo_cnj=proc_num,
                            url_processo=mov.get('link_processo', ''),
                        )
                        importados += 1

                except Exception:
                    continue

            msg = f'Sincronizado! {importados} movimentação(ões) identificada(s).'
            if importados == 0:
                msg += ' Nenhuma movimentação interna pendente.'
            messages.success(request, msg)

        except Exception as e:
            messages.error(request, f'Erro: {str(e)[:200]}')

        return HttpResponseRedirect(reverse('projudi:movimentacao_dashboard'))

    def _classificar_tipo_cumprimento(self, cmd: dict) -> str:
        """Classifica o tipo de cumprimento baseado no ato + destinatário."""
        ato = (cmd.get('ato') or '').lower().strip()
        tem_dest = bool(cmd.get('destinatario')) and cmd['destinatario'] != 'partes'

        if ato in ('publique-se', 'registre-se', 'anote-se'):
            return 'movimentacao'
        if ato in ('arquive-se', 'certifique-se'):
            return 'movimentacao' if not tem_dest else 'intimacao'
        return 'outro'

    def _mapear_categoria(self, act_verb: str) -> str:
        mapping = {
            'certifique-se': 'certidao',
            'arquive-se': 'arquivamento',
            'publique-se': 'publicacao',
            'registre-se': 'registro',
            'anote-se': 'registro',
        }
        return mapping.get(act_verb.lower().strip(), 'outro')


class MovimentacaoExecutarView(LoginRequiredMixin, View):
    """POST — Executa a movimentação no Projudi."""

    def post(self, request, pk):
        record = get_object_or_404(MovimentacaoRecord, pk=pk, user=request.user)
        service = MovimentacaoService(request.user)
        try:
            sucesso = service.executar(record)
            if sucesso:
                messages.success(
                    request,
                    f'✅ Movimentação "{record.act_verb}" cumprida!')
            else:
                messages.error(
                    request,
                    f'❌ Falha ao executar movimentação "{record.act_verb}".')
        except Exception as e:
            messages.error(request, f'Erro: {str(e)[:200]}')
        return HttpResponseRedirect(
            reverse('projudi:movimentacao_detail', kwargs={'pk': pk}))


class MovimentacaoBatchView(LoginRequiredMixin, View):
    """POST — Executa todas as movimentações pendentes."""

    def post(self, request):
        service = MovimentacaoService(request.user)
        pendentes = MovimentacaoRecord.objects.filter(
            user=request.user, status__in=['pendente', 'falha'])
        try:
            resultado = service.processar_fila(list(pendentes))
            messages.success(
                request,
                f'Lote processado: {resultado["cumpridos"]} cumprida(s), '
                f'{resultado["falhas"]} falha(s).')
        except Exception as e:
            messages.error(request, f'Erro: {str(e)[:200]}')
        return HttpResponseRedirect(reverse('projudi:movimentacao_dashboard'))


class MovimentacaoDispensarView(LoginRequiredMixin, View):
    """POST — Dispensa a movimentação."""

    def post(self, request, pk):
        record = get_object_or_404(MovimentacaoRecord, pk=pk, user=request.user)
        service = MovimentacaoService(request.user)
        try:
            service.dispensar(record)
            messages.success(request,
                             f'Movimentação "{record.act_verb}" dispensada.')
        except Exception as e:
            messages.error(request, f'Erro: {str(e)[:200]}')
        return HttpResponseRedirect(reverse('projudi:movimentacao_dashboard'))


class MovimentacaoLogsJsonView(LoginRequiredMixin, View):
    """GET — Retorna logs em JSON."""

    def get(self, request, pk):
        record = get_object_or_404(MovimentacaoRecord, pk=pk, user=request.user)
        service = MovimentacaoService(request.user)
        logs = service.logs_humanizados(record)
        return JsonResponse({'logs': logs})
