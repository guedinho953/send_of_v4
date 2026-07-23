from django.contrib import admin
from django.urls import path, reverse
from django.shortcuts import redirect
from django.utils.safestring import mark_safe
from django.contrib import messages
import json, os

from .models import Process, Party, Movement, Deadline
from .models import MovementCommand, CommunicationTracking, ComplianceHistory, ProcessSummary
from .models import RAGExample, DocumentTemplate, GeneratedDocument


@admin.register(Process)
class ProcessAdmin(admin.ModelAdmin):
    list_display = ['number', 'status', 'vara', 'class_processual', 'created_at']
    list_filter = ['status', 'vara', 'court']
    search_fields = ['number', 'number_normalized']
    actions = ['expedir_ciap']

    def expedir_ciap(self, request, queryset):
        fila = []
        fp = '/tmp/fila_expedir_ciap.json'
        if os.path.exists(fp):
            with open(fp) as f:
                fila = json.load(f)
        for p in queryset:
            if p.number not in fila:
                fila.append(p.number)
        with open(fp, 'w') as f:
            json.dump(fila, f)
        self.message_user(request, mark_safe(
            f'{len(queryset)} processo(s) na fila. Rode no terminal:<br>'
            f'<code>cd /home/ivan/PythonProjects/send_of_v4 && source .venv/bin/activate && python expedir_humanizado.py --fila</code>'
        ))
    expedir_ciap.short_description = "📨 Expedir Ofício CIAP"


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ['name', 'role', 'process', 'has_lawyer']
    list_filter = ['role', 'has_lawyer']
    search_fields = ['name']


@admin.register(Movement)
class MovementAdmin(admin.ModelAdmin):
    list_display = ['process', 'event_number', 'category', 'act_date']
    list_filter = ['category', 'communication_status']
    search_fields = ['process__number']


@admin.register(Deadline)
class DeadlineAdmin(admin.ModelAdmin):
    list_display = ['process', 'type', 'due_date', 'status']
    list_filter = ['type', 'status']


@admin.register(MovementCommand)
class MovementCommandAdmin(admin.ModelAdmin):
    list_display = ['movement', 'act_verb', 'is_completable', 'extracted_at']
    list_filter = ['is_completable', 'act_verb']
    search_fields = ['movement__process__number']


@admin.register(CommunicationTracking)
class CommunicationTrackingAdmin(admin.ModelAdmin):
    list_display = ['process', 'type', 'event_expedido', 'status', 'date_expedido']
    list_filter = ['type', 'status']
    search_fields = ['process__number']


@admin.register(ComplianceHistory)
class ComplianceHistoryAdmin(admin.ModelAdmin):
    list_display = ['process', 'act_verb', 'means_used', 'compliance_date']
    list_filter = ['means_used', 'email_sent', 'juntada_done']
    search_fields = ['process__number']


@admin.register(ProcessSummary)
class ProcessSummaryAdmin(admin.ModelAdmin):
    list_display = ['process', 'is_automatable', 'automation_status', 'last_analysis']
    list_filter = ['is_automatable', 'automation_status']
    search_fields = ['process__number']


@admin.register(RAGExample)
class RAGExampleAdmin(admin.ModelAdmin):
    list_display = ['process', 'evento_despacho', 'despacho_ato', 'active', 'resumo_sequencia']
    list_filter = ['active']
    search_fields = ['process__number', 'despacho_ato']
    filter_horizontal = ['suggested_templates']
    fieldsets = [
        ('Processo', {'fields': ['process', 'oficio', 'evento_despacho']}),
        ('Decisão do Juiz', {'fields': ['despacho_ato', 'despacho_observacao',
                                         'despacho_data', 'despacho_autor']}),
        ('Cumprimentos', {'fields': ['cumprimentos', 'documentos']}),
        ('Sequência de Execução',
         {'fields': ['sequencia_cumprimento'],
          'classes': ['wide'],
          'description':
              'Lista ORDENADA de atos. Exemplo:<br>'
              '<code>[<br>'
              '&nbsp; {"tipo": "movimentacao", "observacao": "Certifique-se..."},<br>'
              '&nbsp; {"tipo": "oficio", "template_id": 7}<br>'
              ']</code>'}),
        ('Controle', {'fields': ['active', 'suggested_templates']}),
    ]
    actions = ['expedir_ciap']

    def resumo_sequencia(self, obj):
        seq = obj.sequencia_cumprimento or []
        if not seq:
            return '—'
        total = len(seq)
        tipos = ', '.join(s.get('tipo', '?') for s in seq[:5])
        if total > 5:
            tipos += f' … +{total-5}'
        return f'{total} passo(s): {tipos}'
    resumo_sequencia.short_description = 'Sequência'

    def expedir_ciap(self, request, queryset):
        fila = []
        fp = '/tmp/fila_expedir_ciap.json'
        if os.path.exists(fp):
            with open(fp) as f:
                fila = json.load(f)
        for rag in queryset:
            if rag.process and rag.process.number not in fila:
                fila.append(rag.process.number)
        with open(fp, 'w') as f:
            json.dump(fila, f)
        n = len([r for r in queryset if r.process])
        self.message_user(request, mark_safe(
            f'{n} processo(s) adicionados à fila. Rode no terminal:<br>'
            f'<code>cd /home/ivan/PythonProjects/send_of_v4 && source .venv/bin/activate && python expedir_humanizado.py --fila</code>'
        ))
    expedir_ciap.short_description = "📨 Expedir Ofício CIAP"


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'template_type', 'active', 'acoes']
    list_filter = ['template_type', 'active']
    search_fields = ['name', 'description']

    def acoes(self, obj):
        url_fila = reverse('admin:expedir-ciap', args=[obj.id])
        url_rastrear = reverse('admin:rastrear-movs', args=[obj.id])
        return mark_safe(
            f'<a class="button" href="{url_fila}" style="background:#28a745;color:#fff;padding:4px 8px;border-radius:4px;text-decoration:none;margin-right:4px;">📨 Expedir CIAP</a>'
            f'<a class="button" href="{url_rastrear}" style="background:#007bff;color:#fff;padding:4px 8px;border-radius:4px;text-decoration:none;">🔍 Rastrear</a>'
        )
    acoes.short_description = 'Ações'

    def get_urls(self):
        urls = super().get_urls()
        return [
            path('<int:template_id>/expedir-ciap/', self.admin_site.admin_view(self.expedir_view), name='expedir-ciap'),
            path('<int:template_id>/rastrear/', self.admin_site.admin_view(self.rastrear_view), name='rastrear-movs'),
        ] + urls

    def expedir_view(self, request, template_id):
        template = DocumentTemplate.objects.get(id=template_id)
        rags = RAGExample.objects.filter(template=template, active=True)
        procs = [r.process for r in rags if r.process]
        if not procs:
            self.message_user(request, 'Nenhum processo ativo com RAG para este template.', level='WARNING')
            return redirect('admin:processes_documenttemplate_change', template_id)
        fp = '/tmp/fila_expedir_ciap.json'
        with open(fp, 'w') as f:
            json.dump([p.number for p in procs], f)
        self.message_user(request, mark_safe(
            f'{len(procs)} processo(s) na fila. Rode no terminal:<br>'
            f'<code>cd /home/ivan/PythonProjects/send_of_v4 && source .venv/bin/activate && python expedir_humanizado.py --fila</code>'
        ))
        return redirect('admin:processes_documenttemplate_change', template_id)

    def rastrear_view(self, request, template_id):
        fp = '/tmp/rastrear_sinal.json'
        with open(fp, 'w') as f:
            json.dump({'rastrear': True, 'paginas': 3, 'template_id': template_id}, f)
        self.message_user(request, mark_safe(
            '✅ Sinal de rastreamento ativado! Rode no terminal:<br>'
            f'<code>cd /home/ivan/PythonProjects/send_of_v4 && source .venv/bin/activate && python expedir_humanizado.py --rastrear</code>'
        ))
        return redirect('admin:processes_documenttemplate_change', template_id)


@admin.register(GeneratedDocument)
class GeneratedDocumentAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'template', 'process', 'recipient_name', 'created_at']
    list_filter = ['template', 'year']
    search_fields = ['process__number', 'recipient_name']
