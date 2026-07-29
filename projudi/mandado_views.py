"""
Views de Mandados - Dashboard, listagem, detalhe, sincronização e expedição.
Similar ao fluxo de ofícios (oficio_views.py).
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

from .models import MandadoRecord, MandadoLog, ProjudiSession
from .mandado_service import MandadoService
from .services import ProjudiService


class MandadoDashboardView(LoginRequiredMixin, TemplateView):
    """
    Dashboard de Mandados: cards de estatísticas + lista dos últimos.
    """
    template_name = 'projudi/mandado_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        qs = MandadoRecord.objects.filter(user=user)
        context['total'] = qs.count()
        context['pendentes'] = qs.filter(status='pendente').count()
        context['expedidos'] = qs.filter(status__in=['expedido', 'juntado']).count()
        context['juntados'] = qs.filter(status='juntado').count()
        context['falhas'] = qs.filter(status='falha').count()
        context['dispensados'] = qs.filter(status='dispensado').count()

        status_filter = self.request.GET.get('status', '')
        if status_filter:
            if status_filter == 'expedido':
                qs = qs.filter(status__in=['expedido', 'juntado'])
            elif status_filter in dict(MandadoRecord.STATUS_CHOICES):
                qs = qs.filter(status=status_filter)

        context['mandados'] = qs.order_by('-created_at')[:50]
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


class MandadoListView(LoginRequiredMixin, ListView):
    template_name = 'projudi/mandado_list.html'
    context_object_name = 'mandados'
    paginate_by = 20

    def get_queryset(self):
        return MandadoRecord.objects.filter(user=self.request.user).order_by('-created_at')

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


class MandadoDetailView(LoginRequiredMixin, DetailView):
    template_name = 'projudi/mandado_detail.html'
    model = MandadoRecord
    context_object_name = 'mandado'
    pk_url_kwarg = 'pk'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = MandadoService(self.request.user)
        context['logs'] = service.logs_humanizados(self.object)
        return context


@method_decorator(csrf_exempt, name='dispatch')
class MandadoSyncView(LoginRequiredMixin, View):
    """
    POST /projudi/mandados/sync/
    Busca mandados no Projudi e importa para o banco.
    """
    def post(self, request):
        service = MandadoService(request.user)
        try:
            pendentes = service.buscar_mandados_pendentes(quantidade=3)
            importados = 0
            for dados in pendentes:
                dados_completos = service.extrair_mandado(dados)
                if dados_completos:
                    service.importar_mandado(dados_completos)
                    importados += 1

            msg = f"Sincronizado! {importados} mandados importados do Projudi."
            if importados == 0:
                msg += " Nenhum mandado pendente encontrado."
            messages.success(request, msg)

        except Exception as e:
            erro_str = str(e)
            if 'expirada' in erro_str.lower() or 'sessao' in erro_str.lower():
                messages.error(
                    request,
                    f"{erro_str} <a href='{reverse('projudi:sync_session')}'>Clique aqui para sincronizar</a>"
                )
            else:
                messages.error(request, f"Erro ao sincronizar: {e}")
        finally:
            try:
                service.fechar()
            except Exception:
                pass
        return HttpResponseRedirect(reverse('projudi:mandado_dashboard'))


class MandadoExpedirActionView(LoginRequiredMixin, View):
    """
    POST /projudi/mandados/<pk>/expedir/
    Marca mandado como expedido.
    """
    def post(self, request, pk):
        record = get_object_or_404(MandadoRecord, pk=pk, user=request.user)
        service = MandadoService(request.user)
        try:
            resultado = service.expedir_mandado(record)
            if resultado.get('expedido'):
                messages.success(request, f"Mandado {record.numero_mandado} expedido com sucesso!")
            else:
                messages.error(request, f"Falha ao expedir mandado.")
        except Exception as e:
            messages.error(request, f"Erro: {str(e)[:100]}")
        finally:
            try:
                service.fechar()
            except Exception:
                pass
        return HttpResponseRedirect(reverse('projudi:mandado_detail', kwargs={'pk': pk}))


class MandadoSolicitarExpedicaoView(LoginRequiredMixin, View):
    """
    POST /projudi/mandados/<pk>/solicitar-expedicao/
    Faz SOMENTE o Mov 581 (Solicitar Expedição de Mandado) via Playwright,
    SEM confeccionar o documento.
    """
    def post(self, request, pk):
        record = get_object_or_404(MandadoRecord, pk=pk, user=request.user)
        service = MandadoService(request.user)
        try:
            resultado = service.solicitar_expedicao(record)
            if resultado.get('expedido'):
                messages.success(
                    request,
                    f"✅ Solicitação de expedição registrada (Mov 581) para mandado {record.numero_mandado}!"
                )
            else:
                messages.error(
                    request,
                    f"Falha ao solicitar expedição: {resultado.get('erro', 'Erro desconhecido')}"
                )
        except Exception as e:
            messages.error(request, f"Erro: {str(e)[:200]}")
        finally:
            try:
                service.fechar()
            except Exception:
                pass
        return HttpResponseRedirect(reverse('projudi:mandado_detail', kwargs={'pk': pk}))


class MandadoDispensarView(LoginRequiredMixin, View):
    """
    POST /projudi/mandados/<pk>/dispensar/
    Marca mandado como dispensado.
    """
    def post(self, request, pk):
        record = get_object_or_404(MandadoRecord, pk=pk, user=request.user)
        service = MandadoService(request.user)
        try:
            service.dispensar_mandado(record)
            messages.success(request, f"Mandado {record.numero_mandado} dispensado.")
        except Exception as e:
            messages.error(request, f"Erro: {str(e)[:100]}")
        finally:
            try:
                service.fechar()
            except Exception:
                pass
        return HttpResponseRedirect(reverse('projudi:mandado_dashboard'))


class MandadoLogsJsonView(LoginRequiredMixin, View):
    """
    GET /projudi/mandados/<pk>/logs/json/
    Retorna logs em JSON.
    """
    def get(self, request, pk):
        record = get_object_or_404(MandadoRecord, pk=pk, user=request.user)
        service = MandadoService(request.user)
        logs = service.logs_humanizados(record)
        return JsonResponse({'logs': logs})


class MandadoAbrirProjudiView(LoginRequiredMixin, View):
    """
    GET /projudi/mandados/<pk>/abrir-projudi/
    Abre o mandado no Projudi (redirect).
    """
    def get(self, request, pk):
        record = get_object_or_404(MandadoRecord, pk=pk, user=request.user)
        if record.url_mandado:
            return HttpResponseRedirect(record.url_mandado)
        messages.warning(request, "URL do mandado não disponível.")
        return HttpResponseRedirect(reverse('projudi:mandado_detail', kwargs={'pk': pk}))


class MandadoRastrearView(LoginRequiredMixin, View):
    """
    POST /projudi/mandados/rastrear/
    Varre movimentações, match RAG e expede mandado via Playwright.
    Mesmo fluxo do OficioRastrearCiapView, mas para mandados.
    """
    def post(self, request):
        import subprocess, os, sys

        script_path = os.path.join(settings.BASE_DIR, 'expedir_rapido.py')
        env = {**os.environ, 'DJANGO_ALLOW_ASYNC_UNSAFE': 'true'}

        try:
            result = subprocess.run(
                [sys.executable or 'python3', script_path, '--mandados-only'],
                cwd=settings.BASE_DIR, env=env,
                capture_output=True, text=True,
                timeout=600,
            )

            output = (result.stdout or '') + (result.stderr or '')
            linhas_uteis = [
                l.strip() for l in output.split('\n')
                if l.strip()
            ]

            if result.returncode == 0:
                messages.success(request, '🔍 Rastreamento de mandados concluído! Verifique o resultado.')
            else:
                messages.warning(request, f'⚠️ Código {result.returncode}. Verifique o log.')

            for linha in linhas_uteis[-20:]:
                if any(kw in linha.lower() for kw in ['mandado', '✅', '❌', '🔍', 'match', 'exped', 'erro', 'sucess', '>>', 'rag', 'template', 'processo', 'playwright', 'mov', 'fckeditor', 'registrar']):
                    messages.info(request, linha[:300])

        except subprocess.TimeoutExpired:
            messages.error(request, '⏱️ Rastreamento excedeu 10 minutos. Tente novamente.')
        except Exception as e:
            messages.error(request, f'❌ Erro: {str(e)[:200]}')

        return HttpResponseRedirect(reverse('projudi:mandado_dashboard'))


class RastrearExpedirView(LoginRequiredMixin, View):
    """
    POST /projudi/rastrear-expedir/
    Varre movimentações, match RAG e expede mandados E ofícios.
    """
    def post(self, request):
        return self._executar_script(request, [])

    def _executar_script(self, request, args_extra=None):
        import subprocess, os, sys
        from django.conf import settings

        script_path = os.path.join(settings.BASE_DIR, 'expedir_rapido.py')
        env = {**os.environ, 'DJANGO_ALLOW_ASYNC_UNSAFE': 'true'}
        cmd = [sys.executable or 'python3', script_path]
        if args_extra:
            cmd.extend(args_extra)

        try:
            result = subprocess.run(
                cmd, cwd=settings.BASE_DIR, env=env,
                capture_output=True, text=True,
                timeout=600,
            )

            output = (result.stdout or '') + (result.stderr or '')
            linhas_uteis = [l.strip() for l in output.split('\n') if l.strip()]

            if result.returncode == 0:
                messages.success(request, '🔍 Rastreamento concluído! Verifique o resultado.')
            else:
                messages.warning(request, f'⚠️ Código {result.returncode}. Verifique o log.')

            for linha in linhas_uteis[-30:]:
                if any(kw in linha.lower() for kw in ['✅', '❌', '🔍', 'match', 'exped', 'erro', '>>', 'rag', 'template', 'processo', 'playwright', 'mov', 'fckeditor', 'registrar', 'mandado', 'oficio']):
                    messages.info(request, linha[:300])

        except subprocess.TimeoutExpired:
            messages.error(request, '⏱️ Rastreamento excedeu 10 minutos.')
        except Exception as e:
            messages.error(request, f'❌ Erro: {str(e)[:200]}')

        return HttpResponseRedirect(reverse('projudi:cumprimento_dashboard'))


class RastrearMovimentacoesView(LoginRequiredMixin, View):
    """
    POST /projudi/rastrear-movimentacoes/
    Varre movimentações e expede SÓ atos de movimentação (intimações, certidões, etc).
    """
    def post(self, request):
        return RastrearExpedirView._executar_script(self, request, ['--mov-only'])


class OficioRastrearView(LoginRequiredMixin, View):
    """
    POST /projudi/oficios/rastrear/
    Varre movimentações, match RAG e expede ofícios (CIAP, RPV, etc).
    """
    def post(self, request):
        import subprocess, os, sys
        from django.conf import settings

        script_path = os.path.join(settings.BASE_DIR, 'expedir_rapido.py')
        env = {**os.environ, 'DJANGO_ALLOW_ASYNC_UNSAFE': 'true'}

        try:
            result = subprocess.run(
                [sys.executable or 'python3', script_path, '--oficios-only'],
                cwd=settings.BASE_DIR, env=env,
                capture_output=True, text=True,
                timeout=600,
            )

            output = (result.stdout or '') + (result.stderr or '')
            linhas_uteis = [l.strip() for l in output.split('\n') if l.strip()]

            if result.returncode == 0:
                messages.success(request, '🔍 Rastreamento de ofícios concluído!')
            else:
                messages.warning(request, f'⚠️ Código {result.returncode}. Verifique o log.')

            for linha in linhas_uteis[-30:]:
                if any(kw in linha.lower() for kw in ['✅', '❌', '🔍', 'match', 'exped', 'erro', 'rag', 'template', 'oficio', 'rpv', 'ciap']):
                    messages.info(request, linha[:300])

        except subprocess.TimeoutExpired:
            messages.error(request, '⏱️ Rastreamento excedeu 10 minutos.')
        except Exception as e:
            messages.error(request, f'❌ Erro: {str(e)[:200]}')

        return HttpResponseRedirect(reverse('projudi:oficio_dashboard'))


class AutoRastrearToggleView(LoginRequiredMixin, View):
    """
    POST /projudi/auto-rastrear/toggle/
    Liga/desliga o loop de auto-rastreamento (a cada 5min).
    """
    def post(self, request):
        import subprocess, os, sys
        from django.conf import settings
        script = os.path.join(settings.BASE_DIR, 'auto_rastrear.py')
        pid_file = '/tmp/auto_rastrear.pid'

        if os.path.exists(pid_file):
            try:
                subprocess.run([sys.executable, script, '--stop'], capture_output=True, timeout=10)
                messages.success(request, '⏹️ Auto-rastrear desligado')
            except Exception as e:
                messages.error(request, f'Erro ao desligar: {e}')
        else:
            try:
                subprocess.Popen(
                    [sys.executable, script],
                    cwd=settings.BASE_DIR,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                messages.success(request, '▶️ Auto-rastrear ligado (a cada 5 minutos)')
            except Exception as e:
                messages.error(request, f'Erro ao ligar: {e}')

        return HttpResponseRedirect(reverse('projudi:cumprimento_dashboard'))
