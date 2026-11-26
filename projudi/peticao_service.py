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
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

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

    def _intimacao_do_processo(self, session, processo_url, data_envio):
        """Localiza a intimação mais próxima após a petição e o meio usado."""
        if not processo_url:
            return {}
        if processo_url in self._cache_intimacao:
            return self._cache_intimacao[processo_url]

        resultado = {}
        try:
            resposta = session.get(processo_url, timeout=30)
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
                texto = ' '.join(
                    td.get_text(' ', strip=True) for td in tds
                )
                if 'INTIMA' not in _norm(texto):
                    continue

                data_mov = _parse_data(texto)
                if not data_mov:
                    continue
                if data_envio and data_mov < data_envio:
                    continue

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

    def listar(self):
        """Lê a fila e devolve somente os tipos que geram certidão."""
        session = self._session()
        resposta = session.get(URL_PETICOES, timeout=40)
        if resposta.status_code != 200 or 'expirou' in resposta.text.lower():
            raise RuntimeError('Não foi possível abrir a fila de petições.')

        soup = BeautifulSoup(resposta.text, 'html.parser')
        form = soup.find('form', attrs={'name': 'formPeticoes'})
        if not form:
            return []

        itens = []
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
            data_envio = _parse_data(
                ' '.join(td.get_text(' ', strip=True) for td in tds)
            )

            texto_tipo = ' '.join(
                td.get_text(' ', strip=True) for td in tds
            )
            tipo = classificar_peticao(texto_tipo)
            if not tipo:
                continue

            doc_link = tr.find('a', href=re.compile('DownloadArquivo'))
            doc_url = ''
            doc_texto = ''
            if doc_link:
                doc_url = urljoin(BASE_URL, doc_link.get('href', ''))
                doc_texto = doc_link.get_text(' ', strip=True)

            if not data_envio:
                continue

            info = TIPOS[tipo]
            processo_url = urljoin(BASE_URL, proc_link.get('href', ''))

            intimacao = self._intimacao_do_processo(
                session, processo_url, data_envio
            )
            data_inicio = intimacao.get('data') or data_envio
            fluxo_intimacao = intimacao.get('meio') or 'intimacao'
            meio_label = intimacao.get(
                'meio_label', MEIO_LABEL.get(fluxo_intimacao, '')
            )
            if not intimacao:
                meio_label = 'Data de envio (intimação não localizada no processo)'

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
                'cod_documento': cod_doc,
                'processo': processo,
                'processo_url': processo_url,
                'data_envio': data_envio,
                'data_envio_fmt': data_envio.strftime('%d/%m/%Y'),
                'data_intimacao': intimacao.get('data'),
                'data_intimacao_fmt': (
                    intimacao['data'].strftime('%d/%m/%Y')
                    if intimacao.get('data') else ''
                ),
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
                'tipo': tipo,
                'tipo_label': info['label'],
                'dias': info['dias'],
                'documento_url': doc_url,
                'documento_texto': doc_texto,
                'recorrente': _nome_documento(texto_tipo),
                'prazo': prazo.to_dict() if prazo else {},
                'erro_prazo': erro_prazo,
            }
            itens.append(item)
            vistos.add(cod_doc)

        return itens
