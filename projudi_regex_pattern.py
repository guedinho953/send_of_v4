"""Padrões regex usados pelo analisador de comandos do Projudi.

Mantido separado para permitir que `projudi_command_analyzer_new` funcione
sem depender de outros módulos internos.
"""
import re


PADROES_COMANDOS = {
    'ato': re.compile(
        r'(intimem?-se|oficie-se|cite-se|notifique-se|expe[cç]a-se|'
        r'arquive-se|certifique-se|publique-se|registre-se|remeta-se|'
        r'insira-se|anote-se|aguarde-se|retorne-se|junte-se|'
        r'comunique-se|transmita-se|protocol[eé]-se|'
        r'determino\s+que|ordeno\s+que|mando\s+que)',
        re.I
    ),
    'destinatario': re.compile(
        r'parte\s+autora|parte\s+r[eé]|executad[ao]s?|embargad[ao]s?|'
        r'exequente|advogado(?:\(a\))?|minist[eé]rio\s+p[úú]blico',
        re.I
    ),
    'meio': re.compile(
        r'por\s+mandado|por\s+of[ií]cio|por\s+e-?mail|'
        r'atrav[eé]s\s+de\s+seu\s+advogado|por\s+oficial\s+de\s+justi[cç]a|'
        r'whats(?:app|zap)|eletr[ooô]nicamente|domic[ií]lio\s+judicial',
        re.I
    ),
    'objetivo': re.compile(
        r'(?:para\s+)?(manifestar-se|contrarrazoar|pagar|juntar|apresentar|'
        r'impugnar|regularizar|comparecer|informar|comprovar|depositar|'
        r'efetuar\s+pagamento|manifesta[cç][aã]o|ci[eê]ncia)',
        re.I
    ),
    'prazo': re.compile(
        r'(?:no\s+prazo\s+de|prazo\s+de)\s+(\d+\s*(?:dias?|horas?|meses?))',
        re.I
    ),
    'condicoes': re.compile(
        r'\b('
            r'sob\s+pena\s+de\s+[a-zçãéêíóú\s]+'
            r'|findo\s+o\s+prazo(?:\s+[a-zçãéêíóú\s]+)?'
            r'|caso\s+n[aã]o\s+haja\s+[a-zçãéêíóú\s]+'
            r'|na\s+aus[eê]ncia\s+de\s+[a-zçãéêíóú\s]+'
            r'|se\s+n[aã]o\s+houver\s+[a-zçãéêíóú\s]+'
            r'|havendo\s+concord[aâ]ncia'
            r'|satisfeitos\s+os\s+pressupostos\s+recursais'
            r'|expeça-se\s+of[ií]cio\s+requisit[oó]rio\s+de\s+pequeno\s+valor'
            r'|exped[irça]-?s?e?\s+alvar[aá]'
            r'|certifique-se\s+o\s+preparo'
        r')\b',
        re.I
    ),
}

PADROES_CUSTAS = {
    'custas': re.compile(
        r'custas|despesas\s+processuais|taxa\s+judici[aá]ria|'
        r'preparo|recolhimento|guia\s+de\s+recolhimento',
        re.I
    ),
}
