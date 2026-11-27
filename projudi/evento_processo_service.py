"""Datas de eventos e intimações do processo no Projudi.

Usado quando o usuário informa apenas o evento da petição/despacho: o
sistema busca a data no processo, sem exigir o preenchimento manual.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .peticao_service import _norm, _nome_compacto
from .transito_julgado_service import TransitoJulgadoService, _data_br


def _texto_proprio(texto):
    """Remove os movimentos anteriores repetidos dentro da linha HTML."""
    return re.split(
        r'\s+Movimentação sem arquivos\b',
        texto or '',
        maxsplit=1,
        flags=re.I,
    )[0]


def _data_disponibilizacao(texto):
    m = re.search(
        r'disponibiliz[^\n]{0,120}?(\d{1,2}/\d{1,2}/\d{2,4})',
        texto or '', re.I,
    )
    return _data_br(m.group(1)) if m else None


def _descricao_evento(texto):
    texto = re.sub(r'^\s*\d+\s*', '', texto or '')
    texto = re.split(r'\b\d{2}/\d{2}/\d{2,4}\b', texto)[0]
    texto = re.split(r'\s+Arquivos:', texto, flags=re.I)[0]
    return _norm(texto).strip()


def _classificar_meio(texto):
    alvo = _norm(texto)
    if ('DJEN' in alvo
            or 'DOMICILIO ELETRONICO' in alvo
            or 'DISPONIBILIZ' in alvo):
        return 'eletronico'
    if 'ADVOGADO' in alvo:
        return 'advogado'
    if 'E-MAIL' in alvo or 'EMAIL' in alvo:
        return 'email'
    if 'AVISO DE RECEBIMENTO' in alvo or re.search(r'\bAR\b', alvo):
        return 'ar'
    if 'MANDADO' in alvo:
        return 'mandado'
    return 'intimacao'


def carregar_movimentacoes(user, processo_url):
    if not processo_url:
        return []
    session = TransitoJulgadoService(user)._sessao()
    if not session:
        return []
    try:
        resposta = session.get(processo_url, timeout=30)
        if resposta.status_code != 200:
            return []
        soup = BeautifulSoup(resposta.text, 'html.parser')
        return TransitoJulgadoService(user)._movimentacoes(soup)
    except Exception:
        return []


def data_evento_processo(user, processo_url, evento):
    """Data do próprio evento informado (petição, requerimento etc.)."""
    alvo = str(evento or '').strip()
    if not alvo:
        return None
    for mov in carregar_movimentacoes(user, processo_url):
        if str(mov.get('evento')) != alvo:
            continue
        texto = _texto_proprio(mov.get('texto') or '')
        return (
            _data_disponibilizacao(texto)
            or mov.get('data')
            or _data_br(texto)
        )
    return None


def localizar_intimacao_do_processo(user, processo_url, evento, parte=''):
    """Intimação do evento informado ou a primeira intimação posterior.

    Retorna ``{'evento', 'data', 'meio', 'texto'}`` ou ``None``.
    """
    alvo_evento = str(evento or '').strip()
    if not alvo_evento:
        return None
    movs = carregar_movimentacoes(user, processo_url)
    if not movs:
        return None

    alvo_parte = _nome_compacto(parte) if parte else ''

    def item(mov, origem):
        texto = _texto_proprio(mov.get('texto') or '')
        data = (
            _data_disponibilizacao(texto)
            or mov.get('data')
            or _data_br(texto)
        )
        if not data:
            return None
        return {
            'evento': str(mov.get('evento')),
            'data': data,
            'meio': _classificar_meio(texto),
            'texto': texto[:500],
            'origem': origem,
        }

    mov_evento = next(
        (m for m in movs if str(m.get('evento')) == alvo_evento), None
    )
    if not mov_evento:
        return None

    texto_evento = _norm(_texto_proprio(mov_evento.get('texto') or ''))
    descricao_evento = _descricao_evento(
        _texto_proprio(mov_evento.get('texto') or '')
    )
    if any(k in texto_evento for k in ('INTIMA', 'DISPONIBILIZ')):
        achado = item(mov_evento, 'evento')
        if achado:
            return achado

    candidatos = []
    try:
        numero_evento = int(alvo_evento)
    except ValueError:
        return None
    for mov in movs:
        try:
            numero = int(mov.get('evento'))
        except (TypeError, ValueError):
            continue
        if numero <= numero_evento:
            continue
        texto = _texto_proprio(mov.get('texto') or '')
        inicio = _norm(re.sub(r'^\s*\d+\s*', '', texto))
        if inicio.startswith((
            'ATO ORDINATORIO', 'DECORRIDO PRAZO', 'JUNTADA',
            'CERTIDAO', 'CONCLUSAO', 'DOCUMENTO',
        )):
            continue
        up = _norm(texto)
        if not any(k in up for k in ('INTIMA', 'DISPONIBILIZ')):
            continue
        if alvo_parte and alvo_parte not in _nome_compacto(texto):
            continue
        achado = item(mov, 'posterior')
        if not achado:
            continue
        # Publicação efetiva no DJEN vale mais que a simples expedição.
        if 'AGUARDANDO DISPONIBILIZACAO' in up:
            score = 100
        elif 'DISPONIBILIZACAO NO DIARIO' in up or 'DJEN' in up:
            score = 1000
        else:
            score = 500
        if descricao_evento and descricao_evento in up:
            score += 500
        elif 'REFERENTE AO EVENTO' in up:
            score -= 50
        candidatos.append((score, numero, achado))

    if not candidatos:
        return None
    # Maior prioridade (publicação) e, depois, a intimação mais antiga.
    candidatos.sort(key=lambda c: (-c[0], c[1]))
    return candidatos[0][2]
