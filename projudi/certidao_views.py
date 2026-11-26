"""Dashboard de certidões/prazos DJEN (controle interno)."""

import json
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.views.generic import DetailView, TemplateView

from .models import PrazoDjenRecord
from .prazo_service import TIPOS_PRAZO


def _status_registro(reg):
    if reg.tempestivo is True:
        return 'tempestivo', 'TEMPESTIVO'
    if reg.tempestivo is False:
        return 'intempestivo', 'INTEMPESTIVO'
    return 'sem_protocolo', 'SEM PROTOCOLO'


def _datas_br(valores):
    resultado = []
    for valor in valores or []:
        try:
            resultado.append(
                datetime.strptime(str(valor)[:10], '%Y-%m-%d')
                .strftime('%d/%m/%Y'))
        except ValueError:
            resultado.append(str(valor))
    return resultado


class CertidaoDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'projudi/certidao_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base = PrazoDjenRecord.objects.all()

        busca = (self.request.GET.get('q') or '').strip()
        status = (self.request.GET.get('status') or '').strip()
        tipo = (self.request.GET.get('tipo') or '').strip()

        qs = base
        if busca:
            qs = qs.filter(
                Q(processo__icontains=busca)
                | Q(parte__icontains=busca)
                | Q(motivo__icontains=busca)
            )
        if status == 'tempestivo':
            qs = qs.filter(tempestivo=True)
        elif status == 'intempestivo':
            qs = qs.filter(tempestivo=False)
        elif status == 'sem_protocolo':
            qs = qs.filter(tempestivo__isnull=True)
        if tipo:
            qs = qs.filter(tipo_prazo=tipo)

        registros = list(qs.order_by('-created_at')[:200])
        for reg in registros:
            reg.status_classe, reg.status_label = _status_registro(reg)
            reg.tipo_label = TIPOS_PRAZO.get(
                reg.tipo_prazo, {}).get('label', reg.tipo_prazo)

        context.update({
            'registros': registros,
            'total': base.count(),
            'tempestivas': base.filter(tempestivo=True).count(),
            'intempestivas': base.filter(tempestivo=False).count(),
            'sem_protocolo': base.filter(tempestivo__isnull=True).count(),
            'busca': busca,
            'filtro_status': status,
            'filtro_tipo': tipo,
            'tipos': [
                {'valor': chave, **info}
                for chave, info in TIPOS_PRAZO.items()
            ],
        })
        return context


class CertidaoDetailView(LoginRequiredMixin, DetailView):
    model = PrazoDjenRecord
    template_name = 'projudi/certidao_detail.html'
    context_object_name = 'registro'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        reg = self.object
        context['status_classe'], context['status_label'] = _status_registro(reg)
        context['tipo_label'] = TIPOS_PRAZO.get(
            reg.tipo_prazo, {}).get('label', reg.tipo_prazo)
        info = reg.prazo_info or {}
        context['dias_contados_br'] = _datas_br(info.get('dias_contados'))
        context['dias_excluidos_br'] = _datas_br(info.get('dias_excluidos'))
        context['prazo_info_pretty'] = json.dumps(
            info, indent=2, ensure_ascii=False, default=str)
        context['preview_disponivel'] = bool(reg.certidao_path)
        return context


class CertidaoPreviewView(LoginRequiredMixin, View):
    """Serve o HTML do preview salvo em var/ (sem expor outros arquivos)."""

    def get(self, request, pk):
        reg = get_object_or_404(PrazoDjenRecord, pk=pk)
        if not reg.certidao_path:
            raise Http404('Esta certidão não tem preview salvo.')

        caminho = Path(reg.certidao_path).expanduser()
        try:
            caminho = caminho.resolve()
        except OSError:
            raise Http404('Caminho do preview inválido.')

        pasta_var = (Path(settings.BASE_DIR) / 'var').resolve()
        if pasta_var not in caminho.parents or not caminho.is_file():
            raise Http404(
                'Preview fora da pasta var/ ou arquivo inexistente.')

        return HttpResponse(
            caminho.read_text(encoding='utf-8'),
            content_type='text/html; charset=utf-8',
        )
