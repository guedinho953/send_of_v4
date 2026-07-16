from django.contrib import admin

from .models import ProjudiSession, Court, Vara, Judge, OficioRecord, OficioLog


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
    list_display = ['numero_oficio', 'processo', 'email_destino', 'status', 'status_retorno', 'data_envio', 'data_retorno', 'created_at']
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
