"""Dashboard de Certidões.

Separa as certidões em dois grupos:

- **Análises de petições**: `MovimentacaoRecord` com `rag_example` preenchido
  (a certidão nasceu de uma decisão/petição analisada pela RAG).
- **Movimentações**: `MovimentacaoRecord` sem `rag_example`
  (a certidão nasceu da varredura de movimentações do Projudi).
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from .models import MovimentacaoRecord, ProjudiSession
from .services import ProjudiService


class CertidaoDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'projudi/certidao_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        qs = MovimentacaoRecord.objects.filter(
            user=user, categoria='certidao'
        )

        status_filter = self.request.GET.get('status', '')
        if status_filter and status_filter in dict(
                MovimentacaoRecord.STATUS_CHOICES):
            qs = qs.filter(status=status_filter)

        peticoes = qs.filter(rag_example__isnull=False)
        movimentacoes = qs.filter(rag_example__isnull=True)

        total_peticoes = peticoes.count()
        total_movimentacoes = movimentacoes.count()

        origem = self.request.GET.get('origem', '')
        if origem == 'peticao':
            movimentacoes = movimentacoes.none()
        elif origem == 'movimentacao':
            peticoes = peticoes.none()

        context.update({
            'total': qs.count(),
            'total_peticoes': total_peticoes,
            'total_movimentacoes': total_movimentacoes,
            'pendentes': qs.filter(status='pendente').count(),
            'processando': qs.filter(status='processando').count(),
            'cumpridos': qs.filter(status='cumprido').count(),
            'falhas': qs.filter(status='falha').count(),
            'dispensados': qs.filter(status='dispensado').count(),
            'certidoes_peticoes': peticoes.order_by('-created_at')[:100],
            'certidoes_movimentacoes': movimentacoes.order_by('-created_at')[:100],
            'status_atual': status_filter,
            'origem_atual': origem,
            'session_active': self._session_ativa(user),
        })
        return context

    def _session_ativa(self, user):
        try:
            sessao = ProjudiSession.objects.filter(
                user=user, status='active').first()
            if sessao:
                return ProjudiService(user).check_session()
        except Exception:
            pass
        return False
