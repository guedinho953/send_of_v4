"""ComunicacaoTracker — Emparelhamento de comunicações processuais.

Acompanha o ciclo de vida de cada comunicação: comando judicial → expedição → leitura.

Funções:
  1. PRE-CHECK: Dado um processo + ato + parte, verifica se já existe
     comunicação expedida pendente ou concluída (evita duplicidade).
  2. POST-TRACK: Dado um CumprimentoRecord, monitora se a comunicação
     gerou retorno (lida, devolvida, cumprida).
  3. Emparelha expedidas com lidas/devolvidas usando dados do
     ProcessoParser + CommunicationTracking existente.

VISÃO FUTURA (proposta registrada em 2026-08-06 — ainda NÃO implementada):
  - FISCALIZAR PRAZOS: usar o emparelhamento expedida→lida para calcular
    se o prazo da comunicação foi respeitado (data de expedição → data de
    leitura/retorno) e alertar comunicações com prazo vencido sem retorno.
  - FISCALIZAR CUMPRIMENTOS: para cada comunicação expedida, verificar se
    o comando judicial associado foi cumprido (retorno lido/cumprido x
    pendente/vencido), alimentando o dashboard de "cumprimentos aguardando".
  - CONTEXTO DE EVENTOS PASSADOS PARA CUMPRIR O EVENTO ATUAL: ao executar
    uma movimentação, o tracker pode fornecer os EVENTOS ANTERIORES do
    processo (ex.: citação/AR/audiência de eventos passados) como contexto
    para decidir e preencher o ato atual — p. ex., o número do evento que
    originou o prazo, quem já foi intimado, qual meio funcionou antes.
    Isso viabiliza despachos que fazem remissão a atos anteriores (RAG
    contextual via `referenced_event_obj`).
  Como fazer depois: expor os dados já emparelhados (_expedidas/_lidas/
  _pendentes com data_obj) via métodos de consulta (ex.: listar_expedidas
  sem retorno há mais de N dias, obter_evento_por_tipo(tipo, parte)) e
  criar uma view/endpoint de fiscalização que consome essas consultas.
  Nada disso existe ainda — por ora o tracker é usado apenas no pré-check
  de duplicidade antes do FluxoDecisor.
"""

import re
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple

from django.db.models import Q


# ── Mapeamento: categoria do ato → tipo de comunicação ──
CATEGORIA_PARA_TIPO = {
    'intimacao': 'intimacao',
    'citacao': 'citacao',
    'mandado': 'mandado',
    'certidao': 'certidao',
    'oficio': 'oficio',
    'ar': 'ar',
}

# ── Situações que indicam comunicação CONCLUÍDA ──
SITUACOES_CONCLUIDA = {
    'lida',
    'devolvida_sem_leitura',
    'ar_juntado',
    'mandado_devolvido',
    'mandado_assinado',
    'mandado_disponivel',
    'realizada',
}

# ── Situações que indicam comunicação PENDENTE ──
SITUACOES_PENDENTE = {
    'expedida',
    'mandado_solicitado',
}


class ComunicacaoTracker:
    """Rastreia o estado das comunicações de um processo.

    Usa o histórico de movimentações (do Projudi ou do banco) para
    determinar se um ato já foi cumprido e se o resultado já retornou.
    """

    def __init__(self, movimentacoes: List[Dict]):
        """
        Args:
            movimentacoes: lista de dicts do ProcessoParser.extrair_movimentacoes()
                           ou do Movement.objects.filter(process=proc).values()
        """
        self._movs = movimentacoes
        self._expedidas: List[Dict] = []
        self._lidas: List[Dict] = []
        self._pendentes: List[Dict] = []
        self._processar()

    # =================================================================
    # PROCESSAMENTO INICIAL
    # =================================================================
    def _processar(self):
        """Classifica cada movimentação como expedida, lida ou outra."""
        from processes.movimentacoes_service import situacao_comunicacao, tipo_comunicacao

        self._expedidas = []
        self._lidas = []
        self._pendentes = []

        for mov in self._movs:
            ato = mov.get('ato_normalizado', '') or mov.get('act_description', '')
            situacao = situacao_comunicacao(ato)

            if situacao == 'expedida':
                self._expedidas.append(self._enriquecer(mov, situacao))
            elif situacao in SITUACOES_CONCLUIDA:
                self._lidas.append(self._enriquecer(mov, situacao))
            elif situacao in SITUACOES_PENDENTE:
                pend = self._enriquecer(mov, situacao)
                self._pendentes.append(pend)
                # Pendentes também entram como expedidas para pareamento
                self._expedidas.append(pend)

    def _enriquecer(self, mov: Dict, situacao: str) -> Dict:
        """Adiciona metadados calculados a uma movimentação."""
        from processes.movimentacoes_service import tipo_comunicacao, meio_comunicacao

        ato = mov.get('ato_normalizado', '') or mov.get('act_description', '')
        return {
            'evento': mov.get('evento', ''),
            'ato': mov.get('ato', '') or mov.get('act_description', ''),
            'data_texto': mov.get('data_texto', ''),
            'data_obj': mov.get('data_obj', None),
            'situacao': situacao,
            'tipo': tipo_comunicacao(ato) or mov.get('category', ''),
            'meio': meio_comunicacao(ato) or mov.get('communication_means', ''),
            'destinatario': self._extrair_destinatario(mov),
            'observacao': mov.get('observacao', ''),
            'evento_referenciado': mov.get('evento_referenciado', ''),
        }

    def _extrair_destinatario(self, mov: Dict) -> str:
        """Extrai o destinatário da movimentação."""
        dest = mov.get('destinatario', '')
        if isinstance(dest, dict):
            return dest.get('nome', str(dest))
        if isinstance(dest, list):
            return ', '.join(str(d) for d in dest)
        return str(dest) if dest else ''

    # =================================================================
    # PRE-CHECK: Já existe comunicação para este ato + parte?
    # =================================================================
    def ja_expedida(self, tipo_ato: str, parte_nome: str,
                    command_snippet: str = '') -> Dict:
        """Verifica se já existe comunicação expedida compatível.

        Args:
            tipo_ato: tipo do ato ('intimacao', 'citacao', 'certidao', etc.)
            parte_nome: nome da parte destinatária
            command_snippet: trecho do comando para fuzzy match

        Returns:
            Dict com:
              - existe: True/False
              - evento: número do evento se existir
              - situacao: 'expedida', 'lida', 'pendente' ou None
              - detalhes: dict com info da comunicação existente
              - mensagem: explicação legível
        """
        tipo_busca = CATEGORIA_PARA_TIPO.get(tipo_ato, tipo_ato)

        # Busca em expedidas
        for exp in self._expedidas:
            if self._match(exp, tipo_busca, parte_nome, command_snippet):
                # Verifica se já foi lida/devolvida
                lida = self._buscar_lida(exp)
                if lida:
                    return {
                        'existe': True,
                        'evento': exp['evento'],
                        'situacao': lida['situacao'],
                        'detalhes': lida,
                        'mensagem': (
                            f"Comunicação já realizada: {lida['situacao']} "
                            f"(evento {exp['evento']} → evento {lida['evento']})."
                        ),
                    }
                return {
                    'existe': True,
                    'evento': exp['evento'],
                    'situacao': exp['situacao'],
                    'detalhes': exp,
                    'mensagem': (
                        f"Comunicação já {'iniciada' if exp['situacao'] != 'expedida' else 'expedida'} "
                        f"para {parte_nome} "
                        f"(evento {exp['evento']}). Aguardando retorno."
                    ),
                }

        # Busca em pendentes
        for pen in self._pendentes:
            if self._match(pen, tipo_busca, parte_nome, command_snippet):
                return {
                    'existe': True,
                    'evento': pen['evento'],
                    'situacao': pen['situacao'],
                    'detalhes': pen,
                    'mensagem': (
                        f"Comunicação pendente: {pen['situacao']} "
                        f"(evento {pen['evento']})."
                    ),
                }

        return {
            'existe': False,
            'evento': None,
            'situacao': None,
            'detalhes': None,
            'mensagem': f"Nenhuma comunicação encontrada para {parte_nome} ({tipo_ato}).",
        }

    def _match(self, mov: Dict, tipo_busca: str, parte_nome: str,
               command_snippet: str = '') -> bool:
        """Verifica se uma movimentação corresponde ao ato + parte."""
        # 1. Tipo
        if mov.get('tipo') != tipo_busca:
            # Fallback: busca por palavra no ato
            if tipo_busca not in mov.get('ato', '').lower():
                return False

        # 2. Destinatário
        dest_mov = (mov.get('destinatario') or '').lower().strip()
        parte_busca = parte_nome.lower().strip()
        if dest_mov and parte_busca:
            if dest_mov not in parte_busca and parte_busca not in dest_mov:
                return False

        return True

    def _buscar_lida(self, expedida: Dict) -> Optional[Dict]:
        """Busca a movimentação de retorno (lida/devolvida) para uma expedida."""
        for lida in self._lidas:
            # Match por evento referenciado
            if lida.get('evento_referenciado') == expedida['evento']:
                return lida
            # Match por destinatário + tipo
            if (lida.get('tipo') == expedida.get('tipo')
                    and lida.get('destinatario') == expedida.get('destinatario')
                    and lida.get('data_obj') == expedida.get('data_obj')):
                return lida
        return None

    # =================================================================
    # POST-CHECK: Após executar, acompanhar resultado
    # =================================================================
    def rastrear_resultado(self, processo_numero: str, ato_verb: str,
                           parte_nome: str, fluxo: str) -> Dict:
        """Após executar um cumprimento, verifica se o resultado apareceu.

        Varre as movimentações mais recentes e tenta encontrar uma
        que corresponda ao ato executado.

        Args:
            processo_numero: número do processo
            ato_verb: verbo do ato executado (ex: 'intime-se')
            parte_nome: nome da parte destinatária
            fluxo: fluxo utilizado (ar, mandado, eletronico, etc.)

        Returns:
            Dict com status do rastreio:
              - encontrou: True/False
              - situacao: 'lida', 'devolvida', 'pendente', None
              - evento: número do evento de retorno
              - mensagem: explicação
        """
        from processes.movimentacoes_service import situacao_comunicacao

        # Filtra movimentações recentes que parecem ser resultado
        resultados_possiveis = []
        for mov in self._movs:
            ato = mov.get('ato_normalizado', '') or mov.get('act_description', '')
            situacao = situacao_comunicacao(ato)
            if not situacao:
                continue

            dest = self._extrair_destinatario(mov)
            parte_match = not parte_nome or (
                parte_nome.lower().strip() in dest.lower()
                or dest.lower().strip() in parte_nome.lower()
            )

            if parte_match and situacao in SITUACOES_CONCLUIDA:
                resultados_possiveis.append({
                    'evento': mov.get('evento', ''),
                    'ato': mov.get('ato', '') or mov.get('act_description', ''),
                    'situacao': situacao,
                    'destinatario': dest,
                    'data_texto': mov.get('data_texto', ''),
                })

        if resultados_possiveis:
            # Pega o mais recente
            mr = resultados_possiveis[-1]
            return {
                'encontrou': True,
                'situacao': mr['situacao'],
                'evento': mr['evento'],
                'mensagem': (
                    f"Resultado encontrado: {mr['situacao']} "
                    f"(evento {mr['evento']})."
                ),
                'detalhes': mr,
            }

        return {
            'encontrou': False,
            'situacao': 'pendente',
            'evento': None,
            'mensagem': 'Nenhum resultado encontrado ainda. '
                        'Comunicação ainda pendente.',
            'detalhes': None,
        }

    # =================================================================
    # PAIRING COMPLETO (expedidas × lidas)
    # =================================================================
    def parear_comunicacoes(self) -> List[Dict]:
        """Retorna todas as comunicações do processo emparelhadas.

        Similar ao _rastrear_comunicacoes do MovimentacoesService,
        mas sem dependência de pandas.
        """
        pares = []

        for exp in self._expedidas:
            lida = self._buscar_lida(exp)
            par = {
                'expedicao': {
                    'evento': exp['evento'],
                    'ato': exp['ato'],
                    'data': exp['data_texto'],
                    'destinatario': exp['destinatario'],
                    'tipo': exp['tipo'],
                    'meio': exp['meio'],
                },
                'retorno': None,
                'status': 'pendente',
            }
            if lida:
                par['retorno'] = {
                    'evento': lida['evento'],
                    'ato': lida['ato'],
                    'data': lida['data_texto'],
                    'situacao': lida['situacao'],
                }
                par['status'] = lida['situacao']

            pares.append(par)

        # Expedidas sem retorno
        return pares

    def resumo(self) -> Dict:
        """Resumo das comunicações do processo."""
        pares = self.parear_comunicacoes()
        return {
            'total_expedidas': len(self._expedidas),
            'total_lidas': len(self._lidas),
            'total_pendentes': len(self._pendentes),
            'com_retorno': sum(1 for p in pares if p['retorno']),
            'sem_retorno': sum(1 for p in pares if not p['retorno']),
            'pares': pares,
        }

    @staticmethod
    def from_processo_parser(html: str) -> 'ComunicacaoTracker':
        """Cria tracker a partir do HTML do DadosProcesso do Projudi."""
        from projudiProcessNavigator import ProcessoParser
        parser = ProcessoParser(html)
        movimentacoes, _ = parser.extrair_movimentacoes()
        return ComunicacaoTracker(movimentacoes)

    @staticmethod
    def from_movement_queryset(qs) -> 'ComunicacaoTracker':
        """Cria tracker a partir de uma QuerySet de Movement."""
        movs = list(qs.values(
            'event_number', 'act_description', 'act_normalized',
            'act_date', 'category', 'communication_status',
            'communication_means', 'recipient', 'observation',
            'referenced_event',
        ))
        normalizadas = []
        for m in movs:
            normalizadas.append({
                'evento': m.get('event_number', ''),
                'ato': m.get('act_description', ''),
                'ato_normalizado': m.get('act_normalized', '')
                                   or m.get('act_description', '').lower(),
                'data_texto': str(m.get('act_date', '')),
                'data_obj': m.get('act_date'),
                'category': m.get('category', ''),
                'communication_status': m.get('communication_status', ''),
                'communication_means': m.get('communication_means', ''),
                'destinatario': m.get('recipient', ''),
                'observacao': m.get('observation', ''),
                'evento_referenciado': m.get('referenced_event', ''),
            })
        return ComunicacaoTracker(normalizadas)
