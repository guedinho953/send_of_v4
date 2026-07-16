from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView
from django.shortcuts import get_object_or_404, render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from .models import Process, Movement, MovementCommand, CommunicationTracking, ProcessSummary, ComplianceHistory, RAGExample, DocumentTemplate
from .movimentacoes_service import MovimentacoesService


class ProcessListView(LoginRequiredMixin, ListView):
    model = Process
    template_name = 'processes/process_list.html'
    context_object_name = 'processes'
    paginate_by = 20


class ProcessDetailView(LoginRequiredMixin, DetailView):
    model = Process
    template_name = 'processes/process_detail.html'
    context_object_name = 'process'


class ProcessMovimentacoesView(LoginRequiredMixin, DetailView):
    """View para visualizar e analisar movimentacoes de um processo."""
    model = Process
    template_name = 'processes/process_movimentacoes.html'
    context_object_name = 'process'
    pk_url_kwarg = 'pk'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        processo = self.object

        # Movimentacoes do processo (mais recentes primeiro - por numero de evento)
        movements = Movement.objects.filter(
            process=processo
        ).prefetch_related('commands').order_by('-event_number')
        ctx['movements'] = movements

        # Ultima movimentacao (provavelmente a que precisa cumprir)
        ctx['ultima_movimentacao'] = movements.first()

        # Avaliar prontidao da ultima movimentacao
        from .movimentacoes_service import MovimentacoesService
        service = MovimentacoesService(user=self.request.user)
        ctx['service'] = service
        if ctx['ultima_movimentacao']:
            ctx['avaliacao_ultima'] = service.avaliar_prontidao_cumprimento(
                processo, ctx['ultima_movimentacao']
            )

        # Comandos extraidos
        ctx['commands'] = MovementCommand.objects.filter(
            movement__process=processo
        ).select_related('movement')

        # Comunicacoes rastreadas
        ctx['communications'] = CommunicationTracking.objects.filter(
            process=processo
        )

        # Ranqueamento e sugestao (pre-computados para evitar erros no template)
        ctx['ranqueamento'] = service.rankear_movimentacoes_por_facilidade(processo)
        ctx['sugestao'] = service.sugerir_proxima_acao(processo)

        # Resumo
        ctx['summary'] = getattr(processo, 'summary', None)

        # Estatisticas
        ctx['stats'] = {
            'total_movimentacoes': movements.count(),
            'total_comandos': ctx['commands'].count(),
            'completaveis': ctx['commands'].filter(is_completable=True).count(),
            'bloqueados': ctx['commands'].filter(is_completable=False).count(),
            'comunicacoes_pendentes': ctx['communications'].filter(status='pendente').count(),
            'comunicacoes_lidas': ctx['communications'].filter(status='lida').count(),
        }

        # Comandos por categoria
        ctx['commands_by_category'] = {}
        for cmd in ctx['commands']:
            cat = cmd.movement.category
            if cat not in ctx['commands_by_category']:
                ctx['commands_by_category'][cat] = []
            ctx['commands_by_category'][cat].append(cmd)

        return ctx


@login_required
@require_POST
def processar_movimentacoes_view(request, pk):
    """Recebe HTML via POST, processa movimentacoes e redireciona para visualizacao."""
    processo = get_object_or_404(Process, pk=pk)

    html = request.POST.get('html', '')
    if not html and request.FILES.get('html_file'):
        html = request.FILES['html_file'].read().decode('utf-8', errors='replace')

    if not html:
        return JsonResponse({'success': False, 'error': 'HTML obrigatorio'})

    try:
        service = MovimentacoesService(
            user=request.user,
            html_dados_processo=html,
            process_number=processo.number
        )
        resultado = service.processar_movimentacoes(
            html=html,
            numero_processo=processo.number,
            processo_obj=processo
        )
        return JsonResponse({'success': True, **resultado})
    except Exception as e:
        import traceback
        return JsonResponse({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        })


@login_required
def compliance_history_list(request):
    qs = RAGExample.objects.select_related('process').prefetch_related('suggested_templates').filter(
        tenant=request.user.tenant
    )
    processo_filter = request.GET.get('processo', '')
    if processo_filter:
        qs = qs.filter(process__number__icontains=processo_filter)
    active_filter = request.GET.get('active', '')
    if active_filter == '1':
        qs = qs.filter(active=True)
    elif active_filter == '0':
        qs = qs.filter(active=False)

    tipo_filter = request.GET.get('tipo', '')
    if tipo_filter == 'juiz':
        from django.db.models import Q
        qs = qs.filter(
            Q(despacho_ato__icontains='despacho') |
            Q(despacho_ato__icontains='sentença') |
            Q(despacho_ato__icontains='sentenca') |
            Q(despacho_ato__icontains='decisão') |
            Q(despacho_ato__icontains='decisao')
        )

    total = qs.count()
    total_active = qs.filter(active=True).count()

    return render(request, 'processes/compliance_history_list.html', {
        'records': qs,
        'total': total,
        'total_active': total_active,
        'processo_filter': processo_filter,
        'active_filter': active_filter,
        'tipo_filter': tipo_filter,
    })


@login_required
@require_POST
def compliance_edit_obs(request, pk):
    ch = get_object_or_404(RAGExample, pk=pk, tenant=request.user.tenant)
    obs = request.POST.get('observacao', '').strip()
    ch.despacho_observacao = obs
    ch.save()
    messages.success(request, f'Observação do exemplo #{pk} atualizada')
    return redirect(request.META.get('HTTP_REFERER', 'processes:compliance_list'))


@login_required
@require_POST
def compliance_history_delete(request, pk):
    ch = get_object_or_404(RAGExample, pk=pk, tenant=request.user.tenant)
    ch.delete()
    messages.success(request, f'Exemplo #{pk} excluído')
    return redirect(request.META.get('HTTP_REFERER', 'processes:compliance_list'))


@login_required
@require_POST
def compliance_history_toggle(request, pk):
    ch = get_object_or_404(RAGExample, pk=pk, tenant=request.user.tenant)
    ch.active = not ch.active
    ch.save()
    messages.success(request, f'Exemplo #{pk} {"ativado" if ch.active else "desativado"} para RAG')
    return redirect(request.META.get('HTTP_REFERER', 'processes:compliance_list'))


@login_required
@require_POST
def extrair_todas_movimentacoes_view(request):
    """Roda o comando extrair_movimentacoes_projudi para todos os processos."""
    from io import StringIO
    from django.core.management import call_command
    from django.contrib import messages
    from django.shortcuts import redirect

    out = StringIO()
    try:
        call_command('extrair_movimentacoes_projudi', stdout=out, stderr=out, limite=80)
        output = out.getvalue()
        messages.success(request, "Extracao de movimentacoes concluida!")
        for line in output.split('\n'):
            line = line.strip()
            if line and ('[OK]' in line or '[INFO]' in line or 'Processos processados' in line or 'Pares' in line):
                messages.info(request, line)
    except Exception as e:
        messages.error(request, f"Erro na extracao: {e}")

    return redirect('dashboard')


@login_required
def gerar_documento(request, pk, template_id):
    rag = get_object_or_404(RAGExample, pk=pk, tenant=request.user.tenant)
    template = get_object_or_404(DocumentTemplate, pk=template_id, active=True)
    parties = rag.process.parties.all()

    from .document_suggester import analisar_decisao, mapear_destinatarios, extrair_dados_audiencia
    analise = analisar_decisao(rag.despacho_observacao or rag.despacho_ato)
    dados_audiencia = extrair_dados_audiencia(rag.process)

    if request.method == 'POST':
        from .models import GeneratedDocument
        from base.crypto import encrypt
        from datetime import date

        parte_ids = request.POST.getlist('parte_ids')
        nomes_extras = request.POST.getlist('nome_extra')
        emails_extras = request.POST.getlist('email_extra')
        enderecos_extras = request.POST.getlist('endereco_extra')

        # Salvar dados complementares das partes (RG, pai, mae, CPF)
        for party in parties:
            rg = request.POST.get(f'parte_rg_{party.id}', '').strip()
            pai = request.POST.get(f'parte_pai_{party.id}', '').strip()
            mae = request.POST.get(f'parte_mae_{party.id}', '').strip()
            cpf = request.POST.get(f'parte_cpf_{party.id}', '').strip()
            changed = False
            if rg and rg != party.rg:
                party.rg = rg
                party.rg_encrypted = encrypt(rg)
                changed = True
            if pai and pai != party.nome_pai:
                party.nome_pai = pai
                changed = True
            if mae and mae != party.nome_mae:
                party.nome_mae = mae
                changed = True
            if cpf and cpf != party.cpf_cnpj:
                party.cpf_cnpj = cpf
                party.cpf_cnpj_encrypted = encrypt(cpf)
                changed = True
            if changed:
                party.save()

        ctx_base = rag.get_template_context()
        ctx_base.update(dados_audiencia)
        documents = []

        requested_ids = [int(x) for x in parte_ids if x.isdigit()]
        for party in parties:
            if party.id in requested_ids:
                num = GeneratedDocument.proximo_numero(template)
                ctx = rag.get_template_context(parte_id=party.id)
                ctx['numero_documento'] = f'{num:03d}/{date.today().year}'
                ctx.update(dados_audiencia)
                prazo = request.POST.get(f'parte_prazo_servico_{party.id}', '').strip()
                valor = request.POST.get(f'parte_valor_pecuniaria_{party.id}', '').strip()
                parcelas = request.POST.get(f'parte_parcelas_{party.id}', '').strip()
                if prazo:
                    ctx['prazo_prestacao_servico'] = prazo
                if valor:
                    ctx['valor_prestacao_pecuniaria'] = valor
                    ctx['tem_prestacao_pecuniaria'] = True
                if parcelas:
                    ctx['parcelas_prestacao_pecuniaria'] = parcelas
                html = template.render(ctx)
                doc = GeneratedDocument.objects.create(
                    tenant=rag.tenant,
                    process=rag.process,
                    rag_example=rag,
                    template=template,
                    sequential_number=num,
                    year=date.today().year,
                    recipient_name=party.name,
                    recipient_email=party.email or '',
                    html_content=html,
                )
                documents.append({'parte': party, 'html': html, 'numero': f'{num:03d}', 'id': doc.id})

        for nome, email, endereco in zip(nomes_extras, emails_extras, enderecos_extras):
            nome = nome.strip()
            if nome:
                num = GeneratedDocument.proximo_numero(template)
                ctx = {**ctx_base, 'partes': [{
                    'nome': nome,
                    'papel': 'Destinatário',
                    'cpf_cnpj': '',
                    'email': email.strip(),
                    'telefone': '',
                    'endereco': endereco.strip(),
                    'advogado': '',
                }], 'parte': {
                    'nome': nome,
                    'papel': 'Destinatário',
                    'cpf_cnpj': '',
                    'email': email.strip(),
                    'telefone': '',
                    'endereco': endereco.strip(),
                    'advogado': '',
                }, 'numero_documento': f'{num:03d}/{date.today().year}'}
                html = template.render(ctx)
                GeneratedDocument.objects.create(
                    tenant=rag.tenant,
                    process=rag.process,
                    rag_example=rag,
                    template=template,
                    sequential_number=num,
                    year=date.today().year,
                    recipient_name=nome,
                    recipient_email=email.strip(),
                    html_content=html,
                )
                documents.append({'parte': None, 'html': html, 'nome_extra': nome, 'numero': f'{num:03d}'})

        return render(request, 'processes/documento_preview.html', {
            'rag': rag,
            'template': template,
            'documents': documents,
        })

    sugestao_partes = mapear_destinatarios(analise, parties)

    return render(request, 'processes/documento_selecao.html', {
        'rag': rag,
        'template': template,
        'parties': parties,
        'analise': analise,
        'sugestao_partes': sugestao_partes,
        'dados_audiencia': dados_audiencia,
    })
