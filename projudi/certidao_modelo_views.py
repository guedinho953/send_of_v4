"""Cadastro de modelos de certidão dentro do módulo de Certidões."""
from datetime import date

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from processes.models import DocumentTemplate


SAMPLE_CONTEXT = {
    'processo': '0000000-00.0000.8.05.0191',
    'parte': 'FULANO DE TAL',
    'recorrente': 'FULANO DE TAL',
    'data': date.today().strftime('%d/%m/%Y'),
    'servidor': 'Ivan Guedes da Silva',
    'servidor_cargo': 'Secretário em Substituição',
    'observacao_prazo': (
        'Certifico que o prazo transcorreu integralmente.'
    ),
    'descricao_movimentacao': 'Certifique-se o decurso de prazo.',
    'texto_certidao': (
        'Certifico, para os devidos fins, que não existem custas '
        'processuais pendentes.'
    ),
}


class CertidaoModeloListView(LoginRequiredMixin, View):
    template_name = 'projudi/certidao_modelos.html'

    def get(self, request):
        modelos = (
            DocumentTemplate.objects
            .filter(template_type='certidao')
            .prefetch_related('rag_examples')
            .order_by('name')
        )
        return render(request, self.template_name, {
            'modelos': modelos,
            'total': modelos.count(),
            'ativos': modelos.filter(active=True).count(),
        })


class CertidaoModeloCreateView(LoginRequiredMixin, View):
    template_name = 'projudi/certidao_modelo_form.html'

    def get(self, request):
        return render(request, self.template_name, {
            'modelo': None,
            'valores': {
                'name': '',
                'description': '',
                'html_template': '',
                'active': True,
            },
        })

    def post(self, request):
        nome = (request.POST.get('name') or '').strip()
        descricao = (request.POST.get('description') or '').strip()
        html = (request.POST.get('html_template') or '').strip()
        ativo = request.POST.get('active') == '1'

        if not nome or not html:
            messages.error(request, 'Nome e template HTML são obrigatórios.')
            return render(request, self.template_name, {
                'modelo': None,
                'valores': {
                    'name': nome,
                    'description': descricao,
                    'html_template': html,
                    'active': ativo,
                },
            })

        modelo = DocumentTemplate.objects.create(
            name=nome,
            template_type='certidao',
            description=descricao,
            html_template=html,
            active=ativo,
        )
        messages.success(request, f'✅ Modelo "{modelo.name}" criado.')
        return redirect('projudi:certidao_modelos')


class CertidaoModeloUpdateView(LoginRequiredMixin, View):
    template_name = 'projudi/certidao_modelo_form.html'

    def get(self, request, pk):
        modelo = get_object_or_404(
            DocumentTemplate, pk=pk, template_type='certidao'
        )
        return render(request, self.template_name, {
            'modelo': modelo,
            'valores': {
                'name': modelo.name,
                'description': modelo.description,
                'html_template': modelo.html_template,
                'active': modelo.active,
            },
        })

    def post(self, request, pk):
        modelo = get_object_or_404(
            DocumentTemplate, pk=pk, template_type='certidao'
        )
        nome = (request.POST.get('name') or '').strip()
        descricao = (request.POST.get('description') or '').strip()
        html = (request.POST.get('html_template') or '').strip()
        ativo = request.POST.get('active') == '1'

        if not nome or not html:
            messages.error(request, 'Nome e template HTML são obrigatórios.')
            return render(request, self.template_name, {
                'modelo': modelo,
                'valores': {
                    'name': nome,
                    'description': descricao,
                    'html_template': html,
                    'active': ativo,
                },
            })

        modelo.name = nome
        modelo.description = descricao
        modelo.html_template = html
        modelo.active = ativo
        modelo.save(update_fields=[
            'name', 'description', 'html_template', 'active',
        ])
        messages.success(request, f'✅ Modelo "{modelo.name}" atualizado.')
        return redirect('projudi:certidao_modelos')


class CertidaoModeloPreviewView(LoginRequiredMixin, View):
    template_name = 'projudi/certidao_modelo_preview.html'

    def get(self, request, pk):
        modelo = get_object_or_404(
            DocumentTemplate, pk=pk, template_type='certidao'
        )
        html = modelo.render(SAMPLE_CONTEXT)
        return render(request, self.template_name, {
            'modelo': modelo,
            'html_content': html,
        })


class CertidaoModeloDuplicarView(LoginRequiredMixin, View):
    def post(self, request, pk):
        origem = get_object_or_404(
            DocumentTemplate, pk=pk, template_type='certidao'
        )
        copia = DocumentTemplate.objects.create(
            name=f'{origem.name} (cópia)',
            template_type='certidao',
            description=origem.description,
            html_template=origem.html_template,
            active=False,
        )
        messages.success(
            request,
            f'✅ Cópia criada: "{copia.name}". Ela está inativa; '
            'edite e ative quando estiver pronta.'
        )
        return redirect('projudi:certidao_modelo_editar', pk=copia.pk)


class CertidaoModeloToggleView(LoginRequiredMixin, View):
    def post(self, request, pk):
        modelo = get_object_or_404(
            DocumentTemplate, pk=pk, template_type='certidao'
        )
        modelo.active = not modelo.active
        modelo.save(update_fields=['active'])
        estado = 'ativado' if modelo.active else 'desativado'
        messages.success(request, f'✅ Modelo "{modelo.name}" {estado}.')
        return redirect('projudi:certidao_modelos')
