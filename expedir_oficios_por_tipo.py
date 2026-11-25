"""Expede em lote os ofícios pendentes do CumprimentoCartorio, por tipo.

FLUXO BASE APROVADO
===================
Este é o fluxo de referência para os demais ofícios. Variações devem mudar
poucas coisas (tipo/modelo, aliases, template, regra de ata, destinatário e
numeração), mantendo a mesma sequência:
  lista pendente -> ata (inclusive "audin") -> modelo -> "Redigir sem AR"
  -> FCKeditor -> Submeter -> Registrar -> planilha Google.

Documentação: docs/OFICIOS_BASE.md
Referência JSON: docs/oficio_base_referencia.json

O link usado é o mesmo que lista todos os ofícios pendentes:

    /projudi/listagens/CumprimentoCartorio?tipo=oficio&acao=expedir

Para cada linha (form ``formCumprimento*``) o script lê o select
``codModelo`` e o texto da linha. Quando ``--tipo`` é informado, só processa
as linhas cujo modelo/tipo contenha o termo (ex.: ``CIAP``, ``RPV``,
``Ofício comum``).

Observação: RPA aqui é o nome da AUTOMAÇÃO (Robotic Process Automation),
não um tipo de ofício. No Projudi o modelo genérico de ofício pode aparecer
como "RPA" no select ``codModelo``; o script trata "Ofício comum" como esse
modelo genérico.

Fluxo por linha:
  1. submete o próprio form com ``gerarar=false`` (equivale a "Redigir sem AR");
  2. no editor, cola o HTML de um ``GeneratedDocument`` do processo, se existir;
  3. se não existir documento gerado, mantém o conteúdo padrão do modelo do
     Projudi (ex.: CIAP/RPV/genérico) e apenas Submete/Registra;
  4. volta para a lista e repete.

Com ``--tipo`` vazio ("Todos os modelos"), o script mantém o modelo que já
está marcado na linha. Se a linha não tiver modelo, tenta inferir pelo texto
(CIAP/RPV/Ofício comum). Se não houver modelo nem documento gerado, a linha
é pulada para não submeter um ofício vazio.

Uso:
  python expedir_oficios_por_tipo.py --tipo CIAP --user-id 1
  python expedir_oficios_por_tipo.py --tipo "Ofício comum" --limite 10
  python expedir_oficios_por_tipo.py --tipo RPV
  python expedir_oficios_por_tipo.py --tipo ""        # todos os pendentes
"""
import argparse
import os
import re
import sys
import time
import unicodedata
from datetime import date
from types import SimpleNamespace

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'

import django  # noqa: E402

django.setup()

from playwright.sync_api import sync_playwright  # noqa: E402

from accounts.models import User  # noqa: E402
from processes.models import DocumentTemplate, GeneratedDocument, Process  # noqa: E402
from projudi.models import ProjudiSession  # noqa: E402
from projudi.services import ProjudiService  # noqa: E402

URL_CUMPRIMENTO = (
    'https://projudi.tjba.jus.br/projudi/listagens/'
    'CumprimentoCartorio?tipo=oficio&acao=expedir'
)

# No Projudi o CIAP pode aparecer pela sigla ou pelo nome completo.
CIAP_ALIASES = (
    'CIAP',
    'CENTRAL INTEGRADA',
    'ALTERNATIVAS PENAIS',
)
RPV_ALIASES = (
    'RPV',
    'REQUISICAO DE PEQUENO VALOR',
    'REQUISIÇÃO DE PEQUENO VALOR',
)

# Assinantes disponíveis para o ofício.
ASSINANTES = {
    'ivan': ('IVAN GUEDES DA SILVA', 'SECRETÁRIO EM SUBSTITUIÇÃO'),
    'mauro': (
        'MAURO EMILIO VIANA DA SILVA MOREIRA',
        'SECRETÁRIO',
    ),
}
ASSINANTE_PADRAO = 'ivan'

# Dados fixos do 20º BPM usados no ofício de apresentação de policiais.
BPM20 = {
    'nome': 'Ten Cel PM EMÍLIA SILVA COSTA NETA',
    'cargo': 'Comandante do 20º BPM',
    'endereco': 'Av. da Providência, S/N, Perpétuo Socorro, Paulo Afonso - Bahia.',
    'email': 'bpm20.cmd@pm.ba.gov.br',
    'email_copia': 'anilton.estevam@pm.ba.gov.br',
    'link_audiencia': 'https://audinplay.tjba.jus.br/',
    'finalidade': 'participar',
}

MESES_PT = {
    'janeiro': 'Janeiro', 'fevereiro': 'Fevereiro', 'marco': 'Março',
    'março': 'Março', 'abril': 'Abril', 'maio': 'Maio', 'junho': 'Junho',
    'julho': 'Julho', 'agosto': 'Agosto', 'setembro': 'Setembro',
    'outubro': 'Outubro', 'novembro': 'Novembro', 'dezembro': 'Dezembro',
}


def _normalizar(texto):
    """Maiúsculas, sem acentos e com espaços normalizados (para comparar tipos)."""
    texto = unicodedata.normalize('NFKD', str(texto or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', texto).strip().upper()


def _extrair_cnj(texto):
    m = re.search(r'\d{7}-\d{2}\.\d{4}\.8\.05\.\d{4}', texto or '')
    return m.group(0) if m else ''


def _eh_ciap(texto):
    alvo = _normalizar(texto)
    return any(_normalizar(alias) in alvo for alias in CIAP_ALIASES)


def _eh_rpv(texto):
    alvo = _normalizar(texto)
    return any(_normalizar(alias) in alvo for alias in RPV_ALIASES)


def _eh_20bpm(texto):
    alvo = _normalizar(texto)
    return any(x in alvo for x in (
        '20BPM', '20 BPM', '20O BPM', '20° BPM',
    ))


def _termos_busca(tipo):
    """Termos que identificam o tipo no Projudi.

    CIAP pode aparecer como sigla ou como
    "CENTRAL INTEGRADA DE ALTERNATIVAS PENAIS PAULO AFONSO".
    "Ofício comum" é o modelo genérico, que no Projudi pode aparecer
    com o rótulo "RPA" — por isso os aliases abaixo.
    """
    alvo = _normalizar(tipo)
    if not alvo:
        return []

    if _eh_20bpm(alvo):
        return ['20BPM', '20 BPM', '20O BPM', '20° BPM']
    if _eh_ciap(alvo):
        return [_normalizar(alias) for alias in CIAP_ALIASES]
    if _eh_rpv(alvo):
        return [_normalizar(alias) for alias in RPV_ALIASES]
    if 'COMUM' in alvo or 'OFICIO' in alvo:
        # RPA aqui é apenas o rótulo do modelo genérico no Projudi.
        return ['RPA', 'OFICIO', 'COMUM']

    return [alvo]


def _termos_modelo(tipo):
    """Termos usados para escolher o modelo no select codModelo do Projudi."""
    if _eh_20bpm(tipo):
        # O Projudi pode não ter um modelo específico de 20 BPM; nesse caso
        # usa o ofício RPA/genérico e cola o HTML confeccionado.
        return ['20 BPM', '20º BPM', '20O BPM', 'RPA', 'OFICIO', 'COMUM']
    return _termos_busca(tipo)


def _selecionado_placeholder(item):
    selecionado = _normalizar(item.get('selected'))
    return (
        not selecionado
        or 'SELECIONE' in selecionado
        or selecionado in ('-1', 'NENHUM', 'NENHUM MODELO', 'MODELO PADRAO')
    )


def _termos_por_texto(texto):
    """Infere o tipo a partir do texto, sem confundir com o 'Ofício' genérico."""
    alvo = _normalizar(texto)
    if _eh_20bpm(alvo):
        return ['20BPM', '20 BPM', '20O BPM', '20° BPM']
    if _eh_ciap(alvo):
        return [_normalizar(alias) for alias in CIAP_ALIASES]
    if _eh_rpv(alvo):
        return [_normalizar(alias) for alias in RPV_ALIASES]
    if 'RPA' in alvo:
        return ['RPA']
    if 'COMUM' in alvo:
        return ['RPA', 'OFICIO', 'COMUM']
    return []


def _termos_do_item(item):
    """Para o modo 'Todos', mantém o modelo da linha ou infere pelo texto."""
    if not _selecionado_placeholder(item):
        return []
    return _termos_por_texto(item.get('rowText'))


def _chave_item(item):
    return '|'.join([
        str(item.get('name') or ''),
        str(item.get('codCump') or ''),
        _normalizar(item.get('rowText'))[:100],
    ])


def _item_corresponde(item, tipo):
    """True se a linha pertence ao tipo pedido.

    A ordem de preferência é:
      1. modelo já selecionado no select ``codModelo``;
      2. texto da linha (coluna "Tipo"/descrição);
      3. opções do select somente quando não há seleção nem texto de tipo.
    """
    termos = _termos_busca(tipo)
    if not termos:
        return True

    # "Ofício comum" não pode casar com "Ofício CIAP"/"Ofício RPV" apenas
    # porque os três começam com "Ofício".
    generico = any(t in ('RPA', 'OFICIO', 'COMUM') for t in termos)

    selecionado = _normalizar(item.get('selected'))
    placeholder = (
        not selecionado
        or 'SELECIONE' in selecionado
        or selecionado in ('-1', 'NENHUM', 'NENHUM MODELO', 'MODELO PADRAO')
    )
    if not placeholder:
        if generico and (_eh_ciap(selecionado) or _eh_rpv(selecionado)):
            return False
        return any(termo in selecionado for termo in termos)

    texto_linha = _normalizar(item.get('rowText'))
    if generico and (_eh_ciap(texto_linha) or _eh_rpv(texto_linha)):
        return False
    if any(termo in texto_linha for termo in termos):
        return True

    # As opções do select são a lista GLOBAL de modelos, iguais em todas as
    # linhas. Elas não identificam o tipo daquela linha — por isso não são
    # usadas no filtro. O tipo vem do modelo já selecionado ou do texto da
    # linha (destinatário/movimentação).
    return False


def _carregar_usuario(user_id):
    if user_id:
        try:
            return User.objects.get(pk=user_id, is_active=True)
        except User.DoesNotExist:
            print(f'ERRO: usuário {user_id} não encontrado/ativo.')
            sys.exit(2)

    user = User.objects.filter(is_active=True).order_by('id').first()
    if not user:
        print('ERRO: nenhum usuário ativo.')
        sys.exit(2)
    return user


def _carregar_cookies(user):
    try:
        resultado = ProjudiService(user)._get_session_from_cookies()
        if resultado:
            _session, cookies = resultado
            if cookies and 'JSESSIONID' in cookies:
                return cookies
    except Exception as e:
        print(f'[WARN] Falha ao capturar cookies: {e}')

    sessao = ProjudiSession.objects.filter(user=user, status='active').first()
    if sessao and sessao.cookies:
        cookies = sessao.cookies if isinstance(sessao.cookies, dict) else {}
        if 'JSESSIONID' in cookies:
            return cookies

    print(
        'ERRO: sessão do Projudi não encontrada. '
        'Sincronize a sessão em /projudi/sessao/ e tente novamente.'
    )
    sys.exit(2)


def _criar_sessao_http(cookies):
    """Sessão requests para baixar a ata/documentos do processo."""
    session = requests.Session()
    for name, value in cookies.items():
        session.cookies.set(
            str(name), str(value), domain='projudi.tjba.jus.br'
        )
    session.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) '
            'Gecko/20100101 Firefox/128.0'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9',
    })
    return session


def _tipo_efetivo(item, tipo):
    """Tipo realmente aplicável à linha (explícito ou inferido)."""
    if tipo:
        return tipo

    if not _selecionado_placeholder(item):
        selecionado = item.get('selected') or ''
        if _eh_ciap(selecionado):
            return 'CIAP'
        if _eh_rpv(selecionado):
            return 'RPV'
        return selecionado

    texto = item.get('rowText') or ''
    if _eh_20bpm(texto):
        return '20BPM'
    if _eh_ciap(texto):
        return 'CIAP'
    if _eh_rpv(texto):
        return 'RPV'
    alvo = _normalizar(texto)
    if 'RPA' in alvo or 'COMUM' in alvo:
        return 'Ofício comum'
    return ''


def _destinatario_item(item, tipo_efetivo):
    """Órgão/pessoa de destino para gravar na planilha."""
    if _eh_ciap(tipo_efetivo):
        return 'CENTRAL INTEGRADA DE ALTERNATIVAS PENAIS PAULO AFONSO'
    if _eh_20bpm(tipo_efetivo):
        return '20 BPM'

    texto = item.get('rowText') or ''
    texto = re.sub(
        r'\d{7}-\d{2}\.\d{4}\.8\.05\.\d{4}', ' ', texto
    )

    m = re.search(
        r'(.+?)\s+(Juntada|Ato ordinatório|Movimentação|Expedição|'
        r'Cumprimento|Petição|Decisão|Sentença|Despacho)',
        texto, re.I,
    )
    destino = m.group(1) if m else texto

    # Remove nomes de juízes conhecidos.
    try:
        from projudi.models import Judge
        for nome in Judge.objects.values_list('name', flat=True):
            if nome:
                destino = re.sub(re.escape(nome), ' ', destino, flags=re.I)
    except Exception:
        pass

    destino = re.sub(
        r'MARTINHO\s+FERRAZ\s+DA\s+NOBREGA\s+JUNIOR', ' ',
        destino, flags=re.I,
    )
    destino = re.sub(r'Redigir.*$', ' ', destino, flags=re.I)
    destino = re.sub(r'\s+', ' ', destino).strip(' -')
    return destino[:250]


def _preferencia_ciap(dados_ata):
    """Escolhe o modelo CIAP correto conforme a prestação lida na ata."""
    tipo = _normalizar((dados_ata or {}).get('prestacao_tipo'))
    if 'SERVICO' in tipo or 'COMUNIDADE' in tipo:
        return ['SERVICO', 'COMUNIDADE']
    if 'PECUNI' in tipo:
        return ['PECUNIARIA']
    return []


def _resolver_processo(item):
    """Localiza o Process pelo CNJ da linha ou pelo numeroProcesso do link."""
    texto = ' '.join([
        item.get('rowText') or '',
        item.get('procText') or '',
    ])
    cnj = _extrair_cnj(texto)
    if cnj:
        proc = Process.objects.filter(number=cnj).first()
        if proc:
            return proc

    href = item.get('procHref') or ''
    m = re.search(r'numeroProcesso=(\d+)', href)
    if m:
        numero_projudi = m.group(1)
        proc = Process.objects.filter(projudi_url__icontains=numero_projudi).first()
        if proc:
            return proc

    return None


def _resolver_template(tipo):
    qs = DocumentTemplate.objects.filter(template_type='oficio', active=True)
    if not tipo:
        return None

    alvo = _normalizar(tipo)
    template = qs.filter(name__icontains=tipo).order_by('id').first()
    if template:
        return template

    # Aliases conhecidos do projeto:
    #   5 = Ofício CIAP | 7 = Ofício RPV | 3 = Ofício comum (com numeração)
    if _eh_20bpm(alvo):
        template = (
            qs.filter(name__icontains='20º BPM').first()
            or qs.filter(name__icontains='20 BPM').first()
        )
    elif _eh_ciap(alvo):
        template = qs.filter(pk=5).first() or qs.filter(name__icontains='ciap').first()
    elif _eh_rpv(alvo):
        template = qs.filter(pk=7).first() or qs.filter(name__icontains='rpv').first()
    elif 'COMUM' in alvo or 'OFICIO' in alvo or alvo == 'RPA':
        template = (
            qs.filter(pk=3).first()
            or qs.filter(name__icontains='numeração').first()
            or qs.filter(name__icontains='numeracao').first()
        )

    return template


def _html_do_processo(proc, tipo):
    """Retorna (html, documento) do último GeneratedDocument compatível."""
    if not proc:
        return '', None

    qs = GeneratedDocument.objects.filter(process=proc).exclude(html_content='')
    template = _resolver_template(tipo)
    if template:
        qs = qs.filter(template=template)
    elif tipo:
        qs = qs.filter(template__name__icontains=tipo)

    # Prefere documento ainda não exportado; se só houver exportado, usa-o.
    doc = qs.filter(exported_to_projudi=False).order_by('-created_at').first()
    if not doc:
        doc = qs.order_by('-created_at').first()
    if not doc and tipo:
        doc = (
            GeneratedDocument.objects
            .filter(process=proc, template__name__icontains=tipo)
            .exclude(html_content='')
            .order_by('-created_at')
            .first()
        )

    return (doc.html_content, doc) if doc else ('', None)


def _obter_processo(item, user, http_session):
    """Process do banco ou criado a partir do DadosProcesso do Projudi."""
    proc = _resolver_processo(item)
    if proc:
        return proc

    texto = ' '.join([
        item.get('rowText') or '',
        item.get('procText') or '',
    ])
    cnj = _extrair_cnj(texto)
    href = item.get('procHref') or ''
    if not cnj or not href:
        return None

    try:
        from expedir_rapido import _criar_processo
        return _criar_processo(
            http_session,
            {'link_processo': href},
            cnj,
            user,
        )
    except Exception as e:
        print(f'   ⚠️ Não foi possível criar/abrir o processo {cnj}: {e}')
        return None


def _parse_data_br(texto):
    if not texto:
        return None
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', texto)
    if not m:
        return None
    dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if ano < 100:
        ano += 2000
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def _movimentos_20bpm(proc, item=None, http_session=None):
    """Movimentações em ordem cronológica (a última é a mais recente)."""
    from processes.models import Movement

    movs = []

    for mov in Movement.objects.filter(process=proc).order_by('id'):
        texto = ' '.join([
            mov.act_description or '',
            mov.observation or '',
            mov.act_normalized or '',
        ]).strip()
        if not texto:
            continue
        data_mov = mov.act_date or mov.reference_date or _parse_data_br(texto)
        evento = 0
        try:
            evento = int(str(mov.event_number).strip())
        except (TypeError, ValueError):
            pass
        movs.append({
            'data': data_mov,
            'evento': evento,
            'texto': texto,
        })

    # Se o processo ainda não tem movimentações no banco, busca no Projudi.
    if item and http_session and item.get('procHref'):
        try:
            resposta = http_session.get(item['procHref'], timeout=30)
            if resposta.status_code == 200 and 'expirou' not in resposta.text.lower():
                from projudiProcessNavigator import ProcessoParser
                parser = ProcessoParser(resposta.text)
                movs_projudi, _ = parser.extrair_movimentacoes()
                for mov in movs_projudi:
                    texto = ' '.join([
                        mov.get('ato', '') or '',
                        mov.get('observacao', '') or '',
                        mov.get('ato_normalizado', '') or '',
                    ]).strip()
                    if not texto:
                        continue
                    data_mov = _parse_data_br(
                        mov.get('data_texto', '') or texto
                    )
                    evento = 0
                    try:
                        evento = int(str(mov.get('evento', '')).strip())
                    except (TypeError, ValueError):
                        pass
                    movs.append({
                        'data': data_mov,
                        'evento': evento,
                        'texto': texto,
                    })
        except Exception as e:
            print(f'   ⚠️ Não foi possível ler as movimentações no Projudi: {e}')

    # Ordena do mais antigo para o mais recente. As movimentações sem data
    # ficam no fim, preservando a ordem de evento.
    movs.sort(key=lambda m: (
        m['data'] or date.min,
        m['evento'],
    ))

    return movs


def _texto_movimentos_20bpm(proc, item=None, http_session=None):
    movs = _movimentos_20bpm(proc, item=item, http_session=http_session)
    return '\n'.join(m['texto'] for m in movs if m.get('texto'))


def _data_audiencia_recente_20bpm(movs):
    """Procura a data da audiência nas últimas movimentações.

    A prioridade é a movimentação mais recente que designa audiência de
    instrução. Depois, qualquer movimentação recente que mencione audiência,
    ignorando audiências já realizadas/certificadas.
    """
    for exigir_designacao in (True, False):
        for mov in reversed(movs):
            texto = mov.get('texto') or ''
            up = _normalizar(texto)

            if any(k in up for k in (
                    'REALIZADA', 'AUDIENCIA REALIZADA',
                    'AUDIÊNCIA REALIZADA', 'CERTIFICO QUE A AUDIENCIA',
                    'CERTIFICO QUE A AUDIÊNCIA')):
                continue

            if exigir_designacao:
                if not any(k in up for k in (
                        'DESIGNADA', 'INSTRUCAO', 'INSTRUÇÃO')):
                    continue
            else:
                if not any(k in up for k in (
                        'AUDIENCIA', 'AUDIÊNCIA',
                        'PARTICIPAR DA AUDIENCIA',
                        'PARTICIPAR DA AUDIÊNCIA')):
                    continue

            data = _data_audiencia_20bpm(texto)
            if data:
                return data

    return ''


def _tem_patente_pm(nome):
    """Reconhece patentes/abreviações de policial militar."""
    alvo = _normalizar(nome)
    padrao = (
        r'\b(?:SD|SGT|SUB\s*TEN|SUBTEN|TEN|TENENTE|CAP|CAPITAO|'
        r'MAJ|MAJOR|CEL|CORONEL|CMT|CMDT|COMANDANTE|ALF|ALFERES|'
        r'SOLDADO|CABO|POLICIAL|PM|1O\s*SGT|2O\s*SGT|3O\s*SGT)\b'
    )
    return bool(re.search(padrao, alvo))


def _endereco_20bpm(party):
    endereco = _normalizar(getattr(party, 'address', '') or '')
    return any(k in endereco for k in (
        '20 BPM', '20O BPM', '20° BPM', 'BATALHAO 20',
        '20 BATALHAO', '20º BPM',
    ))


def _testemunha_especifica_20bpm(texto):
    """Detecta quando o despacho pede apenas uma testemunha específica."""
    padroes = (
        r'(?:apenas|somente|especificamente|em especial|t[ãa]o somente)'
        r'\s+(?:a\s+)?testemunha\s+'
        r'([A-ZÀ-Ú]{2,}(?:\s+(?:DE|DA|DO|DAS|DOS|E|[A-ZÀ-Ú]{2,})){1,6})',
        r'testemunha\s+'
        r'([A-ZÀ-Ú]{2,}(?:\s+(?:DE|DA|DO|DAS|DOS|E|[A-ZÀ-Ú]{2,})){1,6})'
        r'[,;]?\s+(?:apenas|somente|especificamente)',
    )
    for padrao in padroes:
        m = re.search(padrao, texto, re.I)
        if m:
            return m.group(1).strip().upper()
    return ''


def _policiais_20bpm(proc, texto):
    from processes.models import Party

    especifica = _testemunha_especifica_20bpm(texto)
    nomes = []

    for party in Party.objects.filter(process=proc):
        # O ofício do 20º BPM é para testemunhas/terceiros, não para o
        # autor do fato, vítima, réu ou executado.
        if party.role != 'terceiro':
            continue

        up = _normalizar(party.name)
        sinais_pm = _tem_patente_pm(party.name)

        # Inclui quem tem nome/patente de PM ou endereço no 20º BPM.
        if not sinais_pm and not _endereco_20bpm(party):
            continue
        if any(k in up for k in (
                '20 BPM', 'POLICIA', 'MILITAR', 'BATALHAO', 'LOTADO',
                'VITIMA', 'AUTOR', 'REU', 'EXECUTADO')):
            continue

        nome = party.name.strip()
        if especifica and especifica not in up and up not in especifica:
            continue
        nomes.append(nome)

    # Fallback: nomes citados após "testemunhas"/"arrolamento" no despacho.
    if not nomes:
        m = re.search(
            r'(?:testemunhas?|arrolamento)[^:\n]{0,120}:\s*(.+)',
            texto, re.I,
        )
        trecho = m.group(1) if m else ''
        for pedaco in re.split(r'[;,]|\s+e\s+', trecho):
            nome = re.sub(r'\s+', ' ', pedaco).strip(' .')
            palavras = nome.split()
            up = _normalizar(nome)
            if (2 <= len(palavras) <= 8
                    and re.search(r'[A-ZÀ-Ú]{2,}', nome)
                    and not any(k in up for k in (
                        'POLICIA', 'MILITAR', 'BPM', 'LOTADO',
                        'TESTEMUNHA', 'ARROLAMENTO', 'COMANDANTE',
                        'VITIMA', 'AUTOR', 'REU', 'EXECUTADO'))):
                if especifica and especifica not in up and up not in especifica:
                    continue
                nomes.append(nome.upper())

    if especifica and not nomes:
        nomes.append(especifica)

    # Deduplica preservando a ordem.
    return list(dict.fromkeys(n for n in nomes if n))


def _data_audiencia_20bpm(texto):
    meses = {
        'janeiro': 1, 'fevereiro': 2, 'marco': 3, 'março': 3,
        'abril': 4, 'maio': 5, 'junho': 6, 'julho': 7, 'agosto': 8,
        'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12,
    }

    candidatos = []

    for m in re.finditer(
            r'(\d{1,2})\s+de\s+([a-zçãéíóú]+)\s+de\s+(\d{4})'
            r'\s*(?:às|as|a partir das)\s*(\d{1,2})[:h](\d{2})',
            texto, re.I):
        mes = meses.get(m.group(2).lower())
        if mes:
            candidatos.append((
                int(m.group(3)), mes, int(m.group(1)),
                int(m.group(4)), int(m.group(5)),
            ))

    for m in re.finditer(
            r'(\d{1,2})/(\d{1,2})/(\d{4})'
            r'\s*(?:às|as|a partir das)\s*(\d{1,2})[:h](\d{2})',
            texto, re.I):
        candidatos.append((
            int(m.group(3)), int(m.group(2)), int(m.group(1)),
            int(m.group(4)), int(m.group(5)),
        ))

    if not candidatos:
        return ''

    ano, mes, dia, hora, minuto = candidatos[-1]
    nome_mes = next(
        (nome for nome, num in MESES_PT.items() if num == mes),
        str(mes),
    )
    # Corrige a chave sem acento para o nome exibido.
    nome_mes = {
        1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
        5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
        9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro',
    }.get(mes, nome_mes)
    return f'{dia:02d} de {nome_mes} de {ano} às {hora:02d}:{minuto:02d}'


def _gerar_conteudo_20bpm(item, user, http_session,
                          assinante_nome=None, assinante_cargo=None,
                          numero_documento=None):
    from django.template import Context, Template
    from processes.models import GeneratedDocument, RAGExample
    from expedir_rapido import _aplicar_assinatura, _remover_rpa_numero

    proc = _obter_processo(item, user, http_session)
    if not proc:
        return '', None, None, {}, ''

    template = _resolver_template('20BPM')
    if not template:
        print('   ⚠️ Template "Ofício 20º BPM" não encontrado.')
        return '', None, proc, {}, ''

    movs = _movimentos_20bpm(proc, item=item, http_session=http_session)
    texto = '\n'.join(m['texto'] for m in movs if m.get('texto'))
    data_audiencia = (
        _data_audiencia_recente_20bpm(movs)
        or _data_audiencia_20bpm(texto)
    )

    # A RAG serve só como contexto para achar os policiais; não entra na
    # escolha da data da audiência.
    for rag in RAGExample.objects.filter(
            process=proc, active=True).order_by('-id')[:5]:
        texto += '\n' + ' '.join([
            rag.despacho_ato or '',
            rag.despacho_observacao or '',
        ])
    policiais = _policiais_20bpm(proc, texto)

    if not policiais:
        print('   ⚠️ Não encontrei os policiais/testemunhas do 20º BPM.')
        return '', template, proc, {}, ''
    if not data_audiencia:
        print('   ⚠️ Não encontrei a data/hora da audiência no último despacho.')
        return '', template, proc, {}, ''

    if len(policiais) == 1:
        policiais_texto = policiais[0]
    else:
        policiais_texto = ', '.join(policiais[:-1]) + ' e ' + policiais[-1]

    rag = RAGExample.objects.filter(
        process=proc, active=True).order_by('-id').first()
    juiz = (
        (rag.despacho_autor if rag else '')
        or 'MARTINHO FERRAZ DA NOBREGA JUNIOR'
    )

    numero = numero_documento
    if not numero:
        seq = GeneratedDocument.proximo_numero(template)
        numero = f'{seq:03d}/{date.today().year}'

    ctx = {
        'numero_documento': numero,
        'processo': proc.number,
        'destinatario_nome': BPM20['nome'],
        'destinatario_cargo': BPM20['cargo'],
        'destinatario_endereco': BPM20['endereco'],
        'destinatario_email': BPM20['email'],
        'email_copia': BPM20['email_copia'],
        'policiais': policiais_texto,
        'data_audiencia': data_audiencia,
        'link_audiencia': BPM20['link_audiencia'],
        'finalidade': BPM20['finalidade'],
        'juiz': juiz,
        'assinante_nome': assinante_nome or 'IVAN GUEDES DA SILVA',
        'assinante_cargo': assinante_cargo or 'SECRETÁRIO(SUBSTITUTO)',
    }

    try:
        html = Template(template.html_template).render(Context(ctx))
        html = _aplicar_assinatura(html, assinante_nome, assinante_cargo)
        html = _remover_rpa_numero(html)
    except Exception as e:
        print(f'   ⚠️ Erro ao gerar ofício 20º BPM: {e}')
        return '', template, proc, {}, ''

    return html, template, proc, {}, policiais_texto


def _gerar_conteudo(item, tipo_efetivo, user, http_session,
                    assinante_nome=None, assinante_cargo=None,
                    numero_documento=None):
    """Lê a ata e monta o HTML do ofício (pessoa + prestação)."""
    if _eh_20bpm(tipo_efetivo):
        return _gerar_conteudo_20bpm(
            item, user, http_session,
            assinante_nome=assinante_nome,
            assinante_cargo=assinante_cargo,
            numero_documento=numero_documento,
        )

    from expedir_rapido import _extrair_dados_ata, _gerar_html
    from processes.models import Party, RAGExample

    proc = _obter_processo(item, user, http_session)
    if not proc:
        return '', None, None, {}, ''

    template = _resolver_template(tipo_efetivo)
    dados_ata = {}

    if _eh_ciap(tipo_efetivo):
        try:
            dados_ata = _extrair_dados_ata(
                http_session,
                proc,
                {'link_processo': item.get('procHref') or proc.projudi_url},
            ) or {}
        except Exception as e:
            print(f'   ⚠️ Erro ao ler a ata de audiência: {e}')
            dados_ata = {}

        if not dados_ata.get('prestacao_tipo'):
            print('   ⚠️ Ata encontrada, mas sem prestação de serviços/pecuniária.')
            return '', template, proc, dados_ata, ''

    nome = ''
    autores = dados_ata.get('autores_do_fato') or []
    if autores:
        nome = (autores[0] or '').strip()

    party = None
    if nome:
        party = Party.objects.filter(
            process=proc, name__icontains=nome[:25]
        ).first()
    if not party:
        party = (
            Party.objects.filter(
                process=proc,
                role__in=['reu', 'executado', 'PROMOVIDO', 'EXECUTADO'],
            ).first()
            or Party.objects.filter(process=proc).first()
        )

    if party:
        nome = nome or party.name
        parte = SimpleNamespace(
            name=nome,
            address=party.address or '',
            # O telefone do ofício CIAP deve vir da ata de audiência.
            # O cadastro da parte é só fallback quando a ata não informa.
            phone=dados_ata.get('telefone', '') or party.phone,
            email=party.email or '',
            cpf_cnpj=party.cpf_cnpj or '',
            rg=party.rg or '',
            nome_pai=party.nome_pai or '',
            nome_mae=party.nome_mae or '',
        )
    elif nome:
        # Processo ainda não cadastrado: usa o que a ata informou.
        parte = SimpleNamespace(
            name=nome,
            address='',
            phone=dados_ata.get('telefone', ''),
            email='',
            cpf_cnpj='',
            rg='',
            nome_pai='',
            nome_mae='',
        )
    else:
        print('   ⚠️ Ata sem autor do fato identificado.')
        return '', template, proc, dados_ata, ''

    rag = RAGExample.objects.filter(
        process=proc, active=True
    ).order_by('-id').first()
    if not rag:
        rag = SimpleNamespace(
            despacho_ato='',
            despacho_observacao='',
            despacho_data='',
            despacho_autor='MARTINHO FERRAZ DA NOBREGA JUNIOR',
        )

    try:
        html = _gerar_html(
            proc, parte, rag, template, dados_ata=dados_ata or None,
            assinante_nome=assinante_nome,
            assinante_cargo=assinante_cargo,
            numero_documento=numero_documento,
        ) or ''
    except Exception as e:
        print(f'   ⚠️ Erro ao gerar o HTML do ofício: {e}')
        html = ''

    return html, template, proc, dados_ata, nome


JS_SCAN = r'''() => {
    const forms = Array.from(document.querySelectorAll('form[name^="formCumprimento"]'));
    return forms.map((form, idx) => {
        const sel = form.querySelector('select[name="codModelo"]');
        const options = sel ? Array.from(sel.options).map(o => ({
            value: o.value,
            text: (o.text || '').trim(),
        })) : [];
        // Só considera "selecionado" se o HTML tiver o atributo selected.
        // Sem isso, o navegador assume a 1ª opção (ex.: CÍVEL - INSS) e o
        // filtro acaba descartando o ofício antes de escolher o modelo certo.
        const selectedOpt = sel
            ? Array.from(sel.options).find(o => o.hasAttribute('selected'))
            : null;
        const selected = selectedOpt ? (selectedOpt.text || '').trim() : '';
        const row = form.closest('tr') || form.parentElement;
        // innerText da linha inclui o texto de TODAS as opções do select
        // (inclusive CIAP/RPV/RPA). Remove form/select para sobrar apenas
        // processo, destinatário, movimentação e data.
        let rowText = '';
        if (row) {
            const clone = row.cloneNode(true);
            clone.querySelectorAll('select, form, input, button, option')
                .forEach(el => el.remove());
            rowText = (clone.innerText || '')
                .replace(/\s+/g, ' ').trim();
        }
        const link = row
            ? row.querySelector('a[href*="DadosProcesso"], a[href*="numeroProcesso="]')
            : null;
        let codCump = '';
        for (const input of form.querySelectorAll('input')) {
            const nome = (input.name || '').toLowerCase();
            if (nome.includes('codcumprimento') && input.value) {
                codCump = input.value;
            }
        }
        return {
            idx: idx,
            name: form.name || '',
            selected: selected,
            options: options,
            rowText: rowText,
            procHref: link ? link.href : '',
            procText: link ? (link.innerText || '').trim() : '',
            codCump: codCump,
        };
    });
}'''


JS_SELECIONAR_TIPO = r'''({name, termos, preferir}) => {
    const form = document.forms[name];
    if (!form) return {ok: false, motivo: 'form não encontrado'};
    const sel = form.querySelector('select[name="codModelo"]');
    const alvos = (termos || []).filter(Boolean);
    if (!sel || !alvos.length) return {ok: true, alterado: false};

    const norm = (s) => (s || '').normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '').toLowerCase();
    const alvosNorm = alvos.map(norm);
    const prefNorm = (preferir || []).map(norm).filter(Boolean);
    const generico = alvosNorm.some(a => a === 'rpa' || a === 'oficio' || a === 'comum');

    let melhor = null;
    let melhorScore = 0;
    for (const opt of sel.options) {
        const texto = norm(opt.text);
        if (!texto) continue;
        // "Ofício comum" não pode cair no CIAP/RPV só porque ambos começam
        // com "Ofício". O CIAP também pode aparecer como "Central Integrada
        // de Alternativas Penais".
        if (generico && (
            texto.includes('ciap')
            || texto.includes('central integrada')
            || texto.includes('alternativas penais')
            || texto.includes('rpv')
        )) {
            continue;
        }
        let score = 0;
        for (const alvo of alvosNorm) {
            if (texto === alvo) score = Math.max(score, 3);
            else if (texto.startsWith(alvo)) score = Math.max(score, 2);
            else if (texto.includes(alvo)) score = Math.max(score, 1);
        }
        // Preferência pelo conteúdo da ATA (ex.: SERVIÇO x PECUNIÁRIA).
        for (const pref of prefNorm) {
            if (texto.includes(pref)) score += 2;
        }
        if (score > melhorScore) {
            melhorScore = score;
            melhor = opt;
        }
    }

    if (!melhor) {
        return {ok: false, motivo: 'tipo não encontrado no select codModelo'};
    }
    sel.value = melhor.value;
    sel.dispatchEvent(new Event('change', {bubbles: true}));
    return {ok: true, alterado: true, texto: (melhor.text || '').trim()};
}'''


JS_CLICAR_REDIGIR = r'''(name) => {
    const form = document.forms[name];
    if (!form) return {ok: false, motivo: 'form não encontrado'};

    // Preferência: clicar no link real "Redigir sem AR" da linha.
    const links = Array.from(document.querySelectorAll('a'));
    const link = links.find(a => {
        const texto = (a.innerText || '').trim();
        const href = a.getAttribute('href') || a.getAttribute('onclick') || '';
        return texto === 'Redigir sem AR' && href.includes(name);
    });
    if (link) {
        link.click();
        return {ok: true, via: 'link Redigir sem AR'};
    }

    // Fallback: mesmo submit que o link executa.
    if (form.gerarar) {
        form.gerarar.value = 'false';
    } else {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'gerarar';
        input.value = 'false';
        form.appendChild(input);
    }
    form.submit();
    return {ok: true, via: 'submit do form'};
}'''


def _colar_html(page, html):
    """Cola o HTML no FCKeditor preservando o brasão do modelo do Projudi."""
    original = page.evaluate(r'''() => {
        try { return FCKeditorAPI.GetInstance('FCKeditor1').GetHTML(); }
        catch (e) {
            try { return window.parent.FCKeditorAPI.GetInstance('FCKeditor1').GetHTML(); }
            catch (e2) { return ''; }
        }
    }''')

    brasao = ''
    m = re.search(r'(<img[^>]+src="[^"]*brasao[^"]*"[^>]*>)', original or '', re.I)
    if m:
        brasao = f'<div style="text-align:center; margin-bottom:8px;">{m.group(1)}</div>'

    return page.evaluate(r'''(html) => {
        try {
            const ed = FCKeditorAPI.GetInstance('FCKeditor1');
            ed.SetHTML('');
            ed.SetHTML(html);
            return 'OK';
        } catch (e) {
            try {
                const ed2 = window.parent.FCKeditorAPI.GetInstance('FCKeditor1');
                ed2.SetHTML('');
                ed2.SetHTML(html);
                return 'OK parent';
            } catch (e2) {
                return 'ERRO: ' + e2.message;
            }
        }
    }''', brasao + html)


def _submeter_e_registrar(page):
    """Clica Submeter e, se aparecer, Registrar. Retorna True se registrou."""
    submeter = page.locator('input[src*="bot-submeter"]').first
    if not submeter.count():
        submeter = page.locator("input[value='Submeter']").first
    if not submeter.count():
        submeter = page.locator('input[type="image"]').first
    if not submeter.count():
        print('   ❌ Botão Submeter não encontrado.')
        return False

    submeter.scroll_into_view_if_needed()
    time.sleep(1)
    submeter.click()
    time.sleep(5)
    try:
        page.wait_for_load_state('networkidle', timeout=10000)
    except Exception:
        pass

    registrar = page.locator(
        "input[value='Registrar'], button:has-text('Registrar'), input[src*='registrar']"
    ).first
    if not registrar.count():
        print('   ⚠️ Botão Registrar não encontrado após Submeter.')
        return False

    registrar.scroll_into_view_if_needed()
    time.sleep(1)
    registrar.click()
    time.sleep(4)
    print('   ✅ Registrar clicado.')
    return True


def _processar_item(page, item, tipo, user, http_session,
                    assinante_nome=None, assinante_cargo=None,
                    planilha=None):
    """Monta o ofício, clica em "Redigir sem AR", Submete e Registra."""
    nome_form = item.get('name')
    if not nome_form:
        print('   ⚠️ Linha sem nome de form — ignorada.')
        return False

    tipo_efetivo = _tipo_efetivo(item, tipo)
    termos = _termos_modelo(tipo_efetivo) if tipo_efetivo else _termos_do_item(item)
    preferir = []

    html_gerado = ''
    proc = None
    dados_ata = {}
    nome_parte = ''
    template = None
    numero_planilha = ''

    # Número oficial da planilha Google: último número + 1.
    if planilha:
        try:
            numero_planilha = planilha.proximo_numero()
            print(f'   🔢 Próximo número da planilha: {numero_planilha}')
        except Exception as e:
            print(f'   ⚠️ Não foi possível ler a planilha Google: {e}')

    # CIAP: a ata é a fonte da pessoa que vai cumprir e do tipo de prestação
    # (serviços x pecuniária). Sem isso, não confecciona o ofício.
    if tipo_efetivo:
        html_gerado, template, proc, dados_ata, nome_parte = _gerar_conteudo(
            item, tipo_efetivo, user, http_session,
            assinante_nome=assinante_nome,
            assinante_cargo=assinante_cargo,
            numero_documento=numero_planilha or None,
        )

    if _eh_ciap(tipo_efetivo):
        preferir = _preferencia_ciap(dados_ata)
        if not preferir:
            print('   ⏭️ Ata não informou prestação de serviços/pecuniária — '
                  'pulando para não usar o modelo CIAP errado.')
            return False
        if not html_gerado:
            print('   ⏭️ Não foi possível montar o ofício CIAP a partir da ata — '
                  'pulando.')
            return False

    if _eh_20bpm(tipo_efetivo) and not html_gerado:
        print('   ⏭️ Não foi possível montar o ofício 20º BPM — pulando.')
        return False

    if not proc:
        proc = _resolver_processo(item)
    html_doc, doc = _html_do_processo(proc, tipo_efetivo)
    html = html_gerado or html_doc

    # Em "Todos", se a linha não tem modelo, não foi possível inferir o tipo
    # e também não há documento gerado, não abre o editor.
    if (not tipo_efetivo and not termos and not html):
        print('   ⏭️ Sem modelo definido e sem documento gerado — pulando.')
        return False

    if dados_ata:
        print(
            f'   📋 Ata: {dados_ata.get("prestacao_tipo") or "tipo não lido"} '
            f'| pessoa: {nome_parte or "(não identificada)"}'
        )
    elif _eh_20bpm(tipo_efetivo) and nome_parte:
        print(f'   👮 Policiais: {nome_parte}')

    selecao = page.evaluate(
        JS_SELECIONAR_TIPO,
        {'name': nome_form, 'termos': termos, 'preferir': preferir},
    )
    if termos and not selecao.get('ok'):
        print(f'   ❌ Não foi possível aplicar o modelo/tipo '
              f'({", ".join(termos)}): {selecao.get("motivo")} — '
              f'item não será submetido.')
        return False

    # Clica no link real "Redigir sem AR" da linha (fallback: submit do form).
    try:
        with page.expect_navigation(timeout=30000):
            page.evaluate(JS_CLICAR_REDIGIR, nome_form)
    except Exception as e:
        print(f'   ❌ Não navegou para o editor: {e}')
        return False

    time.sleep(3)
    if 'ExpedirCumprimento' not in page.url:
        # Alguns fluxos abrem a edição em outra URL; confere pelo editor.
        tem_editor = page.evaluate(
            "() => !!(window.FCKeditorAPI || document.querySelector('iframe[src*=\"FCKeditor\"]'))"
        )
        if not tem_editor:
            print(f'   ❌ Página de edição não encontrada. URL: {page.url[:120]}')
            return False

    print(f'   📝 Editor aberto: {page.url[:120]}')
    modelo_aplicado = selecao.get('texto')
    if modelo_aplicado:
        print(f'   🏷️ Modelo aplicado: {modelo_aplicado}')

    if html:
        origem = 'confeccionado a partir da ata' if html_gerado else f'#{doc.id}'
        print(f'   📄 Ofício {origem} — colando HTML ({len(html)} chars).')
        resultado = _colar_html(page, html)
        print(f'   📝 FCKeditor: {resultado}')
        if not str(resultado).startswith('OK'):
            print('   ❌ Falha ao colar o HTML no editor — item não será submetido.')
            return False
        time.sleep(2)
    else:
        if proc:
            print(f'   ℹ️ Sem HTML gerado para {proc.number}; '
                  f'usando o conteúdo padrão do modelo do Projudi.')
        else:
            print('   ℹ️ Processo não localizado no banco; '
                  'usando o conteúdo padrão do modelo do Projudi.')

    sucesso = _submeter_e_registrar(page)
    if sucesso and doc:
        doc.exported_to_projudi = True
        doc.save(update_fields=['exported_to_projudi'])
        print(f'   💾 GeneratedDocument #{doc.id} marcado como exportado.')

    if sucesso and planilha and numero_planilha:
        processo_num = (
            proc.number if proc else
            _extrair_cnj(
                ' '.join([
                    item.get('rowText') or '',
                    item.get('procText') or '',
                ])
            )
        )
        destinatario = _destinatario_item(item, tipo_efetivo)
        try:
            planilha.registrar(
                numero_planilha,
                processo_num,
                destinatario,
            )
            print(
                f'   ✅ Planilha Google: linha adicionada '
                f'({numero_planilha} | {processo_num} | {destinatario[:60]}).'
            )
        except Exception as e:
            print(
                f'   ⚠️ Ofício expedido, mas a planilha Google não foi '
                f'atualizada: {e}'
            )

    return sucesso


def main():
    parser = argparse.ArgumentParser(
        description='Expede ofícios pendentes do CumprimentoCartorio por tipo.'
    )
    parser.add_argument(
        '--tipo', default='',
        help=(
            'CIAP (Central Integrada de Alternativas Penais), RPV, '
            '"Ofício comum", etc. Vazio = todos.'
        )
    )
    parser.add_argument('--user-id', type=int, default=None, help='ID do usuário Django.')
    parser.add_argument('--limite', type=int, default=20, help='Máximo de ofícios (default 20).')
    parser.add_argument(
        '--assinante', default=ASSINANTE_PADRAO, choices=sorted(ASSINANTES),
        help='Assinante do ofício: ivan (Secretário em Substituição) ou mauro (Secretário).',
    )
    parser.add_argument(
        '--planilha', action='store_true',
        help='Preenche a planilha Google Docs (conta de serviço).',
    )
    args = parser.parse_args()

    tipo = (args.tipo or '').strip()
    assinante_nome, assinante_cargo = ASSINANTES[args.assinante]
    user = _carregar_usuario(args.user_id)
    cookies = _carregar_cookies(user)
    http_session = _criar_sessao_http(cookies)

    planilha = None
    if args.planilha:
        try:
            from projudi.oficio_planilha_service import obter_servico_planilha
            planilha = obter_servico_planilha()
            if planilha:
                tipo_servico = type(planilha).__name__
                print(f'Planilha Google configurada ({tipo_servico}).')
            else:
                print(
                    '⚠️ Planilha Google solicitada, mas não configurada. '
                    'Defina GOOGLE_OFICIOS_WEBHOOK_URL (Apps Script) ou '
                    'GOOGLE_SERVICE_ACCOUNT_FILE. Seguindo sem planilha.'
                )
        except Exception as e:
            print(f'⚠️ Planilha Google indisponível: {e}')
            planilha = None

    print('=' * 60)
    print(f'Expedir ofícios por tipo: {tipo or "TODOS"}')
    print(f'Usuário: {user.email or user.username} (id={user.id})')
    print(f'Assinante: {assinante_nome} — {assinante_cargo}')
    print(f'Limite: {args.limite}')
    print('=' * 60)

    processados = set()
    total = 0
    falhas = 0
    tentativas = 0
    max_tentativas = max(args.limite * 3, 10)

    with sync_playwright() as pw:
        browser = pw.firefox.launch(headless=False, slow_mo=300)
        contexto = browser.new_context(
            viewport={'width': 1500, 'height': 950},
            locale='pt-BR',
        )
        contexto.add_cookies([
            {
                'name': str(name),
                'value': str(value),
                'domain': 'projudi.tjba.jus.br',
                'path': '/',
            }
            for name, value in cookies.items()
        ])
        page = contexto.new_page()
        page.on('dialog', lambda dialog: dialog.accept())

        while total < args.limite and tentativas < max_tentativas:
            tentativas += 1
            try:
                page.goto(URL_CUMPRIMENTO, wait_until='networkidle', timeout=60000)
            except Exception as e:
                print(f'❌ Erro ao abrir a lista de ofícios: {e}')
                break

            time.sleep(2)
            try:
                titulo = (page.title() or '').lower()
                inicio = (page.content() or '')[:3000].lower()
                if ('expirou' in titulo
                        or 'sessão expirou' in inicio
                        or 'sessao expirou' in inicio):
                    print('SESSAO_EXPIRADA')
                    break
            except Exception:
                pass

            try:
                itens = page.evaluate(JS_SCAN)
            except Exception as e:
                print(f'❌ Erro ao ler a lista de ofícios: {e}')
                break

            if itens:
                modelos_vistos = []
                for item in itens:
                    rotulo = (item.get('selected') or '(sem modelo)').strip()
                    if rotulo not in modelos_vistos:
                        modelos_vistos.append(rotulo)
                print(
                    f'ℹ️ Modelos/tipos encontrados na página '
                    f'({len(itens)} pendente(s)): '
                    f'{"; ".join(modelos_vistos)[:800]}'
                )

            if not itens:
                if total > 0:
                    print('FIM_PROCESSAMENTO')
                else:
                    print('NENHUM_OFICIO_PENDENTE')
                break

            candidatos = []
            for item in itens:
                chave = _chave_item(item)
                if chave in processados:
                    continue
                if _item_corresponde(item, tipo):
                    candidatos.append(item)

            if not candidatos:
                if total > 0:
                    print('FIM_PROCESSAMENTO')
                elif tipo:
                    print(f'NENHUM_OFICIO_DO_TIPO: {tipo}')
                else:
                    print('NENHUM_OFICIO_PENDENTE')
                break

            item = candidatos[0]
            processados.add(_chave_item(item))
            print(
                f'\n[{total + 1}/{args.limite}] {item.get("name")} '
                f'| modelo: {item.get("selected") or "(não selecionado)"} '
                f'| {item.get("procText") or "processo não identificado"}'
            )

            try:
                if _processar_item(
                    page, item, tipo, user, http_session,
                    assinante_nome=assinante_nome,
                    assinante_cargo=assinante_cargo,
                    planilha=planilha,
                ):
                    total += 1
                else:
                    falhas += 1
            except Exception as e:
                falhas += 1
                print(f'   ❌ Erro no item: {e}')
                import traceback
                traceback.print_exc()

        browser.close()

    print('\n' + '=' * 60)
    print(f'Expedidos/registrados: {total}')
    print(f'Falhas: {falhas}')
    print('=' * 60)

    if total == 0 and falhas == 0:
        return 0
    if total == 0 and falhas > 0:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
