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

        from processes.models import RAGExample
        rags_certidao = (
            RAGExample.objects
            .filter(
                active=True,
                suggested_templates__template_type='certidao',
                suggested_templates__active=True,
            )
            .distinct()
            .order_by('-created_at')[:50]
        )

        context.update({
            'rags_certidao': rags_certidao,
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
            paginas = int(request.POST.get('paginas') or 10)
        except (ValueError, TypeError):
            paginas = 10
        paginas = max(1, min(paginas, 30))
        rag_id_raw = (request.POST.get('rag_id') or '').strip()
        rag_filtro_id = int(rag_id_raw) if rag_id_raw.isdigit() else None
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

            pages = client.obter_paginas_finais_movimentacoes(
                quantidade=paginas
            )
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
            if rag_filtro_id:
                decisoes = [
                    decisao for decisao in decisoes
                    if getattr(decisao.get('rag'), 'id', None) == rag_filtro_id
                ]

            executar_auto = request.POST.get('executar') == '1'
            importados = 0
            executados = 0
            falhas = 0
            processos = set()
            for decisao in decisoes:
                try:
                    record = service.importar_cumprimento(decisao)
                    if not record:
                        continue
                    importados += 1
                    processos.add(record.processo)

                    if (executar_auto
                            and record.status == 'pendente'
                            and getattr(record, 'template_used', None)
                            and record.template_used.template_type == 'certidao'):
                        service.executar_cumprimento(record)
                        record.refresh_from_db()
                        if record.status == 'cumprido':
                            executados += 1
                        else:
                            falhas += 1
                except Exception as exc:
                    print(f'[CertidaoRAG] Erro importando: {exc}')

            if importados:
                sufixo = ' de hoje' if somente_hoje else ''
                lista_proc = ', '.join(sorted(processos)[:8])
                msg = (
                    f'🔎 {importados} certidão(ões) de RAG{sufixo} '
                    f'localizada(s). Processos: {lista_proc}.'
                )
                if executar_auto:
                    msg += (
                        f' {executados} gerada(s)/juntada(s) no Projudi, '
                        f'{falhas} falha(s).'
                    )
                else:
                    msg += (
                        ' Clique em "Executar certidão" para gerar e juntar.'
                    )
                messages.success(request, msg)
            else:
                messages.info(
                    request,
                    'Nenhuma certidão de RAG nova foi localizada.'
                )
        except Exception as exc:
            messages.error(request, f'Erro ao rastrear RAG: {exc}')

        return HttpResponseRedirect(reverse('projudi:certidao_dashboard'))


class CertidaoGerarViaRagView(LoginRequiredMixin, View):
    """Gera a certidão de uma RAG diretamente para um processo.

    Diferente da fila de movimentações, aqui o documento da certidão é
    montado a partir do template vinculado à RAG e inserido/assinado no
    Projudi via `CumprimentoService.executar_cumprimento`.
    """

    def post(self, request):
        from base.utils import normalize_process_number
        from processes.models import Process, RAGExample
        from .cumprimento_service import CumprimentoService

        processo = (request.POST.get('processo') or '').strip()
        rag_id = (request.POST.get('rag_id') or '').strip()
        processo_url = (request.POST.get('processo_url') or '').strip()
        forcar = request.POST.get('forcar') == '1'

        if not processo or not rag_id.isdigit():
            messages.error(request, 'Informe o processo e a RAG.')
            return HttpResponseRedirect(reverse('projudi:certidao_dashboard'))

        rag = RAGExample.objects.filter(
            pk=int(rag_id), active=True
        ).first()
        if not rag:
            messages.error(request, 'RAG não encontrada ou inativa.')
            return HttpResponseRedirect(reverse('projudi:certidao_dashboard'))

        template = (
            rag.suggested_templates
            .filter(template_type='certidao', active=True)
            .first()
        )
        if not template:
            messages.error(
                request,
                'Esta RAG não tem template de certidão vinculado.'
            )
            return HttpResponseRedirect(reverse('projudi:certidao_dashboard'))

        proc, _ = Process.objects.get_or_create(
            number=processo,
            defaults={
                'number_normalized': normalize_process_number(processo),
                'tenant': request.user.tenant,
                'status': 'analyzing',
                'projudi_url': processo_url,
            },
        )
        if processo_url and not proc.projudi_url:
            proc.projudi_url = processo_url
            proc.save(update_fields=['projudi_url'])
        elif not processo_url and proc.projudi_url:
            processo_url = proc.projudi_url

        existente = CumprimentoRecord.objects.filter(
            user=request.user,
            processo=processo,
            rag_example=rag,
            template_used=template,
            status='cumprido',
        ).first()
        if existente and not forcar:
            messages.warning(
                request,
                f'Já existe certidão cumprida para este processo '
                f'(#{existente.id}). Marque "Gerar novamente" para repetir.'
            )
            return HttpResponseRedirect(reverse('projudi:certidao_dashboard'))

        record = CumprimentoRecord.objects.create(
            processo=processo,
            numero_processo_cnj=processo,
            fluxo='movimentacao_simples',
            fluxo_justificativa=(
                'Certidão gerada diretamente pela RAG '
                f'#{rag.id} — {rag.despacho_ato}'
            ),
            act_verb=(rag.despacho_ato or 'certifique-se')[:50],
            snippet=(rag.despacho_observacao or '')[:2000],
            template_used=template,
            rag_example=rag,
            url_processo=processo_url,
            status='pendente',
            user=request.user,
        )

        service = CumprimentoService(request.user)
        try:
            service.executar_cumprimento(record)
            record.refresh_from_db()
            if record.status == 'cumprido':
                messages.success(
                    request,
                    f'✅ {template.name} gerada, assinada e juntada no '
                    f'Projudi para o processo {processo}.'
                )
            else:
                messages.warning(
                    request,
                    f'⚠️ A certidão do processo {processo} terminou com '
                    f'status {record.get_status_display()}.'
                )
        except Exception as exc:
            messages.error(
                request,
                f'Erro ao gerar a certidão via RAG: {exc}'
            )

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
                    f'✅ Certidão do processo {record.processo} gerada e '
                    'juntada no Projudi.'
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
            f'Certidões geradas e juntadas: {cumpridas}; '
            f'falhas: {falhas}.'
        )
        return HttpResponseRedirect(reverse('projudi:certidao_dashboard'))
