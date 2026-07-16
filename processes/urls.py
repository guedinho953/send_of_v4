from django.urls import path
from . import views
from . import views_movimentacoes

app_name = 'processes'

urlpatterns = [
    path('', views.ProcessListView.as_view(), name='list'),
    path('<int:pk>/', views.ProcessDetailView.as_view(), name='detail'),
    # Pipeline de movimentacoes - visualizacao
    path('<int:pk>/movimentacoes/', views.ProcessMovimentacoesView.as_view(), name='movimentacoes'),
    path('<int:pk>/movimentacoes/processar/', views.processar_movimentacoes_view, name='processar_movimentacoes'),
    # Pipeline de movimentacoes - API
    path('<int:process_id>/analisar-movimentacoes/', views_movimentacoes.analisar_movimentacoes, name='analisar_movimentacoes'),
    path('<int:process_id>/resumo-movimentacoes/', views_movimentacoes.resumo_movimentacoes, name='resumo_movimentacoes'),
    path('<int:process_id>/comandos-pendentes/', views_movimentacoes.comandos_pendentes, name='comandos_pendentes'),
    path('<int:process_id>/comunicacoes-rastreadas/', views_movimentacoes.comunicacoes_rastreadas, name='comunicacoes_rastreadas'),
    path('<int:process_id>/buscar-dados-processo/', views_movimentacoes.buscar_dados_processo, name='buscar_dados_processo'),
    path('extrair-todas/', views.extrair_todas_movimentacoes_view, name='extrair_todas'),
    path('compliance/', views.compliance_history_list, name='compliance_list'),
    path('compliance/<int:pk>/toggle/', views.compliance_history_toggle, name='compliance_toggle'),
    path('compliance/<int:pk>/delete/', views.compliance_history_delete, name='compliance_delete'),
    path('compliance/<int:pk>/edit-obs/', views.compliance_edit_obs, name='compliance_edit_obs'),
    path('compliance/<int:pk>/gerar-documento/<int:template_id>/', views.gerar_documento, name='gerar_documento'),
]
