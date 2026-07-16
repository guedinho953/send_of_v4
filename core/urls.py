from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse

from base.views import LandingView, DashboardView


def healthcheck(request):
    return JsonResponse({'status': 'ok'})


urlpatterns = [
    path('health/', healthcheck, name='healthcheck'),
    path('admin/', admin.site.urls),
    path('', LandingView.as_view(), name='landing'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('accounts/', include('accounts.urls', namespace='accounts')),
    path('projudi/', include('projudi.urls', namespace='projudi')),
    path('processes/', include('processes.urls', namespace='processes')),
    path('commands/', include('commands.urls', namespace='commands')),
    path('compliances/', include('compliances.urls', namespace='compliances')),
    path('documents/', include('documents.urls', namespace='documents')),
    path('emails/', include('emails_app.urls', namespace='emails')),
    path('ai/', include('ai.urls', namespace='ai')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
