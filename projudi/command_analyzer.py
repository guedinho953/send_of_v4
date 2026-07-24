"""CommandAnalyzer — Extração e classificação de comandos judiciais.

Portado do notebook scripts_send_of_v2/transforma_texto_dict.ipynb.

Pipeline:
  1. Classificar tipo do documento (sentenca, decisao, despacho)
  2. Extrair comandos (intime-se, cite-se, oficie-se, etc.)
  3. Para cada comando: extrair destinatário, meio, objetivo, prazo, condições
  4. Validar destinatários com spaCy
  5. Determinar se é cumprível automaticamente
"""

import re
from typing import Dict, List, Optional, Tuple


# =========================================================================
# CLASSIFICADORES — Tipo do documento por scoring de palavras-chave
# =========================================================================
CLASSIFICADORES = {
    "sentenca": re.compile(
        r'julgo\s+procedente'
        r'|julgo\s+improcedente'
        r'|extingo\s+o\s+processo'
        r'|resolu[cç][aã]o\s+de\s+m[eé]rito'
        r'|art\.\s*487'
        r'|condeno'
        r'|honor[aá]rios?\s+advocat[ií]cios?',
        re.I
    ),
    "decisao": re.compile(
        r'tutela\s+de\s+urg[eê]ncia'
        r'|probabilidade\s+do\s+direito'
        r'|perigo\s+de\s+dano'
        r'|fumus\s+boni\s+iuris'
        r'|periculum\s+in\s+mora'
        r'|defiro\s+a\s+liminar'
        r'|indefiro\s+a\s+liminar',
        re.I
    ),
    "despacho": re.compile(
        r'despacho'
        r'|intimem?-se'
        r'|expe[cç]a-se'
        r'|oficie-?se'
        r'|certifique-se'
        r'|arquive-se'
        r'|cumpra-se',
        re.I
    ),
}


# =========================================================================
# PADRÕES DE COMANDOS — Extração estruturada de cada ato
# =========================================================================
PADROES_COMANDOS = {
    # ── ATO (verbo principal) ──
    'ato': re.compile(
        r'(intimem?-se'
        r'|oficie-?se'
        r'|cite-se'
        r'|notifique-se'
        r'|expe[cç]a-se'
        r'|arquive-se'
        r'|certifique-se'
        r'|cumpra-se'
        r'|confeccione-se'
        r'|proceda-se'
        r'|publique-se'
        r'|registre-se'
        r'|anote-se'
        r'|designem?-se)',
        re.I
    ),

    # ── DESTINATÁRIO ──
    'destinatario': re.compile(
        r'parte\s+autora'
        r'|parte\s+r[eé]'
        r'|parte\s+embargada'
        r'|parte\s+executada'
        r'|partes?\s+r[eé]s?'
        r'|executad[ao]s?'
        r'|embargad[ao]s?'
        r'|embargante[s]?'
        r'|exequente[s]?'
        r'|minist[ée]rio\s+p[úu]blico'
        r'|advogado[s]?(?:\(a\))?'
        r'|autora[s]?'
        r'|requerente[s]?',
        re.I | re.S
    ),

    # ── MEIO DE COMUNICAÇÃO ──
    'meio': re.compile(
        r'por\s+mandado'
        r'|por\s+seu\s+advogado'
        r'|por\s+(?:meio\s+do\s+)?seu\s+advogado(?:\(a\))?'
        r'|atrav[eé]s\s+de\s+seus\s+advogados'
        r'|por\s+of[íi]cio'
        r'|(?:por\s*)e-?mail'
        r'|por\s*oficial\s+de\s+justi[cç]a'
        r'|por\s+carta'
        r'|por\s+ar'
        r'|whats(?:app|zap)'
        r'|(?:por\s*)telefone'
        r'|eletronicamente'
        r'|\brpv\b'
        r'|bacenjud'
        r'|sisbajud'
        r'|renajud',
        re.I | re.S
    ),

    # ── OBJETIVO ──
    'objetivo': re.compile(
        r'(?:para\s+)?'
        r'('
            r'manifestar-se'
            r'|contrarrazoar'
            r'|pagar'
            r'|\brpv\b'
            r'|juntar'
            r'|apresentar'
            r'|impugnar'
            r'|regularizar'
            r'|emendar'
            r'|comparecer'
            r'|informar'
            r'|comprovar'
            r'|retirar'
            r'|depositar'
            r'|efetuar\s+pagamento'
            r'|expedir\s+rpv'
            r'|expedir\s+of[ií]cio'
            r'|manifesta[cç][aã]o'
            r'|ci[eê]ncia'
            r'|cumprir'
            r'|devolver'
        r')'
        r'([^.;]{0,120})',
        re.I | re.S
    ),

    # ── PRAZO ──
    'prazo': re.compile(
        r'(?:no\s+prazo\s+de|prazo\s+de|em\s+at[eé])\s+'
        r'('
            r'\d+\s*(?:\([^)]+\))?\s*dias?'
            r'|\d+\s+horas?'
            r'|\d+\s+meses?'
        r')',
        re.I | re.S
    ),

    # ── CONDIÇÕES ──
    'condicoes': re.compile(
        r'\b('
            r'findo\s+o\s+prazo(?:[^.;]+)?'
            r'|decorrido\s+o\s+prazo(?:[^.;]+)?'
            r'|ap[oó]s\s+o\s+prazo(?:[^.;]+)?'
            r'|caso\s+n[aã]o\s+haja(?:[^.;]+)?'
            r'|na\s+aus[eê]ncia\s+de(?:[^.;]+)?'
            r'|se\s+n[aã]o\s+houver(?:[^.;]+)?'
            r'|havendo\s+concord[aâ]ncia'
            r'|satisfeitos\s+os\s+pressupostos\s+recursais'
            r'|certifique-se\s+a\s+tempestividade'
            r'|se\s*tempestivo\s*e?\s*preparado'
            r'|expeça-?se\s*of[íi]cio\s*requisit[óo]rio\s*de\s*pequeno\s*valor'
        r')\b',
        re.I | re.S
    ),
}


# =========================================================================
# ATOS PERMITIDOS (cumpríveis sem condição)
# =========================================================================
ATOS_PERMITIDOS = {
    'arquive-se', 'intime-se', 'intimem-se',
    'publique-se', 'registre-se', 'anote-se',
    'certifique-se', 'cumpra-se',
}

# =========================================================================
# MAPA: tipo de comando → tipo de cumprimento
# =========================================================================
COMANDO_PARA_TIPO = {
    'intime-se': 'intimacao',
    'intimem-se': 'intimacao',
    'cite-se': 'citacao',
    'oficie-se': 'oficio',
    'oficie-?se': 'oficio',
    'expeça-se': 'expedicao',
    'expeca-se': 'expedicao',
    'arquive-se': 'movimentacao',
    'certifique-se': 'certidao',
    'cumpra-se': 'cumprimento',
    'publique-se': 'movimentacao',
    'registre-se': 'movimentacao',
    'anote-se': 'movimentacao',
}


# =========================================================================
# FUNÇÕES PRINCIPAIS
# =========================================================================

def classificar_tipo(texto: str) -> Tuple[str, Dict[str, int]]:
    """Classifica o tipo do documento por scoring.

    Args:
        texto: Texto do documento judicial (limpo).

    Returns:
        (tipo, scores) — tipo: 'sentenca', 'decisao', 'despacho' ou 'indefinido'
    """
    scores = {}
    for tipo, padrao in CLASSIFICADORES.items():
        scores[tipo] = len(padrao.findall(texto))

    tipo_final = max(scores, key=scores.get)
    if scores[tipo_final] == 0:
        return 'indefinido', scores
    return tipo_final, scores


def extrair_comandos(texto: str) -> List[str]:
    """Extrai todos os comandos (atos) encontrados no texto.

    Args:
        texto: Texto do documento judicial (limpo, lowercase)

    Returns:
        Lista de strings, cada uma contendo um comando completo
        (do ato até o próximo ato ou final do texto).
    """
    matches = list(PADROES_COMANDOS['ato'].finditer(texto))
    comandos = []
    for i, m in enumerate(matches):
        inicio = m.start()
        if i + 1 < len(matches):
            fim = matches[i + 1].start()
        else:
            fim = len(texto)
        comando = texto[inicio:fim].strip()
        comando = re.sub(r'\s+', ' ', comando)
        comandos.append(comando)
    return comandos


def extrair_comandos_dict(texto: str) -> List[Dict]:
    """Extrai comandos com dados estruturados (destinatário, prazo, etc).

    Args:
        texto: Texto do documento judicial (limpo, lowercase)

    Returns:
        Lista de dicts, cada um com:
        - ato: o verbo do comando
        - trecho: o texto do comando
        - destinatario: lista de destinatários extraídos
        - meio: lista de meios de comunicação
        - objetivo: lista de objetivos
        - prazo: lista de prazos
        - condicoes: lista de condições
        - cumprivel: se o ato pode ser cumprido automaticamente
        - tipo: tipo do documento (sentenca/decisao/despacho)
    """
    tipo, _ = classificar_tipo(texto)
    atos = list(PADROES_COMANDOS['ato'].finditer(texto))
    atos_extraidos = {m.group().lower().strip() for m in atos}
    cumprivel_global = atos_extraidos.issubset(ATOS_PERMITIDOS)

    resultado = []
    for j, m in enumerate(atos):
        inicio = m.start()
        if j < len(atos) - 1:
            fim = atos[j + 1].start()
        else:
            fim = len(texto)

        trecho = texto[inicio:fim]
        dados = {
            'tipo': tipo,
            'cumprivel': cumprivel_global,
            'ato': m.group().lower().strip(),
            'trecho': trecho,
            'condicoes': [],
            'destinatario': [],
            'meio': [],
            'objetivo': [],
            'prazo': [],
        }

        for campo in ['condicoes', 'destinatario', 'meio', 'objetivo', 'prazo']:
            dados[campo] = [
                g.group().strip()
                for g in PADROES_COMANDOS[campo].finditer(trecho)
            ]

        # Bloqueia cumprimento se houver condições
        if dados['condicoes']:
            dados['cumprivel'] = False

        # Valida destinatários com spaCy
        if dados['destinatario']:
            try:
                validos = validar_destinatarios(trecho, dados['destinatario'])
                dados['destinatario'] = validos if validos else 'partes'
            except Exception:
                dados['destinatario'] = dados['destinatario'][:1] if dados['destinatario'] else ['partes']
        else:
            dados['destinatario'] = ['partes']

        # Classifica tipo de cumprimento
        ato_clean = re.sub(r'[-\s]', '', dados['ato'].lower())
        for padrao, tipo_cmd in COMANDO_PARA_TIPO.items():
            padrao_clean = re.sub(r'[-\s]', '', padrao.lower())
            if ato_clean == padrao_clean or re.match(padrao.replace('?', ''), dados['ato'], re.I):
                dados['tipo_cumprimento'] = tipo_cmd
                break
        else:
            dados['tipo_cumprimento'] = 'outro'

        resultado.append(dados)

    return resultado


def validar_destinatarios(texto: str, destinatarios: List[str],
                          verbo_alvo: str = 'intim') -> List[str]:
    """Valida destinatários usando análise sintática com spaCy.

    Verifica se o destinatário extraído realmente aparece como
    complemento do verbo no texto.

    Args:
        texto: Trecho do comando
        destinatarios: Lista de destinatários candidatos
        verbo_alvo: Radical do verbo (ex: 'intim' para intime-se)

    Returns:
        Lista de destinatários validados (vazia se nenhum confirmado)
    """
    import spacy
    try:
        nlp = spacy.load("pt_core_news_sm")
    except OSError:
        # spaCy model not installed — fallback: retorna todos
        return destinatarios

    doc = nlp(texto)
    validos = set()

    for token in doc:
        if token.pos_ in ('VERB', 'AUX') and verbo_alvo in token.lemma_.lower():
            # Verifica children que são objetos do verbo
            for child in token.children:
                if child.dep_ in ("obj", "obl", "iobj", "nsubj"):
                    bloco = ' '.join(t.text.lower() for t in child.subtree)
                    for dest in destinatarios:
                        if dest.lower() in bloco:
                            validos.add(dest)

            # Entidades nomeadas
            for ent in doc.ents:
                if ent.label_ in ("PER", "ORG"):
                    for dest in destinatarios:
                        if dest.lower() in ent.text.lower():
                            validos.add(dest)

    return list(validos)


# =========================================================================
# CLASSE PRINCIPAL
# =========================================================================

class CommandAnalyzer:
    """Analisador de comandos judiciais.

    Uso:
        analyzer = CommandAnalyzer()
        resultado = analyzer.analisar(texto_do_documento)
        # resultado['tipo'] = 'sentenca' | 'decisao' | 'despacho'
        # resultado['comandos'] = [...]
    """

    def __init__(self):
        self.texto = ''
        self.tipo = ''
        self.scores = {}
        self.comandos = []

    def analisar(self, texto: str) -> Dict:
        """Pipeline completo: classificar + extrair comandos.

        Args:
            texto: Texto do documento judicial (HTML limpo)

        Returns:
            {
                'tipo': 'sentenca' | 'decisao' | 'despacho' | 'indefinido',
                'scores': {...},
                'comandos': [lista de dicts extraídos],
                'cumprivel': bool,
            }
        """
        self.texto = re.sub(r'\s+', ' ', texto).strip().lower()
        self.tipo, self.scores = classificar_tipo(self.texto)
        self.comandos = extrair_comandos_dict(self.texto)
        cumprivel = all(cmd.get('cumprivel', False) for cmd in self.comandos)

        return {
            'tipo': self.tipo,
            'scores': self.scores,
            'comandos': self.comandos,
            'cumprivel': cumprivel,
        }
