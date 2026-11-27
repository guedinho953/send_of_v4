"""Certidão de decurso do prazo de pagamento voluntário (15 dias)."""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from base.utils import normalize_process_number
from projudiProcessNavigator import ProcessoParser
from .cumprimento_service import CumprimentoService
from .peticao_service import _nome_compacto, _norm
from .processo_lookup import localizar_processo
from .transito_julgado_service import (
    TransitoJulgadoService, _data_disponibilizacao,
)


class DecursoPagamentoService:
    def __init__(self, user):
        self.user = user

    def analisar(self, numero, evento='', parte_nome='', dias=15,
                 evento_requerimento=''):
        digitos = normalize_process_number(numero)
        if len(digitos) < 15:
            return {'erro': 'Número de processo inválido.'}
        digitos = digitos.zfill(20)
        localizado = localizar_processo(self.user, digitos)
        if not localizado:
            return {'erro': 'Processo não localizado no Projudi.'}

        session = TransitoJulgadoService(self.user)._sessao()
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
        for parte in partes:
            parte['nome'] = re.split(
                r'Processo\(s\)\s*Distribu', parte.get('nome') or '',
                flags=re.I,
            )[0].strip()

        movs = TransitoJulgadoService(self.user)._movimentacoes(soup)
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
                (m for m in movs if m['evento'] == evento), None
            )
            if not despacho:
                return {
                    'erro': (
                        f'Evento {evento} não encontrado. Confira o número '
                        'e informe novamente.'
                    )
                }
        else:
            despacho = self._localizar_despacho_pagamento(session, movs)
            if not despacho:
                return {
                    'erro': (
                        'Não foi possível localizar automaticamente o '
                        'despacho que determina o pagamento em 15 dias. '
                        'Informe o evento do despacho manualmente.'
                    )
                }
            evento = despacho['evento']
            despacho_auto = True

        evento_requerimento = str(evento_requerimento or '').strip()
        if evento_requerimento:
            if not evento_requerimento.isdigit():
                return {
                    'erro': (
                        'Evento do requerimento inválido. Informe apenas '
                        'o número do evento.'
                    )
                }
            requerimento = next(
                (m for m in movs
                 if m['evento'] == evento_requerimento),
                None,
            )
            if not requerimento:
                return {
                    'erro': (
                        f'Evento {evento_requerimento} do requerimento não '
                        'encontrado.'
                    )
                }
        else:
            requerimento = self._localizar_requerimento(movs, evento)

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
                    if 'PROMOVIDO' in (p.get('papel') or '').upper()
                    or 'REU' in (p.get('papel') or '').upper()
                    or 'RÉU' in (p.get('papel') or '').upper()
                    or 'EXECUTADO' in (p.get('papel') or '').upper()
                ),
                partes[0] if partes else None,
            )
            if not parte:
                return {'erro': 'Não foi possível identificar a parte executada.'}

        alvo = _nome_compacto(parte['nome'])
        intima = self._intimacao(
            movs, evento, alvo,
            self._descricao_evento(despacho['texto']),
        )
        if not intima:
            return {
                'erro': (
                    'Não foi localizada a intimação do despacho para a '
                    'parte executada.'
                )
            }

        parte_autora = next(
            (
                p for p in partes
                if (p.get('tipo') or '').upper() in (
                    'EXEQUENTE', 'PROMOVENTE',
                )
                or 'PROMOVENTE' in (p.get('papel') or '').upper()
            ),
            None,
        )
        canais_autora = []
        if parte_autora:
            if parte_autora.get('domicilio_cnj'):
                canais_autora.append('DJEN')
            if parte_autora.get('recebe_intimacao_email'):
                canais_autora.append('e-mail')
            if parte_autora.get('tem_advogado'):
                canais_autora.append('advogado')
        canal_autora_eletronico = bool(canais_autora)

        try:
            prazo = CumprimentoService(self.user).contar_prazo_por_fluxo(
                intima['meio'], intima['data'], dias,
                modo='uteis', tenant=getattr(self.user, 'tenant', None),
            )
        except Exception as exc:
            return {'erro': f'Erro no cálculo do prazo: {exc}'}

        return {
            'processo': localizado['numero'],
            'numero_interno': localizado['numero_interno'],
            'url': localizado['url'],
            'evento_despacho': evento,
            'data_despacho': despacho.get('data'),
            'despacho_texto': despacho['texto'][:500],
            'despacho_auto': despacho_auto,
            'despacho_trecho': (despacho.get('trecho') or '')[:500],
            'evento_requerimento': (
                requerimento['evento'] if requerimento else ''
            ),
            'data_requerimento': (
                requerimento.get('data') if requerimento else None
            ),
            'executado': parte['nome'],
            'parte_papel': parte.get('papel') or '',
            'parte_autora': (
                parte_autora['nome'] if parte_autora else 'parte autora'
            ),
            'parte_autora_papel': (
                parte_autora.get('papel') if parte_autora else ''
            ) or 'PROMOVENTE',
            'parte_autora_canais': canais_autora,
            'parte_autora_canal_eletronico': canal_autora_eletronico,
            'evento_intimacao': intima['evento'],
            'data_intimacao': intima['data'],
            'meio': intima['meio'],
            'meio_label': (
                'DJEN / domicílio eletrônico'
                if intima['meio'] == 'eletronico'
                else 'Intimação'
            ),
            'dias': dias,
            'data_inicio': prazo.data_inicio,
            'ultimo_dia': prazo.ultimo_dia,
            'data_decurso': prazo.data_decurso,
            'prazo_info': prazo.to_dict(),
        }

    def _localizar_despacho_pagamento(self, session, movs):
        """Percorre os eventos de cima para baixo e acha o despacho.

        A página do Projudi exibe os eventos mais recentes no topo. A busca
        segue essa ordem, baixando o documento de cada ato decisório até
        encontrar a ordem de pagamento em 15 dias.
        """
        termos_decisao = (
            'DESPACHO', 'DECISAO', 'SENTENCA', 'ACORDAO',
            'JULGADA', 'JULGADO', 'HOMOLOG',
        )
        candidatos = []
        for mov in movs:
            if not mov.get('links'):
                continue
            up = _norm(mov['texto'])
            # Não confunde petições/juntadas que apenas citam o despacho
            # com o próprio ato decisório.
            if any(k in up for k in (
                'JUNTADA DE PETICAO', 'PETICAO', 'REQUERIMENTO',
                'IMPUGNACAO', 'CONTRARRAZOES', 'RECURSO',
                'MANIFESTACAO', 'MEMORIAIS',
            )):
                continue
            if not any(t in up for t in termos_decisao):
                continue
            if 'INTIMA' in up or 'DISPONIBILIZ' in up:
                continue
            candidatos.append(mov)

        # Eventos mais recentes primeiro, como aparecem na tela.
        candidatos.sort(key=lambda m: int(m['evento']), reverse=True)

        for mov in candidatos[:30]:
            for link in mov.get('links') or []:
                texto = self._ler_documento(session, link)
                if not texto:
                    continue
                trecho = self._trecho_pagamento(texto)
                if trecho:
                    resultado = dict(mov)
                    resultado['trecho'] = trecho
                    resultado['documento_texto'] = texto
                    return resultado
        return None

    @staticmethod
    def _ler_documento(session, link):
        """Baixa e extrai o texto de um documento HTML ou PDF."""
        if not link:
            return ''
        url = urljoin('https://projudi.tjba.jus.br', link)
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
                resposta.encoding or 'latin-1', errors='ignore'
            )
            return BeautifulSoup(html, 'html.parser').get_text(
                '\n', strip=True
            )
        except Exception:
            return ''

    @staticmethod
    def _trecho_pagamento(texto):
        """Retorna o trecho que caracteriza a ordem de pagamento em 15 dias."""
        up = _norm(texto)
        if not up:
            return ''
        if not any(k in up for k in (
            'PAGAMENTO', 'PAGAR', 'ART. 523', 'CUMPRIR', 'CUMPRA',
        )):
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

    @staticmethod
    def _localizar_requerimento(movs, evento_despacho):
        """Localiza a petição/requerimento que antecedeu o despacho."""
        candidatos = []
        for mov in movs:
            try:
                if int(mov['evento']) >= int(evento_despacho):
                    continue
            except (TypeError, ValueError):
                continue
            up = _norm(mov['texto'])
            inicio = _norm(re.sub(r'^\s*\d+\s*', '', mov['texto']))
            if not re.match(
                    r'JUNTADA DE (PETICAO|REQUERIMENTO)\b', inicio):
                continue
            if 'PETICAO' not in inicio and 'REQUERIMENTO' not in inicio:
                continue
            if not any(k in up for k in (
                'EXECUCAO', 'CUMPRIMENTO', 'PAGAMENTO', 'REQUERIMENTO',
            )):
                continue
            if any(k in up for k in (
                'INTIMA', 'DISPONIBILIZ', 'CERTIDAO', 'DESPACHO',
                'DECISAO', 'JULGADA', 'JULGADO',
            )):
                continue
            candidatos.append(mov)
        if not candidatos:
            return None
        candidatos.sort(key=lambda m: int(m['evento']))
        return candidatos[-1]

    @staticmethod
    def _descricao_evento(texto):
        """Extrai a descrição do evento, sem número, data e assinatura."""
        texto = re.sub(r'^\s*\d+\s*', '', texto or '')
        texto = re.split(r'\b\d{2}/\d{2}/\d{2,4}\b', texto)[0]
        texto = re.split(r'\s+Arquivos:', texto, flags=re.I)[0]
        return _norm(texto).strip()

    def _intimacao(self, movs, evento, alvo, descricao_despacho=''):
        candidatas = []
        for mov in movs:
            if int(mov['evento']) <= int(evento):
                continue
            # O HTML do Projudi repete os movimentos anteriores dentro do
            # texto do movimento atual. Para escolher a intimação é preciso
            # olhar só a linha do próprio evento; caso contrário um evento
            # antigo aninhado pode "emprestar" a data/publicação e vencer.
            texto = re.split(
                r'\s+Movimentação sem arquivos\b',
                mov['texto'],
                maxsplit=1,
                flags=re.I,
            )[0]
            inicio = _norm(re.sub(r'^\s*\d+\s*', '', texto))
            if inicio.startswith(('DECORRIDO PRAZO', 'TERMINO DA CONTAGEM')):
                continue
            # A juntada é o ato/documento, não a publicação da intimação.
            # Mantemos como fallback para processos antigos que só têm a
            # juntada, mas com pontuação bem menor que o DJEN.
            eh_juntada = inicio.startswith('JUNTADA DE INTIMACAO')
            up = _norm(texto)
            if not any(k in up for k in ('INTIMA', 'DISPONIBILIZ')):
                continue
            if alvo not in _nome_compacto(texto):
                continue
            data = _data_disponibilizacao(texto) or mov['data']
            if not data:
                continue
            if eh_juntada:
                meio = 'intimacao'
            elif 'AGUARDANDO DISPONIBILIZACAO' in up:
                meio = 'intimacao'
            elif 'DISPONIBILIZACAO NO DIARIO' in up or 'DJEN' in up:
                meio = 'eletronico'
            else:
                meio = 'intimacao'

            # A intimação correta é a publicação eletrônica quando existir.
            # Ex.: no processo 694, evento 77 é DJEN de BANCO BRADESCO;
            # no 2019, evento 84 é DJEN do despacho 78.
            score = 0
            if descricao_despacho and descricao_despacho in up:
                score += 100
            elif 'REFERENTE AO EVENTO' in up and descricao_despacho:
                score -= 100
            if meio == 'eletronico':
                score += 200
            if 'DISPONIBILIZACAO NO DIARIO' in up:
                # Publicação efetiva tem prioridade sobre a expedição.
                score += 200
            if eh_juntada:
                score -= 300

            candidatas.append({
                'evento': mov['evento'],
                'data': data,
                'meio': meio,
                'score': score,
            })
        if not candidatas:
            return None
        candidatas.sort(key=lambda c: (-c['score'], c['data']))
        return candidatas[0]
