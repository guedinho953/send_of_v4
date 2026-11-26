"""Cálculo de trânsito em julgado por parte.

Fase 1: prévia/leitura. A emissão da Mov848 é feita em etapa separada.
"""
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from base.utils import normalize_process_number
from projudiProcessNavigator import ProcessoParser
from .cumprimento_service import CumprimentoService
from .peticao_service import _norm
from .processo_lookup import localizar_processo
from .services import ProjudiService


def _data_br(valor):
    match = re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b', valor or '')
    if not match:
        return None
    dia, mes, ano = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if ano < 100:
        ano += 2000
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def _data_no_texto(texto):
    return _data_br(texto)


def _data_disponibilizacao(texto):
    match = re.search(
        r'disponibiliz[^\n]{0,120}?(\d{2}/\d{2}/\d{2,4})',
        texto or '', re.I,
    )
    return _data_br(match.group(1)) if match else None


def _norm_nome(texto):
    return re.sub(r'[^A-Z0-9 ]+', ' ', _norm(texto or '')).strip()


class TransitoJulgadoService:
    def __init__(self, user):
        self.user = user
        self.cumprimento = CumprimentoService(user)

    def _sessao(self):
        resultado = ProjudiService(self.user)._get_session_from_cookies()
        return resultado[0] if resultado else None

    def analisar(self, numero):
        digitos = normalize_process_number(numero)
        if len(digitos) < 15:
            return {'erro': 'Número de processo inválido.'}
        digitos = digitos.zfill(20)
        localizado = localizar_processo(self.user, digitos)
        if not localizado:
            return {'erro': 'Processo não localizado no Projudi.'}

        session = self._sessao()
        if not session:
            return {'erro': 'Sessão do Projudi não disponível.'}

        resposta = session.get(localizado['url'], timeout=25)
        if resposta.status_code != 200:
            return {'erro': 'Não foi possível abrir o processo no Projudi.'}

        soup = BeautifulSoup(resposta.text, 'html.parser')
        parser = ProcessoParser(resposta.text)
        try:
            partes = parser.extrair_partes(soup)
        except Exception:
            partes = []

        # O parser às vezes gruda o rótulo "Processo(s) Distribuído(s)"
        # no nome da parte. Limpa para permitir o match nas intimações.
        for parte in partes:
            nome = (parte.get('nome') or '')
            nome = re.split(
                r'Processo\(s\)\s*Distribu', nome, flags=re.I
            )[0].strip()
            parte['nome'] = nome

        movs = self._movimentacoes(soup)

        sentenca = self._sentenca(movs)
        recurso = self._recurso(movs, sentenca)
        recorrentes = self._partes_do_recurso(
            session, recurso, partes
        ) if recurso else set()

        resultado_partes = []
        for parte in partes:
            nome = (parte.get('nome') or '').strip()
            if not nome:
                continue
            intima = self._intimacao_da_parte(movs, nome, sentenca)
            status, info = self._status_parte(
                parte, intima, recurso, recorrentes, movs
            )
            resultado_partes.append({
                'nome': nome,
                'papel': parte.get('papel') or parte.get('tipo') or '',
                'status': status,
                **info,
            })

        if not resultado_partes:
            return {
                'erro': 'Não foi possível extrair as partes do processo.',
                'processo': localizado['numero'],
                'url': localizado['url'],
            }

        status_geral = self._status_geral(resultado_partes)
        return {
            'processo': localizado['numero'],
            'numero_interno': localizado['numero_interno'],
            'url': localizado['url'],
            'sentenca': sentenca,
            'recurso': recurso,
            'partes': resultado_partes,
            'status_geral': status_geral,
        }

    def _movimentacoes(self, soup):
        movs = []
        for tr in soup.find_all('tr'):
            tds = tr.find_all('td', recursive=False)
            if not tds:
                continue
            primeira = tds[0].get_text(' ', strip=True)
            match = re.match(r'\s*(\d+)\b', primeira)
            if not match:
                continue
            evento = match.group(1)
            texto = ' '.join(
                td.get_text(' ', strip=True) for td in tds
            )
            data = _data_no_texto(texto)
            links = [
                a.get('href') for a in tr.find_all('a', href=True)
                if 'DownloadArquivo' in a.get('href', '')
            ]
            movs.append({
                'evento': evento,
                'texto': texto,
                'data': data,
                'links': links,
            })
        movs.sort(key=lambda m: int(m['evento']))
        return movs

    def _sentenca(self, movs):
        candidatas = [
            mov for mov in movs
            if any(k in _norm(mov['texto']) for k in (
                'JULGADA', 'SENTENCA', 'HOMOLOG', 'ACORDAO',
            ))
            and not any(k in _norm(mov['texto']) for k in (
                'INTIMA', 'DISPONIBILIZ',
            ))
        ]
        return candidatas[-1] if candidatas else None

    def _recurso(self, movs, sentenca):
        if not sentenca:
            return None
        depois = [
            mov for mov in movs
            if int(mov['evento']) > int(sentenca['evento'])
            and any(k in _norm(mov['texto']) for k in (
                'RECURSO INOMINADO', 'APELACAO', 'RECURSO',
            ))
            and not any(k in _norm(mov['texto']) for k in (
                'INTIMA', 'DISPONIBILIZ',
            ))
        ]
        return depois[0] if depois else None

    def _partes_do_recurso(self, session, recurso, partes):
        """Tenta descobrir o recorrente pelo texto do documento do recurso."""
        if not recurso or not recurso.get('links'):
            return set()
        try:
            link = recurso['links'][0]
            if link.startswith('/'):
                link = 'https://projudi.tjba.jus.br' + link
            resposta = session.get(link, timeout=25)
            texto = BeautifulSoup(
                resposta.text, 'html.parser'
            ).get_text(' ', strip=True)
            texto_norm = _norm_nome(texto)
            return {
                parte['nome']
                for parte in partes
                if _norm_nome(parte.get('nome')) in texto_norm
            }
        except Exception:
            return set()

    def _intimacao_da_parte(self, movs, nome_parte, sentenca):
        if not sentenca:
            return None
        alvo = _norm_nome(nome_parte)
        if not alvo:
            return None
        candidatas = []
        for mov in movs:
            if int(mov['evento']) < int(sentenca['evento']):
                continue
            up = _norm(mov['texto'])
            if not any(k in up for k in ('INTIMA', 'DISPONIBILIZ')):
                continue
            if alvo not in _norm_nome(mov['texto']):
                continue
            data_base = _data_disponibilizacao(mov['texto']) or mov['data']
            if not data_base:
                continue
            if 'AGUARDANDO DISPONIBILIZACAO' in up:
                # "Juntada de intimação aguardando DJEN" ≠ publicação no DJEN.
                meio = 'intimacao'
            elif 'DISPONIBILIZACAO NO DIARIO' in up or 'DJEN' in up:
                meio = 'eletronico'
            else:
                meio = 'intimacao'
            candidatas.append({
                'evento': mov['evento'],
                'data': data_base,
                'meio': meio,
                'texto': mov['texto'][:500],
            })
        if not candidatas:
            return None
        # Prefere a disponibilização no DJEN (marco legal) em vez da
        # juntada da intimação, que é anterior.
        eletronicas = [
            c for c in candidatas if c['meio'] == 'eletronico'
        ]
        lista = eletronicas or candidatas
        lista.sort(key=lambda c: c['data'])
        return lista[0]

    def _status_parte(self, parte, intima, recurso, recorrentes, movs):
        nome = parte.get('nome') or ''
        if nome in recorrentes:
            return 'RECURSO PENDENTE', {
                'evento_recurso': recurso['evento'] if recurso else '',
                'observacao': 'Recurso interposto por esta parte.',
            }

        # Renúncia/dispensa expressa.
        alvo = _norm_nome(nome)
        for mov in movs:
            up = _norm(mov['texto'])
            if (('RENUNCIA' in up or 'DISPENSA' in up)
                    and 'RECURSO' in up
                    and alvo in _norm_nome(mov['texto'])):
                return 'RENÚNCIA/DISPENSA', {
                    'evento_renuncia': mov['evento'],
                    'observacao': mov['texto'][:250],
                }

        if not intima:
            return 'INTIMAÇÃO NÃO LOCALIZADA', {}

        try:
            prazo = self.cumprimento.contar_prazo_por_fluxo(
                intima['meio'], intima['data'], 10,
                modo='uteis', tenant=getattr(self.user, 'tenant', None),
            )
        except Exception as exc:
            return 'ERRO NO PRAZO', {'observacao': str(exc)}

        info = {
            'evento_intimacao': intima['evento'],
            'data_intimacao': intima['data'],
            'ultimo_dia': prazo.ultimo_dia,
            'decurso': prazo.data_decurso,
            'meio': intima['meio'],
        }
        if prazo.data_decurso <= date.today():
            return 'TRANSITADO', info
        return 'PRAZO EM CURSO', info

    def _status_geral(self, partes):
        status = {p['status'] for p in partes}
        if status <= {'TRANSITADO', 'RENÚNCIA/DISPENSA'}:
            return 'TRANSITADO'
        return 'NÃO TRANSITADO'
