"""Sugestão de certidão para uma movimentação, a partir da RAG.

A fila de movimentações baixa o documento do despacho, procura a RAG
mais próxima e devolve o tipo de certidão configurado no campo
``RAGExample.tipo_certidao``. Os localizadores configurados na RAG também
são devolvidos para serem aplicados junto com a juntada.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup
from django.core.cache import cache
from django.urls import reverse

BASE = 'https://projudi.tjba.jus.br/projudi/'

TIPOS_CERTIDAO = [
    {'valor': 'inominado', 'label': 'Recurso Inominado', 'dias': 10},
    {
        'valor': 'contrarrazoes_inominado',
        'label': 'Contrarrazões ao Recurso Inominado',
        'dias': 10,
    },
    {
        'valor': 'cumprimento_sentenca',
        'label': 'Impugnação/Cumprimento de Sentença',
        'dias': 15,
    },
    {
        'valor': 'pagamento_impugnacao_penhora',
        'label': 'Impugnação/Decurso da Penhora',
        'dias': 15,
    },
    {
        'valor': 'decurso_pagamento',
        'label': 'Decurso de Pagamento Voluntário',
        'dias': 15,
    },
    {
        'valor': 'impugnacao_embargos_execucao',
        'label': 'Impugnação/Embargos à Execução',
        'dias': 15,
    },
]

CONCLUSAO_LABELS = {
    '1': 'Despacho',
    '2': 'Decisão',
    '3': 'Sentença',
    '5': 'Decisão Urgente',
    '17': 'Embargos de Declaração',
    '18': 'Embargos de Execução',
    '19': 'Sentença Extintiva',
    '22': 'Exceção de Pré-executividade',
}


def _normalizar(texto):
    texto = unicodedata.normalize('NFKD', str(texto or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', texto).strip().upper()


def _texto_documento(session, url):
    if not url:
        return ''
    if not url.startswith('http'):
        url = urljoin(BASE, url)
    resposta = session.get(url, timeout=15)
    if resposta.status_code != 200:
        return ''
    content_type = (resposta.headers.get('content-type') or '').lower()
    conteudo = resposta.content or b''
    if 'pdf' in content_type or conteudo.lstrip().startswith(b'%PDF'):
        try:
            import fitz
            pdf = fitz.open(stream=conteudo, filetype='pdf')
            try:
                limite = min(10, pdf.page_count)
                return '\n'.join(
                    pdf[i].get_text() for i in range(limite)
                )
            finally:
                pdf.close()
        except Exception:
            return ''
    return BeautifulSoup(
        resposta.text, 'html.parser').get_text(' ', strip=True)


def _tipo_por_texto(texto):
    alvo = _normalizar(texto)
    if 'CONTRARRAZOES' in alvo:
        return 'contrarrazoes_inominado'
    if 'RECURSO INOMINADO' in alvo:
        return 'inominado'
    if 'EMBARGOS' in alvo and 'EXECUCAO' in alvo:
        return 'impugnacao_embargos_execucao'
    if 'IMPUGNACAO' in alvo and 'EXECUCAO' in alvo:
        return 'impugnacao_embargos_execucao'
    if 'DECURSO' in alvo and ('PAGAMENTO' in alvo or 'PAGAR' in alvo):
        return 'decurso_pagamento'
    if 'IMPUGNACAO' in alvo and (
            'PENHORA' in alvo or 'DECURSO' in alvo):
        return 'pagamento_impugnacao_penhora'
    if ('IMPUGNACAO' in alvo or 'CUMPRIMENTO' in alvo
            or 'EXECUCAO' in alvo):
        return 'cumprimento_sentenca'
    return ''


def _localizadores_da_rag(rag):
    tipo = getattr(rag, 'tipo_localizador', '') or ''
    local = getattr(rag, 'localizador', '') or ''
    if tipo or local:
        return tipo, local
    for passo in rag.sequencia_cumprimento or []:
        if not isinstance(passo, dict):
            continue
        tipo = str(passo.get('tipo_localizador') or '').strip()
        local = str(passo.get('localizador') or '').strip()
        if tipo or local:
            return tipo, local
    return '', ''


def _label_tipo(valor):
    return next(
        (t['label'] for t in TIPOS_CERTIDAO if t['valor'] == valor),
        valor,
    )


def sugerir_certidao(user, processo, documento_url, processo_url=''):
    """Retorna o tipo de certidão e os parâmetros sugeridos pela RAG."""
    from processes.models import RAGExample
    from processes.movimentacoes_service import buscar_cumprimentos_similares
    from projudi.services import ProjudiService

    chave_cache = (
        f'certidao_sugestao_v1:{processo}:{documento_url}'
        if documento_url else ''
    )
    if chave_cache:
        em_cache = cache.get(chave_cache)
        if em_cache:
            return em_cache

    resultado = {
        'processo': processo,
        'tipo_certidao': '',
        'tipo_label': '',
        'rag_encontrada': False,
        'origem_sugestao': '',
        'rag_id': None,
        'rag_ato': '',
        'tipo_localizador': '',
        'localizador': '',
        'tipo_conclusao': '18',
        'tipo_conclusao_label': CONCLUSAO_LABELS['18'],
        'juiz_conclusao': '41201',
        'mensagem': '',
        'url_form': '',
    }

    if not documento_url:
        resultado['mensagem'] = 'Movimentação sem documento para analisar.'
        return resultado

    sessao = ProjudiService(user)._get_session_from_cookies()
    if not sessao:
        resultado['mensagem'] = 'Sessão do Projudi não disponível.'
        return resultado
    session, _ = sessao

    try:
        texto = _texto_documento(session, documento_url)
    except Exception as exc:
        resultado['mensagem'] = f'Erro ao baixar o documento: {exc}'
        return resultado
    if len(texto.strip()) < 30:
        resultado['mensagem'] = 'Documento sem texto suficiente para a RAG.'
        return resultado

    similares = buscar_cumprimentos_similares(texto, top_k=10)
    tipo = ''
    rag = None
    rag_similar = None
    tipo_rag_texto = ''
    rag_tipo_texto = None
    origem = ''
    for similar in similares:
        candidata = RAGExample.objects.filter(id=similar['id']).first()
        if not candidata:
            continue
        if rag_similar is None:
            rag_similar = candidata
        if candidata.tipo_certidao:
            tipo = candidata.tipo_certidao
            rag = candidata
            origem = 'rag'
            break
        if not tipo_rag_texto:
            tipo_rag_texto = _tipo_por_texto(
                f'{candidata.despacho_ato or ""} '
                f'{candidata.despacho_observacao or ""}'
            )
            if tipo_rag_texto:
                rag_tipo_texto = candidata
    if rag is None:
        rag = rag_similar
    if not tipo and tipo_rag_texto:
        tipo = tipo_rag_texto
        rag = rag_tipo_texto or rag
        origem = 'rag_texto'
    if not tipo:
        tipo = _tipo_por_texto(texto)
        if tipo:
            origem = 'texto_rag' if rag else 'texto'
    if not tipo and rag:
        # A RAG existe, mas ainda não foi configurada com uma certidão.
        origem = 'rag_sem_certidao'

    if not tipo:
        if rag:
            resultado.update({
                'rag_encontrada': True,
                'origem_sugestao': origem,
                'rag_id': rag.id,
                'rag_ato': (rag.despacho_ato or '')[:160],
                'mensagem': (
                    'RAG encontrada, mas sem tipo de certidão configurado.'
                ),
            })
        else:
            resultado['mensagem'] = 'Nenhuma RAG com certidão configurada.'
        if chave_cache:
            cache.set(chave_cache, resultado, 900)
        return resultado

    label = _label_tipo(tipo)
    tipo_localizador, localizador = (
        _localizadores_da_rag(rag) if rag else ('', ''))

    resultado.update({
        'tipo_certidao': tipo,
        'tipo_label': label,
        'rag_encontrada': bool(rag),
        'origem_sugestao': origem,
        'rag_id': rag.id if rag else None,
        'rag_ato': (rag.despacho_ato[:160] if rag else ''),
        'tipo_localizador': tipo_localizador,
        'localizador': localizador,
        'tipo_conclusao': (
            getattr(rag, 'tipo_conclusao', '') or '18') if rag else '18',
        'tipo_conclusao_label': CONCLUSAO_LABELS.get(
            (getattr(rag, 'tipo_conclusao', '') or '18') if rag else '18',
            'Embargos de Execução'),
        'juiz_conclusao': (
            getattr(rag, 'juiz_conclusao', '') or '41201') if rag else '41201',
    })

    if tipo == 'decurso_pagamento':
        params = {'processo': processo}
        if processo_url:
            params['url'] = processo_url
        resultado['url_form'] = (
            reverse('projudi:certidao_decurso_pagamento')
            + '?' + urlencode(params)
        )

    if chave_cache:
        cache.set(chave_cache, resultado, 900)
    return resultado
