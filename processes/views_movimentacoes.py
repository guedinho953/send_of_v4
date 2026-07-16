"""
Views para o pipeline de processamento de movimentacoes.

Endpoints:
- POST /processes/<id>/analisar-movimentacoes/
  Recebe HTML do DadosProcesso, processa e retorna resumo.

- GET /processes/<id>/resumo-movimentacoes/
  Retorna resumo salvo no banco.

- GET /processes/<id>/comandos-pendentes/
  Lista comandos cumpriveis pendentes.
"""

import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST, require_GET

from .models import Process, Movement, MovementCommand, ProcessSummary, CommunicationTracking
from .movimentacoes_service import MovimentacoesService


def _json_response(data: dict, status=200):
    return JsonResponse(data, status=status)


@require_POST
@csrf_exempt
def analisar_movimentacoes(request, process_id):
    """
    POST /processes/<id>/analisar-movimentacoes/
    Body: multipart/form-data ou JSON com campo 'html'
    """
    try:
        processo = get_object_or_404(Process, id=process_id)

        # Extrair HTML do body
        html = request.POST.get('html', '') or request.FILES.get('html_file')
        if html and hasattr(html, 'read'):
            html = html.read().decode('utf-8')

        if not html:
            return _json_response({
                'success': False,
                'error': 'HTML do DadosProcesso eh obrigatorio'
            }, 400)

        # Executar pipeline
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

        return _json_response({
            'success': True,
            'processo': resultado['processo'],
            'movimentacoes': resultado['movimentacoes'],
            'comandos': resultado['comandos'],
            'completaveis': resultado['completaveis'],
            'comunicacoes_rastreadas': resultado['comunicacoes_rastreadas'],
            'automatizavel': resultado['automatizavel'],
            'status': resultado['status'],
        })

    except Exception as e:
        import traceback
        return _json_response({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }, 500)


@require_GET
def resumo_movimentacoes(request, process_id):
    """
    GET /processes/<id>/resumo-movimentacoes/
    Retorna resumo completo do processo.
    """
    processo = get_object_or_404(Process, id=process_id)
    summary = getattr(processo, 'summary', None)

    movimentacoes = Movement.objects.filter(process=processo).values(
        'event_number', 'category', 'act_description', 'act_date',
        'communication_status', 'communication_means', 'recipient'
    )

    return _json_response({
        'success': True,
        'processo': processo.number,
        'status': summary.automation_status if summary else 'nao_analisado',
        'automatizavel': summary.is_automatable if summary else False,
        'total_movimentacoes': summary.total_movements if summary else 0,
        'total_comandos': summary.total_commands if summary else 0,
        'completaveis': summary.completable_commands if summary else 0,
        'movimentacoes': list(movimentacoes),
    })


@require_GET
def comandos_pendentes(request, process_id):
    """
    GET /processes/<id>/comandos-pendentes/
    Lista comandos cumpriveis (is_completable=True).
    """
    processo = get_object_or_404(Process, id=process_id)

    comandos = MovementCommand.objects.filter(
        movement__process=processo,
        is_completable=True
    ).select_related('movement').values(
        'id',
        'movement__event_number',
        'movement__act_description',
        'act_verb',
        'recipient',
        'means',
        'objective',
        'deadline',
        'conditions',
        'extracted_at'
    )

    # Montar prompt para cada comando
    service = MovimentacoesService(user=request.user)
    prompts = []
    for cmd in comandos:
        movement = Movement.objects.get(event_number=cmd['movement__event_number'], process=processo)
        prompt = service.preparar_prompt_cumprimento(processo, movement)
        prompts.append({
            'comando_id': cmd['id'],
            'evento': cmd['movement__event_number'],
            'ato': cmd['act_verb'],
            'prompt': prompt
        })

    return _json_response({
        'success': True,
        'processo': processo.number,
        'total_pendentes': len(comandos),
        'comandos': list(comandos),
        'prompts': prompts,
    })


@require_GET
def comunicacoes_rastreadas(request, process_id):
    """
    GET /processes/<id>/comunicacoes-rastreadas/
    Lista rastreamento de comunicacoes (expedidas x lidas).
    """
    processo = get_object_or_404(Process, id=process_id)

    comunicacoes = CommunicationTracking.objects.filter(
        process=processo
    ).values(
        'type', 'event_expedido', 'date_expedido', 'act_expedido',
        'recipient', 'means', 'status', 'date_lido', 'event_lido',
        'deadline_days'
    )

    return _json_response({
        'success': True,
        'processo': processo.number,
        'total': len(comunicacoes),
        'comunicacoes': list(comunicacoes),
    })


@require_POST
@csrf_exempt
def buscar_dados_processo(request, process_id):
    """
    POST /processes/<id>/buscar-dados-processo/
    Baixa o HTML do DadosProcesso do Projudi automaticamente
    usando os cookies salvos no ProjudiSession.
    Retorna o HTML bruto para ser processado.
    """
    try:
        processo = get_object_or_404(Process, id=process_id)

        # Importar servico do app projudi
        from projudi.services import ProjudiService
        projudi = ProjudiService(user=request.user)

        # Tentar capturar cookies frescos
        session = projudi._capturar_cookies_fresh()
        if not session:
            return _json_response({
                'success': False,
                'error': (
                    'Nao foi possivel capturar sessao do Projudi.\n'
                    'Certifique-se de estar logado no Firefox do Windows '
                    'e re-execute o script de captura de cookies.'
                )
            }, 401)

        # Baixar DadosProcesso
        url = (
            f'https://projudi.tjba.jus.br/projudi/'
            f'listagens/DadosProcesso?numeroProcesso={processo.number}'
        )
        print(f'[INFO] Buscando DadosProcesso: {url}')
        resp = session.get(url)

        if resp.status_code != 200 or 'sessao expirou' in resp.text.lower():
            return _json_response({
                'success': False,
                'error': (
                    f'Sessao expirada ou pagina invalida '
                    f'(status={resp.status_code})'
                )
            }, 401)

        html = resp.text

        # Salvar HTML no campo do processo (opcional)
        # processo.projudi_raw_html = html
        # processo.save()

        # Salvar cookies atualizados
        projudi._salvar_cookies(session.cookies.get_dict())

        return _json_response({
            'success': True,
            'processo': processo.number,
            'html_length': len(html),
            'html': html[:5000] + '... [truncado]' if len(html) > 5000 else html,
        })

    except Exception as e:
        import traceback
        return _json_response({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }, 500)
