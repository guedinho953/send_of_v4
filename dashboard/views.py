from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.utils import timezone

from projudi.models import OficioRecord, ProjudiSession
from projudi.services import ProjudiService


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Estatisticas de oficios
        qs = OficioRecord.objects.filter(user=user)
        context['oficios_total'] = qs.count()
        context['oficios_pendentes'] = qs.filter(status='pendente').count()
        context['oficios_enviados'] = qs.filter(status__in=['enviado', 'juntado']).count()
        context['oficios_juntados'] = qs.filter(status='juntado').count()
        context['oficios_falhas'] = qs.filter(status__in=['falhou_email', 'falhou_juntada']).count()

        # Ultimos 5 oficios
        context['ultimos_oficios'] = qs.order_by('-created_at')[:5]

        # Status da sessao Projudi
        context['session_active'] = self._session_ativa(user)

        # Ultima sincronizacao
        ultima = qs.order_by('-updated_at').first()
        if ultima:
            context['ultima_sync'] = ultima.updated_at.strftime('%d/%m/%Y %H:%M')

        return context

    def _session_ativa(self, user):
        try:
            sessao = ProjudiSession.objects.filter(user=user, status='active').first()
            if sessao:
                svc = ProjudiService(user)
                return svc.check_session()
        except Exception:
            pass
        return False
