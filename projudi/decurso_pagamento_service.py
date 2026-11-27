"""Certidão de decurso do prazo de pagamento voluntário (15 dias).

O serviço localiza o despacho que determinou o pagamento em 15 dias, a
intimação desse despacho para o executado e calcula o decurso. A certidão
só deve ser gerada depois do decurso; antes disso, o sistema informa a data.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from projudiProcessNavigator import ProcessoParser
from projudi.cumprimento_service import CumprimentoService
from projudi.verificacao_inominado import data_djen, data_mov, evento_mov

URL_BASE = 'https://projudi.tjba.jus.br'
DIAS_PAGAMENTO = 15


def _norm(texto):
    import unicodedata
    texto = unicodedata.normalize('NFKD', str(texto or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', texto).strip().upper()


def _nome_compacto(texto):
    return re.sub(r'[^A-Z0-9]+', '', _norm(texto))


def _data_br(texto):
    m = re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b', str(texto or ''))
    if not m:
        return None
    dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if ano < 100:
        ano += 2000
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def _data_disponibilizacao(texto):
    m = re.search(
        r'disponibiliz[^\n]{0,120}?(\d{1,2}/\d{1,2}/\d{2,4})',
        str(texto or ''), re.I,
    )
    return _data_br(m.group(1)) if m else None


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


MEIO_LABEL = {
    'eletronico': 'DJEN / domicílio eletrônico',
    'advogado': 'Advogado constituído',
    'email': 'E-mail',
    'ar': 'AR / Correios',
    'mandado': 'Mandado',
    'intimacao': 'Intimação (meio não identificado)',
}


def _texto_mov(mov):
    return ' '.join(
        str(mov.get(k) or '') for k in
        ('ato', 'observacao', 'ato_normalizado', 'descricao')
    )


def _limpar_nome_parte(nome):
    nome = re.split(
        r'Processo\(s\)\s*Distribu', str(nome or ''), flags=re.I
    )[0]
    return re.sub(r'\s+', ' ', nome).strip(' -;,.')


def _descricao_evento(texto):
    """Descrição do evento, sem número, data e assinatura."""
    texto = re.sub(r'^\s*\d+\s*', '', texto or '')
    texto = re.split(r'\b\d{2}/\d{2}/\d{2,4}\b', texto)[0]
    texto = re.split(r'\s+Arquivos:', texto, flags=re.I)[0]
    return _norm(texto).strip()


class DecursoPagamentoService:
    def __init__(self, user):
        self.user = user

    # ─────────────────────────── sessão / processo ───────────────────────────
    def _sessao(self):
        from projudi.services import ProjudiService
        resultado = ProjudiService(self.user)._get_session_from_cookies()
        return resultado[0] if resultado else None

    def _resolver_url(self, processo, url=None):
        if url:
            return url

        from processes.models import Process
        from projudi.models import OficioRecord

        proc = Process.objects.filter(number=processo).first()
        if proc and proc.projudi_url:
            return proc.projudi_url

        oficio = (
            OficioRecord.objects
            .filter(numero_processo_cnj=processo)
            .exclude(processo='')
            .first()
        )
        if oficio:
            return (
                'https://projudi.tjba.jus.br/projudi/listagens/'
                f'DadosProcesso?numeroProcesso={oficio.processo}'
            )

        raise ValueError(
            'Não localizei a URL do processo. Informe --url com a URL '
            'DadosProcesso do Projudi.'
        )

    def _carregar(self, processo, url=None):
        session = self._sessao()
        if not session:
            raise ValueError(
                'Sessão do Projudi não disponível. Sincronize a sessão.'
            )

        url = self._resolver_url(processo, url)
        resposta = session.get(url, timeout=40)
        if resposta.status_code != 200 or 'expirou' in resposta.text.lower():
            raise ValueError(
                'Não foi possível abrir o processo ou a sessão expirou.'
            )

        soup = BeautifulSoup(resposta.text, 'html.parser')
        parser = ProcessoParser(resposta.text)
        try:
            partes = parser.extrair_partes(soup)
        except Exception:
            partes = []
        for parte in partes:
            parte['nome'] = _limpar_nome_parte(parte.get('nome'))
        partes = [p for p in partes if p.get('nome')]

        movs, _ = parser.extrair_movimentacoes()
        return session, url, partes, movs

    # ────────────────────────────── análise ─────────────────────────────────
    def analisar(self, numero, evento='', parte_nome='', url=None,
                 dias=DIAS_PAGAMENTO, hoje=None):
        try:
            session, url, partes, movs = self._carregar(numero, url)
        except ValueError as exc:
            return {'erro': str(exc)}

        if not movs:
            return {'erro': 'Nenhuma movimentação encontrada no processo.'}

        evento = str(evento or '').strip()
        despacho_auto = False
        if evento:
            if not evento.isdigit():
                return {
                    'erro': (
                        'Evento inválido. Informe apenas o número do evento '
                        'do despacho.'
                    )
                }
            despacho = next(
                (m for m in movs if str(m.get('evento')) == evento), None
            )
            if not despacho:
                return {
                    'erro': (
                        f'Evento {evento} não encontrado. Confira o número.'
                    )
                }
        else:
            despacho = self._localizar_despacho_pagamento(session, movs)
            if not despacho:
                return {
                    'erro': (
                        'Não localizei automaticamente o despacho que '
                        'determina o pagamento em 15 dias. Informe o evento '
                        'do despacho.'
                    )
                }
            evento = str(despacho.get('evento') or '')
            despacho_auto = True

        parte = None
        if parte_nome:
            alvo = _nome_compacto(parte_nome)
            parte = next(
                (p for p in partes if alvo in _nome_compacto(p['nome'])),
                None,
            )
            if not parte:
                return {'erro': 'Parte executada não encontrada.'}
        else:
            parte = next(
                (
                    p for p in partes
                    if any(k in _norm(p.get('papel') or p.get('tipo'))
                           for k in ('PROMOVIDO', 'REU', 'EXECUTADO'))
                ),
                partes[0] if partes else None,
            )
            if not parte:
                return {
                    'erro': 'Não foi possível identificar a parte executada.'
                }

        texto_despacho = _texto_mov(despacho)
        intima = self._intimacao(
            movs, evento, _nome_compacto(parte['nome']),
            _descricao_evento(texto_despacho),
        )
        if not intima:
            return {
                'erro': (
                    'Não localizei a intimação do despacho para a parte '
                    'executada.'
                )
            }

        try:
            prazo = CumprimentoService(self.user).contar_prazo_por_fluxo(
                intima['meio'], intima['data'], dias,
                modo='uteis', tenant=getattr(self.user, 'tenant', None),
            )
        except Exception as exc:
            return {'erro': f'Erro no cálculo do prazo: {exc}'}

        hoje = hoje or date.today()
        return {
            'processo': numero,
            'url': url,
            'partes': partes,
            'executado': parte['nome'],
            'parte_papel': parte.get('papel') or parte.get('tipo') or '',
            'evento_despacho': str(evento),
            'despacho_texto': texto_despacho[:500],
            'despacho_auto': despacho_auto,
            'despacho_trecho': (despacho.get('trecho') or '')[:500],
            'evento_intimacao': intima['evento'],
            'data_intimacao': intima['data'],
            'meio': intima['meio'],
            'meio_label': MEIO_LABEL.get(
                intima['meio'], intima['meio']),
            'dias': dias,
            'data_inicio': prazo.data_inicio,
            'ultimo_dia': prazo.ultimo_dia,
            'data_decurso': prazo.data_decurso,
            'prazo_info': prazo.to_dict(),
            'decorrido': hoje >= prazo.data_decurso,
            'hoje': hoje,
        }

    # ─────────────────────── despacho de pagamento ──────────────────────────
    def _localizar_despacho_pagamento(self, session, movs):
        termos_decisao = (
            'DESPACHO', 'DECISAO', 'SENTENCA', 'ACORDAO',
            'JULGADA', 'JULGADO', 'HOMOLOG',
        )
        candidatos = []
        for mov in movs:
            texto = _texto_mov(mov)
            up = _norm(texto)
            if any(k in up for k in (
                    'JUNTADA DE PETICAO', 'PETICAO', 'REQUERIMENTO',
                    'IMPUGNACAO', 'CONTRARRAZOES', 'RECURSO',
                    'MANIFESTACAO', 'MEMORIAIS')):
                continue
            if not any(t in up for t in termos_decisao):
                continue
            if 'INTIMA' in up or 'DISPONIBILIZ' in up:
                continue
            candidatos.append(mov)

        candidatos.sort(
            key=lambda m: int(m.get('evento') or 0), reverse=True)

        for mov in candidatos[:30]:
            texto = _texto_mov(mov)
            trecho = self._trecho_pagamento(texto)
            if trecho:
                resultado = dict(mov)
                resultado['trecho'] = trecho
                return resultado

            for doc in mov.get('documentos') or []:
                link = doc.get('url') if isinstance(doc, dict) else doc
                texto_doc = self._ler_documento(session, link)
                if not texto_doc:
                    continue
                trecho = self._trecho_pagamento(texto_doc)
                if trecho:
                    resultado = dict(mov)
                    resultado['trecho'] = trecho
                    resultado['documento_texto'] = texto_doc
                    return resultado
        return None

    @staticmethod
    def _ler_documento(session, link):
        if not link:
            return ''
        url = urljoin(URL_BASE, link)
        try:
            resposta = session.get(url, timeout=12)
            if resposta.status_code != 200:
                return ''
            ctype = (resposta.headers.get('content-type') or '').lower()
            if 'pdf' in ctype or 'original=true' in url.lower():
                import fitz
                pdf = fitz.open(stream=resposta.content, filetype='pdf')
                return '\n'.join(p.get_text() for p in pdf)
            html = resposta.content.decode(
                resposta.encoding or 'latin-1', errors='ignore')
            return BeautifulSoup(html, 'html.parser').get_text(
                '\n', strip=True)
        except Exception:
            return ''

    @staticmethod
    def _trecho_pagamento(texto):
        up = _norm(texto)
        if not up:
            return ''
        if not any(k in up for k in (
                'PAGAMENTO', 'PAGAR', 'ART. 523', 'CUMPRIR', 'CUMPRA')):
            return ''
        padroes = (
            r'INTIME.{0,400}EXECUTAD.{0,400}CUMPRIR.{0,400}\b15\b',
            r'EXECUTAD.{0,400}CUMPRIR.{0,400}\b15\b',
            r'CUMPRIR.{0,300}SENTENCA.{0,300}\b15\b',
            r'PAGAMENTO.{0,400}\b15\b.{0,80}(?:DIAS|QUINZE)',
            r'\b15\b.{0,80}(?:DIAS|QUINZE).{0,400}PAGAMENTO',
            r'PRAZO DE 15.{0,80}(?:DIAS|QUINZE).{0,300}CUMPRIR',
            r'ART\.?\s*523',
        )
        for padrao in padroes:
            m = re.search(padrao, up)
            if m:
                return m.group(0)[:500]
        return ''

    # ───────────────────────────── intimação ────────────────────────────────
    def _intimacao(self, movs, evento, alvo, descricao_despacho=''):
        candidatas = []
        for mov in movs:
            ev = evento_mov(mov)
            if ev <= int(evento):
                continue
            texto = _texto_mov(mov)
            up = _norm(texto)
            if not any(k in up for k in ('INTIMA', 'DISPONIBILIZ')):
                continue
            if alvo not in _nome_compacto(texto):
                continue

            data = (
                _data_disponibilizacao(texto)
                or data_djen(mov)
                or data_mov(mov)
            )
            if not data:
                continue

            if 'AGUARDANDO DISPONIBILIZACAO' in up:
                meio = 'intimacao'
            else:
                meio = _classificar_meio(texto)

            score = 0
            if descricao_despacho and descricao_despacho in up:
                score += 100
            elif 'REFERENTE AO EVENTO' in up and descricao_despacho:
                score -= 100
            if meio == 'eletronico':
                score += 50

            candidatas.append({
                'evento': str(ev),
                'data': data,
                'meio': meio,
                'score': score,
                'texto': texto[:500],
            })

        if not candidatas:
            return None
        candidatas.sort(key=lambda c: (-c['score'], c['data']))
        return candidatas[0]
