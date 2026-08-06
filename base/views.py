from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class LandingView(TemplateView):
    template_name = 'base/landing.html'


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'base/dashboard.html'
