"""Leitura da fila de petições (JuntadaPeticao) e classificação de prazos.

A fila fica em:
    https://projudi.tjba.jus.br/projudi/listagens/JuntadaPeticao

Tipos relevantes para certidão:
  - Recurso Inominado ......................... 10 dias úteis
  - Contrarrazões ao Recurso Inominado ........ 10 dias úteis
  - Impugnação/Cumprimento de Sentença ........ 15 dias úteis
  - Impugnação/Decurso do prazo da Penhora .... 15 dias úteis
"""
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
from django.core.cache import cache

from projudi.cumprimento_service import CumprimentoService
from projudi.services import ProjudiService

BASE_URL = 'https://projudi.tjba.jus.br/projudi/'
URL_PETICOES = urljoin(BASE_URL, 'listagens/JuntadaPeticao')

TIPOS = {
    'recurso_inominado': {
        'label': 'Recurso Inominado',
        'dias': 10,
    },
    'contrarrazoes': {
        'label': 'Contrarrazões ao Recurso Inominado',
        'dias': 10,
    },
    'impugnacao_cumprimento': {
        'label': 'Impugnação/Cumprimento de Sentença',
        'dias': 15,
    },
    'impugnacao_penhora': {
        'label': 'Impugnação/Decurso do Prazo da Penhora',
        'dias': 15,
    },
}


def _norm(texto):
    import unicodedata
    texto = unicodedata.normalize('NFKD', str(texto or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', texto).strip().upper()


def classificar_peticao(texto):
    """Retorna a chave de TIPOS ou None."""
    alvo = _norm(texto)

    if 'RECURSO INOMINADO' in alvo:
        return 'recurso_inominado'
    if 'CONTRARRAZOES' in alvo or 'CONTRARRAZAO' in alvo:
        return 'contrarrazoes'

    tem_impugnacao = 'IMPUGNACAO' in alvo
    tem_penhora = 'PENHORA' in alvo or 'DECURSO' in alvo
    tem_cumprimento = 'CUMPRIMENTO DE SENTENCA' in alvo or 'CUMPRIMENTO' in alvo

    if tem_impugnacao and tem_penhora:
        return 'impugnacao_penhora'
    if tem_impugnacao or tem_cumprimento:
        return 'impugnacao_cumprimento'
    return None


def _texto_linha(tr):
    """Texto da própria linha, sem o conteúdo de tabelas aninhadas."""
    partes = []
    for td in tr.find_all('td', recursive=False):
        clone = BeautifulSoup(str(td), 'html.parser')
        for nested in clone.find_all('table'):
            nested.decompose()
        partes.append(clone.get_text(' ', strip=True))
    return ' '.join(partes)


def _parse_data(texto):
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', texto or '')
    if not m:
        return None
    dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if ano < 100:
        ano += 2000
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def _nome_documento(texto):
    """Tenta extrair um nome próprio do nome do arquivo da petição."""
    texto = re.sub(r'\s+', ' ', texto or '')
    # Padrões comuns: "... - LUCIMAR LIMA CORREIA TEIXEIRA.pdf"
    m = re.search(
        r'[-–]\s*([A-ZÀ-Ú][A-ZÀ-Ú\s]{5,}?)(?:\.pdf|\.PDF|$)',
        texto,
    )
    if m:
        nome = m.group(1).strip()
        if not any(k in _norm(nome) for k in (
                'RECURSO', 'PETICAO', 'IMPUGNACAO', 'CUMPRIMENTO',
                'PENHORA', 'CONTRARRAZOES', 'COMPROVANTE', 'GUIA')):
            return nome.title()
    return ''


MEIO_LABEL = {
    'eletronico': 'DJEN / domicílio eletrônico',
    'advogado': 'Advogado constituído',
    'email': 'E-mail',
    'ar': 'AR / Correios',
    'mandado': 'Mandado',
    'intimacao': 'Intimação (meio não identificado)',
}


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


class PeticaoQueueService:
    def __init__(self, user):
        self.user = user
        self._cache_intimacao = {}

    def _session(self):
        resultado = ProjudiService(self.user)._get_session_from_cookies()
        if not resultado:
            raise RuntimeError(
                'Sessão do Projudi não disponível. Sincronize a sessão.'
            )
        return resultado[0]

    @staticmethod
    def _nova_sessao(cookies):
        import requests
        sessao = requests.Session()
        for nome, valor in cookies.items():
            sessao.cookies.set(nome, valor)
        sessao.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) '
                'Gecko/20100101 Firefox/128.0'
            ),
            'Accept': (
                'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            ),
            'Accept-Language': 'pt-BR,pt;q=0.9',
        })
        return sessao

    def _recorrente_do_documento(self, session, documento_url, documento_texto):
        """Nome do recorrente a partir do texto da petição de recurso."""
        # 1) Tenta pelo texto do PDF da petição.
        if documento_url:
            try:
                resposta = session.get(documento_url, timeout=10)
                if resposta.status_code == 200:
                    texto = ''
                    try:
                        import fitz
                        pdf = fitz.open(
                            stream=resposta.content, filetype='pdf'
                        )
                        texto = '\n'.join(p.get_text() for p in pdf)
                    except Exception:
                        texto = ''

                    if texto:
                        # Olha só o cabeçalho da petição, antes das razões.
                        trecho = texto[:6000]
                        corte = re.search(
                            r'RAZ[ÕO]ES\s+DO\s+RECURSO', trecho, re.I
                        )
                        if corte:
                            trecho = trecho[:corte.start()]

                        padroes = (
                            r'^[ \t]*([A-ZÀ-Ú0-9][A-ZÀ-Ú0-9\.\-&/ \t]{3,120}?),'
                            r'[ \t]*(?i:j[áa]\s+devidamente\s+qualificad[oa])',
                            r'([A-ZÀ-Ú0-9][A-ZÀ-Ú0-9\.\-&/ \t]{3,120}?),'
                            r'[ \t]+por\s+interm[ée]dio\s+dos\s+seus\s+procuradores',
                            r'RECORRENTE\s*:?\s*'
                            r'([A-ZÀ-Ú0-9][A-ZÀ-Ú0-9\.\-&/ \t]{3,100}?)'
                            r'(?:\n|,|\.\s)',
                        )
                        for padrao in padroes:
                            m = re.search(padrao, trecho, re.M)
                            if not m:
                                continue
                            nome = re.sub(r'\s+', ' ', m.group(1)).strip(
                                ' .,-'
                            )
                            if (len(nome) >= 5
                                    and not any(k in _norm(nome) for k in (
                                        'RECURSO', 'PETICAO', 'EXCELENT',
                                        'PROCESSO', 'RAZOES', 'CERTIDAO',
                                        'TURMA', 'EGREGIA', 'COLENDA'))):
                                return nome
            except Exception:
                pass

        # 2) Fallback: nome no arquivo da petição.
        return _nome_documento(documento_texto)

    def _evento_recurso(self, session, processo_url, data_envio):
        """Evento em que a petição de recurso inominado foi protocolada."""
        if not processo_url:
            return ''
        chave = f'evento_recurso:{processo_url}:{data_envio}'
        if chave in self._cache_intimacao:
            return self._cache_intimacao[chave]

        evento = ''
        try:
            resposta = session.get(processo_url, timeout=12)
            if resposta.status_code != 200 or 'expirou' in resposta.text.lower():
                return ''
            soup = BeautifulSoup(resposta.text, 'html.parser')
            candidatos = []
            for tr in soup.find_all('tr'):
                tds = tr.find_all('td', recursive=False)
                if not tds:
                    continue
                texto = _texto_linha(tr)
                up = _norm(texto)
                if 'RECURSO INOMINADO' not in up:
                    continue
                data_mov = _parse_data(texto)
                if not data_mov:
                    continue
                ev = tds[0].get_text(' ', strip=True)
                if not ev.isdigit():
                    continue
                candidatos.append((abs((data_mov - data_envio).days),
                                   data_mov, ev))
            if candidatos:
                candidatos.sort(key=lambda c: (c[0], c[1]))
                evento = candidatos[0][2]
        except Exception:
            evento = ''

        self._cache_intimacao[chave] = evento
        return evento

    def _intimacao_da_sentenca(self, session, processo_url, data_envio):
        """Data/meio da intimação da SENTENÇA para o recurso inominado.

        O prazo do recurso inominado conta da intimação da sentença ao
        recorrente, não da data em que o recurso foi protocolado.
        """
        if not processo_url:
            return {}
        chave = f'sentenca:{processo_url}'
        if chave in self._cache_intimacao:
            return self._cache_intimacao[chave]

        resultado = {}
        try:
            resposta = session.get(processo_url, timeout=12)
            if resposta.status_code != 200 or 'expirou' in resposta.text.lower():
                return {}

            soup = BeautifulSoup(resposta.text, 'html.parser')
            candidatos = []
            candidatos_genericos = []
            eventos_recurso = []

            for tr in soup.find_all('tr'):
                tds = tr.find_all('td', recursive=False)
                if not tds:
                    continue
                texto = _texto_linha(tr)
                up = _norm(texto)

                if 'RECURSO INOMINADO' in up:
                    data_rec = _parse_data(texto)
                    ev_rec = tds[0].get_text(' ', strip=True)
                    if data_rec and ev_rec.isdigit():
                        eventos_recurso.append((
                            abs((data_rec - data_envio).days),
                            data_rec,
                            ev_rec,
                        ))

                if 'INTIMA' not in up and 'DISPONIBILIZ' not in up:
                    continue

                data_mov = _parse_data(texto)
                if not data_mov:
                    continue
                # A intimação da sentença é anterior ao recurso.
                if data_envio and data_mov > data_envio:
                    continue

                evento = tds[0].get_text(' ', strip=True)
                if not evento.isdigit():
                    evento = ''

                meio = _classificar_meio(texto)
                data_base = data_mov
                if meio == 'eletronico':
                    m = re.search(
                        r'disponibiliz[^\n]{0,100}?'
                        r'(\d{1,2}/\d{1,2}/\d{2,4})',
                        texto, re.I,
                    )
                    if m:
                        data_base = _parse_data(m.group(1)) or data_base

                item = {
                    'data': data_base,
                    'data_mov': data_mov,
                    'evento': evento,
                    'meio': meio,
                    'meio_label': MEIO_LABEL.get(meio, meio),
                    'texto': texto[:500],
                }

                if any(k in up for k in (
                        'SENTENCA', 'JULGADA', 'JULGADO',
                        'HOMOLOG', 'ACORDAO')):
                    candidatos.append(item)
                candidatos_genericos.append(item)

            # Prefere a intimação que referencia a sentença; se não houver,
            # usa a última intimação anterior ao recurso.
            lista = candidatos or candidatos_genericos
            if lista:
                lista.sort(key=lambda c: (c['data'], c['data_mov']))
                resultado = lista[-1]

            if eventos_recurso:
                eventos_recurso.sort(key=lambda e: (e[0], e[1]))
                resultado = dict(resultado)
                resultado['evento_recurso'] = eventos_recurso[0][2]
        except Exception:
            resultado = {}

        self._cache_intimacao[chave] = resultado
        return resultado

    def _intimacao_do_processo(self, session, processo_url, data_envio,
                               tipo=None):
        """Localiza a intimação mais próxima e o meio usado."""
        if tipo == 'recurso_inominado':
            return self._intimacao_da_sentenca(
                session, processo_url, data_envio
            )
        if not processo_url:
            return {}
        if processo_url in self._cache_intimacao:
            return self._cache_intimacao[processo_url]

        resultado = {}
        try:
            resposta = session.get(processo_url, timeout=12)
            if resposta.status_code != 200 or 'expirou' in resposta.text.lower():
                return {}

            soup = BeautifulSoup(resposta.text, 'html.parser')
            candidatos = []

            # Lê diretamente as linhas da tabela de movimentações. Evita o
            # parser completo, que quebra em algumas variações de data.
            for tr in soup.find_all('tr'):
                tds = tr.find_all('td', recursive=False)
                if not tds:
                    continue
                texto = _texto_linha(tr)
                if 'INTIMA' not in _norm(texto):
                    continue

                data_mov = _parse_data(texto)
                if not data_mov:
                    continue
                if data_envio and data_mov < data_envio:
                    continue

                evento = tds[0].get_text(' ', strip=True)
                if not evento.isdigit():
                    evento = ''

                meio = _classificar_meio(texto)
                data_base = data_mov

                # DJEN: o marco é a disponibilização, se estiver no texto.
                if meio == 'eletronico':
                    m = re.search(
                        r'disponibiliz[^\n]{0,100}?'
                        r'(\d{1,2}/\d{1,2}/\d{2,4})',
                        texto, re.I,
                    )
                    if m:
                        data_base = _parse_data(m.group(1)) or data_base

                candidatos.append({
                    'data': data_base,
                    'data_mov': data_mov,
                    'evento': evento,
                    'meio': meio,
                    'meio_label': MEIO_LABEL.get(meio, meio),
                    'texto': texto[:500],
                })

            if candidatos:
                # A primeira intimação após a petição é a que abre o prazo.
                candidatos.sort(key=lambda c: (c['data'], c['data_mov']))
                resultado = candidatos[0]
        except Exception:
            resultado = {}

        self._cache_intimacao[processo_url] = resultado
        return resultado

    def listar(self, forcar=False):
        """Lê a fila e devolve somente os tipos que geram certidão."""
        chave_cache = f'peticao_queue:{self.user.pk}'
        if not forcar:
            em_cache = cache.get(chave_cache)
            if em_cache is not None:
                return em_cache

        session = self._session()
        resposta = session.get(URL_PETICOES, timeout=20)
        if resposta.status_code != 200 or 'expirou' in resposta.text.lower():
            raise RuntimeError('Não foi possível abrir a fila de petições.')

        soup = BeautifulSoup(resposta.text, 'html.parser')
        form = soup.find('form', attrs={'name': 'formPeticoes'})
        if not form:
            return []

        bases = []
        vistos = set()

        for tr in form.find_all('tr'):
            tds = tr.find_all('td', recursive=False)
            if len(tds) < 4:
                continue

            proc_link = tr.find('a', href=re.compile('DadosProcesso'))
            mov_link = tr.find(
                'a', href=re.compile(r'JuntarPeticao.*codDocumento')
            )
            if not proc_link or not mov_link:
                continue

            cod_doc = parse_qs(
                urlparse(mov_link.get('href', '')).query
            ).get('codDocumento', [''])[0]
            if not cod_doc or cod_doc in vistos:
                continue

            processo = proc_link.get_text(' ', strip=True).split()[0]
            texto_data = ' '.join(
                td.get_text(' ', strip=True) for td in tds
            )
            data_envio = _parse_data(texto_data)
            # A célula do tipo/documento contém tabela aninhada; usa o texto
            # completo dela para classificar.
            texto_tipo = (
                tds[3].get_text(' ', strip=True)
                if len(tds) > 3 else texto_data
            )
            tipo = classificar_peticao(texto_tipo)
            if not tipo or not data_envio:
                continue

            doc_link = tr.find('a', href=re.compile('DownloadArquivo'))
            doc_url = ''
            doc_texto = ''
            if doc_link:
                doc_url = urljoin(BASE_URL, doc_link.get('href', ''))
                doc_texto = doc_link.get_text(' ', strip=True)

            bases.append({
                'cod_documento': cod_doc,
                'processo': processo,
                'processo_url': urljoin(
                    BASE_URL, proc_link.get('href', '')
                ),
                'data_envio': data_envio,
                'tipo': tipo,
                'documento_url': doc_url,
                'documento_texto': doc_texto,
            })
            vistos.add(cod_doc)

        # As consultas ao processo e ao PDF são independentes: roda em
        # paralelo para a fila não ficar "rodando" por muito tempo.
        # Cada thread usa sua própria sessão requests para não serializar
        # as conexões.
        if bases:
            cookies = session.cookies.get_dict()
            with ThreadPoolExecutor(max_workers=min(6, len(bases))) as executor:
                futuros = {
                    executor.submit(
                        self._analisar_item, cookies, base
                    ): base
                    for base in bases
                }
                for futuro in as_completed(futuros):
                    base = futuros[futuro]
                    try:
                        intimacao, recorrente, evento_recurso = futuro.result()
                    except Exception:
                        intimacao, recorrente, evento_recurso = {}, '', ''
                    base['_intimacao'] = intimacao
                    base['_recorrente'] = recorrente
                    base['_evento_recurso'] = evento_recurso

        itens = []
        for base in bases:
            info = TIPOS[base['tipo']]
            intimacao = base.get('_intimacao') or {}
            data_inicio = intimacao.get('data') or base['data_envio']
            fluxo_intimacao = intimacao.get('meio') or 'intimacao'
            meio_label = intimacao.get(
                'meio_label', MEIO_LABEL.get(fluxo_intimacao, '')
            )
            if not intimacao:
                meio_label = (
                    'Data de envio (intimação não localizada no processo)'
                )

            prazo = None
            erro_prazo = ''
            try:
                prazo = CumprimentoService(
                    self.user
                ).contar_prazo_por_fluxo(
                    fluxo_intimacao,
                    data_inicio,
                    info['dias'],
                    modo='uteis',
                    tenant=getattr(self.user, 'tenant', None),
                )
            except Exception as exc:
                erro_prazo = str(exc)

            item = {
                'cod_documento': base['cod_documento'],
                'processo': base['processo'],
                'processo_url': base['processo_url'],
                'data_envio': base['data_envio'],
                'data_envio_fmt': base['data_envio'].strftime('%d/%m/%Y'),
                'data_intimacao': intimacao.get('data'),
                'data_intimacao_fmt': (
                    intimacao['data'].strftime('%d/%m/%Y')
                    if intimacao.get('data') else ''
                ),
                'evento_intimacao': intimacao.get('evento', ''),
                'data_inicio': data_inicio,
                'data_inicio_fmt': data_inicio.strftime('%d/%m/%Y'),
                'meio_intimacao': fluxo_intimacao,
                'meio_label': meio_label,
                'ultimo_dia': prazo.ultimo_dia if prazo else None,
                'ultimo_dia_fmt': (
                    prazo.ultimo_dia.strftime('%d/%m/%Y') if prazo else ''
                ),
                'data_decurso': prazo.data_decurso if prazo else None,
                'data_decurso_fmt': (
                    prazo.data_decurso.strftime('%d/%m/%Y') if prazo else ''
                ),
                'vencido': prazo.vencido if prazo else None,
                'dias_restantes': (
                    prazo.saldo_restante() if prazo else None
                ),
                'tempestivo': (
                    base['data_envio'] <= prazo.ultimo_dia
                    if prazo and base['data_envio'] else None
                ),
                'tipo': base['tipo'],
                'tipo_label': info['label'],
                'dias': info['dias'],
                'documento_url': base['documento_url'],
                'documento_texto': base['documento_texto'],
                'recorrente': (
                    base.get('_recorrente')
                    or _nome_documento(base['documento_texto'])
                ),
                'evento_recurso': base.get('_evento_recurso', ''),
                'prazo': prazo.to_dict() if prazo else {},
                'erro_prazo': erro_prazo,
            }
            itens.append(item)

        cache.set(chave_cache, itens, 300)
        return itens

    def _analisar_item(self, cookies, base):
        session = self._nova_sessao(cookies)
        intimacao = self._intimacao_do_processo(
            session,
            base['processo_url'],
            base['data_envio'],
            tipo=base['tipo'],
        )
        recorrente = self._recorrente_do_documento(
            session,
            base['documento_url'],
            base['documento_texto'],
        )
        evento_recurso = ''
        if base['tipo'] == 'recurso_inominado':
            evento_recurso = intimacao.get('evento_recurso', '')
        return intimacao, recorrente, evento_recurso
