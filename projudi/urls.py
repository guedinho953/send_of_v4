from django.urls import path
from . import views
from . import oficio_views
from . import mandado_views
from . import cumprimento_views
from . import movimentacao_views

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
    path('oficios/juntar-em-massa/', oficio_views.OficioBulkJuntarView.as_view(), name='oficio_bulk_juntar'),
    path('oficios/dispensar-em-massa/', oficio_views.OficioBulkDispensarView.as_view(), name='oficio_bulk_dispensar'),
    path('oficios/dispensar-juntados/', oficio_views.OficioBulkDispensarJuntadosView.as_view(), name='oficio_bulk_dispensar_juntados'),
    path('oficios/<int:pk>/logs/json/', oficio_views.OficioLogsJsonView.as_view(), name='oficio_logs_json'),
    path('oficios/expedir-ciap/', oficio_views.OficioExpedirCiapView.as_view(), name='oficio_expedir_ciap'),
    path('oficios/rastrear-ciap/', oficio_views.OficioRastrearCiapView.as_view(), name='oficio_rastrear_ciap'),
    path('oficios/expedir-ciap-proc/', oficio_views.OficioExpedirCiapProcessoView.as_view(), name='oficio_expedir_ciap_processo'),
    path('oficios/processar-pendentes/', oficio_views.OficioProcessarPendentesView.as_view(), name='oficio_processar_pendentes'),

    # Aba Mandados
    path('mandados/dashboard/', mandado_views.MandadoDashboardView.as_view(), name='mandado_dashboard'),
    path('mandados/lista/', mandado_views.MandadoListView.as_view(), name='mandado_list'),
    path('mandados/sync/', mandado_views.MandadoSyncView.as_view(), name='mandado_sync'),
    path('mandados/<int:pk>/', mandado_views.MandadoDetailView.as_view(), name='mandado_detail'),
    path('mandados/<int:pk>/expedir/', mandado_views.MandadoExpedirActionView.as_view(), name='mandado_expedir_action'),
    path('mandados/<int:pk>/solicitar-expedicao/', mandado_views.MandadoSolicitarExpedicaoView.as_view(), name='mandado_solicitar_expedicao'),
    path('mandados/<int:pk>/dispensar/', mandado_views.MandadoDispensarView.as_view(), name='mandado_dispensar'),
    path('mandados/<int:pk>/logs/json/', mandado_views.MandadoLogsJsonView.as_view(), name='mandado_logs_json'),
    path('mandados/<int:pk>/abrir-projudi/', mandado_views.MandadoAbrirProjudiView.as_view(), name='mandado_abrir_projudi'),
    path('mandados/rastrear/', mandado_views.MandadoRastrearView.as_view(), name='mandado_rastrear'),
    path('oficios/rastrear/', mandado_views.OficioRastrearView.as_view(), name='oficio_rastrear'),
    path('rastrear-expedir/', mandado_views.RastrearExpedirView.as_view(), name='rastrear_expedir'),
    path('rastrear-movimentacoes/', mandado_views.RastrearMovimentacoesView.as_view(), name='rastrear_movimentacoes'),
    path('auto-rastrear/toggle/', mandado_views.AutoRastrearToggleView.as_view(), name='auto_rastrear_toggle'),

    # Aba Retornos (GERENCIAMENTO DE RESPOSTAS)
    path('retornos/dashboard/', oficio_views.RetornoDashboardView.as_view(), name='retorno_dashboard'),
    path('retornos/lista/', oficio_views.RetornoListView.as_view(), name='retorno_list'),
    path('retornos/<int:pk>/', oficio_views.RetornoDetailView.as_view(), name='retorno_detail'),
    path('retornos/<int:pk>/processar/', oficio_views.RetornoProcessarView.as_view(), name='retorno_processar'),
    path('retornos/<int:pk>/juntar-resposta/', oficio_views.RetornoJuntarRespostaView.as_view(), name='retorno_juntar_resposta'),
    path('retornos/importar/', oficio_views.RetornoImportarView.as_view(), name='retorno_importar'),
    path('retornos/juntar-todos/', oficio_views.RetornoJuntarTodosView.as_view(), name='retorno_juntar_todos'),

    # Aba Cumprimentos (NOVO FLUXO — atos de secretaria)
    path('cumprimentos/dashboard/', cumprimento_views.CumprimentoDashboardView.as_view(), name='cumprimento_dashboard'),
    path('cumprimentos/lista/', cumprimento_views.CumprimentoListView.as_view(), name='cumprimento_list'),
    path('cumprimentos/sync/', cumprimento_views.CumprimentoSyncView.as_view(), name='cumprimento_sync'),
    path('cumprimentos/<int:pk>/', cumprimento_views.CumprimentoDetailView.as_view(), name='cumprimento_detail'),
    path('cumprimentos/<int:pk>/executar/', cumprimento_views.CumprimentoExecutarView.as_view(), name='cumprimento_executar'),
    path('cumprimentos/<int:pk>/expedir-rapido/', cumprimento_views.CumprimentoExpedirRapidoView.as_view(), name='cumprimento_expedir_rapido'),
    path('cumprimentos/<int:pk>/dispensar/', cumprimento_views.CumprimentoDispensarView.as_view(), name='cumprimento_dispensar'),
    path('cumprimentos/executar-todos/', cumprimento_views.CumprimentoBatchView.as_view(), name='cumprimento_batch'),
    path('cumprimentos/<int:pk>/logs/json/', cumprimento_views.CumprimentoLogsJsonView.as_view(), name='cumprimento_logs_json'),

    # Aba Movimentações (NOVO — atos internos via Mov581)
    path('movimentacoes/dashboard/', movimentacao_views.MovimentacaoDashboardView.as_view(), name='movimentacao_dashboard'),
    path('movimentacoes/lista/', movimentacao_views.MovimentacaoListView.as_view(), name='movimentacao_list'),
    path('movimentacoes/sync/', movimentacao_views.MovimentacaoSyncView.as_view(), name='movimentacao_sync'),
    path('movimentacoes/<int:pk>/', movimentacao_views.MovimentacaoDetailView.as_view(), name='movimentacao_detail'),
    path('movimentacoes/<int:pk>/executar/', movimentacao_views.MovimentacaoExecutarView.as_view(), name='movimentacao_executar'),
    path('movimentacoes/<int:pk>/dispensar/', movimentacao_views.MovimentacaoDispensarView.as_view(), name='movimentacao_dispensar'),
    path('movimentacoes/executar-todos/', movimentacao_views.MovimentacaoBatchView.as_view(), name='movimentacao_batch'),
    path('movimentacoes/<int:pk>/logs/json/', movimentacao_views.MovimentacaoLogsJsonView.as_view(), name='movimentacao_logs_json'),
]
