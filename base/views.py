from django.views.generic import TemplateView


class LandingView(TemplateView):
    template_name = 'base/landing.html'


class DashboardView(TemplateView):
    template_name = 'base/dashboard.html'
