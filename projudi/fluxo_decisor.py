"""FluxoDecisor — Árvore de decisão para determinar qual fluxo executar.

A partir da classificação das partes (ParteClassifier) e dos dados brutos,
decide qual mecanismo do Projudi deve ser usado para cada ato + parte.

Fluxos disponíveis:
  movimentacao_simples  → Mov581 interno, sem destinatário (certidões, arquivamento)
  eletronico            → Domicílio Judicial Eletrônico (DJEN/CNJ)
  advogado              → Intimação ao advogado constituído (via DJEN)
  email                 → Envio por e-mail (com opt-in formal)
  email_condicional     → Envio por e-mail (sem opt-in, apenas atos não formais)
  ar                    → Aviso de Recebimento (Correios)
  mandado               → Mandado (oficial de justiça local)
  mandado_precatorio    → Mandado via carta precatória (outra comarca)
  edital                → Edital / publicação (endereço desconhecido)

Uso:
    decisor = FluxoDecisor(partes_raw, ato_data)
    resultado = decisor.decidir()
    # resultado['partes'][0]['fluxo']  → 'mandado'
    # resultado['partes'][0]['justificativa']  → 'Endereço em Paulo Afonso...'
"""

import re
from typing import List, Dict, Optional, Tuple


# ── Comarcas da Bahia próximas a Paulo Afonso (para referência) ──
COMARCA_PAULO_AFONSO = 'PAULO AFONSO'
COMARCAS_BA_VIZINHAS = {
    'PAULO AFONSO', 'GLORIA', 'RODELAS', 'ABARE',
    'MACURURE', 'CHORROCHO', 'JEREMOABO', 'CANUDOS',
    'EUCLIDES DA CUNHA', 'MONTE SANTO', 'CICERO DANTAS',
    'HELIOPOLIS', 'RIBEIRA DO AMPARO', 'ITAPICURU',
    'NOVA SOURE', 'CIPO', 'TUCANO', 'QUIJINGUE',
    'ARACI', 'BIRITINGA', 'SERRINHA',
}


class FluxoDecisor:
    """Árvore de decisão para selecionar o fluxo de cumprimento.

    ENTRADA:
      - partes_raw: lista de dicts (mesmo formato do ProcessoParser ou Django Party)
      - partes_classificadas: saída do ParteClassifier.classificar()['partes']
      - ato_data (opcional): dict com { 'tipo_ato', 'act_verb', 'destinatario_texto' }

    SAÍDA:
      {
        'partes': [
          {
            'nome', 'fluxo', 'justificativa',
            'endereco_analisado': {...},
            'canais_possiveis': [...],
          }
        ],
        'resumo': { 'fluxos': { 'mandado': [...], 'ar': [...], ... } }
      }
    """

    # Palavras em bairro/logradouro que indicam zona rural
    PADROES_ZONA_RURAL = re.compile(
        r'\b(?:zona\s*rural|povoado|distrito|fazenda|sítio|'
        r'sitio|roça|roca|assentamento|comunidade|'
        r'aldeia|quilombo|acampamento|chácara|chacara|'
        r'loteamento\s*rural|gleba|colônia|colonia)\b',
        re.I
    )

    # Atos que NÃO têm destinatário (sempre internos)
    ATOS_SEM_DESTINATARIO = {
        'publique-se', 'registre-se', 'anote-se',
    }

    # Atos que exigem citação/intimação pessoal (sempre precatória se fora da comarca)
    ATOS_COM_CITACAO_PESSOAL = {
        'citacao', 'citacao_pessoal', 'intimacao_pessoal',
    }

    # Atos que, mesmo sendo intimações, podem ser feitos por AR
    ATOS_SEM_PESSOALIDADE = {
        'intimacao', 'notificar', 'comunicar', 'intimar_ato_ordinario',
        'certificar', 'encaminhar',
    }

    # =================================================================
    # CONSTRUÇÃO
    # =================================================================
    def __init__(
        self,
        partes_raw: List[Dict],
        partes_classificadas: List[Dict],
        ato_data: Optional[Dict] = None,
    ):
        """
        Args:
            partes_raw: lista de dicts do ProcessoParser.extrair_partes()
                        ou Django Party.values()
            partes_classificadas: resultado['partes'] do ParteClassifier
            ato_data: opcional, dict com info do ato:
                      { 'tipo_ato': 'intimacao'|'citacao'|'certificar'|...,
                        'act_verb': 'intime-se'|'cite-se'|...,
                        'destinatario_texto': 'parte autora'|'executado'|... }
        """
        self._partes_raw = partes_raw
        self._partes_classif = partes_classificadas
        self._ato_data = ato_data or {}
        self._resultado: Optional[Dict] = None

    # =================================================================
    # PIPELINE PRINCIPAL
    # =================================================================
    def decidir(self) -> Dict:
        """Executa a árvore de decisão para cada parte."""
        # Se o CommandAnalyzer já classificou como movimentação, pula árvore
        if self._eh_movimentacao():
            return self._resposta_sem_destinatario()

        # Se o ato não tem destinatário, retorna fluxo simples
        if self._ato_sem_destinatario():
            return self._resposta_sem_destinatario()

        resultados_partes = []
        for p_cls in self._partes_classif:
            p_raw = self._encontrar_raw(p_cls['nome_normalizado'])
            decisao = self._decidir_para_parte(p_cls, p_raw)
            resultados_partes.append(decisao)

        self._resultado = self._montar_saida(resultados_partes)
        return self._resultado

    # =================================================================
    # ÁRVORE DE DECISÃO POR PARTE
    # =================================================================
    def _decidir_para_parte(self, p: Dict, p_raw: Optional[Dict]) -> Dict:
        """Aplica a árvore de decisão para uma parte específica."""
        nome = p['nome']
        justificativas = []
        endereco_info = {}

        # ── NÍVEL 1: DJEN? ──
        if p.get('domicilio_cnj'):
            return self._decisao(
                nome, 'eletronico',
                'Parte possui Domicílio Judicial Eletrônico CNJ — '
                'intimação eletrônica via DJEN.',
                endereco_info
            )

        # ── NÍVEL 2: Advogado? ──
        if p.get('tem_advogado'):
            return self._decisao(
                nome, 'advogado',
                'Parte possui advogado constituído — '
                'intimação ao advogado via DJEN.',
                endereco_info
            )

        # ── NÍVEL 3: Email? ──
        tipo_ato = self._ato_data.get('tipo_ato', '')
        if p.get('email_opt_in'):
            return self._decisao(
                nome, 'email',
                f"Parte optou por intimação por e-mail ({p.get('email')}).",
                endereco_info
            )
        if p.get('email_sem_optin') and self._ato_permite_email_condicional(tipo_ato):
            return self._decisao(
                nome, 'email_condicional',
                f"Parte possui e-mail ({p.get('email')}) sem opt-in formal, "
                f"mas o ato '{tipo_ato}' permite uso condicional.",
                endereco_info
            )

        # ── NÍVEL 4: Endereço? ──
        endereco_info = self._analisar_endereco(p, p_raw)
        endereco_valido = endereco_info.get('valido', False)

        if not endereco_valido:
            return self._decisao(
                nome, 'edital',
                'Endereço não disponível ou incompleto — '
                'necessária intimação por edital/publicação.',
                endereco_info
            )

        cidade = endereco_info.get('cidade', '').upper()
        uf = endereco_info.get('uf', '').upper()
        bairro = endereco_info.get('bairro', '')
        rural = endereco_info.get('zona_rural', False)
        exige_pessoal = tipo_ato in self.ATOS_COM_CITACAO_PESSOAL

        # ── NÍVEL 5: Localização ──
        # Regras gerais:
        #   Citação/intimação pessoal → sempre mandado (precatória se outro estado)
        #   Demais atos:
        #     Paulo Afonso → mandado
        #     BA (fora PA) → AR (mandado se rural)
        #     Outro estado → AR (precatória se rural)

        if cidade == COMARCA_PAULO_AFONSO:
            return self._decisao(
                nome, 'mandado',
                f'Endereço em {cidade}/{uf}'
                f'{f" (zona rural: {bairro})" if rural else ""} — '
                f'mandado por oficial de justiça local.',
                endereco_info
            )

        if exige_pessoal:
            return self._decisao(
                nome, 'mandado' if uf == 'BA' else 'mandado_precatorio',
                f'Endereço em {cidade}/{uf} — o ato "{tipo_ato}" exige '
                f'citação/intimação pessoal, portanto '
                f'{"mandado" if uf == "BA" else "carta precatória"} necessário.',
                endereco_info
            )

        # Atos sem pessoalidade (intimação, notificação, certificar, etc.)
        if uf == 'BA':
            if rural:
                return self._decisao(
                    nome, 'mandado',
                    f'Endereço em {cidade}/{uf} (zona rural: {bairro}) — '
                    f'AR pode não alcançar; mandado por oficial de justiça.',
                    endereco_info
                )
            return self._decisao(
                nome, 'ar',
                f'Endereço em {cidade}/{uf} — '
                f'Aviso de Recebimento (AR) pelos Correios.',
                endereco_info
            )

        # Outro estado
        if rural:
            return self._decisao(
                nome, 'mandado_precatorio',
                f'Endereço em {cidade}/{uf} (zona rural) — '
                f'fora da Bahia e em área rural; mandado via carta precatória.',
                endereco_info
            )

        return self._decisao(
            nome, 'ar',
            f'Endereço em {cidade}/{uf} — '
            f'Aviso de Recebimento (AR) pelos Correios. '
            f'Caso não localizado, converter para precatória.',
            endereco_info
        )

    # =================================================================
    # ANÁLISE DE ENDEREÇO
    # =================================================================
    def _analisar_endereco(self, p: Dict, p_raw: Optional[Dict]) -> Dict:
        """Extrai e analisa os componentes do endereço.

        Tenta obter dados estruturados primeiro do raw (parser),
        depois do campo textão 'endereco'/'address'.
        """
        info: Dict = {
            'cidade': None,
            'uf': None,
            'bairro': None,
            'logradouro': None,
            'cep': None,
            'zona_rural': False,
            'valido': False,
            'fonte': None,
        }

        # Tenta dados estruturados do parser (cidade, uf, bairro individuais)
        if p_raw:
            cidade = p_raw.get('cidade') or ''
            uf = p_raw.get('uf') or ''
            bairro = p_raw.get('bairro') or ''

            if cidade and uf:
                info['cidade'] = str(cidade).upper().strip()
                info['uf'] = str(uf).upper().strip()
                info['bairro'] = str(bairro).strip() if bairro else None
                info['logradouro'] = str(p_raw.get('logradouro', '')).strip() or None
                info['cep'] = str(p_raw.get('cep', '')).strip() or None
                info['fonte'] = 'parser_estruturado'
                info['valido'] = True
                info['zona_rural'] = self._detectar_zona_rural(
                    bairro, p_raw.get('logradouro', '')
                )
                return info

        # Fallback: tenta extrair do campo textão 'endereco' / 'address'
        endereco_texto = p.get('endereco', '') or ''
        if endereco_texto:
            parsed = self._parse_endereco_texto(endereco_texto)
            info.update(parsed)
            info['fonte'] = 'parse_texto'
            # Só considera válido se achou cidade+UF
            info['valido'] = bool(info['cidade'] and info['uf'])
            return info

        return info

    def _parse_endereco_texto(self, texto: str) -> Dict:
        """Tenta extrair cidade/UF/CEP/bairro de um endereço em texto livre.

        Exemplos de formatos:
          'Rua A, 100, Centro, Paulo Afonso - BA, CEP: 48600000'
          'Rua B, 200, Bairro X, Salvador - BA'
        """
        resultado = {
            'cidade': None, 'uf': None, 'bairro': None,
            'logradouro': None, 'cep': None, 'zona_rural': False,
        }

        # CEP
        cep_m = re.search(r'\b(\d{5}-?\d{3})\b', texto)
        if cep_m:
            resultado['cep'] = cep_m.group(1)

        # Cidade - UF (última ocorrência de "CIDADE - UF" antes do CEP)
        m = re.search(
            r'(?:,|\s)\s*([A-ZÀ-Ú][A-ZÀ-Ú\s]+?)\s*-\s*([A-Z]{2})\s*(?:,|\s|$|CEP)',
            texto, re.I
        )
        if m:
            resultado['cidade'] = m.group(1).strip().upper()
            resultado['uf'] = m.group(2).strip().upper()

        # Bairro (último segmento antes de cidade-UF)
        if resultado['cidade']:
            # Pega o que vem antes de "cidade - UF"
            padrao = rf'([^,]+?),\s*{re.escape(resultado["cidade"])}\s*-\s*{re.escape(resultado["uf"])}'
            m_bairro = re.search(padrao, texto, re.I)
            if m_bairro:
                resultado['bairro'] = m_bairro.group(1).strip()

        # Zona rural
        resultado['zona_rural'] = self._detectar_zona_rural(
            resultado.get('bairro') or '',
            texto
        )

        return resultado

    def _detectar_zona_rural(self, bairro: str, logradouro: str = '') -> bool:
        """Verifica se o endereço indica zona rural."""
        texto = f'{bairro} {logradouro}'.lower()
        return bool(self.PADROES_ZONA_RURAL.search(texto))

    # =================================================================
    # HELPERS
    # =================================================================
    def _ato_sem_destinatario(self) -> bool:
        """Verifica se o ato não precisa de destinatário.

        Ex: 'arquive-se', 'certifique-se', 'publique-se'.
        """
        act_verb = (self._ato_data.get('act_verb') or '').lower().strip()
        return act_verb in self.ATOS_SEM_DESTINATARIO

    def _eh_movimentacao(self) -> bool:
        """Verifica se o CommandAnalyzer já classificou como movimentação."""
        tipo = (self._ato_data.get('tipo_cumprimento') or '').lower().strip()
        if tipo == 'movimentacao':
            return True
        # Fallback: verifica pelo act_verb + sem destinatário
        act_verb = (self._ato_data.get('act_verb') or '').lower().strip()
        if act_verb in self.ATOS_SEM_DESTINATARIO:
            return True
        return False

    def _ato_permite_email_condicional(self, tipo_ato: str) -> bool:
        """Verifica se o tipo de ato permite usar e-mail sem opt-in."""
        from projudi.parte_classifier import ParteClassifier
        return tipo_ato.lower() in ParteClassifier.ATOS_COM_EMAIL_CONDICIONAL

    def _encontrar_raw(self, nome_normalizado: str) -> Optional[Dict]:
        """Localiza a entrada crua correspondente na lista raw."""
        nn = (nome_normalizado or '').lower().strip()
        for p in self._partes_raw:
            raw_nn = (
                p.get('nome_normalizado') or p.get('name_normalized')
                or p.get('nome', '') or p.get('name', '')
            )
            if raw_nn.lower().strip() == nn:
                return p
            # Fallback: contém
            if nn and raw_nn and (nn in raw_nn.lower() or raw_nn.lower() in nn):
                return p
        return None

    def _decisao(self, nome: str, fluxo: str, justificativa: str,
                  endereco_info: Dict) -> Dict:
        return {
            'nome': nome,
            'fluxo': fluxo,
            'justificativa': justificativa,
            'endereco_analisado': endereco_info,
        }

    def _resposta_sem_destinatario(self) -> Dict:
        act_verb = self._ato_data.get('act_verb', '')
        return {
            'tipo': 'ato_sem_destinatario',
            'ato': act_verb,
            'justificativa': f"Ato '{act_verb}' não possui destinatário — "
                             f"apenas movimentação interna (Mov581) necessária.",
            'partes': [],
            'resumo': {'fluxos': {'movimentacao_simples': []}},
        }

    def _montar_saida(self, resultados: List[Dict]) -> Dict:
        fluxos: Dict[str, List[str]] = {}
        for r in resultados:
            f = r['fluxo']
            if f not in fluxos:
                fluxos[f] = []
            fluxos[f].append(r['nome'])

        return {
            'tipo': 'partes',
            'partes': resultados,
            'resumo': {
                'total_partes': len(resultados),
                'fluxos': fluxos,
                'tem_mandado': any(r['fluxo'] in ('mandado', 'mandado_precatorio')
                                   for r in resultados),
                'tem_ar': any(r['fluxo'] == 'ar' for r in resultados),
                'tem_eletronico': any(r['fluxo'] == 'eletronico' for r in resultados),
                'tem_edital': any(r['fluxo'] == 'edital' for r in resultados),
            },
        }
