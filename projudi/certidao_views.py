"""Dashboard de Certidões.

Separa as certidões/procedimentos em dois grupos, pelo campo `origem`:

- **Petições**: gerados pela fila/análise de petições;
- **Movimentações**: gerados pela análise/varredura de movimentações.

Tudo fica dentro do módulo de Certidões; o dashboard de Movimentações não
lista mais os registros com `categoria='certidao'`.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from .models import (
    CumprimentoRecord, MovimentacaoRecord, ProjudiSession,
)
from .services import ProjudiService


class CertidaoDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'projudi/certidao_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        qs = MovimentacaoRecord.objects.filter(
            user=user, categoria='certidao'
        )

        status_filter = self.request.GET.get('status', '')
        if status_filter and status_filter in dict(
                MovimentacaoRecord.STATUS_CHOICES):
            qs = qs.filter(status=status_filter)

        peticoes = qs.filter(origem='peticao')
        movimentacoes = qs.exclude(origem='peticao')

        # Certidões originadas de RAG de despacho/movimentação. Ainda não
        # são MovimentacaoRecord: ficam aqui para revisão e execução
        # individual, sem executar todos os cumprimentos.
        certidoes_rag = (
            CumprimentoRecord.objects
            .filter(user=user, template_used__template_type='certidao')
            .exclude(status='dispensado')
            .select_related('rag_example', 'template_used')
            .order_by('-created_at')
        )
        rag_pendentes = certidoes_rag.filter(
            status__in=['pendente', 'falha']
        ).count()

        total_peticoes = peticoes.count()
        total_movimentacoes = movimentacoes.count()

        origem = self.request.GET.get('origem', '')
        if origem == 'peticao':
            movimentacoes = movimentacoes.none()
        elif origem == 'movimentacao':
            peticoes = peticoes.none()

        context.update({
            'total': qs.count(),
            'total_peticoes': total_peticoes,
            'total_movimentacoes': total_movimentacoes,
            'pendentes': qs.filter(status='pendente').count(),
            'processando': qs.filter(status='processando').count(),
            'cumpridos': qs.filter(status='cumprido').count(),
            'falhas': qs.filter(status='falha').count(),
            'dispensados': qs.filter(status='dispensado').count(),
            'certidoes_peticoes': peticoes.order_by('-created_at')[:100],
            'certidoes_movimentacoes': movimentacoes.order_by('-created_at')[:100],
            'certidoes_rag': certidoes_rag[:100],
            'total_rag': certidoes_rag.count(),
            'rag_pendentes': rag_pendentes,
            'status_atual': status_filter,
            'origem_atual': origem,
            'session_active': self._session_ativa(user),
        })
        return context

    def _session_ativa(self, user):
        try:
            sessao = ProjudiSession.objects.filter(
                user=user, status='active').first()
            if sessao:
                return ProjudiService(user).check_session()
        except Exception:
            pass
        return False


class CertidaoRastrearRagView(LoginRequiredMixin, View):
    """Varre movimentações, faz match RAG e importa só certidões de despacho.

    Diferente da sincronização de Cumprimentos, aqui os templates válidos
    são apenas `template_type='certidao'`. O usuário depois executa somente
    as certidões (individualmente ou em lote), sem executar todos os
    cumprimentos/movimentações.
    """

    def post(self, request):
        from projudi_client import ProjudiClient
        from bs4 import BeautifulSoup
        from processes.models import DocumentTemplate
        from .cumprimento_service import CumprimentoService
        from .movimentacao_utils import filtrar_hoje

        service = CumprimentoService(request.user)
        somente_hoje = request.POST.get('hoje') == '1'
        try:
            result = service.projudi_service._get_session_from_cookies()
            if not result:
                messages.error(
                    request,
                    'Sessão do Projudi não disponível. Sincronize primeiro.'
                )
                return HttpResponseRedirect(
                    reverse('projudi:certidao_dashboard')
                )

            session, cookies_dict = result
            client = ProjudiClient()
            client.session = session
            client.cookies = cookies_dict

            pages = client.obter_paginas_finais_movimentacoes(quantidade=3)
            movs = []
            for pagina in pages:
                data = {'pagina': str(pagina), 'loginJuiz': ''}
                resposta = session.post(
                    client.URL_MOVIMENTACOES, data=data, timeout=15
                )
                if len(resposta.text) > 1000:
                    soup = BeautifulSoup(resposta.text, 'html.parser')
                    movs.extend(
                        client.extrair_links_movimentacoes(soup)
                    )

            if somente_hoje:
                movs = filtrar_hoje(movs)

            if not movs:
                messages.info(
                    request,
                    'Nenhuma movimentação encontrada nas últimas páginas.'
                )
                return HttpResponseRedirect(
                    reverse('projudi:certidao_dashboard')
                )

            templates_certidao = DocumentTemplate.objects.filter(
                active=True, template_type='certidao'
            )
            decisoes = service.buscar_cumprimentos_pendentes(
                movs, session, cookies_dict,
                templates_validos=templates_certidao,
            )

            importados = 0
            for decisao in decisoes:
                try:
                    record = service.importar_cumprimento(decisao)
                    if record:
                        importados += 1
                except Exception as exc:
                    print(f'[CertidaoRAG] Erro importando: {exc}')

            if importados:
                sufixo = ' de hoje' if somente_hoje else ''
                messages.success(
                    request,
                    f'🔎 {importados} certidão(ões) de RAG{sufixo} '
                    'identificada(s). Confira a lista e execute somente as '
                    'certidões desejadas.'
                )
            else:
                messages.info(
                    request,
                    'Nenhuma certidão de RAG nova foi identificada.'
                )
        except Exception as exc:
            messages.error(request, f'Erro ao rastrear RAG: {exc}')

        return HttpResponseRedirect(reverse('projudi:certidao_dashboard'))


class CertidaoExecutarRagView(LoginRequiredMixin, View):
    """Executa uma única certidão originada de RAG de despacho."""

    def post(self, request, pk):
        from .cumprimento_service import CumprimentoService

        record = get_object_or_404(
            CumprimentoRecord,
            pk=pk,
            user=request.user,
            template_used__template_type='certidao',
        )
        service = CumprimentoService(request.user)
        try:
            service.executar_cumprimento(record)
            record.refresh_from_db()
            if record.status == 'cumprido':
                messages.success(
                    request,
                    f'✅ Certidão do processo {record.processo} cumprida.'
                )
            else:
                messages.warning(
                    request,
                    f'⚠️ A certidão do processo {record.processo} terminou '
                    f'com status {record.get_status_display()}.'
                )
        except Exception as exc:
            messages.error(
                request,
                f'Erro ao executar certidão do processo '
                f'{record.processo}: {exc}'
            )
        return HttpResponseRedirect(reverse('projudi:certidao_dashboard'))


class CertidaoExecutarRagPendentesView(LoginRequiredMixin, View):
    """Executa somente as certidões de RAG pendentes/falhas."""

    def post(self, request):
        from .cumprimento_service import CumprimentoService

        records = list(
            CumprimentoRecord.objects
            .filter(
                user=request.user,
                template_used__template_type='certidao',
                status__in=['pendente', 'falha'],
            )
            .select_related('template_used', 'rag_example')
            .order_by('created_at')
        )
        if not records:
            messages.info(request, 'Nenhuma certidão pendente para executar.')
            return HttpResponseRedirect(
                reverse('projudi:certidao_dashboard')
            )

        service = CumprimentoService(request.user)
        cumpridas = 0
        falhas = 0
        for record in records:
            try:
                service.executar_cumprimento(record)
                record.refresh_from_db()
                if record.status == 'cumprido':
                    cumpridas += 1
                else:
                    falhas += 1
            except Exception as exc:
                falhas += 1
                print(
                    f'[CertidaoRAG] Erro em {record.processo}: {exc}'
                )

        messages.success(
            request,
            f'Certidões processadas: {cumpridas} cumprida(s), '
            f'{falhas} falha(s).'
        )
        return HttpResponseRedirect(reverse('projudi:certidao_dashboard'))
