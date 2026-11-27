"""Partes do processo e identificação do recorrente no recurso inominado.

A tempestividade do recurso é apurada pela intimação **do recorrente**.
Quando a petição PDF identifica quem recorre, o sistema filtra o DJEN por
esse nome; caso contrário, o usuário pode informar ``--recorrente``.
"""

from __future__ import annotations

import re
import unicodedata


def _normalizar(texto) -> str:
    texto = unicodedata.normalize('NFKD', str(texto or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', texto).strip().upper()


def _normalizar_parte(texto) -> str:
    """Normaliza nome para comparação, ignorando pontuação."""
    texto = _normalizar(texto)
    texto = re.sub(r'[^A-Z0-9 ]+', ' ', texto)
    return re.sub(r'\s+', ' ', texto).strip()


def limpar_nome_parte(nome) -> str:
    """Remove rótulos que o parser do Projudi costuma colar ao nome."""
    texto = re.sub(r'\s+', ' ', str(nome or '')).strip()
    texto = re.split(
        r'\s*(?:Processo\(s\)|CPF|CNPJ|RG|OAB|Endere[çc]o|E-?mail|'
        r'Telefone|Tel\.)(?![A-Za-z])',
        texto,
        maxsplit=1,
        flags=re.I,
    )[0]
    return texto.strip(' -;,.')


def extrair_partes_processo(parser, soup) -> list[dict]:
    """Lê as partes da página DadosProcesso e limpa os nomes."""
    try:
        partes = parser.extrair_partes(soup)
    except Exception:
        return []

    resultado = []
    for parte in partes or []:
        nome = limpar_nome_parte(parte.get('nome'))
        if not nome:
            continue
        item = dict(parte)
        item['nome'] = nome
        item['nome_normalizado'] = _normalizar_parte(nome)
        resultado.append(item)
    return resultado


def texto_partes(partes) -> str:
    """Monta a linha ``Promovente: ... / Promovido: ...``."""
    promovente = ''
    promovido = ''
    for parte in partes or []:
        papel = _normalizar(parte.get('papel') or parte.get('tipo'))
        nome = parte.get('nome') or ''
        if not nome:
            continue
        if 'PROMOVENTE' in papel or 'ATIVO' in papel:
            promovente = promovente or nome
        elif 'PROMOVIDO' in papel or 'PASSIVO' in papel:
            promovido = promovido or nome

    if promovente and promovido:
        return f'Promovente: {promovente} / Promovido: {promovido}'
    if promovente:
        return f'Promovente: {promovente}'
    if promovido:
        return f'Promovido: {promovido}'

    nomes = [p.get('nome') for p in (partes or []) if p.get('nome')]
    if len(nomes) >= 2:
        return f'Promovente: {nomes[0]} / Promovido: {nomes[1]}'
    return nomes[0] if nomes else ''


def achar_recorrente(texto_pdf, partes) -> str:
    """Identifica o recorrente a partir do texto da petição e das partes.

    Estratégia:
    1. rótulos explícitos (RECORRENTE, AGRAVANTE, APELANTE...);
    2. trechos típicos do cabeçalho: "já devidamente qualificado",
       "nos autos da Ação", "por intermédio dos seus procuradores",
       "inconformado" e "vem interpor";
    3. primeira parte citada no início da petição, como fallback.

    A pontuação evita confundir o recorrido com o recorrente quando o
    cabeçalho cita o adversário primeiro.
    """
    texto = _normalizar_parte(texto_pdf)
    if not texto or not partes:
        return ''

    nomes = [
        p for p in partes
        if p.get('nome') and p.get('nome_normalizado')
    ]
    if not nomes:
        return ''

    rotulos = (
        'RECORRENTE', 'AGRAVANTE', 'APELANTE', 'EMBARGANTE',
        'IMPETRANTE', 'REQUERENTE',
    )

    def pontuar(parte):
        nome = parte['nome_normalizado']
        score = 0
        # Rótulo explícito perto do nome.
        for rotulo in rotulos:
            for match in re.finditer(rf'\b{rotulo}\b', texto):
                janela = texto[match.end():match.end() + 450]
                if nome in janela:
                    score += 100
                    break

        # Marcadores imediatamente após o nome.
        if re.search(
            rf'{re.escape(nome)}\s+'
            rf'(?:JA DEVIDAMENTE|NOS AUTOS|POR INTERMEDIO|INCONFORMAD)',
            texto,
        ):
            score += 80

        indice = texto.find(nome)
        if indice >= 0:
            score += 10
            janela = texto[indice:indice + 500]
            if 'VEM' in janela and 'INTERPOR' in janela:
                score += 60
        else:
            indice = 10 ** 9
        return score, indice

    candidatos = [
        (*pontuar(parte), parte['nome'])
        for parte in nomes
    ]
    score, indice, nome = max(
        candidatos, key=lambda c: (c[0], -c[1]))
    if score > 0:
        return nome

    # Fallback: primeira parte citada no começo da petição.
    cabeca = texto[:3000]
    ocorrencias = []
    for parte in nomes:
        indice = cabeca.find(parte['nome_normalizado'])
        if indice >= 0:
            ocorrencias.append((indice, parte['nome']))
    if ocorrencias:
        return min(ocorrencias, key=lambda c: c[0])[1]

    return ''


def url_peticao_movimento(mov) -> str:
    """Escolhe o PDF da petição entre os documentos do movimento."""
    documentos = (mov or {}).get('documentos') or []
    if not documentos:
        return ''
    for doc in documentos:
        nome = _normalizar(doc.get('nome'))
        if any(k in nome for k in ('RECURSO', 'PETICAO', 'PETIÇÃO', 'RI.PDF')):
            return doc.get('url') or ''
    for doc in documentos:
        url = doc.get('url') or ''
        if '.pdf' in url.lower():
            return url
    return ''


def texto_pdf(http, url, paginas=4) -> str:
    """Baixa o PDF e devolve o texto das primeiras páginas."""
    if http is None or not url:
        return ''
    try:
        resposta = http.get(url, timeout=60)
        if resposta.status_code != 200 or not resposta.content:
            return ''
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        documento = fitz.open(stream=resposta.content, filetype='pdf')
        partes = []
        for indice, pagina in enumerate(documento):
            if indice >= paginas:
                break
            partes.append(pagina.get_text() or '')
        documento.close()
        return '\n'.join(partes)
    except Exception:
        return ''
