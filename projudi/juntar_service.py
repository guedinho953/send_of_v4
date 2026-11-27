"""Planejamento (dry-run) de juntada e intimação de certidões.

Nesta etapa o serviço monta o plano completo — certidão, processo, polo,
prazo e observações — mas NÃO chama o Projudi. A execução real será feita
pelo MovimentacaoService depois da validação do plano.
"""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup
from django.conf import settings


def _template_nome(registro) -> str:
    if registro.tipo_prazo == 'inominado':
        return 'Certidão de Recurso Inominado (COJE)'
    if registro.tipo_prazo == 'decurso_pagamento':
        return 'Certidão de Decurso de Prazo para Pagamento Voluntário'
    return 'Certidão de Prazo — Modelo Base'


def _html_certidao(registro) -> str:
    caminho = Path(registro.certidao_path or '')
    if not caminho.is_file():
        return ''
    try:
        resolvido = caminho.resolve()
    except OSError:
        return ''
    pasta_var = (Path(settings.BASE_DIR) / 'var').resolve()
    if pasta_var not in resolvido.parents:
        return ''
    html = resolvido.read_text(encoding='utf-8')
    soup = BeautifulSoup(html, 'html.parser')
    folha = soup.find('div', class_='folha')
    if folha:
        return folha.decode_contents().strip()
    return (soup.body.decode_contents() if soup.body else html).strip()


def _processo_url(registro, url_informada='') -> str:
    from processes.models import Process
    from projudi.models import OficioRecord

    proc = Process.objects.filter(number=registro.processo).first()
    if proc and proc.projudi_url:
        return proc.projudi_url
    if url_informada:
        return url_informada
    oficio = (
        OficioRecord.objects
        .filter(numero_processo_cnj=registro.processo)
        .exclude(processo='')
        .first()
    )
    if oficio:
        return (
            'https://projudi.tjba.jus.br/projudi/listagens/'
            f'DadosProcesso?numeroProcesso={oficio.processo}'
        )
    return ''


def _proc_projudi(url) -> str:
    match = re.search(r'numeroProcesso=(\d+)', url or '')
    return match.group(1) if match else ''


def _situacao(registro) -> str:
    if registro.tipo_prazo != 'inominado':
        return 'outro'
    if registro.tempestivo is False:
        return 'intempestivo'
    if registro.preparo_status == 'gratuidade':
        return 'gratuidade'
    if registro.preparo_status in (
            'completo', 'incompleto', 'nao_pago'):
        return 'preparo'
    return 'indefinida'


def _polo_recorrente(registro) -> str:
    from processes.models import Party, Process

    match = re.search(
        r'Recorrente:\s*(.+)', registro.parte or '', re.I)
    if not match:
        return ''
    nome = match.group(1).strip()
    if not nome:
        return ''
    proc = Process.objects.filter(number=registro.processo).first()
    if not proc:
        return ''
    parte = (
        Party.objects
        .filter(process=proc, name__icontains=nome[:40])
        .first()
    )
    if parte and parte.is_author_side:
        return 'autores'
    if parte and parte.is_defendant_side:
        return 'res'
    return ''


def _polo_intimacao(registro, situacao, polo_informado='') -> str:
    if polo_informado in ('autores', 'res'):
        return polo_informado
    recorrente = _polo_recorrente(registro)
    if situacao == 'intempestivo':
        return recorrente or 'autores'
    if situacao in ('preparo', 'gratuidade'):
        return 'res' if recorrente == 'autores' else 'autores'
    return 'autores'


def _prazo_intimacao(registro, situacao, prazo_informado='') -> str:
    if prazo_informado in ('5', '10', '15'):
        return prazo_informado
    return '5' if situacao == 'intempestivo' else '10'


def _observacao_intimacao(registro, situacao) -> str:
    evento = str(registro.evento_recurso or '').strip()
    texto_evento = f' (evento {evento})' if evento.isdigit() else ''
    if situacao in ('preparo', 'gratuidade'):
        return (
            'Intime(m)-se o(s) recorrido(s) para que, querendo, '
            'apresente(m) contrarrazões ao Recurso Inominado'
            f'{texto_evento}, no prazo de 10 dias úteis.'
        )
    if situacao == 'intempestivo':
        return (
            'Intime-se o recorrente para ciência da INTEMPESTIVIDADE do '
            'recurso interposto/apresentado, conforme certidão em anexo.'
        )
    return ''


def montar_plano(registro, user=None, processo_url='', polo='',
                 prazo='') -> dict:
    """Monta o plano sem escrever no Projudi."""
    template_nome = _template_nome(registro)
    html = _html_certidao(registro)
    url = _processo_url(registro, processo_url)
    interno = _proc_projudi(url)
    situacao = _situacao(registro)
    polo_final = _polo_intimacao(registro, situacao, polo)
    prazo_final = _prazo_intimacao(registro, situacao, prazo)
    observacao_intimacao = _observacao_intimacao(registro, situacao)

    erros = []
    if not html:
        erros.append(
            'Preview da certidão não encontrado. Gere novamente a certidão.')
    if not url:
        erros.append(
            'URL do processo no Projudi não cadastrada. Informe a URL '
            'DadosProcesso.')
    if not interno:
        erros.append(
            'Número interno do Projudi (numeroProcesso=...) não encontrado '
            'na URL.')

    pode_intimar = (
        registro.tipo_prazo == 'inominado'
        and situacao in ('preparo', 'gratuidade', 'intempestivo')
    )

    return {
        'registro': registro,
        'template_nome': template_nome,
        'processo': registro.processo,
        'processo_url': url,
        'proc_projudi': interno,
        'html_certidao': html,
        'html_tamanho': len(html),
        'parte': registro.parte,
        'situacao': situacao,
        'polo': polo_final,
        'prazo': prazo_final,
        'pode_intimar': pode_intimar,
        'observacao_juntada': (
            f'Juntada da {template_nome}.'
        ),
        'observacao_intimacao': observacao_intimacao,
        'erros': erros,
        'preview_disponivel': bool(registro.certidao_path),
        'pode_juntar': bool(html and url and interno),
    }
