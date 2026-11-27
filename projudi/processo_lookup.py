"""Localiza um processo no Projudi pelo número CNJ."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from base.utils import format_process_number, normalize_process_number

URL_BUSCA = 'https://projudi.tjba.jus.br/projudi/buscas/ProcessosParte'
BASE = 'https://projudi.tjba.jus.br'


def _payload_do_formulario(soup):
    form = soup.find('form', attrs={'name': 'busca'})
    if not form:
        return None
    payload = {}
    for campo in form.find_all(['input', 'select']):
        nome = campo.get('name')
        if not nome:
            continue
        if campo.name == 'select':
            opcao = campo.find('option', selected=True) or campo.find('option')
            payload[nome] = opcao.get('value', '') if opcao else ''
        elif campo.get('type') in ('checkbox', 'radio'):
            if campo.has_attr('checked'):
                payload[nome] = campo.get('value', 'on')
        else:
            payload[nome] = campo.get('value', '')
    return payload


def localizar_processo(user, numero):
    """Retorna dict {numero, numero_interno, url} ou None."""
    digitos = normalize_process_number(numero)
    if len(digitos) < 15:
        return None
    numero_formatado = format_process_number(digitos.zfill(20))

    from .services import ProjudiService

    resultado = ProjudiService(user)._get_session_from_cookies()
    if not resultado:
        return None
    session = resultado[0]

    try:
        resposta = session.get(URL_BUSCA, timeout=20)
        if resposta.status_code != 200 or 'expirou' in resposta.text.lower():
            return None

        soup = BeautifulSoup(resposta.text, 'html.parser')
        payload = _payload_do_formulario(soup)
        if not payload:
            return None

        payload['numeroProcesso'] = numero_formatado
        payload['Buscar.x'] = '10'
        payload['Buscar.y'] = '10'

        resposta = session.post(URL_BUSCA, data=payload, timeout=30)
        if resposta.status_code != 200:
            return None

        soup = BeautifulSoup(resposta.text, 'html.parser')
        for link in soup.find_all('a', href=True):
            href = link['href']
            if 'DadosProcesso?numeroProcesso=' not in href:
                continue
            match = re.search(r'numeroProcesso=(\d+)', href)
            if not match:
                continue
            return {
                'numero': numero_formatado,
                'numero_interno': match.group(1),
                'url': urljoin(BASE, href),
            }
    except Exception:
        return None
    return None
