"""Certidão de decurso do prazo de pagamento voluntário (15 dias)."""
import re

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

    def analisar(self, numero, evento, parte_nome='', dias=15):
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
        if not evento.isdigit():
            return {'erro': 'Informe o evento do despacho.'}
        despacho = next(
            (m for m in movs if m['evento'] == evento), None
        )
        if not despacho:
            return {'erro': f'Evento {evento} não encontrado no processo.'}

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
            'despacho_texto': despacho['texto'][:500],
            'executado': parte['nome'],
            'parte_papel': parte.get('papel') or '',
            'evento_intimacao': intima['evento'],
            'data_intimacao': intima['data'],
            'meio': intima['meio'],
            'meio_label': (
                'DJEN / domicílio eletrônico'
                if intima['meio'] == 'eletronico'
                else 'Intimação'
            ),
            'dias': dias,
            'ultimo_dia': prazo.ultimo_dia,
            'data_decurso': prazo.data_decurso,
        }

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
            up = _norm(mov['texto'])
            if not any(k in up for k in ('INTIMA', 'DISPONIBILIZ')):
                continue
            if alvo not in _nome_compacto(mov['texto']):
                continue
            data = _data_disponibilizacao(mov['texto']) or mov['data']
            if not data:
                continue
            if 'AGUARDANDO DISPONIBILIZACAO' in up:
                meio = 'intimacao'
            elif 'DISPONIBILIZACAO NO DIARIO' in up or 'DJEN' in up:
                meio = 'eletronico'
            else:
                meio = 'intimacao'

            # A intimação correta é a que referencia o próprio despacho.
            # Ex.: evento 84 referencia "Proferido despacho de mero
            # expediente"; o evento 80 referencia "Transitado em Julgado"
            # e não deve ser usado para o prazo de pagamento.
            score = 0
            if descricao_despacho and descricao_despacho in up:
                score += 100
            elif 'REFERENTE AO EVENTO' in up and descricao_despacho:
                score -= 100
            if meio == 'eletronico':
                score += 50

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
