from django.contrib import admin
from datetime import date

from .models import (
    ProjudiSession, Court, Vara, Judge,
    OficioRecord, OficioLog,
    MandadoRecord, MandadoLog,
    CumprimentoRecord, CumprimentoLog,
    MovimentacaoRecord, MovimentacaoLog,
    Feriado, SuspensaoPrazo,
)


@admin.register(ProjudiSession)
class ProjudiSessionAdmin(admin.ModelAdmin):
    list_display = ['user', 'status', 'last_activity', 'tenant']
    list_filter = ['status', 'tenant']
    search_fields = ['user__email']


@admin.register(Court)
class CourtAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'state', 'is_active']
    list_filter = ['state', 'is_active']
    search_fields = ['name', 'code']


@admin.register(Vara)
class VaraAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'comarca', 'court', 'is_active']
    list_filter = ['court', 'is_active']
    search_fields = ['name', 'code', 'comarca']


@admin.register(Judge)
class JudgeAdmin(admin.ModelAdmin):
    list_display = ['name', 'vara', 'email']
    list_filter = ['vara']
    search_fields = ['name']


@admin.register(OficioRecord)
class OficioRecordAdmin(admin.ModelAdmin):
    list_display = ['numero_oficio', 'processo', 'email_destino', 'status',
                    'status_retorno', 'data_envio', 'data_retorno', 'created_at']
    list_filter = ['status', 'status_retorno', 'data_envio', 'created_at']
    search_fields = ['numero_oficio', 'processo', 'email_destino', 'assunto_retorno']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(OficioLog)
class OficioLogAdmin(admin.ModelAdmin):
    list_display = ['oficio', 'tipo', 'mensagem_resumo', 'created_at']
    list_filter = ['tipo', 'created_at']
    search_fields = ['mensagem', 'oficio__numero_oficio']
    readonly_fields = ['created_at']

    def mensagem_resumo(self, obj):
        return obj.mensagem[:80] + '...' if len(obj.mensagem) > 80 else obj.mensagem
    mensagem_resumo.short_description = 'Mensagem'


@admin.register(MandadoRecord)
class MandadoRecordAdmin(admin.ModelAdmin):
    list_display = ['numero_mandado', 'processo', 'parte_nome', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['numero_mandado', 'processo', 'parte_nome']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(MandadoLog)
class MandadoLogAdmin(admin.ModelAdmin):
    list_display = ['mandado', 'tipo', 'mensagem_resumo', 'created_at']
    list_filter = ['tipo', 'created_at']
    search_fields = ['mensagem', 'mandado__numero_mandado']
    readonly_fields = ['created_at']

    def mensagem_resumo(self, obj):
        return obj.mensagem[:80] + '...' if len(obj.mensagem) > 80 else obj.mensagem
    mensagem_resumo.short_description = 'Mensagem'


@admin.register(CumprimentoRecord)
class CumprimentoRecordAdmin(admin.ModelAdmin):
    list_display = ['fluxo', 'processo', 'parte_nome', 'status', 'created_at']
    list_filter = ['fluxo', 'status', 'created_at']
    search_fields = ['processo', 'parte_nome', 'fluxo_justificativa']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(CumprimentoLog)
class CumprimentoLogAdmin(admin.ModelAdmin):
    list_display = ['cumprimento', 'tipo', 'mensagem_resumo', 'created_at']
    list_filter = ['tipo', 'created_at']
    search_fields = ['mensagem', 'cumprimento__processo']
    readonly_fields = ['created_at']

    def mensagem_resumo(self, obj):
        return obj.mensagem[:80] + '...' if len(obj.mensagem) > 80 else obj.mensagem
    mensagem_resumo.short_description = 'Mensagem'


@admin.register(MovimentacaoRecord)
class MovimentacaoRecordAdmin(admin.ModelAdmin):
    list_display = ['act_verb', 'processo', 'categoria', 'status', 'created_at']
    list_filter = ['categoria', 'status', 'created_at']
    search_fields = ['processo', 'act_verb', 'observacao', 'parte_nome']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(MovimentacaoLog)
class MovimentacaoLogAdmin(admin.ModelAdmin):
    list_display = ['movimentacao', 'tipo', 'mensagem_resumo', 'created_at']
    list_filter = ['tipo', 'created_at']
    search_fields = ['mensagem', 'movimentacao__processo']
    readonly_fields = ['created_at']

    def mensagem_resumo(self, obj):
        return obj.mensagem[:80] + '...' if len(obj.mensagem) > 80 else obj.mensagem
    mensagem_resumo.short_description = 'Mensagem'


@admin.register(Feriado)
class FeriadoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'tipo', 'escopo', 'data_ou_fixa', 'court', 'vara',
                    'is_active', 'tenant']
    list_filter = ['tipo', 'escopo', 'is_active', 'court', 'tenant']
    search_fields = ['nome']
    list_editable = ['is_active']
    readonly_fields = ['created_at', 'updated_at']

    def data_ou_fixa(self, obj):
        return obj.as_date(date.today().year) if obj.tipo == 'fixo' else obj.data
    data_ou_fixa.short_description = 'Data'


@admin.register(SuspensaoPrazo)
class SuspensaoPrazoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'tipo', 'escopo', 'data_inicio', 'data_fim',
                    'court', 'vara', 'is_active', 'tenant']
    list_filter = ['tipo', 'escopo', 'is_active', 'court', 'tenant']
    search_fields = ['nome']
    list_editable = ['is_active']
    readonly_fields = ['created_at', 'updated_at']
