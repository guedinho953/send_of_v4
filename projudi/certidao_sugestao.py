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


def limpar_texto_despacho(texto):
    """Extrai o corpo útil do despacho/decisão.

    Remove o cabeçalho do tribunal e o bloco de assinatura/eletrônica que
    costumam vir no PDF, mantendo apenas o texto que interessa para a RAG.
    """
    import re

    texto = (
        str(texto or '')
        .replace('\xa0', ' ')
        .replace('\r\n', '\n')
        .replace('\r', '\n')
    )
    if not texto.strip():
        return ''

    # Corta o cabeçalho a partir do título do ato.
    inicio = re.search(
        r'\b(DESPACHO|DECIS[ÃA]O|SENTEN[ÇC]A|ATO\s+ORDINAT[ÓO]RIO)\b',
        texto,
        re.I,
    )
    if inicio:
        # Mantém o título do ato (DESPACHO/DECISÃO/SENTENÇA), que ajuda a
        # identificar o tipo na RAG; remove apenas o cabeçalho do tribunal.
        texto = texto[inicio.start():]

    # Corta a assinatura e os dados de validação.
    assinatura = re.search(
        r'(?i)(?:Paulo\s+Afonso(?:-BA)?,\s*'
        r'(?:data\s+da\s+assinatura|\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4})'
        r'|Documento\s+Assinado\s+Eletronicamente'
        r'|Assinado\s+eletronicamente\s+por'
        r'|C[óo]digo\s+de\s+valida[çc][ãa]o'
        r'|Este\s+documento\s+foi\s+assinado)',
        texto,
    )
    if assinatura:
        texto = texto[:assinatura.start()]

    # Remove restos de paginação/linhas vazias e normaliza os espaços.
    linhas = []
    for linha in texto.splitlines():
        linha = re.sub(r'\s+', ' ', linha).strip()
        if not linha or linha.isdigit():
            continue
        if re.match(r'^(P[ÁA]GINA|PAG\.?)\s*\d+', linha, re.I):
            continue
        linhas.append(linha)
    texto = re.sub(r'\s+', ' ', ' '.join(linhas)).strip()
    texto = re.sub(r'\s+([,.;:!?])', r'\1', texto)
    return texto


def _texto_documento(session, url):
    if not url:
        return ''
    if not url.startswith('http'):
        url = urljoin(BASE, url)
    # Alguns links da movimentação vêm com "downloadarquivo" minúsculo,
    # mas o Projudi só responde no caminho "DownloadArquivo".
    url = url.replace('downloadarquivo', 'DownloadArquivo')
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
    if 'ADJUDICACAO' in alvo and (
            'MANIFESTACAO' in alvo or 'DECURSO' in alvo):
        return 'decurso_manifestacao_adjudicacao'
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
        'rag_encontrada': False,
        'origem_sugestao': '',
        'rag_id': None,
        'rag_ato': '',
        'tipo_localizador': '',
        'localizador': '',
        'evento_despacho': '',
        'evento_peticao': '',
        'evento_intimacao': '',
        'tipo_conclusao': '18',
        'tipo_conclusao_label': CONCLUSAO_LABELS['18'],
        'juiz_conclusao': '41201',
        'acoes_fluxo': [],
        'template_id': None,
        'template_nome': '',
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
    texto = limpar_texto_despacho(texto)
    if len(texto.strip()) < 30:
        resultado['mensagem'] = 'Documento sem texto suficiente para a RAG.'
        return resultado

    similares = buscar_cumprimentos_similares(texto, top_k=10)
    tipo = ''
    rag = None
    origem = ''
    for similar in similares:
        candidata = RAGExample.objects.filter(id=similar['id']).first()
        if not candidata:
            continue
        if candidata.tipo_certidao:
            tipo = candidata.tipo_certidao
            rag = candidata
            origem = 'rag'
            break
    if not tipo:
        tipo = _tipo_por_texto(texto)
        if tipo:
            origem = 'texto'

    if not tipo:
        resultado['mensagem'] = 'Nenhuma RAG com certidão configurada.'
        return resultado

    label = next(
        (t['label'] for t in TIPOS_CERTIDAO if t['valor'] == tipo),
        tipo,
    )
    tipo_localizador, localizador = (
        _localizadores_da_rag(rag) if rag else ('', ''))
    template = None
    if rag:
        template = rag.suggested_templates.filter(
            template_type='certidao', active=True).first()

    resultado.update({
        'tipo_certidao': tipo,
        'tipo_label': label,
        'rag_encontrada': origem == 'rag',
        'origem_sugestao': origem,
        'rag_id': rag.id if rag else None,
        'rag_ato': (rag.despacho_ato[:160] if rag else ''),
        'tipo_localizador': tipo_localizador,
        'localizador': localizador,
        'evento_despacho': (
            getattr(rag, 'evento_despacho', '') if rag else ''),
        'evento_peticao': (
            getattr(rag, 'evento_peticao', '') if rag else ''),
        'evento_intimacao': (
            getattr(rag, 'evento_intimacao', '') if rag else ''),
        'tipo_conclusao': (
            getattr(rag, 'tipo_conclusao', '') or '18') if rag else '18',
        'tipo_conclusao_label': CONCLUSAO_LABELS.get(
            (getattr(rag, 'tipo_conclusao', '') or '18') if rag else '18',
            'Embargos de Execução'),
        'juiz_conclusao': (
            getattr(rag, 'juiz_conclusao', '') or '41201') if rag else '41201',
        'acoes_fluxo': (
            list(getattr(rag, 'acoes_fluxo', []) or [])
            if rag else []),
        'template_id': template.id if template else None,
        'template_nome': template.name if template else '',
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
