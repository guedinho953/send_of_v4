from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LogoutView
from django.views.generic import CreateView, TemplateView, UpdateView
from django.urls import reverse_lazy

from .models import User, ServerProfile


class RegisterView(CreateView):
    model = User
    template_name = 'accounts/register.html'
    fields = ['email', 'first_name', 'last_name', 'password1', 'password2']
    success_url = reverse_lazy('accounts:login')


class ProfileView(LoginRequiredMixin, UpdateView):
    model = ServerProfile
    template_name = 'accounts/profile.html'
    fields = ['oab', 'specialization']
    success_url = reverse_lazy('accounts:profile')

    def get_object(self, queryset=None):
        profile, created = ServerProfile.objects.get_or_create(user=self.request.user)
        return profile


class PasswordResetView(TemplateView):
    template_name = 'accounts/password_reset.html'


class LogoutGetView(LogoutView):
    """Logout que aceita GET para facilitar o uso."""
    http_method_names = ['get', 'post']
