"""Sugestão de certidão para uma movimentação, a partir da RAG.

A fila de movimentações baixa o documento do despacho, procura o exemplo RAG
mais próximo e devolve o tipo de certidão configurado no campo
``RAGExample.tipo_certidao``. Os localizadores configurados na RAG também
são devolvidos para serem aplicados junto com a juntada.
"""

from __future__ import annotations

from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

BASE = 'https://projudi.tjba.jus.br/projudi/'
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
    import re
    import unicodedata

    texto = unicodedata.normalize('NFKD', str(texto or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', texto).strip().upper()


def _texto_documento(session, url):
    if not url:
        return ''
    if not url.startswith('http'):
        url = urljoin(BASE, url)
    resposta = session.get(url, timeout=30)
    if resposta.status_code != 200:
        return ''
    content_type = (resposta.headers.get('content-type') or '').lower()
    conteudo = resposta.content or b''
    if 'pdf' in content_type or conteudo.lstrip().startswith(b'%PDF'):
        try:
            import fitz
            pdf = fitz.open(stream=conteudo, filetype='pdf')
            try:
                return '\n'.join(p.get_text() for p in pdf)
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


def sugerir_certidao(user, processo, documento_url, processo_url=''):
    """Retorna o tipo de certidão e os localizadores sugeridos pela RAG."""
    from processes.models import RAGExample
    from processes.movimentacoes_service import buscar_cumprimentos_similares
    from projudi.peticoes_inominado import TIPOS_CERTIDAO
    from projudi.services import ProjudiService

    resultado = {
        'processo': processo,
        'tipo_certidao': '',
        'tipo_label': '',
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
    for similar in similares:
        candidata = RAGExample.objects.filter(id=similar['id']).first()
        if not candidata:
            continue
        if candidata.tipo_certidao:
            tipo = candidata.tipo_certidao
            rag = candidata
            break
    if not tipo:
        tipo = _tipo_por_texto(texto)
        if tipo and similares:
            rag = RAGExample.objects.filter(id=similares[0]['id']).first()

    if not tipo:
        resultado['mensagem'] = 'Nenhuma RAG com certidão configurada.'
        return resultado

    label = next(
        (t['label'] for t in TIPOS_CERTIDAO if t['valor'] == tipo),
        tipo,
    )
    tipo_localizador, localizador = (
        _localizadores_da_rag(rag) if rag else ('', ''))

    resultado.update({
        'tipo_certidao': tipo,
        'tipo_label': label,
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

    if tipo == 'impugnacao_embargos_execucao':
        from django.urls import reverse
        params = {
            'processo': processo,
            'url': processo_url or '',
            'tipo_localizador': tipo_localizador,
            'localizador': localizador,
            'tipo_conclusao': resultado['tipo_conclusao'],
            'juiz_conclusao': resultado['juiz_conclusao'],
        }
        resultado['url_form'] = (
            reverse('projudi:certidao_impugnacao_embargos')
            + '?' + urlencode(params))
    return resultado
