"""Leitura da fila ``JuntadaPeticao`` do Projudi.

A página lista petições/documentos enviados e aguardando análise de
juntada.  Cada linha de processo traz o número CNJ, a data de envio, o
tipo da juntada e os PDFs (petição, guias, comprovantes etc.).

O filtro de recurso inominado é feito, nesta ordem:

1. pelo tipo da juntada (ex.: "Juntada de Petição de Recurso Inominado");
2. pelo nome do PDF da petição (ex.: "RECURSO INOMINADO - ....pdf");
3. opcionalmente, pelo conteúdo do PDF (quando ``verificar_pdf=True``).

Os comprovantes/guias são apenas listados para conferência do usuário;
o preparo NÃO é inferido automaticamente.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

URL_BASE = 'https://projudi.tjba.jus.br'
URL_JUNTADA_PETICAO = (
    f'{URL_BASE}/projudi/listagens/JuntadaPeticao'
)


def _normalizar(texto) -> str:
    texto = unicodedata.normalize('NFKD', str(texto or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', texto).strip().upper()


def _data(texto):
    """Converte ``25/11/26`` (ou ``25/11/2026``) em ``date``."""
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', str(texto or ''))
    if not m:
        return None
    dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if ano < 100:
        ano += 2000
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def _absoluta(href, base_url=URL_BASE):
    if not href:
        return ''
    return urljoin(base_url.rstrip('/') + '/', href)


def _tabela_alvo(soup):
    """Localiza a tabela que contém o cabeçalho da fila de juntadas."""
    for tabela in soup.find_all('table'):
        texto = tabela.get_text(' ', strip=True)
        if 'Nº do processo' in texto and 'Petição/Documento' in texto:
            return tabela
    return None


def _tipo_juntada(celula):
    """Extrai o tipo antes do link "Mostrar/Ocultar".

    Ex.: ``Juntada de Petição de Recurso Inominado Mostrar/Ocultar ...``
    vira ``Juntada de Petição de Recurso Inominado``.
    """
    texto = re.sub(r'\s+', ' ', celula or '').strip()
    if not texto:
        return ''
    return re.split(r'\s*Mostrar/Ocultar\s*', texto, maxsplit=1)[0].strip()


def _links_download(tr):
    """PDFs (DownloadArquivo) presentes na linha, sem repetir URL."""
    docs = []
    vistos = set()
    for a in tr.find_all('a', href=True):
        href = a['href']
        if 'DownloadArquivo' not in href:
            continue
        url = _absoluta(href)
        if url in vistos:
            continue
        vistos.add(url)
        nome = re.sub(r'\s+', ' ', a.get_text(' ', strip=True)).strip()
        docs.append({'nome': nome, 'url': url})
    return docs


def _texto_pdf(http, url, paginas=3):
    """Texto normalizado das primeiras páginas do PDF (vazio se falhar)."""
    if http is None or not url:
        return ''
    try:
        resposta = http.get(url, timeout=60)
        if resposta.status_code != 200 or not resposta.content:
            return ''
        import fitz  # PyMuPDF

        documento = fitz.open(stream=resposta.content, filetype='pdf')
        partes = []
        for indice, pagina in enumerate(documento):
            if indice >= paginas:
                break
            partes.append(pagina.get_text() or '')
        documento.close()
        return _normalizar(' '.join(partes))
    except Exception:
        return ''


def _classificar_por_nome(nome):
    """Rótulo auxiliar para exibição (não decide o preparo)."""
    n = _normalizar(nome)
    if any(k in n for k in (
            'GUIA', 'COMPROVANTE', 'CUSTAS', 'DAJE', 'PIX',
            'DEPOSITO', 'DEPÓSITO')):
        return 'preparo'
    if 'RECURSO INOMINADO' in n:
        return 'peticao'
    return 'anexo'


def _finalizar(grupo, http=None, verificar_pdf=False):
    """Monta o dicionário da petição a partir das linhas coletadas."""
    documento_peticao = None
    documentos = []
    vistos = set()
    for doc in grupo['documentos']:
        if doc['url'] in vistos:
            continue
        vistos.add(doc['url'])
        doc = dict(doc)
        doc['categoria'] = _classificar_por_nome(doc['nome'])
        documentos.append(doc)
        if documento_peticao is None:
            documento_peticao = doc

    # A petição é o primeiro PDF, salvo quando algum PDF se identifica
    # explicitamente como "RECURSO INOMINADO".
    for doc in documentos:
        if 'RECURSO INOMINADO' in _normalizar(doc['nome']):
            documento_peticao = doc
            break

    tipo = grupo['tipo']
    tipo_norm = _normalizar(tipo)
    nomes_norm = _normalizar(' '.join(d['nome'] for d in documentos))

    contrarrazoes = (
        'CONTRARRAZOES' in tipo_norm
        or 'CONTRARRAZOES' in nomes_norm
    )

    confirmado = False
    origem = ''
    if not contrarrazoes:
        if 'RECURSO INOMINADO' in tipo_norm:
            confirmado = True
            origem = 'tipo da juntada'
        elif 'RECURSO INOMINADO' in nomes_norm:
            confirmado = True
            origem = 'nome do PDF'
        elif verificar_pdf and documento_peticao:
            conteudo = _texto_pdf(http, documento_peticao['url'])
            if 'RECURSO INOMINADO' in conteudo:
                confirmado = True
                origem = 'conteúdo do PDF'

    preparo_docs = [
        d for d in documentos
        if d is not documento_peticao
        and d['categoria'] == 'preparo'
    ]
    anexos = [
        d for d in documentos
        if d is not documento_peticao
        and d['categoria'] != 'preparo'
    ]

    return {
        'processo': grupo['processo'],
        'processo_url': grupo['processo_url'],
        'data_envio': grupo['data_envio'],
        'tipo': tipo,
        'texto': grupo['texto'],
        'documentos': documentos,
        'peticao': documento_peticao,
        'preparo_docs': preparo_docs,
        'anexos': anexos,
        'eh_recurso_inominado': confirmado,
        'origem_deteccao': origem,
    }


def ler_peticoes(html, http=None, verificar_pdf=False):
    """Lê todas as petições da página e devolve uma lista de dicionários."""
    soup = BeautifulSoup(html, 'html.parser')
    tabela = _tabela_alvo(soup)
    if tabela is None:
        return []

    grupos = []
    atual = None

    for tr in tabela.find_all('tr'):
        links_processo = [
            a for a in tr.find_all('a', href=True)
            if 'DadosProcesso' in a['href']
        ]
        texto = re.sub(r'\s+', ' ', tr.get_text(' ', strip=True)).strip()

        if links_processo:
            if atual:
                grupos.append(atual)
            link = links_processo[0]
            celulas = [
                re.sub(r'\s+', ' ', td.get_text(' ', strip=True)).strip()
                for td in tr.find_all('td', recursive=False)
            ]
            data_envio = None
            for celula in celulas:
                data_envio = data_envio or _data(celula)
            tipo = ''
            if len(celulas) >= 4:
                tipo = _tipo_juntada(celulas[3])
            if not tipo:
                tipo = _tipo_juntada(texto)

            atual = {
                'processo': link.get_text(' ', strip=True).strip(),
                'processo_url': _absoluta(link['href']),
                'data_envio': data_envio or _data(texto),
                'tipo': tipo,
                'texto': texto,
                'documentos': _links_download(tr),
            }
            continue

        if atual is None:
            continue

        if texto:
            atual['texto'] += ' ' + texto
        atual['documentos'].extend(_links_download(tr))

    if atual:
        grupos.append(atual)

    return [
        _finalizar(g, http=http, verificar_pdf=verificar_pdf)
        for g in grupos
    ]


def listar_peticoes_inominado(
        html, http=None, verificar_pdf=False, somente_recurso=True):
    """Lista as petições da fila, opcionalmente só as de recurso inominado."""
    peticoes = ler_peticoes(html, http=http, verificar_pdf=verificar_pdf)
    if somente_recurso:
        peticoes = [p for p in peticoes if p['eh_recurso_inominado']]
    return peticoes
