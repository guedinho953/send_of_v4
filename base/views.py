from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from projudi.models import ProjudiSession


class LandingView(TemplateView):
    template_name = 'base/landing.html'


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'base/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sessao = ProjudiSession.objects.filter(
            user=self.request.user, status='active'
        ).first()
        context['projudi_session'] = sessao
        context['projudi_session_active'] = bool(sessao)
        return context
