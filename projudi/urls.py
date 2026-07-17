from django.urls import path
from . import views
from . import oficio_views

app_name = 'projudi'

urlpatterns = [
    path('sessao/sincronizar/', views.SyncSessionView.as_view(), name='sync'),
    path('sessao/status/', views.SessionStatusView.as_view(), name='session_status'),
    path('sessao/', views.SyncSessionTemplateView.as_view(), name='sync_session'),
    path('movimentacoes/', views.MovimentacoesListView.as_view(), name='movimentacoes'),
    path('oficios/', views.OficiosListView.as_view(), name='oficios'),

    # Aba Oficios (ENVIO)
    path('oficios/dashboard/', oficio_views.OficioDashboardView.as_view(), name='oficio_dashboard'),
    path('oficios/lista/', oficio_views.OficioListView.as_view(), name='oficio_list'),
    path('oficios/<int:pk>/', oficio_views.OficioDetailView.as_view(), name='oficio_detail'),
    path('oficios/sync/', oficio_views.OficioSyncView.as_view(), name='oficio_sync'),
    path('oficios/<int:pk>/enviar/', oficio_views.OficioSendView.as_view(), name='oficio_send'),
    path('oficios/<int:pk>/dispensar/', oficio_views.OficioDispensarView.as_view(), name='oficio_dispensar'),
    path('oficios/<int:pk>/juntar/', oficio_views.OficioJuntarView.as_view(), name='oficio_juntar'),
    path('oficios/enviar-em-massa/', oficio_views.OficioBulkSendView.as_view(), name='oficio_bulk_send'),
    path('oficios/<int:pk>/logs/json/', oficio_views.OficioLogsJsonView.as_view(), name='oficio_logs_json'),
    path('oficios/expedir-ciap/', oficio_views.OficioExpedirCiapView.as_view(), name='oficio_expedir_ciap'),
    path('oficios/rastrear-ciap/', oficio_views.OficioRastrearCiapView.as_view(), name='oficio_rastrear_ciap'),
    path('oficios/expedir-ciap-proc/', oficio_views.OficioExpedirCiapProcessoView.as_view(), name='oficio_expedir_ciap_processo'),
    path('oficios/processar-pendentes/', oficio_views.OficioProcessarPendentesView.as_view(), name='oficio_processar_pendentes'),

    # Aba Retornos (GERENCIAMENTO DE RESPOSTAS)
    path('retornos/dashboard/', oficio_views.RetornoDashboardView.as_view(), name='retorno_dashboard'),
    path('retornos/lista/', oficio_views.RetornoListView.as_view(), name='retorno_list'),
    path('retornos/<int:pk>/', oficio_views.RetornoDetailView.as_view(), name='retorno_detail'),
    path('retornos/<int:pk>/processar/', oficio_views.RetornoProcessarView.as_view(), name='retorno_processar'),
    path('retornos/<int:pk>/juntar-resposta/', oficio_views.RetornoJuntarRespostaView.as_view(), name='retorno_juntar_resposta'),
    path('retornos/importar/', oficio_views.RetornoImportarView.as_view(), name='retorno_importar'),
    path('retornos/juntar-todos/', oficio_views.RetornoJuntarTodosView.as_view(), name='retorno_juntar_todos'),
]
