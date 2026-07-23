"""ParteClassifier — Classifica partes de um processo judicial.

Recebe dados de partes (do ProcessoParser ou do Django model Party)
e retorna uma estrutura contendo:
- quantas são autoras/réus
- canal prioritário de intimação (advogado > djen > email_optin > fisica)
- canais disponíveis totais (incluindo e-mail condicional)
- quem tem advogado / DJEN / e-mail
- quem necessita intimação física (fallback)

Uso típico:
    classifier = ParteClassifier(partes_raw)
    resultado = classifier.classificar()

    # Canal formal/prioritário
    resultado['partes'][0]['canal_prioritario']  # 'advogado'

    # E-mail disponível mesmo sem opt-in?
    resultado['partes'][0]['email_sem_optin']     # True/False

    # Filtrar por tipo de ato
    resultado['partes'][0]['canais_disponiveis']  # ['advogado']
    resultado['partes'][0]['canais_para_ato']('intimacao')  # ['advogado']
"""

from typing import List, Dict, Optional, Tuple


class ParteClassifier:
    """Classifica cada parte segundo seus canais de intimação disponíveis.

    Aceita dois formatos de entrada:
      1. Lista de dicts do ProcessoParser.extrair_partes()
      2. QuerySet ou lista do Django model Party
    """

    CAMPOS_PARSER = {
        'nome', 'nome_normalizado', 'cpf/cnpj', 'tipo', 'papel',
        'recebe_intimacao_email', 'domicilio_cnj', 'tem_advogado',
        'email', 'tel', 'revelia', 'revel', 'logradouro', 'numero',
        'complemento', 'bairro', 'cidade', 'uf', 'cep',
    }

    CAMPOS_MODEL = {
        'name', 'name_normalized', 'role', 'email', 'phone',
        'has_lawyer', 'receives_email_intimation', 'has_domicilio_cnj',
        'is_revel', 'address',
    }

    MAPA_PAPEL = {
        'exequente': 'PROMOVENTE',
        'autor': 'PROMOVENTE',
        'requerente': 'PROMOVENTE',
        'executado': 'PROMOVIDO',
        'réu': 'PROMOVIDO',
        'reu': 'PROMOVIDO',
        'requerido': 'PROMOVIDO',
    }

    # Atos que permitem uso de e-mail mesmo sem opt-in formal
    ATOS_COM_EMAIL_CONDICIONAL = {
        'certificar',
        'intimar_ato_ordinario',
        'notificar',
        'encaminhar',
        'comunicar',
    }

    # =================================================================
    # CONSTRUÇÃO
    # =================================================================
    def __init__(self, partes: List[Dict]):
        """partes: lista de dicts (raw do parser OU model Party)."""
        self._raw = partes
        self._normalizadas: List[Dict] = []
        self._resultado: Optional[Dict] = None

    # =================================================================
    # PIPELINE PRINCIPAL
    # =================================================================
    def classificar(self) -> Dict:
        """Executa a classificação completa e retorna o resultado."""
        self._normalizadas = [self._normalizar(p) for p in self._raw]
        self._resultado = self._montar_saida(self._normalizadas)
        return self._resultado

    # =================================================================
    # NORMALIZAÇÃO (unifica formato parser + model)
    # =================================================================
    def _normalizar(self, parte: Dict) -> Dict:
        if 'nome' in parte:
            return self._de_parser(parte)
        return self._de_model(parte)

    def _de_parser(self, p: Dict) -> Dict:
        return {
            'nome': p.get('nome', ''),
            'nome_normalizado': p.get('nome_normalizado', '').lower().strip(),
            'papel': p.get('papel') or self._mapear_papel(p.get('tipo', '')),
            'tipo': p.get('tipo', ''),
            'cpf_cnpj': p.get('cpf/cnpj', ''),
            'email': str(p.get('email') or ''),
            'telefone': str(p.get('tel') or ''),
            'tem_advogado': bool(p.get('tem_advogado', False)),
            'recebe_email': bool(p.get('recebe_intimacao_email', False)),
            'domicilio_cnj': bool(p.get('domicilio_cnj', False)),
            'revel': bool(p.get('revelia', False)) or bool(p.get('revel', False)),
            'endereco': self._extrair_endereco(p),
            'e_promovente': self._e_promovente(p),
            'e_promovido': self._e_promovido(p),
        }

    def _de_model(self, p: Dict) -> Dict:
        role = (p.get('role') or '').lower()
        return {
            'nome': p.get('name', ''),
            'nome_normalizado': (p.get('name_normalized') or p.get('name', '')).lower().strip(),
            'papel': 'PROMOVENTE' if role in ('autor', 'exequente')
                     else 'PROMOVIDO' if role in ('reu', 'executado')
                     else '',
            'tipo': 'EXEQUENTE' if role in ('autor', 'exequente')
                    else 'EXECUTADO',
            'cpf_cnpj': p.get('cpf_cnpj', ''),
            'email': str(p.get('email') or ''),
            'telefone': str(p.get('phone') or ''),
            'tem_advogado': bool(p.get('has_lawyer', False)),
            'recebe_email': bool(p.get('receives_email_intimation', False)),
            'domicilio_cnj': bool(p.get('has_domicilio_cnj', False)),
            'revel': bool(p.get('is_revel', False)),
            'endereco': p.get('address', ''),
            'e_promovente': role in ('autor', 'exequente'),
            'e_promovido': role in ('reu', 'executado'),
        }

    # =================================================================
    # HELPERS DE NORMALIZAÇÃO
    # =================================================================
    def _mapear_papel(self, tipo: str) -> str:
        return self.MAPA_PAPEL.get(tipo.lower(), '') or ''

    def _e_promovente(self, p: Dict) -> bool:
        papel = p.get('papel') or self._mapear_papel(p.get('tipo', ''))
        return papel == 'PROMOVENTE'

    def _e_promovido(self, p: Dict) -> bool:
        papel = p.get('papel') or self._mapear_papel(p.get('tipo', ''))
        return papel == 'PROMOVIDO'

    def _extrair_endereco(self, p: Dict) -> str:
        partes_end = []
        for k in ('logradouro', 'numero', 'complemento', 'bairro', 'cidade', 'uf'):
            v = p.get(k)
            if v:
                partes_end.append(str(v).strip())
        cep = p.get('cep')
        if cep:
            partes_end.append(f'CEP: {cep}')
        return ', '.join(partes_end)

    # =================================================================
    # CLASSIFICAÇÃO DOS CANAIS
    # =================================================================
    def _classificar_canal_prioritario(self, p: Dict) -> str:
        """Canal FORMAL/legal prioritário para intimações.

        Hierarquia:
          1. Tem advogado → 'advogado' (intimação ao advogado via DJEN)
          2. Sem advogado + Domicílio CNJ → 'djen'
          3. Sem advogado + Sem DJEN + e-mail com opt-in → 'email'
          4. Nenhum → 'fisica'
        """
        if p.get('tem_advogado'):
            return 'advogado'
        if p.get('domicilio_cnj'):
            return 'djen'
        if p.get('recebe_email') and p.get('email'):
            return 'email'
        return 'fisica'

    def _canais_disponiveis(self, p: Dict) -> List[str]:
        """Todos os canais tecnicamente disponíveis, incluindo condicionais.

        A diferença do prioritário:
        - 'email' só entra se tem opt-in (recebe_email=True)
        - 'email_condicional' entra se tem e-mail mesmo sem opt-in
        """
        canais = []
        if p.get('tem_advogado'):
            canais.append('advogado')
        if p.get('domicilio_cnj'):
            canais.append('djen')
        tem_email = bool(p.get('email'))
        if tem_email and p.get('recebe_email'):
            canais.append('email')
        elif tem_email and not p.get('recebe_email'):
            canais.append('email_condicional')
        if not canais:
            canais.append('fisica')
        return canais

    def _explicar_canal(self, p: Dict, canal: str) -> str:
        explicacoes = {
            'advogado': 'Parte possui advogado constituído — '
                        'intimações são feitas através do DJEN (advogado).',
            'djen': 'Parte SEM advogado, mas possui Domicílio Judicial '
                    'Eletrônico CNJ — intimações eletrônicas no DJEN.',
            'email': f"Parte SEM advogado e SEM DJEN, mas optou por "
                     f"e-mail ({p.get('email')}) — intimação por e-mail.",
            'email_condicional': f"Parte possui e-mail ({p.get('email')}) "
                                f"mas SEM opt-in formal — pode ser usado para "
                                f"atos não formais (certidões, comunicações).",
            'fisica': 'Parte SEM advogado, SEM DJEN e SEM e-mail — '
                      'necessita intimação física (mandado/AR/oficial de justiça).',
        }
        return explicacoes.get(canal, 'Canal não classificado.')

    def email_sem_optin(self, p: Dict) -> bool:
        """Tem e-mail no cadastro mas NÃO tem o ícone de envelope (opt-in)."""
        return bool(p.get('email')) and not p.get('recebe_email')

    def email_disponivel(self, p: Dict) -> bool:
        """Tem e-mail cadastrado (com ou sem opt-in)."""
        return bool(p.get('email'))

    def _is_destinatario_cumprimento(self, p: Dict, polo_alvo: Optional[str] = None) -> bool:
        """Define se a parte é destinatária do cumprimento.
        Se polo_alvo for None, considera TODAS como potenciais destinatárias.
        """
        if polo_alvo is None:
            return True
        if polo_alvo == 'promovente':
            return p.get('e_promovente', False)
        if polo_alvo == 'promovido':
            return p.get('e_promovido', False)
        return True

    # =================================================================
    # MONTAGEM DA SAÍDA
    # =================================================================
    def _montar_saida(self, partes: List[Dict], polo_alvo: str = None) -> Dict:
        # --- Agrupar por canal prioritário ---
        canais_prioritario = {
            'advogado': [], 'djen': [], 'email': [], 'fisica': [],
        }

        # --- Agrupar por canais disponíveis totais ---
        canais_disponivel = {
            'advogado': [], 'djen': [], 'email': [], 'email_condicional': [], 'fisica': [],
        }

        email_condicional_nomes = []

        partes_classificadas = []
        for p in partes:
            canal_prio = self._classificar_canal_prioritario(p)
            canais_disp = self._canais_disponiveis(p)
            explicacao = self._explicar_canal(p, canal_prio)
            destinatario = self._is_destinatario_cumprimento(p, polo_alvo)

            entrada = {
                'nome': p['nome'],
                'nome_normalizado': p['nome_normalizado'],
                'papel': p['papel'],
                'tipo': p['tipo'],
                'cpf_cnpj': p['cpf_cnpj'],
                'email': p['email'],
                'telefone': p['telefone'],
                'tem_advogado': p['tem_advogado'],
                'domicilio_cnj': p['domicilio_cnj'],
                'recebe_email': p['recebe_email'],
                'revel': p['revel'],
                'endereco': p['endereco'],
                # Canal formal/prioritário (meio legal)
                'canal_prioritario': canal_prio,
                # Todos os canais disponíveis (incluindo condicionais)
                'canais_disponiveis': canais_disp,
                # Flags de e-mail
                'email_opt_in': p['recebe_email'] and bool(p['email']),
                'email_disponivel': bool(p['email']),
                'email_sem_optin': bool(p['email']) and not p['recebe_email'],
                'canal_explicacao': explicacao,
                'destinatario_cumprimento': destinatario,
            }
            partes_classificadas.append(entrada)

            # Agrupa nos agregadores
            canais_prioritario[canal_prio].append(p['nome'])
            for c in canais_disp:
                if c in canais_disponivel:
                    canais_disponivel[c].append(p['nome'])

            if self.email_sem_optin(p):
                email_condicional_nomes.append(p['nome'])

        # --- Estatísticas ---
        autores = [p for p in partes if p.get('e_promovente')]
        reus = [p for p in partes if p.get('e_promovido')]
        tem_email_sem_optin = sum(1 for p in partes if self.email_sem_optin(p))

        estatisticas = {
            'total_partes': len(partes),
            'autores': len(autores),
            'reus': len(reus),
            'com_advogado': sum(1 for p in partes if p['tem_advogado']),
            'com_domicilio_cnj': sum(1 for p in partes if p['domicilio_cnj']),
            'com_email_opt_in': sum(1 for p in partes if p['recebe_email'] and p['email']),
            'com_email_sem_optin': tem_email_sem_optin,
            'com_email_total': sum(1 for p in partes if p['email']),
            'intimacao_fisica_necessaria': len(canais_prioritario['fisica']),
            'canal_prioritario': {k: len(v) for k, v in canais_prioritario.items()},
        }

        return {
            'resumo': {
                'total_partes': len(partes),
                'autores': len(autores),
                'reus': len(reus),
            },
            'partes': partes_classificadas,
            'canais': {
                'prioritario': canais_prioritario,
                'disponivel': canais_disponivel,
                'email_condicional': email_condicional_nomes,
            },
            'estatisticas': estatisticas,
            'polos': self._resumo_polos(autores, reus),
        }

    def _resumo_polos(self, autores: List[Dict], reus: List[Dict]) -> Dict:
        def _resumo(partes_lista):
            return {
                'quantidade': len(partes_lista),
                'nomes': [p['nome'] for p in partes_lista],
                'com_advogado': [p['nome'] for p in partes_lista if p['tem_advogado']],
                'com_domicilio_cnj': [p['nome'] for p in partes_lista if p['domicilio_cnj']],
                'com_email': [p['nome'] for p in partes_lista if p['email']],
                'intimacao_fisica': [p['nome'] for p in partes_lista
                                     if self._classificar_canal_prioritario(p) == 'fisica'],
            }
        return {
            'promovente': _resumo(autores),
            'promovido': _resumo(reus),
        }

    # =================================================================
    # FILTRO POR TIPO DE ATO
    # =================================================================
    def canais_para_ato(self, tipo_ato: str) -> Dict:
        """Retorna, para cada parte, quais canais são válidos para o tipo de ato.

        Args:
            tipo_ato: 'intimacao', 'citacao', 'certificar', 'notificar',
                      'oficiar', 'intimar_ato_ordinario', etc.

        Returns:
            { 'partes': [ { nome, canais_validos, canal_prioritario, ... } ] }
        """
        if not self._resultado:
            self.classificar()
        resultado = self._resultado
        ato_permite_email_condicional = tipo_ato.lower() in self.ATOS_COM_EMAIL_CONDICIONAL

        partes_filtradas = []
        for p in resultado['partes']:
            canais = list(p['canais_disponiveis'])

            # Se o ato NÃO permite e-mail condicional, remove dos canais
            if not ato_permite_email_condicional:
                canais = [c for c in canais if c != 'email_condicional']

            # Se após remover condicional ficou vazio, cai para física
            if not canais:
                canais = ['fisica']

            partes_filtradas.append({
                'nome': p['nome'],
                'papel': p['papel'],
                'canal_prioritario': p['canal_prioritario'],
                'canais_validos': canais,
                'email': p['email'],
                'email_opt_in': p['email_opt_in'],
                'email_sem_optin': p['email_sem_optin'],
            })

        return {
            'tipo_ato': tipo_ato,
            'permite_email_condicional': ato_permite_email_condicional,
            'partes': partes_filtradas,
        }

    # =================================================================
    # MÉTODOS DE ACESSO RÁPIDO
    # =================================================================
    @property
    def resultado(self) -> Optional[Dict]:
        return self._resultado

    def get_partes_por_canal(self, canal: str) -> List[str]:
        if not self._resultado:
            return []
        return self._resultado['canais']['prioritario'].get(canal, [])

    def get_partes_intimacao_fisica(self) -> List[str]:
        return self.get_partes_por_canal('fisica')

    def get_partes_email_condicional(self) -> List[str]:
        if not self._resultado:
            return []
        return self._resultado['canais']['email_condicional']

    def get_destinatarios(self, polo: str = None) -> List[Dict]:
        if not self._resultado:
            self.classificar()
        partes = self._resultado['partes']
        if polo:
            return [p for p in partes if p.get('destinatario_cumprimento')
                    and (
                        (polo == 'promovente' and p.get('papel') == 'PROMOVENTE')
                        or (polo == 'promovido' and p.get('papel') == 'PROMOVIDO')
                    )]
        return [p for p in partes if p.get('destinatario_cumprimento')]
