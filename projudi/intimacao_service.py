"""Localização da intimação de um evento do processo.

Usado pela fila de petições para contrarrazões/impugnação: o usuário informa
o evento da decisão/recurso e o sistema procura a intimação seguinte (ou usa
o próprio evento, quando ele já é a intimação). A data manual fica como
fallback.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from projudiProcessNavigator import ProcessoParser
from projudi.verificacao_inominado import data_djen, data_mov, evento_mov


def _norm(texto):
    import unicodedata
    texto = unicodedata.normalize('NFKD', str(texto or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', texto).strip().upper()


def _nome_compacto(texto):
    return re.sub(r'[^A-Z0-9]+', '', _norm(texto))


def _data_disponibilizacao(texto):
    m = re.search(
        r'disponibiliz[^\n]{0,120}?(\d{1,2}/\d{1,2}/\d{2,4})',
        str(texto or ''), re.I,
    )
    if not m:
        return None
    try:
        dia, mes, ano = [int(x) for x in m.group(1).split('/')]
        if ano < 100:
            ano += 2000
        from datetime import date
        return date(ano, mes, dia)
    except ValueError:
        return None


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


def _texto_mov(mov):
    return ' '.join(
        str(mov.get(k) or '') for k in
        ('ato', 'observacao', 'ato_normalizado', 'descricao')
    )


def _data_movimento(mov):
    texto = _texto_mov(mov)
    return (
        _data_disponibilizacao(texto)
        or data_djen(mov)
        or data_mov(mov)
    )


def _item(mov, origem):
    return {
        'evento': str(evento_mov(mov)),
        'data': _data_movimento(mov),
        'meio': _classificar_meio(_texto_mov(mov)),
        'texto': _texto_mov(mov)[:500],
        'origem': origem,
    }


def localizar_intimacao_por_evento(movs, evento, parte=''):
    """Retorna a intimação do evento ou a primeira intimação após ele.

    - se o próprio evento já for uma intimação/DJEN, usa ele;
    - senão, procura movimentos de intimação posteriores ao evento;
    - se ``parte`` for informada, exige o nome da parte no texto.
    """
    try:
        evento = int(str(evento).strip())
    except (TypeError, ValueError):
        return None

    mov_evento = next(
        (m for m in movs if evento_mov(m) == evento), None)
    if not mov_evento:
        return None

    texto_evento = _norm(_texto_mov(mov_evento))
    if any(k in texto_evento for k in ('INTIMA', 'DISPONIBILIZ')):
        item = _item(mov_evento, 'evento')
        if item['data']:
            return item

    alvo = _nome_compacto(parte) if parte else ''
    descricao_evento = _norm(
        mov_evento.get('ato') or mov_evento.get('ato_normalizado') or '')
    candidatos = []

    for mov in movs:
        ev = evento_mov(mov)
        if ev <= evento:
            continue
        texto = _texto_mov(mov)
        up = _norm(texto)
        if not any(k in up for k in ('INTIMA', 'DISPONIBILIZ')):
            continue
        if alvo and alvo not in _nome_compacto(texto):
            continue
        item = _item(mov, 'posterior')
        if not item['data']:
            continue
        score = 0
        if descricao_evento and descricao_evento in up:
            score += 100
        if 'REFERENTE AO EVENTO' in up:
            score -= 20
        candidatos.append((score, ev, item))

    if not candidatos:
        return None

    # Melhor referência ao evento; depois a intimação mais antiga após ele.
    candidatos.sort(key=lambda c: (-c[0], c[1]))
    return candidatos[0][2]


def carregar_movimentacoes(user, processo_url):
    from projudi.services import ProjudiService

    if not processo_url:
        return []
    resultado = ProjudiService(user)._get_session_from_cookies()
    if not resultado:
        return []
    session = resultado[0]
    try:
        resposta = session.get(processo_url, timeout=30)
        if resposta.status_code != 200:
            return []
        parser = ProcessoParser(resposta.text)
        movs, _ = parser.extrair_movimentacoes()
        return movs
    except Exception:
        return []


def localizar_intimacao_do_processo(user, processo_url, evento, parte=''):
    movs = carregar_movimentacoes(user, processo_url)
    if not movs:
        return None
    return localizar_intimacao_por_evento(movs, evento, parte=parte)
