from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views import View
from django.views.generic import ListView, TemplateView
from django.contrib import messages

from .models import ProjudiSession
from .services import ProjudiService


class SyncSessionView(LoginRequiredMixin, View):
    """
    Sincroniza cookies do Firefox com o Django.
    O usuario deve estar logado no Projudi no Firefox antes de clicar.
    """
    def get(self, request):
        service = ProjudiService(request.user)
        try:
            bot = service.get_bot()
            bot.criar_sessao()
            
            if not bot.testar_login():
                messages.error(request, 
                    "Nao foi possivel capturar a sessao. "
                    "Certifique-se de estar logado no Projudi no Firefox."
                )
                return HttpResponseRedirect(reverse('projudi:sync_session'))
            
            # Salva/Atualiza sessao no banco
            cookies = bot.exportar_cookies()
            session, created = ProjudiSession.objects.update_or_create(
                user=request.user,
                defaults={
                    'cookies': cookies,
                    'status': 'active',
                    'tenant': request.user.tenant,
                    'session_data': {'user_agent': bot.session.headers.get('User-Agent')},
                }
            )
            
            # Inicia keep-alive
            bot.iniciar_keep_alive()
            
            msg = "Sessao sincronizada com sucesso!" if created else "Sessao atualizada!"
            messages.success(request, msg)
            
        except Exception as e:
            messages.error(request, f"Erro ao sincronizar: {str(e)}")
        
        return HttpResponseRedirect(reverse('projudi:sync_session'))


class SessionStatusView(LoginRequiredMixin, View):
    def get(self, request):
        try:
            session = ProjudiSession.objects.filter(
                user=request.user, 
                status='active'
            ).first()
            
            if session:
                # Testa se ainda funciona
                service = ProjudiService(request.user)
                is_active = service.check_session()
                
                if not is_active:
                    session.status = 'expired'
                    session.save()
                
                return JsonResponse({
                    'status': 'active' if is_active else 'expired',
                    'message': 'Sessao ativa' if is_active else 'Sessao expirada - sincronize novamente',
                    'last_activity': session.last_activity.isoformat(),
                })
            
            return JsonResponse({
                'status': 'inactive',
                'message': 'Nenhuma sessao encontrada. Faca login no Firefox e sincronize.',
            })
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


class MovimentacoesListView(LoginRequiredMixin, ListView):
    template_name = 'projudi/movimentacoes_list.html'
    context_object_name = 'movimentacoes'

    def get_queryset(self):
        service = ProjudiService(self.request.user)
        try:
            return service.list_movimentacoes()
        except Exception as e:
            messages.error(self.request, f"Erro ao buscar movimentacoes: {e}")
            return []
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['session_active'] = ProjudiSession.objects.filter(
            user=self.request.user, 
            status='active'
        ).exists()
        return context


class OficiosListView(LoginRequiredMixin, ListView):
    template_name = 'projudi/oficios_list.html'
    context_object_name = 'oficios'

    def get_queryset(self):
        service = ProjudiService(self.request.user)
        try:
            return service.list_oficios()
        except Exception as e:
            messages.error(self.request, f"Erro ao buscar oficios: {e}")
            return []


class SyncSessionTemplateView(LoginRequiredMixin, TemplateView):
    template_name = 'projudi/sync_session.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['session'] = ProjudiSession.objects.filter(
            user=self.request.user
        ).first()
        return context

class MandadoExpedirView(LoginRequiredMixin, View):
    """GET /projudi/mandados/expedir/ - Abre listagem de mandados no Projudi"""
    def get(self, request):
        from projudi.services import ProjudiService
        service = ProjudiService(request.user)
        try:
            # Usa a sessão para acessar a listagem de mandados
            result = service._get_session_from_cookies()
            if result is None:
                from django.contrib import messages
                messages.error(request, "Sessao do Projudi nao disponivel. Sincronize primeiro.")
                return HttpResponseRedirect(reverse('projudi:sync_session'))
            session, cookies = result
            from bs4 import BeautifulSoup
            url = 'https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=mandado&acao=expedir'
            resp = session.get(url, timeout=15)
            if resp.status_code == 200 and 'login' not in resp.url.lower():
                soup = BeautifulSoup(resp.text, 'html.parser')
                texto = soup.get_text(" ", strip=True)[:500]
                from django.contrib import messages
                messages.success(request, f"Mandados carregados ({len(resp.text)} bytes). Implementacao em andamento.")
            else:
                from django.contrib import messages
                messages.error(request, "Nao foi possivel acessar a listagem de mandados. Sessao expirou?")
        except Exception as e:
            from django.contrib import messages
            messages.error(request, f"Erro: {str(e)[:100]}")
        finally:
            try:
                service.fechar()
            except Exception:
                pass
        return HttpResponseRedirect(reverse('projudi:oficio_dashboard'))
