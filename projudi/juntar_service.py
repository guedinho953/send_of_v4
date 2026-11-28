"""Planejamento e execução de juntada/intimação de certidões.

O plano mostra certidão, processo, polo, prazo e observações. A juntada e a
intimação são executadas pelo MovimentacaoService depois da confirmação do
usuário. Para a impugnação/embargos à execução, a intimação do embargado só
é oferecida quando os embargos são TEMPESTIVOS.
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
    from .arquivo_texto import ler_certidao
    html = ler_certidao(resolvido)
    soup = BeautifulSoup(html, 'html.parser')
    folha = soup.find('div', class_='folha')
    if folha:
        return folha.decode_contents().strip()
    return (soup.body.decode_contents() if soup.body else html).strip()


def _processo_url(registro, url_informada='') -> str:
    from processes.models import Process
    from projudi.models import OficioRecord

    if getattr(registro, 'processo_url', ''):
        return registro.processo_url
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
    if registro.tipo_prazo == 'impugnacao_embargos_execucao':
        if registro.tempestivo is True:
            return 'embargos_tempestivos'
        if registro.tempestivo is False:
            return 'embargos_intempestivos'
        return 'outro'
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


def _nome_parte_por_polo(registro, polo):
    """Nome da parte que será intimada, quando cadastrada no processo."""
    from processes.models import Party, Process

    proc = Process.objects.filter(number=registro.processo).first()
    if not proc:
        return ''
    if polo == 'autores':
        papeis = ('autor', 'exequente')
    elif polo == 'res':
        papeis = ('reu', 'executado')
    else:
        return ''
    parte = Party.objects.filter(process=proc, role__in=papeis).first()
    return parte.name if parte else ''


def _polo_intimacao(registro, situacao, polo_informado='') -> str:
    if polo_informado in ('autores', 'res'):
        return polo_informado
    if registro.tipo_prazo == 'impugnacao_embargos_execucao':
        # O embargado é o exequente/credor (polo ativo).
        return 'autores'
    recorrente = _polo_recorrente(registro)
    if situacao == 'intempestivo':
        return recorrente or 'autores'
    if situacao in ('preparo', 'gratuidade'):
        return 'res' if recorrente == 'autores' else 'autores'
    return 'autores'


def _prazo_intimacao(registro, situacao, prazo_informado='') -> str:
    if registro.tipo_prazo == 'impugnacao_embargos_execucao':
        return '15'
    if prazo_informado in ('5', '10', '15'):
        return prazo_informado
    return '5' if situacao == 'intempestivo' else '10'


def _observacao_juntada(registro, template_nome) -> str:
    """Texto da juntada; nos embargos usa a conclusão e a segurança."""
    if registro.tipo_prazo == 'impugnacao_embargos_execucao':
        conclusao = (
            'TEMPESTIVIDADE' if registro.tempestivo
            else 'INTEMPESTIVIDADE')
        texto = (
            f'Juntada da Certidão de {conclusao} da impugnação/Embargos '
            'à Execução')
        if registro.tempestivo:
            seguranca = registro.seguranca_juizo
            if seguranca == 'parcial':
                texto += (
                    ' - depósito PARCIAL, NÃO HAVENDO SEGURANÇA INTEGRAL '
                    'DO JUÍZO')
            elif seguranca == 'integral':
                texto += ' - SEGURANÇA INTEGRAL DO JUÍZO'
            elif seguranca == 'nenhuma':
                texto += ' - NÃO HOUVE SEGURANÇA DO JUÍZO'
        return texto
    return f'Juntada da {template_nome}.'


def _observacao_intimacao(registro, situacao) -> str:
    evento = str(registro.evento_recurso or '').strip()
    texto_evento = f' (evento {evento})' if evento.isdigit() else ''
    if registro.tipo_prazo == 'impugnacao_embargos_execucao':
        if situacao != 'embargos_tempestivos':
            return ''
        return (
            'Intime-se o(a) embargado(a) para, querendo, no prazo de 15 '
            '(quinze) dias úteis, apresentar impugnação/manifestação/'
            'contrarrazões aos embargos à execução'
            f'{texto_evento}, conforme certidão em anexo.'
        )
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

    from projudi.models import MovimentacaoRecord

    ja_juntada = (
        MovimentacaoRecord.objects
        .filter(
            processo=registro.processo,
            descricao_movimentacao=template_nome,
            status='cumprido',
        )
        .order_by('-created_at')
        .first()
    )

    if registro.tipo_prazo == 'impugnacao_embargos_execucao':
        pode_intimar = situacao == 'embargos_tempestivos' and not ja_juntada
    else:
        pode_intimar = (
            registro.tipo_prazo == 'inominado'
            and situacao in ('preparo', 'gratuidade', 'intempestivo')
            and not ja_juntada
        )

    prazo_codigo = {
        '5': '2', '10': '3', '15': '4',
    }.get(prazo_final, '3')

    parte_exibida = registro.parte
    parte_label = 'Parte/recorrente'
    if registro.tipo_prazo == 'impugnacao_embargos_execucao':
        parte_exibida = _nome_parte_por_polo(registro, polo_final)
        parte_label = (
            'Embargado(a)' if polo_final == 'autores'
            else 'Embargante/Executado(a)')
        if not parte_exibida:
            parte_exibida = registro.parte
            parte_label = 'Parte nos autos'

    situacao_label = {
        'preparo': 'Preparo regular',
        'gratuidade': 'Gratuidade',
        'intempestivo': 'INTEMPESTIVO',
        'embargos_tempestivos': 'EMBARGOS TEMPESTIVOS',
        'embargos_intempestivos': 'EMBARGOS INTEMPESTIVOS',
    }.get(situacao, situacao)

    return {
        'registro': registro,
        'template_nome': template_nome,
        'processo': registro.processo,
        'processo_url': url,
        'proc_projudi': interno,
        'html_certidao': html,
        'html_tamanho': len(html),
        'parte': parte_exibida,
        'parte_label': parte_label,
        'situacao': situacao,
        'situacao_label': situacao_label,
        'polo': polo_final,
        'prazo': prazo_final,
        'prazo_codigo': prazo_codigo,
        'motivo_intimacao': '3',
        'tipo_localizador': registro.tipo_localizador or '',
        'localizador': registro.localizador or '',
        'tipo_conclusao': registro.tipo_conclusao or '18',
        'juiz_conclusao': registro.juiz_conclusao or '41201',
        'pode_intimar': pode_intimar,
        'observacao_juntada': _observacao_juntada(
            registro, template_nome),
        'observacao_intimacao': observacao_intimacao,
        'erros': erros,
        'preview_disponivel': bool(registro.certidao_path),
        'pode_juntar': bool(html and url and interno) and not ja_juntada,
        'ja_juntada': bool(ja_juntada),
        'movimentacao_id': ja_juntada.id if ja_juntada else None,
        'assinatura_manual': not bool(
            getattr(user, 'projudi_password', '') if user else ''),
    }


def executar_juntada(registro, user, plano=None):
    """Executa a juntada real no Projudi via MovimentacaoService."""
    from projudi.movimentacao_service import MovimentacaoService

    plano = plano or montar_plano(registro, user)
    if plano.get('ja_juntada'):
        raise ValueError('Certidão já juntada no Projudi.')
    if plano.get('erros'):
        raise ValueError('; '.join(plano['erros']))

    service = MovimentacaoService(user)
    record = service.importar(
        processo_numero=registro.processo,
        act_verb='certifique-se',
        observacao=plano['observacao_juntada'],
        categoria='certidao',
        processo_cnj=registro.processo,
        parte_nome=registro.parte or '',
        url_processo=plano['processo_url'],
        codigo_movimentacao='581',
        descricao_movimentacao=plano['template_nome'],
        tipo_localizador=plano.get('tipo_localizador') or '',
        localizador=plano.get('localizador') or '',
    )
    service.criar_log(
        record,
        'info',
        f'Dados internos da certidão: {registro.motivo}',
        {
            'prazo_djen_id': registro.id,
            'evento_intimacao': registro.evento_intimacao,
        },
    )
    ok = service.executar_requests(
        record,
        certidao_html=plano['html_certidao'],
        certidao_titulo=plano['template_nome'],
    )
    return ok, record


def executar_contadoria(registro, user, plano):
    """Remete os autos à contadoria (movimentação 11383 + contador)."""
    from projudi.movimentacao_service import MovimentacaoService

    service = MovimentacaoService(user)
    record = service.importar(
        processo_numero=registro.processo,
        act_verb='contadoria',
        observacao='Remessa à contadoria.',
        categoria='outro',
        processo_cnj=registro.processo,
        url_processo=plano.get('processo_url') or '',
        codigo_movimentacao='11383',
        descricao_movimentacao='Remessa à Contadoria',
    )
    ok = service.executar_requests(record, enviar_contador=True)
    return ok, record


def executar_conclusao(registro, user, plano, tipo_conclusao='18',
                       juiz_conclusao='41201'):
    """Registra a conclusão ao juiz no Projudi (movimentação 11383).

    O tipo segue o radio ``conclusao`` do Projudi: 1=Despacho,
    2=Decisão, 3=Sentença, 18=Embargos de Execução, 19=Sentença
    Extintiva, entre outros. O juiz padrão é o Dr. Martinho (41201).
    """
    from projudi.movimentacao_service import MovimentacaoService

    service = MovimentacaoService(user)
    record = service.importar(
        processo_numero=registro.processo,
        act_verb='conclusao',
        observacao='Conclusão',
        categoria='outro',
        processo_cnj=registro.processo,
        url_processo=plano.get('processo_url') or '',
        codigo_movimentacao='11383',
        descricao_movimentacao='Conclusão',
    )
    ok = service.executar_requests(
        record,
        conclusao=str(tipo_conclusao or '18'),
        login_conclusao_pessoal=str(juiz_conclusao or '41201'),
    )
    return ok, record


def executar_juntada_e_intimacao(registro, user, plano=None):
    """Junta a certidão e, se cabível, intima o embargado.

    A juntada é executada primeiro. Só depois de confirmada a certidão no
    Projudi é feita a intimação do embargado para manifestação (15 dias).
    Retorna ``(juntada_ok, record, intimacao_ok, erro_intimacao)``.
    """
    plano = plano or montar_plano(registro, user)
    if registro.tipo_prazo != 'impugnacao_embargos_execucao':
        raise ValueError(
            'A juntada com intimação automática está disponível apenas '
            'para a impugnação/embargos à execução.')
    if not plano.get('pode_intimar'):
        raise ValueError(
            'A intimação do embargado só é feita quando os embargos são '
            'TEMPESTIVOS e a certidão ainda não foi juntada.')
    if plano.get('ja_juntada'):
        raise ValueError('Certidão já juntada no Projudi.')

    ok, record = executar_juntada(registro, user, plano=plano)
    if not ok:
        return False, record, False, ''

    from projudi.movimentacao_service import MovimentacaoService

    try:
        intimacao_ok = MovimentacaoService(user).executar_com_intimacao(
            processo_numero=registro.processo,
            observacao=plano['observacao_intimacao'],
            descricao_mov='Intimação',
            proc_projudi=plano['proc_projudi'],
            prazo_intimacao=plano.get('prazo_codigo') or '4',
            motivo_intimacao=plano.get('motivo_intimacao') or '3',
            polo_intimacao=plano.get('polo') or 'autores',
            tipo_localizador=plano.get('tipo_localizador') or '',
            localizador=plano.get('localizador') or '',
            envia_mp=bool(plano.get('enviar_mp')),
            cod_nucleo_mp=plano.get('cod_nucleo_mp') or '31',
            tipo_parecer_mp=plano.get('tipo_parecer_mp') or '6',
            prazo_mp=plano.get('prazo_mp') or '5',
            promotor_mp=plano.get('promotor_mp') or None,
        )
        return True, record, bool(intimacao_ok), ''
    except Exception as exc:
        return True, record, False, str(exc)
