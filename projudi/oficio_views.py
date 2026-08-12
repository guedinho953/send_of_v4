import json
from datetime import datetime
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, DetailView, TemplateView
from django.contrib import messages
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .models import OficioRecord, OficioLog
from .oficio_service import OficioService
from .services import ProjudiService


class OficioDashboardView(LoginRequiredMixin, TemplateView):
    """
    Dashboard / aba Oficios: exibe cards de estatisticas + lista dos ultimos oficios.
    """
    template_name = 'projudi/oficio_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Estatisticas
        qs = OficioRecord.objects.filter(user=user)
        context['total'] = qs.count()
        context['pendentes'] = qs.filter(status='pendente').count()
        context['pendentes_dispensar'] = qs.filter(status='pendente').count()
        context['enviados_para_juntar'] = qs.filter(status='enviado').count()
        context['enviados'] = qs.filter(status__in=['enviado', 'juntado']).count()
        context['juntados'] = qs.filter(status='juntado').count()
        context['falhas'] = qs.filter(status__in=['falhou_email', 'falhou_juntada']).count()
        context['dispensados'] = qs.filter(status='dispensado').count()
        context['juntados_para_dispensar'] = qs.filter(status='juntado').count()

        # Filtragem por status
        status_filter = self.request.GET.get('status', '')
        if status_filter == 'expedido':
            qs = qs.filter(status__in=['enviado', 'juntado'])
        elif status_filter and status_filter in dict(OficioRecord.STATUS_CHOICES):
            qs = qs.filter(status=status_filter)

        # Oficios (ultimos 50 para melhor visualizacao)
        context['oficios'] = qs.order_by('-created_at')[:50]

        # Sessao ativa?
        context['session_active'] = self._session_ativa(user)
        return context

    def _session_ativa(self, user):
        try:
            from .models import ProjudiSession
            sessao = ProjudiSession.objects.filter(user=user, status='active').first()
            if sessao:
                svc = ProjudiService(user)
                return svc.check_session()
        except Exception:
            pass
        return False


class OficioListView(LoginRequiredMixin, ListView):
    template_name = 'projudi/oficio_list.html'
    context_object_name = 'oficios'
    paginate_by = 20

    def get_queryset(self):
        return OficioRecord.objects.filter(user=self.request.user).order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['session_active'] = self._session_ativa()
        return context

    def _session_ativa(self):
        try:
            from .models import ProjudiSession
            sessao = ProjudiSession.objects.filter(user=self.request.user, status='active').first()
            if sessao:
                return ProjudiService(self.request.user).check_session()
        except Exception:
            pass
        return False


class OficioDetailView(LoginRequiredMixin, DetailView):
    template_name = 'projudi/oficio_detail.html'
    model = OficioRecord
    context_object_name = 'oficio'
    pk_url_kwarg = 'pk'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = OficioService(self.request.user)
        context['logs'] = service.logs_humanizados(self.object)
        return context


@method_decorator(csrf_exempt, name='dispatch')
class OficioSyncView(LoginRequiredMixin, View):
    """
    POST /projudi/oficios/sync/
    Busca oficios no Projudi e importa para o banco.
    """
    def post(self, request):
        service = OficioService(request.user)
        try:
            # 1) Busca os oficios (cookies -> ultima pagina -> 3 ultimas paginas)
            pendentes = service.buscar_oficios_pendentes(quantidade=3)
            print(f"[DEBUG] Oficios encontrados: {len(pendentes)}")

            importados = 0
            for dados in pendentes:
                oficio_data = service.extrair_oficio(dados)
                if oficio_data:
                    service.importar_oficio(oficio_data)
                    importados += 1

            msg = f"Sincronizado! {importados} oficios importados do Projudi (buscou 3 ultimas paginas)."
            if importados == 0:
                msg += " Nenhum oficio encontrado nas paginas consultadas."
            messages.success(request, msg)

        except Exception as e:
            erro_str = str(e)
            if 'expirada' in erro_str.lower() or 'sessao' in erro_str.lower():
                messages.error(request, f"{erro_str} <a href='{reverse('projudi:sync_session')}'>Clique aqui para sincronizar</a>")
            else:
                messages.error(request, f"Erro ao sincronizar: {e}")
        finally:
            try:
                service.fechar()
            except Exception:
                pass
        return HttpResponseRedirect(reverse('projudi:oficio_dashboard'))


class OficioSendView(LoginRequiredMixin, View):
    """POST /projudi/oficios/<pk>/enviar/ - Envia e junta (ou impossibilidade)"""
    def post(self, request, pk):
        record = get_object_or_404(OficioRecord, pk=pk, user=request.user)
        service = OficioService(request.user)
        try:
            resultado = service.processar_oficio(record)
            if resultado.get('enviado') and resultado.get('juntado'):
                messages.success(request,
                    f"Enviado e juntado: {record.numero_oficio}")
            elif resultado.get('juntado'):
                messages.success(request,
                    f"Envio falhou, mas juntada de impossibilidade realizada: {record.numero_oficio}")
            elif resultado.get('enviado'):
                messages.success(request,
                    f"Enviado: {record.numero_oficio} (pendente de juntada)")
            else:
                erro = service.humanizar_erro(resultado.get('erro', 'Erro'))
                messages.error(request, f"{erro}")
        except Exception as e:
            messages.error(request, f"Erro: {service.humanizar_erro(str(e))}")
        finally:
            try:
                service.fechar()
            except Exception:
                pass
        return HttpResponseRedirect(reverse('projudi:oficio_detail', kwargs={'pk': pk}))


class OficioJuntarView(LoginRequiredMixin, View):
    """
    POST /projudi/oficios/<pk>/juntar/
    Junta oficio no Projudi (movimentacao de cumprimento).
    """
    def post(self, request, pk):
        record = get_object_or_404(OficioRecord, pk=pk, user=request.user)
        service = OficioService(request.user)
        try:
            resultado = service.juntar_oficio(record)
            if resultado.get('juntado'):
                messages.success(
                    request,
                    f"✅ Oficio {record.numero_oficio} juntado no processo {record.processo}!"
                )
            else:
                erro_humanizado = service.humanizar_erro(resultado.get('erro', 'Erro na juntada'))
                messages.error(request, f"❌ {erro_humanizado}")
        except Exception as e:
            erro_humanizado = service.humanizar_erro(str(e))
            messages.error(request, f"❌ {erro_humanizado}")
        finally:
            try:
                service.fechar()
            except Exception:
                pass
        return HttpResponseRedirect(reverse('projudi:oficio_detail', kwargs={'pk': pk}))


class OficioDispensarView(LoginRequiredMixin, View):
    """
    POST /projudi/oficios/<pk>/dispensar/
    Marca oficio como dispensado (enviado fora deste sistema).
    """
    def post(self, request, pk):
        record = get_object_or_404(OficioRecord, pk=pk, user=request.user)
        record.status = 'dispensado'
        record.save(update_fields=['status'])

        OficioLog.objects.create(
            oficio=record,
            tipo='info',
            mensagem=f"Oficio dispensado por {request.user.full_name}.",
            detalhes={'status_anterior': record.status}
        )

        messages.success(request, f"Oficio {record.numero_oficio} dispensado com sucesso.")
        return HttpResponseRedirect(reverse('projudi:oficio_dashboard'))


class OficioBulkSendView(LoginRequiredMixin, View):
    """
    POST /projudi/oficios/enviar-em-massa/
    Envia todos os oficios pendentes.
    """
    def post(self, request):
        service = OficioService(request.user)
        pendentes = OficioRecord.objects.filter(user=request.user, status='pendente')
        
        enviados = 0
        falhas = 0
        
        for record in pendentes:
            try:
                resultado = service.enviar_oficio(record)
                if resultado.get('enviado'):
                    enviados += 1
                else:
                    falhas += 1
            except Exception as e:
                falhas += 1
                service.criar_log(record, 'erro_email', service.humanizar_erro(str(e)))
        
        try:
            service.fechar()
        except Exception:
            pass
        
        if enviados > 0:
            messages.success(request, f"✅ {enviados} oficios enviados com sucesso!")
        if falhas > 0:
            messages.warning(request, f"⚠️ {falhas} oficios nao puderam ser enviados. Verifique os logs.")
        if enviados == 0 and falhas == 0:
            messages.info(request, "Nenhum oficio pendente para enviar.")
        
        return HttpResponseRedirect(reverse('projudi:oficio_dashboard'))


class OficioBulkJuntarView(LoginRequiredMixin, View):
    """
    POST /projudi/oficios/juntar-em-massa/
    Junta todos os oficios ja enviados por email.
    """
    def post(self, request):
        service = OficioService(request.user)
        a_juntar = OficioRecord.objects.filter(user=request.user, status='enviado')
        
        juntados = 0
        falhas = 0
        
        for record in a_juntar:
            try:
                resultado = service.juntar_oficio(record)
                if resultado.get('juntado'):
                    juntados += 1
                else:
                    falhas += 1
            except Exception as e:
                falhas += 1
                service.criar_log(record, 'erro_juntada', f"Erro ao juntar em lote: {str(e)[:200]}")
        
        if juntados > 0:
            messages.success(request, f"✅ {juntados} oficios juntados com sucesso!")
        if falhas > 0:
            messages.warning(request, f"⚠️ {falhas} oficios nao puderam ser juntados. Verifique os logs.")
        if juntados == 0 and falhas == 0:
            messages.info(request, "Nenhum oficio pendente de juntada.")
        
        return HttpResponseRedirect(reverse('projudi:oficio_dashboard'))


class OficioBulkDispensarView(LoginRequiredMixin, View):
    """
    POST /projudi/oficios/dispensar-em-massa/
    Dispensa todos os oficios pendentes em lote.
    """
    def post(self, request):
        pendentes = OficioRecord.objects.filter(user=request.user, status='pendente')
        count = pendentes.count()
        
        for record in pendentes:
            record.status = 'dispensado'
            record.save(update_fields=['status'])
            OficioLog.objects.create(
                oficio=record,
                tipo='info',
                mensagem=f"Oficio dispensado em lote por {request.user.full_name or request.user.email}.",
                detalhes={'status_anterior': 'pendente', 'lote': True}
            )
        
        if count > 0:
            messages.success(request, f"🚫 {count} oficios dispensados em lote.")
        else:
            messages.info(request, "Nenhum oficio pendente para dispensar.")
        
        return HttpResponseRedirect(reverse('projudi:oficio_dashboard'))


class OficioBulkDispensarJuntadosView(LoginRequiredMixin, View):
    """
    POST /projudi/oficios/dispensar-juntados/
    Dispensa todos os oficios ja juntados (limpa a lista).
    """
    def post(self, request):
        juntados = OficioRecord.objects.filter(user=request.user, status='juntado')
        count = juntados.count()

        for record in juntados:
            record.status = 'dispensado'
            record.save(update_fields=['status'])
            OficioLog.objects.create(
                oficio=record,
                tipo='info',
                mensagem=f"Oficio juntado dispensado em lote por {request.user.full_name or request.user.email}.",
                detalhes={'status_anterior': 'juntado', 'lote': True}
            )

        if count > 0:
            messages.success(request, f"🚫 {count} oficios juntados dispensados (arquivados).")
        else:
            messages.info(request, "Nenhum oficio juntado para arquivar.")

        return HttpResponseRedirect(reverse('projudi:oficio_dashboard'))


class OficioLogsJsonView(LoginRequiredMixin, View):
    """
    GET /projudi/oficios/<pk>/logs/json/
    Retorna logs em JSON para atualizacao dinamica.
    """
    def get(self, request, pk):
        record = get_object_or_404(OficioRecord, pk=pk, user=request.user)
        service = OficioService(request.user)
        logs = service.logs_humanizados(record)
        return JsonResponse({'logs': logs})


class OficioRastrearCiapView(LoginRequiredMixin, View):
    """
    POST /projudi/oficios/rastrear-ciap/
    Varre movimentações do Projudi, identifica CIAP via RAG e expedir ofícios.
    """
    def post(self, request):
        import subprocess, os, sys

        script_path = os.path.join(settings.BASE_DIR, 'expedir_humanizado.py')
        env = {**os.environ, 'DJANGO_ALLOW_ASYNC_UNSAFE': 'true'}

        try:
            result = subprocess.run(
                [sys.executable or 'python3', script_path, '--rastrear', '--paginas', '3'],
                cwd=settings.BASE_DIR, env=env,
                capture_output=True, text=True,
                timeout=600,
            )

            output = (result.stdout or '') + (result.stderr or '')
            linhas_uteis = [
                l.strip() for l in output.split('\n')
                if l.strip() and not l.startswith('[INFO]') and not l.startswith('[16/')
            ]

            if result.returncode == 0:
                messages.success(request, '🔍 Rastreamento concluído! Verifique os ofícios expedidos.')
            else:
                messages.warning(request, f'⚠️ Código {result.returncode}. Verifique o log.')

            for linha in linhas_uteis[-15:]:
                if any(kw in linha.lower() for kw in ['ofi', '✅', '❌', '🔍', 'match', 'exped', 'erro', 'sucess', 'mov', '>>', 'conf', 'documento', 'processo', 'ciap']):
                    messages.info(request, linha[:250])

        except subprocess.TimeoutExpired:
            messages.error(request, '⏱️ Rastreamento excedeu 10 minutos. Tente novamente.')
        except Exception as e:
            messages.error(request, f'❌ Erro: {str(e)[:200]}')

        return HttpResponseRedirect(reverse('projudi:oficio_dashboard'))


class OficioExpedirCiapProcessoView(LoginRequiredMixin, View):
    """
    POST /projudi/oficios/expedir-ciap-proc/?cnj=...
    Expede ofício CIAP para um processo específico (CNJ).
    """
    def post(self, request):
        import subprocess, os, sys

        cnj = request.POST.get('cnj', '').strip()
        if not cnj:
            messages.warning(request, 'CNJ não informado.')
            return HttpResponseRedirect(reverse('projudi:oficio_dashboard'))

        script_path = os.path.join(settings.BASE_DIR, 'expedir_humanizado.py')
        env = {**os.environ, 'DJANGO_ALLOW_ASYNC_UNSAFE': 'true'}

        try:
            result = subprocess.run(
                [sys.executable or 'python3', script_path, cnj],
                cwd=settings.BASE_DIR, env=env,
                capture_output=True, text=True,
                timeout=300,
            )

            output = (result.stdout or '') + (result.stderr or '')
            linhas_uteis = [
                l.strip() for l in output.split('\n')
                if l.strip() and not l.startswith('[INFO]') and not l.startswith('[16/')
            ]

            if result.returncode == 0:
                messages.success(request, f'✅ Ofício CIAP para {cnj} expedido!')
            else:
                messages.warning(request, f'⚠️ Código {result.returncode}. Verifique o log.')

            for linha in linhas_uteis[-10:]:
                if any(kw in linha.lower() for kw in ['ofi', '✅', '❌', '🔍', 'match', 'exped', 'erro', 'sucess', 'mov', '>>', 'conf', 'documento']):
                    messages.info(request, linha[:250])

        except subprocess.TimeoutExpired:
            messages.error(request, '⏱️ Expedição excedeu 5 minutos. Tente novamente.')
        except Exception as e:
            messages.error(request, f'❌ Erro: {str(e)[:200]}')

        return HttpResponseRedirect(reverse('projudi:oficio_dashboard'))


# =============================================================================
# RETORNOS (respostas de e-mail recebidas)
# =============================================================================

class RetornoDashboardView(LoginRequiredMixin, TemplateView):
    """
    Dashboard de Retornos: oficios que receberam resposta por e-mail.
    """
    template_name = 'projudi/retorno_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        qs = OficioRecord.objects.filter(user=user, status__in=['enviado', 'juntado']).exclude(status='dispensado')

        context['total_enviados'] = qs.count()
        context['sem_retorno'] = qs.filter(status_retorno='sem_retorno').count()
        context['recebidos'] = qs.filter(status_retorno='recebido').count()
        context['lidos'] = qs.filter(status_retorno='lido').count()
        context['processados'] = qs.filter(status_retorno='processado').count()
        context['pendente_acao'] = qs.filter(status_retorno='pendente_acao').count()

        # Filtro: por default mostra todos com retorno (exceto sem_retorno)
        filtro = self.request.GET.get('filtro', 'todos')
        retornos_qs = qs.exclude(status_retorno='sem_retorno')
        if filtro == 'pendentes':
            retornos_qs = retornos_qs.exclude(status_retorno='processado')
        elif filtro == 'arquivados':
            retornos_qs = retornos_qs.filter(status_retorno='processado')
        context['retornos'] = retornos_qs.order_by('-data_retorno', '-updated_at')[:20]
        context['filtro'] = filtro

        return context


class RetornoListView(LoginRequiredMixin, ListView):
    template_name = 'projudi/retorno_list.html'
    context_object_name = 'retornos'
    paginate_by = 20

    def get_queryset(self):
        qs = OficioRecord.objects.filter(
            user=self.request.user,
            status__in=['enviado', 'juntado']
        )
        mostrar_arquivados = self.request.GET.get('arquivados') == '1'
        if not mostrar_arquivados:
            qs = qs.exclude(status_retorno='processado')
        return qs.order_by('-data_retorno', '-updated_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['mostrar_arquivados'] = self.request.GET.get('arquivados') == '1'
        context['pendentes_juntar'] = OficioRecord.objects.filter(
            user=self.request.user,
            status__in=['enviado', 'juntado'],
            status_retorno__in=['recebido', 'lido', 'pendente_acao'],
        ).count()
        return context


class RetornoDetailView(LoginRequiredMixin, DetailView):
    template_name = 'projudi/retorno_detail.html'
    model = OficioRecord
    context_object_name = 'oficio'
    pk_url_kwarg = 'pk'

    def get_queryset(self):
        return OficioRecord.objects.filter(
            user=self.request.user,
            status__in=['enviado', 'juntado']
        )


class RetornoJuntarRespostaView(LoginRequiredMixin, View):
    """
    POST /projudi/retornos/<pk>/juntar-resposta/
    Registra acuse de recebimento da resposta no Projudi.
    """
    def post(self, request, pk):
        record = get_object_or_404(OficioRecord, pk=pk, user=request.user)
        service = OficioService(request.user)
        try:
            resultado = service.juntar_resposta(record)
            if resultado.get('juntado'):
                messages.success(request, f"Resposta do oficio {record.numero_oficio} juntada no Projudi!")
            else:
                messages.error(request, f"Falha ao juntar resposta: {resultado.get('erro', 'Erro desconhecido')}")
        except Exception as e:
            messages.error(request, f"Erro ao juntar resposta: {str(e)[:100]}")
        finally:
            try:
                service.fechar()
            except Exception:
                pass
        return HttpResponseRedirect(reverse('projudi:retorno_detail', kwargs={'pk': pk}))


class RetornoProcessarView(LoginRequiredMixin, View):
    """
    POST /projudi/retornos/<pk>/processar/
    Atualiza status de retorno e observacao.
    """
    def post(self, request, pk):
        record = get_object_or_404(OficioRecord, pk=pk, user=request.user)

        novo_status = request.POST.get('status_retorno', 'processado')
        observacao = request.POST.get('observacao_retorno', '').strip()

        record.status_retorno = novo_status
        if observacao:
            if record.observacao_retorno:
                record.observacao_retorno += f"\n\n{request.user.full_name} em {datetime.now().strftime('%d/%m/%Y %H:%M')}:\n{observacao}"
            else:
                record.observacao_retorno = f"{request.user.full_name} em {datetime.now().strftime('%d/%m/%Y %H:%M')}:\n{observacao}"

        if novo_status == 'processado' and not record.data_retorno:
            record.data_retorno = timezone.now()

        record.save()

        OficioLog.objects.create(
            oficio=record,
            tipo='resposta',
            mensagem=f"Retorno marcado como '{record.get_status_retorno_display()}' por {request.user.full_name}.",
            detalhes={'observacao': observacao, 'status': novo_status}
        )

        messages.success(request, f"Retorno do oficio {record.numero_oficio} atualizado com sucesso!")
        return HttpResponseRedirect(reverse('projudi:retorno_detail', kwargs={'pk': pk}))


class RetornoJuntarTodosView(LoginRequiredMixin, View):
    """
    POST /projudi/retornos/juntar-todos/
    Registra acuse no Projudi para todos os retornos pendentes.
    """
    def post(self, request):
        service = OficioService(request.user)
        pendentes = OficioRecord.objects.filter(
            user=request.user,
            status__in=['enviado', 'juntado'],
            status_retorno__in=['recebido', 'lido', 'pendente_acao'],
        )

        juntados = 0
        falhas = 0

        for record in pendentes:
            try:
                resultado = service.juntar_resposta(record)
                if resultado.get('juntado'):
                    juntados += 1
                else:
                    falhas += 1
            except Exception as e:
                falhas += 1
                service.criar_log(record, 'erro_juntada', str(e)[:100])

        try:
            service.fechar()
        except Exception:
            pass

        if juntados > 0:
            messages.success(request, f"{juntados} retornos juntados no Projudi com sucesso!")
        if falhas > 0:
            messages.warning(request, f"{falhas} retornos nao puderam ser juntados. Verifique os logs.")
        if juntados == 0 and falhas == 0:
            messages.info(request, "Nenhum retorno pendente para juntar.")

        return HttpResponseRedirect(reverse('projudi:retorno_dashboard'))


class RetornoImportarView(LoginRequiredMixin, View):
    """
    POST /projudi/retornos/importar/
    Importa respostas de e-mail e vincula aos oficios.
    Renderiza o dashboard com o log da importacao.
    """
    def post(self, request):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        limite = request.POST.get('limite', '30')

        try:
            call_command('receber_respostas', stdout=out, stderr=out, limite=int(limite))
            log_output = out.getvalue()
        except Exception as e:
            log_output = f"Erro na importacao: {e}"

        # Renderiza o dashboard com o log
        view = RetornoDashboardView()
        view.setup(request)
        context = view.get_context_data()
        context['log_importacao'] = log_output
        return render(request, 'projudi/retorno_dashboard.html', context)


class OficioExpedirCiapView(LoginRequiredMixin, View):
    """
    POST /projudi/oficios/expedir-ciap/
    Executa expedição CIAP sincronamente igual "Enviar Pendentes".
    """
    def post(self, request):
        import subprocess, os, json, sys

        # Coletar CNJs dos processos com RAG CIAP do tenant do usuario
        from processes.models import RAGExample
        rags = RAGExample.objects.filter(
            suggested_templates=5,
            process__isnull=False,
            tenant=request.user.tenant,
            active=True,
        ).select_related('process')

        cnjs = sorted(set(
            rag.process.number for rag in rags
            if rag.process and rag.process.number
        ))

        if not cnjs:
            messages.warning(request, 'Nenhum processo com RAG CIAP encontrado para este usuário.')
            return HttpResponseRedirect(reverse('projudi:oficio_dashboard'))

        # Escrever fila
        fila_path = '/tmp/fila_expedir_ciap.json'
        with open(fila_path, 'w') as f:
            json.dump(cnjs, f)
        
        print(f'[DEBUG] Fila CIAP: {cnjs}')
        
        # Executar script sincronamente (bloqueante, igual Enviar Pendentes)
        script_path = os.path.join(settings.BASE_DIR, 'expedir_humanizado.py')
        env = {**os.environ, 'DJANGO_ALLOW_ASYNC_UNSAFE': 'true'}

        try:
            result = subprocess.run(
                [sys.executable or 'python3', script_path, '--fila'],
                cwd=settings.BASE_DIR, env=env,
                capture_output=True, text=True,
                timeout=300,
            )

            output = (result.stdout or '') + (result.stderr or '')
            linhas_uteis = [
                l.strip() for l in output.split('\n')
                if l.strip() and not l.startswith('[INFO]') and not l.startswith('[16/')
            ]

            if result.returncode == 0:
                messages.success(request, '✅ Ofício(s) CIAP expedido(s) com sucesso!')
            else:
                messages.warning(request, f'⚠️ Código {result.returncode}. Verifique o log.')

            for linha in linhas_uteis[-10:]:
                if any(kw in linha.lower() for kw in ['ofi', '✅', '❌', '🔍', 'match', 'exped', 'erro', 'sucess', 'mov', '>>', 'conf', 'documento']):
                    messages.info(request, linha[:250])

        except subprocess.TimeoutExpired:
            messages.error(request, '⏱️ Expedição excedeu 5 minutos. Tente novamente.')
        except Exception as e:
            messages.error(request, f'❌ Erro: {str(e)[:200]}')

        return HttpResponseRedirect(reverse('projudi:oficio_dashboard'))

class OficioProcessarPendentesView(LoginRequiredMixin, View):
    def post(self, request):
        from projudi.oficio_service import OficioService
        service = OficioService(request.user)
        pendentes = OficioRecord.objects.filter(
            user=request.user,
            status__in=['pendente', 'falhou_email']
        )[:10]
        cont = {'env': 0, 'junt': 0, 'err': 0}
        for r in pendentes:
            try:
                res = service.processar_oficio(r)
                if res.get('enviado'): cont['env'] += 1
                if res.get('juntado'): cont['junt'] += 1
                if res.get('erro') and not res.get('juntado'): cont['err'] += 1
            except Exception:
                cont['err'] += 1
        msgs = []
        if cont['env']: msgs.append(f"Enviados: {cont['env']}")
        if cont['junt']: msgs.append(f"Juntados: {cont['junt']}")
        if cont['err']: msgs.append(f"Erros: {cont['err']}")
        if msgs:
            messages.success(request, ' | '.join(msgs))
        else:
            messages.info(request, 'Nenhum pendente.')
        return HttpResponseRedirect(reverse('projudi:oficio_dashboard'))
