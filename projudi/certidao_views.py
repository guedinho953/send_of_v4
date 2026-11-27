"""Dashboard de Certidões.

Separa as certidões/procedimentos em dois grupos, pelo campo `origem`:

- **Petições**: gerados pela fila/análise de petições;
- **Movimentações**: gerados pela análise/varredura de movimentações.

Tudo fica dentro do módulo de Certidões; o dashboard de Movimentações não
lista mais os registros com `categoria='certidao'`.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, TemplateView

from .models import (
    CertidaoRegistro, CumprimentoRecord, MovimentacaoRecord,
    ProjudiSession,
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
            'processo_prefill': (
                self.request.GET.get('processo') or '').strip(),
            'rag_prefill': (
                self.request.GET.get('rag_id') or '').strip(),
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

    @staticmethod
    def _renderizar_preview(service, record, template, rag):
        """Tenta gerar o HTML da certidão sem executar nada no Projudi."""
        try:
            service.gerar_observacao_prazo(record)
        except Exception:
            pass
        try:
            html = service._html_certidao_prazo(record)
        except Exception:
            html = ''
        if not html:
            from datetime import date
            from django.template import Context, Template
            try:
                ctx = rag.get_template_context() or {}
                ctx.update({
                    'data': date.today().strftime('%d/%m/%Y'),
                    'servidor': getattr(service.user, 'full_name', '') or (
                        getattr(service.user, 'first_name', '') or '...'),
                    'servidor_cargo': 'Secretário em Substituição',
                })
                html = Template(template.html_template).render(
                    Context(ctx))
            except Exception:
                html = ''
        return html

    def post(self, request):
        from base.utils import (
            format_process_number, normalize_process_number,
        )
        from datetime import date
        from django.template import Context, Template
        from processes.models import (
            DocumentTemplate, GeneratedDocument, Process, RAGExample,
        )
        from .cumprimento_service import CumprimentoService
        from .processo_lookup import localizar_processo

        processo = (request.POST.get('processo') or '').strip()
        rag_id = (request.POST.get('rag_id') or '').strip()
        processo_url = (request.POST.get('processo_url') or '').strip()
        evento_decisao = (
            request.POST.get('evento_decisao') or ''
        ).strip()
        forcar = request.POST.get('forcar') == '1'
        acao = (request.POST.get('acao') or 'executar').strip().lower()
        if acao not in ('preview', 'executar'):
            acao = 'executar'

        if not processo or not rag_id.isdigit():
            messages.error(request, 'Informe o processo e a RAG.')
            return HttpResponseRedirect(reverse('projudi:certidao_dashboard'))

        digitos = normalize_process_number(processo)
        if len(digitos) < 15:
            messages.error(
                request,
                'Número do processo inválido. Informe o CNJ completo ou '
                'somente os dígitos.'
            )
            return HttpResponseRedirect(reverse('projudi:certidao_dashboard'))
        # Aceita o número sem os zeros à esquerda (ex.: 38222020258050191).
        digitos = digitos.zfill(20)
        processo = format_process_number(digitos)

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

        proc = Process.objects.filter(
            number_normalized=digitos
        ).first()
        if proc is None:
            proc = Process.objects.filter(number=processo).first()

        # Se o processo ainda não tem URL (ou nem está cadastrado),
        # localiza automaticamente pelo número na busca interna do Projudi.
        if proc is None or not proc.projudi_url:
            localizado = localizar_processo(request.user, processo)
            if localizado:
                processo = localizado['numero']
                digitos = normalize_process_number(processo)
                processo_url = localizado['url']

        if proc is None:
            if not processo_url:
                messages.error(
                    request,
                    'Processo não localizado no Projudi pelo número '
                    f'{processo}. Confira o CNJ ou informe a URL '
                    'DadosProcesso?numeroProcesso=...'
                )
                return HttpResponseRedirect(
                    reverse('projudi:certidao_dashboard')
                )
            proc = Process.objects.create(
                number=processo,
                number_normalized=digitos,
                tenant=request.user.tenant,
                status='analyzing',
                projudi_url=processo_url,
            )
        else:
            processo = proc.number
            if processo_url and not proc.projudi_url:
                proc.projudi_url = processo_url
                proc.save(update_fields=['projudi_url'])
            elif not processo_url and proc.projudi_url:
                processo_url = proc.projudi_url

        if not processo_url and proc.projudi_url:
            processo_url = proc.projudi_url

        if not processo_url:
            messages.error(
                request,
                'O processo foi encontrado, mas não foi possível obter a '
                'URL interna do Projudi. Informe a URL '
                'DadosProcesso?numeroProcesso=...'
            )
            return HttpResponseRedirect(reverse('projudi:certidao_dashboard'))

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
            evento_decisao=evento_decisao,
            snippet=(rag.despacho_observacao or '')[:2000],
            template_used=template,
            rag_example=rag,
            url_processo=processo_url,
            status='pendente',
            user=request.user,
        )

        service = CumprimentoService(request.user)
        if acao == 'preview':
            html = self._renderizar_preview(
                service, record, template, rag)
            if not html.strip():
                record.delete()
                messages.error(
                    request,
                    'Não foi possível montar a prévia desta certidão. '
                    'Confira o template vinculado à RAG.'
                )
                return HttpResponseRedirect(
                    reverse('projudi:certidao_dashboard'))
            seq = GeneratedDocument.proximo_numero(template)
            doc = GeneratedDocument.objects.create(
                tenant=getattr(request.user, 'tenant', None),
                process=proc,
                template=template,
                rag_example=rag,
                sequential_number=seq,
                year=date.today().year,
                recipient_name=f'Certidão: {template.name}',
                html_content=html,
            )
            try:
                from .certidao_registro_service import registrar_documento
                registrar_documento(
                    request.user, doc,
                    tipo_prazo=rag.tipo_certidao or 'certidao',
                    origem='movimentacao',
                    parte=record.parte_nome or '',
                    status='gerada',
                    evento_despacho=rag.evento_despacho or '',
                    evento_intimacao=rag.evento_intimacao or '',
                    prazo_info=record.prazo_info or {},
                )
            except Exception:
                pass
            record.delete()
            messages.info(
                request,
                '👁 Prévia gerada. Confira a certidão e escolha a ação '
                'para executar o restante do fluxo.'
            )
            return HttpResponseRedirect(reverse(
                'projudi:certidao_peticao_preview', args=[doc.id]))

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

        try:
            from .models import CertidaoRegistro
            info = record.prazo_info or {}
            CertidaoRegistro.objects.get_or_create(
                cumprimento=record,
                defaults={
                    'tenant': getattr(request.user, 'tenant', None),
                    'user': request.user,
                    'processo': processo,
                    'numero_processo_cnj': processo,
                    'parte': record.parte_nome or '',
                    'origem': 'movimentacao',
                    'tipo_prazo': rag.tipo_certidao or 'certidao',
                    'prazo_dias': info.get('prazo_dias') or 0,
                    'evento_despacho': rag.evento_despacho or '',
                    'evento_intimacao': record.evento_decisao or '',
                    'data_intimacao': record.prazo_info.get(
                        'data_disponibilizacao'),
                    'data_inicio': info.get('data_inicio'),
                    'ultimo_dia': info.get('ultimo_dia'),
                    'data_decurso': info.get('data_decurso'),
                    'texto_certidao': record.texto_html or '',
                    'motivo': record.fluxo_justificativa or '',
                    'rag_example': rag,
                    'template_used': template,
                    'servidor': '',
                    'status': (
                        'juntada' if record.status == 'cumprido'
                        else 'falha' if record.status == 'falha'
                        else 'pendente'
                    ),
                    'prazo_info': info,
                },
            )
        except Exception:
            pass

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


class CertidaoSugestaoMovimentacaoView(LoginRequiredMixin, View):
    """Sugere a certidão de uma movimentação a partir do match RAG."""

    def get(self, request):
        from .certidao_sugestao import sugerir_certidao

        processo = (request.GET.get('processo') or '').strip()
        documento = (request.GET.get('documento') or '').strip()
        processo_url = (request.GET.get('url') or '').strip()
        if not processo:
            return JsonResponse(
                {'erro': 'Processo não informado.'}, status=400)
        try:
            return JsonResponse(sugerir_certidao(
                request.user, processo, documento, processo_url))
        except Exception as exc:
            return JsonResponse(
                {'erro': f'Erro ao sugerir certidão: {exc}'},
                status=500,
            )


class CriarRagMovimentacaoView(LoginRequiredMixin, View):
    """Cria uma RAG a partir de uma movimentação/documento do Projudi."""

    def post(self, request):
        from processes.models import Process, RAGExample, DocumentTemplate
        from base.utils import normalize_process_number
        from .certidao_sugestao import _texto_documento, _tipo_por_texto

        processo = (request.POST.get('processo') or '').strip()
        tipo = (request.POST.get('tipo') or '').strip()
        data = (request.POST.get('data') or '').strip()
        link_processo = (request.POST.get('link_processo') or '').strip()
        link_documento = (request.POST.get('link_documento') or '').strip()
        texto_movimentacao = (
            request.POST.get('texto_movimentacao') or '').strip()

        if not processo:
            messages.error(
                request,
                'Movimentação sem processo para gerar a RAG.',
            )
            return HttpResponseRedirect(reverse('projudi:movimentacoes'))

        resultado = ProjudiService(request.user)._get_session_from_cookies()
        if not resultado:
            messages.error(request, 'Sessão do Projudi não disponível.')
            return HttpResponseRedirect(reverse('projudi:movimentacoes'))
        session, _ = resultado

        texto = _texto_documento(session, link_documento) if link_documento else ''
        usou_texto_movimentacao = False
        if len(texto.strip()) < 30 and texto_movimentacao:
            texto = texto_movimentacao
            usou_texto_movimentacao = True
        if not texto.strip():
            messages.error(
                request,
                'Não há documento nem texto da movimentação para gerar a RAG.',
            )
            return HttpResponseRedirect(reverse('projudi:movimentacoes'))

        numero = normalize_process_number(processo)
        proc = Process.objects.filter(number_normalized=numero).first()
        if not proc:
            proc = Process.objects.create(
                number=processo,
                number_normalized=numero,
                tenant=getattr(request.user, 'tenant', None),
                status='analyzing',
                projudi_url=link_processo,
            )

        template_por_tipo = {
            'inominado': 'Certidão de Recurso Inominado',
            'decurso_pagamento': (
                'Certidão de Decurso de Prazo para Pagamento Voluntário'
            ),
            'cumprimento_sentenca': 'Certidão de Prazo',
            'pagamento_impugnacao_penhora': 'Certidão de Prazo',
            'impugnacao_embargos_execucao': 'Certidão de Prazo',
            'contrarrazoes_inominado': 'Certidão de Prazo',
        }

        def _template_do_tipo(valor):
            return DocumentTemplate.objects.filter(
                name=template_por_tipo.get(valor, ''),
                template_type='certidao',
                active=True,
            ).first()

        def _voltar_fila(processo):
            from urllib.parse import urlencode
            return HttpResponseRedirect(
                reverse('projudi:movimentacoes')
                + '?' + urlencode({'q': processo})
            )

        def _limpar_cache(processo, documento):
            from django.core.cache import cache
            cache.delete(
                f'certidao_sugestao_v1:{processo}:{documento}'
            )

        existente = RAGExample.objects.filter(
            process=proc,
            despacho_observacao=texto,
        ).first()
        if existente:
            template = _template_do_tipo(
                existente.tipo_certidao
                or _tipo_por_texto(existente.despacho_observacao or '')
            )
            if (template and not existente.suggested_templates.filter(
                    template_type='certidao').exists()):
                existente.suggested_templates.add(template)
            _limpar_cache(processo, link_documento)
            messages.info(
                request,
                f'RAG #{existente.id} já existia. '
                + (
                    f'Template "{template.name}" vinculado; '
                    if template else ''
                )
                + 'Use os botões da própria linha para gerar a certidão.'
            )
            return _voltar_fila(processo)

        tipo_certidao = _tipo_por_texto(texto)
        documentos = []
        if link_documento:
            documentos.append({
                'nome': f'Documento — {data or tipo or "movimentação"}',
                'url': link_documento,
            })
        rag = RAGExample.objects.create(
            process=proc,
            tenant=getattr(request.user, 'tenant', None),
            despacho_ato=(tipo or 'Movimentação')[:200],
            despacho_observacao=texto,
            despacho_data=data,
            documentos=documentos,
            tipo_certidao=tipo_certidao,
            active=True,
        )
        template = _template_do_tipo(tipo_certidao)
        if template:
            rag.suggested_templates.add(template)
        _limpar_cache(processo, link_documento)
        messages.success(
            request,
            f'✅ RAG #{rag.id} criada a partir '
            + (
                'do texto da movimentação'
                if usou_texto_movimentacao else 'do documento'
            )
            + (f' com template "{template.name}" vinculado.' if template else '.')
            + ' Use os botões da própria linha para gerar a certidão.',
        )
        return _voltar_fila(processo)


class RagCertidaoListView(LoginRequiredMixin, TemplateView):
    """Tabela das RAGs que geram certidão, separadas por origem."""

    template_name = 'projudi/rag_certidoes.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.db.models import Q
        from processes.models import RAGExample
        from .certidao_sugestao import (
            TIPOS_CERTIDAO, _normalizar, _tipo_por_texto,
        )

        tipos_peticao = {'inominado', 'contrarrazoes_inominado'}
        labels = {t['valor']: t['label'] for t in TIPOS_CERTIDAO}

        busca = (self.request.GET.get('q') or '').strip()
        origem = (self.request.GET.get('origem') or '').strip()
        if origem not in ('peticao', 'movimentacao'):
            origem = ''

        qs = (
            RAGExample.objects
            .select_related('process')
            .prefetch_related('suggested_templates')
            .filter(active=True)
        )
        if busca:
            qs = qs.filter(
                Q(process__number__icontains=busca)
                | Q(despacho_ato__icontains=busca)
                | Q(despacho_observacao__icontains=busca)
            )

        registros = []
        contagem = {'peticao': 0, 'movimentacao': 0}
        for rag in qs.order_by('-created_at'):
            templates = [
                t.name for t in rag.suggested_templates.all()
                if t.template_type == 'certidao'
            ]
            tipo = rag.tipo_certidao or ''
            if not tipo:
                tipo = _tipo_por_texto(
                    f'{rag.despacho_ato or ""} '
                    f'{rag.despacho_observacao or ""}'
                )
            if not tipo and not templates:
                continue
            if tipo in tipos_peticao:
                origem_rag = 'peticao'
            elif tipo:
                origem_rag = 'movimentacao'
            else:
                nomes = _normalizar(' '.join(templates))
                origem_rag = (
                    'peticao'
                    if ('RECURSO INOMINADO' in nomes
                        or 'CONTRARRAZOES' in nomes)
                    else 'movimentacao'
                )

            rag.origem_certidao = origem_rag
            rag.origem_certidao_label = (
                'Petições' if origem_rag == 'peticao' else 'Movimentações'
            )
            rag.tipo_certidao_label = labels.get(
                tipo, templates[0] if templates else 'Sem certidão')
            rag.templates_nomes = templates
            contagem[origem_rag] += 1
            if origem and origem_rag != origem:
                continue
            registros.append(rag)

        context.update({
            'registros': registros,
            'busca': busca,
            'origem_filtro': origem,
            'total': contagem['peticao'] + contagem['movimentacao'],
            'total_peticoes': contagem['peticao'],
            'total_movimentacoes': contagem['movimentacao'],
            'is_staff': self.request.user.is_staff,
        })
        return context


class CertidaoTabelaView(LoginRequiredMixin, TemplateView):
    """Visão em tabela das certidões, preservando o dashboard atual.

    Reúne, sem alterar os fluxos existentes:
    - documentos de certidão ainda não juntados;
    - cumprimentos/RAG de certidão;
    - movimentações de certidão já registradas.
    """

    template_name = 'projudi/certidao_tabela.html'
    origem_fixa = ''
    titulo_visao = '📄 Certidões em Tabela'

    @staticmethod
    def _data_iso(valor):
        if not valor:
            return None
        if hasattr(valor, 'year'):
            return valor
        try:
            from datetime import date
            return date.fromisoformat(str(valor)[:10])
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _origem_por_template(nome, recipient=''):
        alvo = f'{nome or ""} {recipient or ""}'.upper()
        if (str(recipient or '').startswith('Petição:')
                or 'RECURSO INOMINADO' in alvo
                or 'CONTRARRAZ' in alvo):
            return 'peticao'
        return 'movimentacao'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from processes.models import GeneratedDocument
        from .models import CumprimentoRecord, MovimentacaoRecord

        user = self.request.user
        tenant = getattr(user, 'tenant', None)

        rows = []

        docs = GeneratedDocument.objects.filter(
            template__template_type='certidao',
            exported_to_projudi=False,
        ).select_related('process', 'template').prefetch_related(
            'certidao_registros')
        if tenant:
            docs = docs.filter(tenant=tenant)
        docs = docs.order_by('-created_at')[:300]
        for doc in docs:
            nome = doc.template.name if doc.template else (
                doc.recipient_name or 'Certidão')
            rows.append({
                'data': doc.created_at,
                'processo': doc.process.number if doc.process else '—',
                'origem': self._origem_por_template(
                    nome, doc.recipient_name),
                'parte': '',
                'tipo': nome,
                'ultimo_dia': None,
                'status': 'Gerada',
                'status_classe': 'gerada',
                'detail_url': reverse(
                    'projudi:certidao_peticao_preview', args=[doc.id]),
                'preview_url': reverse(
                    'projudi:certidao_peticao_preview', args=[doc.id]),
                'doc_id': doc.id,
                'registro_id': (
                    doc.certidao_registros.first().id
                    if doc.certidao_registros.exists() else None
                ),
                'fonte': 'Documento gerado',
                'fonte_classe': 'doc',
            })

        cumprimentos = (
            CumprimentoRecord.objects
            .filter(user=user, template_used__template_type='certidao')
            .exclude(status='dispensado')
            .select_related('template_used', 'rag_example')
            .order_by('-created_at')[:300]
        )
        for reg in cumprimentos:
            nome = (
                reg.template_used.name if reg.template_used
                else (reg.act_verb or 'Certidão')
            )
            info = reg.prazo_info or {}
            rows.append({
                'data': reg.created_at,
                'processo': reg.numero_processo_cnj or reg.processo,
                'origem': self._origem_por_template(nome),
                'parte': reg.parte_nome,
                'tipo': nome,
                'ultimo_dia': self._data_iso(info.get('ultimo_dia')),
                'status': reg.get_status_display(),
                'status_classe': reg.status,
                'detail_url': reverse(
                    'projudi:cumprimento_detail', args=[reg.id]),
                'preview_url': '',
                'fonte': 'RAG / cumprimento',
                'fonte_classe': 'rag',
            })

        movimentacoes = (
            MovimentacaoRecord.objects
            .filter(user=user, categoria='certidao')
            .select_related('template_used', 'rag_example')
            .order_by('-created_at')[:300]
        )
        for reg in movimentacoes:
            nome = reg.descricao_movimentacao or reg.act_verb or 'Certidão'
            rows.append({
                'data': reg.created_at,
                'processo': reg.numero_processo_cnj or reg.processo,
                'origem': (
                    reg.origem if reg.origem in ('peticao', 'movimentacao')
                    else 'movimentacao'
                ),
                'parte': reg.parte_nome,
                'tipo': nome,
                'ultimo_dia': None,
                'status': reg.get_status_display(),
                'status_classe': reg.status,
                'detail_url': reverse(
                    'projudi:movimentacao_detail', args=[reg.id]),
                'preview_url': '',
                'fonte': 'Movimentação',
                'fonte_classe': 'mov',
            })

        modo = (self.request.GET.get('modo') or 'juntas').strip().lower()
        if modo not in ('juntas', 'separadas'):
            modo = 'juntas'

        origem = self.origem_fixa or (
            self.request.GET.get('origem') or '').strip()
        if modo == 'separadas':
            origem = ''
        if origem not in ('peticao', 'movimentacao'):
            origem = ''
        status = (self.request.GET.get('status') or '').strip()
        ocultar = self.request.GET.get('ocultar') == '1'
        busca = (self.request.GET.get('q') or '').strip().lower()

        total = len(rows)
        total_peticoes = sum(1 for r in rows if r['origem'] == 'peticao')
        total_movimentacoes = total - total_peticoes
        total_geradas = sum(
            1 for r in rows if r['status_classe'] == 'gerada')
        total_pendentes = sum(
            1 for r in rows if r['status_classe'] in
            ('pendente', 'processando', 'falha'))

        if origem:
            rows = [r for r in rows if r['origem'] == origem]
        if status:
            rows = [r for r in rows if r['status_classe'] == status]
        if ocultar:
            processadas = {
                'gerada', 'cumprido', 'juntada', 'intimada',
                'concluida', 'dispensado',
            }
            rows = [
                r for r in rows
                if r['status_classe'] not in processadas
            ]
        if busca:
            rows = [
                r for r in rows
                if busca in str(r['processo']).lower()
                or busca in str(r['parte']).lower()
                or busca in str(r['tipo']).lower()
                or busca in str(r['fonte']).lower()
            ]
        rows.sort(key=lambda r: r['data'], reverse=True)

        registros_peticoes = [
            r for r in rows if r['origem'] == 'peticao'
        ]
        registros_movimentacoes = [
            r for r in rows if r['origem'] != 'peticao'
        ]

        context.update({
            'registros': rows,
            'registros_peticoes': registros_peticoes,
            'registros_movimentacoes': registros_movimentacoes,
            'modo': modo,
            'origem_fixa': self.origem_fixa,
            'titulo_visao': self.titulo_visao,
            'busca': self.request.GET.get('q', ''),
            'origem_filtro': origem,
            'status_filtro': status,
            'ocultar_processadas': ocultar,
            'total': total,
            'total_peticoes': total_peticoes,
            'total_movimentacoes': total_movimentacoes,
            'total_geradas': total_geradas,
            'total_pendentes': total_pendentes,
            'total_visivel': len(rows),
        })
        return context


class CertidaoPeticaoTabelaView(CertidaoTabelaView):
    origem_fixa = 'peticao'
    titulo_visao = '📄 Certidões de Petições'


class CertidaoMovimentacaoTabelaView(CertidaoTabelaView):
    origem_fixa = 'movimentacao'
    titulo_visao = '⚙️ Certidões de Movimentações'


class CertidaoRegistroDetailView(LoginRequiredMixin, DetailView):
    """Detalhe do registro unificado de certidão."""

    model = CertidaoRegistro
    template_name = 'projudi/certidao_registro_detail.html'
    context_object_name = 'registro'

    def get_queryset(self):
        return CertidaoRegistro.objects.select_related(
            'generated_document', 'movimentacao', 'cumprimento',
            'rag_example', 'template_used',
        )


class CertidaoHubView(LoginRequiredMixin, TemplateView):
    """Ponto de entrada com os fluxos de petições e movimentações separados."""

    template_name = 'projudi/certidao_hub.html'
