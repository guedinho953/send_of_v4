"""
MovimentacoesService - Processa movimentacoes do Projudi antes da juntada.

Fluxo:
1. Parsear HTML do DadosProcesso via ProcessoParser
2. Classificar cada movimentacao (sentenca, despacho, intimacao...)
3. Extrair comandos estruturados (ato, destinatario, meio, objetivo, prazo, condicoes)
4. Rastrear comunicacoes expedidas x lidas
5. Salvar no banco (Movement, MovementCommand, CommunicationTracking)
6. Buscar cumprimentos similares no historico (RAG)
7. Atualizar resumo do processo (ProcessSummary)
"""

import re
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from django.db import transaction

from .models import (
    Process, Party, Movement, MovementCommand,
    CommunicationTracking, ComplianceHistory, ProcessSummary, Deadline
)

# Regex de classificacao
CLASSIFICADORES = {
    "sentenca": re.compile(
        r'julgo\s+procedente|julgo\s+improcedente|extingo\s+o\s+processo|'
        r'resolu[cç][aã]o\s+de\s+m[eé]rito|art\.\s*487|condeno|honor[aá]rios?\s+advocat[ií]cios?',
        re.I
    ),
    "decisao": re.compile(
        r'tutela\s+de\s+urg[eê]ncia|probabilidade\s+do\s+direito|'
        r'perigo\s+de\s+dano|fumus\s+boni\s+iuris|periculum\s+in\s+mora|'
        r'defiro\s+a\s+liminar|indefiro\s+a\s+liminar',
        re.I
    ),
    "despacho": re.compile(
        r'despacho|intimem?-se|expe[cç]a-se|oficie-se|certifique-se|arquive-se|cumpra-se',
        re.I
    ),
    "intimacao": re.compile(r'intima[cç][aã]o', re.I),
    "citacao": re.compile(r'cita[cç][aã]o', re.I),
    "certidao": re.compile(r'certid[aã]o|juntada\s+de\s+ar|aviso\s+de\s+recebimento', re.I),
    "mandado": re.compile(r'mandado', re.I),
    "audiencia": re.compile(r'audi[eê]ncia', re.I),
    "recurso": re.compile(r'recurso\s+inominado', re.I),
    "embargos": re.compile(r'embargos', re.I),
    "peticao": re.compile(r'peti[cç][aã]o', re.I),
}

# Regex de extracao de comandos
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

DEST_MAP = {
    'parte autora': 'autor',
    'parte ré': 'reu',
    'parte re': 'reu',
    'partes rés': 'reu',
    'partes res': 'reu',
    'executado': 'executado',
    'executada': 'executado',
    'executadas': 'executado',
    'exequente': 'exequente',
    'embargado': 'reu',
    'embargada': 'reu',
    'embargante': 'exequente',
    'ministério público': 'mp',
    'ministerio publico': 'mp',
    'partes': 'todos',
}

ATOS_PERMITIDOS = {
    'publique-se', 'registre-se', 'arquive-se',
    'intime-se', 'intimem-se', 'cite-se', 'expeça-se',
    'expeda-se', 'certifique-se', 'oficie-se',
    'remeta-se', 'insira-se', 'anote-se', 'aguarde-se',
    'retorne-se', 'junte-se', 'comunique-se', 'transmita-se',
    'protocole-se', 'notifique-se',
    'determino que', 'ordeno que', 'mando que',
}


def classificar_movimentacao(texto: str) -> Tuple[str, Dict]:
    """Classifica o tipo da movimentacao por regex scoring."""
    scores = {}
    for tipo, padrao in CLASSIFICADORES.items():
        scores[tipo] = len(padrao.findall(texto))
    tipo_final = max(scores, key=scores.get)
    if scores[tipo_final] == 0:
        return "indefinido", scores
    return tipo_final, scores


def extrair_comandos(texto_judicial: str, tipo_classificado: str) -> List[Dict]:
    """
    Transforma texto judicial em lista de dicionarios estruturados.
    Cada dict = um comando cumprivel.
    """
    texto = re.sub(r'\s+', ' ', texto_judicial).strip().lower()

    atos = list(PADROES_COMANDOS['ato'].finditer(texto))
    atos_extraidos = {m.group().lower().strip().replace('.', '').replace(',', '') for m in atos}
    atos_extraidos = {a for a in atos_extraidos if a}

    # Verificar se todos os atos sao permitidos
    cumprivel = atos_extraidos.issubset(ATOS_PERMITIDOS) if atos_extraidos else False

    resultado = []
    for j, ato in enumerate(atos):
        inicio = ato.start()
        fim = atos[j + 1].start() if j < len(atos) - 1 else len(texto)
        trecho = texto[inicio:fim]

        dados = {
            'tipo': tipo_classificado,
            'cumprivel': cumprivel,
            'ato': ato.group(),
            'trecho': trecho,
            'condicoes': [],
            'destinatario': [],
            'meio': [],
            'objetivo': [],
            'prazo': [],
        }

        for campo in ['condicoes', 'destinatario', 'meio', 'objetivo', 'prazo']:
            dados[campo] = [m.group() for m in PADROES_COMANDOS[campo].finditer(trecho)]

        # Bloqueia se houver condicoes perigosas
        if dados['condicoes']:
            dados['cumprivel'] = False

        # Normaliza destinatario
        if not dados['destinatario']:
            dados['destinatario'] = ['partes']

        resultado.append(dados)

    return resultado


def situacao_comunicacao(texto: str) -> Optional[str]:
    texto = str(texto).lower()
    if 'lido(a)' in texto:             return 'lida'
    if 'expedido(a)' in texto:          return 'expedida'
    if 'devolução sem leitura' in texto: return 'devolvida_sem_leitura'
    if 'juntada de ar' in texto:        return 'ar_juntado'
    if 'mandado devolvido' in texto:    return 'mandado_devolvido'
    if 'mandado assinado' in texto:     return 'mandado_assinado'
    if 'mandado à disposição' in texto: return 'mandado_disponivel'
    if 'solicitada a expedição de mandado' in texto: return 'mandado_solicitado'
    return None


def tipo_comunicacao(texto: str) -> str:
    texto = texto.lower()
    if 'citação' in texto:    return 'citacao'
    if 'intimação' in texto:  return 'intimacao'
    if 'certidão' in texto:    return 'certidao'
    if 'mandado' in texto:     return 'mandado'
    if 'aviso de recebimento' in texto or 'juntada de ar' in texto:
        return 'ar'
    return 'outro'


def meio_comunicacao(texto: str) -> Optional[str]:
    texto = texto.lower()
    if any(x in texto for x in ('advgs', '(p/ advgs.', 'advgs.', 'advogado')):
        return 'advogado'
    if 'ofício' in texto or 'oficio' in texto:
        return 'oficio'
    if 'mandado' in texto:
        return 'mandado'
    if 'aviso de recebimento' in texto or 'juntada de ar' in texto:
        return 'ar'
    if re.search(r'\bpara\b', texto):
        return 'pessoal'
    return None


def normalizar_nome(x: str) -> Optional[str]:
    if not x:
        return None
    x = str(x).lower().strip()
    x = re.sub(r'\(rev\.\s*arg\.?\)', '', x, flags=re.I)
    x = re.sub(r'\s+', ' ', x)
    return x


def extrair_prazo_dias(texto: str) -> str:
    """Extrai prazo em dias do texto do despacho.
    Ex: '03 dias' → '03', '05 (cinco) dias' → '05'
    """
    m = re.search(r'(\d+)\s*(?:\([^)]*\))?\s*(?:dias?|dia)', texto, re.I)
    return m.group(1) if m else '03'


def extrair_valor_penhora(texto: str) -> str:
    """Extrai valor em reais do texto do despacho.
    Ex: 'R$ 1.942,52' → '1.942,52'
    """
    m = re.search(
        r'(?:R\$\s*|valor\s*(?:de\s*)?(?:da\s+penhora\s*)?:?\s*R?\$?\s*)'
        r'([\d\.,]+)',
        texto, re.I)
    if m:
        return m.group(1).strip()
    return ''


def numero_por_extenso(numero: str) -> str:
    """Converte número de dias por extenso. Ex: '03' → 'três'."""
    extenso = {
        '1': 'um', '2': 'dois', '3': 'três', '4': 'quatro', '5': 'cinco',
        '6': 'seis', '7': 'sete', '8': 'oito', '9': 'nove', '10': 'dez',
        '15': 'quinze', '20': 'vinte', '30': 'trinta',
    }
    return extenso.get(numero.strip().lstrip('0'), numero)


def extrair_contexto_para_template(rag, parte) -> Dict:
    """Monta o contexto para renderizar um DocumentTemplate,
    extraindo prazo, valor e demais campos do RAGExample."""
    from datetime import date
    texto_busca = f"{rag.despacho_observacao or ''} {rag.despacho_ato or ''}"
    prazo = extrair_prazo_dias(texto_busca)

    ctx = {
        'processo': rag.process.number if rag.process else '',
        'despacho_ato': rag.despacho_ato,
        'despacho_observacao': rag.despacho_observacao,
        'despacho_data': rag.despacho_data,
        'despacho_autor': rag.despacho_autor or 'MARTINHO FERRAZ DA NOBREGA JUNIOR',
        'parte': {
            'nome': parte.name if parte else '',
            'endereco': parte.address if parte else '',
            'email': parte.email if parte else '',
            'telefone': parte.phone if parte else '',
            'cpf_cnpj': parte.cpf_cnpj if parte else '',
            'rg': parte.rg if parte else '',
            'nome_pai': parte.nome_pai if parte else '',
            'nome_mae': parte.nome_mae if parte else '',
        } if parte else {},
        'prazo_dias': prazo,
        'prazo_dias_extenso': numero_por_extenso(prazo),
        'valor_penhora': extrair_valor_penhora(texto_busca),
        'data': date.today().strftime('%d/%m/%Y'),
    }
    return ctx


def normalizar_texto(texto: str) -> str:
    """Minúsculas + remove acentos (endereço → endereco, audiência → audiencia).

    Usado no matching RAG para que variações de acentuação não quebrem
    a sobreposição de palavras.
    """
    import unicodedata
    if not texto:
        return ''
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto.lower())
        if unicodedata.category(c) != 'Mn'
    )


def buscar_cumprimentos_similares(texto_movimentacao: str, top_k: int = 3) -> List[Dict]:
    """
    Busca exemplos RAG similares ao texto da movimentacao.
    Compara palavras em comum com o texto do despacho + cumprimentos.
    NÃO limita a 200 RAGs — considera TODAS as ativas (o limite antigo
    [:200] fazia RAGs recém-criadas ficarem de fora).
    """
    from .models import RAGExample
    exemplos = RAGExample.objects.filter(active=True)
    resultados = []

    palavras_atual = set(normalizar_texto(texto_movimentacao).split())
    for ex in exemplos:
        # Usa despacho_ato + despacho_observacao (conteúdo real da decisão)
        texto_busca = normalizar_texto(
            ex.despacho_ato + ' ' + ex.despacho_observacao)
        for c in ex.cumprimentos:
            texto_busca += ' ' + normalizar_texto(
                c.get('ato', '') + ' ' + c.get('observacao', ''))
        palavras_hist = set(texto_busca.split())
        intersecao = palavras_atual & palavras_hist
        if len(intersecao) >= 2:
            resultados.append({
                'similaridade': len(intersecao),
                'id': ex.id,
                'processo': ex.process.number if ex.process else None,
                'despacho_ato': ex.despacho_ato[:200],
                'despacho_observacao': ex.despacho_observacao[:2000],
                'cumprimentos': ex.cumprimentos,
                'template_ids': list(ex.suggested_templates.values_list('id', flat=True)),
                'data': ex.despacho_data,
                'sequencia_cumprimento': ex.sequencia_cumprimento or [],
            })

    resultados.sort(key=lambda x: x['similaridade'], reverse=True)
    return resultados[:top_k]


class MovimentacoesService:
    """Servico de processamento completo de movimentacoes."""

    def __init__(self, user, html_dados_processo: str = None, process_number: str = None):
        self.user = user
        self.html = html_dados_processo
        self.process_number = process_number

    # ------------------------------------------------------------------
    # PIPELINE PRINCIPAL
    # ------------------------------------------------------------------
    def processar_movimentacoes(self, html: str = None, numero_processo: str = None,
                                 processo_obj: Process = None) -> Dict:
        """
        Pipeline completo de processamento.
        Retorna dict com resumo da analise.
        """
        html = html or self.html
        numero_processo = numero_processo or self.process_number

        if not html or not numero_processo:
            raise ValueError("HTML e numero do processo sao obrigatorios")

        # 1. Parsear HTML
        sys_path = __import__('sys').path
        base_dir = str(__import__('django.conf').conf.settings.BASE_DIR)
        if base_dir not in sys_path:
            sys_path.insert(0, base_dir)

        from projudiProcessNavigator import ProcessoParser
        from bs4 import BeautifulSoup
        parser = ProcessoParser(html)
        partes = parser.extrair_partes(parser.soup)
        movimentacoes, movimentacoes_raw = parser.extrair_movimentacoes()
        links = parser.extrair_links(parser.soup, parser.base_url)
        dados = {
            'partes': partes,
            'movimentacoes': movimentacoes,
            'movimentacoes_raw': movimentacoes_raw,
            'links': links,
        }

        partes = dados.get('partes', [])
        movimentacoes = dados.get('movimentacoes', [])

        # 2. Criar/atualizar Processo
        if processo_obj is None:
            processo_obj, _ = Process.objects.update_or_create(
                number=numero_processo,
                defaults={
                    'status': 'analyzing',
                    'number_normalized': self._normalize_process_number(numero_processo),
                }
            )
        
        tenant = processo_obj.tenant

        # 3. Salvar partes
        self._salvar_partes(processo_obj, partes, tenant)

        # 4. Processar e salvar movimentacoes + comandos
        total_comandos = 0
        completaveis = 0
        for mov in movimentacoes:
            self._salvar_movimentacao(processo_obj, mov, tenant)
            if mov.get('comandos_extraidos'):
                total_comandos += len(mov['comandos_extraidos'])
                completaveis += sum(1 for c in mov['comandos_extraidos'] if c.get('cumprivel'))

        # 5. Rastrear comunicacoes (expedidas x lidas)
        tracked = self._rastrear_comunicacoes(processo_obj, movimentacoes, tenant)

        # 5.5 Casar movimentacoes no tempo (referencias cruzadas)
        movimentacoes = self._casar_movimentacoes_no_tempo(processo_obj, movimentacoes)

        # 6. Verificar status de automatizacao
        auto_status = self._verificar_automatizacao(processo_obj)

        # 7. Atualizar resumo
        summary, _ = ProcessSummary.objects.update_or_create(
            process=processo_obj,
            defaults={
                'is_automatable': auto_status['automatizavel'],
                'automation_status': auto_status['status'],
                'total_movements': len(movimentacoes),
                'total_commands': total_comandos,
                'completable_commands': completaveis,
                'tracked_communications': tracked,
                'last_analysis': datetime.now(),
            }
        )

        return {
            'processo': numero_processo,
            'movimentacoes': len(movimentacoes),
            'comandos': total_comandos,
            'completaveis': completaveis,
            'comunicacoes_rastreadas': tracked,
            'automatizavel': auto_status['automatizavel'],
            'status': auto_status['status'],
        }

    # ------------------------------------------------------------------
    # SUB-FUNCOES
    # ------------------------------------------------------------------
    def _salvar_movimentacao(self, processo: Process, mov: Dict, tenant=None):
        """Salva uma movimentacao e seus comandos extraidos."""
        ato = mov.get('ato', '')
        texto_ato = ato.lower()

        # Classificar
        tipo, _ = classificar_movimentacao(texto_ato)
        mov['tipo'] = tipo

        # Detectar comunicacao
        situacao = situacao_comunicacao(texto_ato)
        meio = mov.get('meio_comunicacao') or meio_comunicacao(texto_ato)
        destinatario = mov.get('destinatario', '')
        if isinstance(destinatario, dict):
            destinatario = destinatario.get('nome', '')

        # Data
        data_obj = mov.get('data_obj')
        if not data_obj and mov.get('data_texto'):
            try:
                data_obj = datetime.strptime(mov['data_texto'], "%d/%m/%y").date()
            except:
                data_obj = None

        defaults = {
            'act_description': mov.get('ato', ''),
            'act_normalized': mov.get('ato_normalizado', ''),
            'category': tipo,
            'act_date': data_obj,
            'reading_date': mov.get('data_leitura_str'),
            'reference_date': mov.get('data_referencia_str'),
            'author': mov.get('autor', ''),
            'communication_status': situacao or '',
            'communication_means': meio or '',
            'recipient': str(destinatario)[:200] if destinatario else '',
            'observation': mov.get('observacao', ''),
            'referenced_event': str(mov.get('evento_referenciado', ''))[:200],
            'document_url': (mov.get('links_mov', [{}])[0].get('url', ''))[:500] if mov.get('links_mov') else '',
        }
        if tenant:
            defaults['tenant'] = tenant

        # Criar/atualizar Movement
        movement, _ = Movement.objects.update_or_create(
            process=processo,
            event_number=mov.get('evento', ''),
            defaults=defaults
        )

        # Extrair e salvar comandos (se for despacho/sentenca/decisao)
        if tipo in ('despacho', 'sentenca', 'decisao', 'ato_ordinatorio'):
            comandos = extrair_comandos(ato, tipo)
            mov['comandos_extraidos'] = comandos

            # Apagar comandos antigos
            MovementCommand.objects.filter(movement=movement).delete()
            for cmd in comandos:
                cmd_data = {
                    'movement': movement,
                    'act_verb': cmd['ato'][:50],
                    'is_completable': cmd.get('cumprivel', False),
                    'recipient': cmd.get('destinatario', []),
                    'means': cmd.get('meio', []),
                    'objective': cmd.get('objetivo', []),
                    'deadline': cmd.get('prazo', []),
                    'conditions': cmd.get('condicoes', []),
                    'snippet': cmd.get('trecho', '')[:5000],
                }
                if tenant:
                    cmd_data['tenant'] = tenant
                MovementCommand.objects.create(**cmd_data)

    def _salvar_partes(self, processo: Process, partes: List[Dict], tenant=None):
        """Salva partes do processo."""
        Party.objects.filter(process=processo).delete()

        for p in partes:
            papel = p.get('papel', '')
            role = 'autor' if papel == 'PROMOVENTE' else 'reu' if papel == 'PROMOVIDO' else 'terceiro'
            if 'EXEQUENTE' in p.get('tipo', '').upper():
                role = 'exequente'
            if 'EXECUTADO' in p.get('tipo', '').upper():
                role = 'executado'

            parte_data = {
                'process': processo,
                'name': p.get('nome', '')[:200],
                'name_normalized': normalizar_nome(p.get('nome_normalizado', p.get('nome', ''))) or '',
                'role': role,
                'cpf_cnpj': p.get('cpf/cnpj', ''),
                'email': p.get('email', ''),
                'phone': p.get('tel', ''),
                'address': json.dumps(self._endereco_dict(p)),
                'has_lawyer': p.get('tem_advogado', False),
                'receives_email_intimation': p.get('recebe_intimacao_email', False),
                'has_domicilio_cnj': p.get('domicilio_cnj', False),
                'is_revel': p.get('revelia', False) or p.get('revel', False),
            }
            if tenant:
                parte_data['tenant'] = tenant
            Party.objects.create(**parte_data)

    def _endereco_dict(self, p: Dict) -> Dict:
        """Extrai campos de endereco de um dict de parte."""
        return {
            k: p.get(k) for k in ['logradouro', 'numero', 'complemento', 'bairro', 'cidade', 'uf', 'cep']
            if p.get(k)
        }

    def _rastrear_comunicacoes(self, processo: Process, movimentacoes: List[Dict], tenant=None) -> int:
        """Cruza expedidas com lidas e salva CommunicationTracking."""
        import pandas as pd

        df = pd.DataFrame(movimentacoes)
        if df.empty:
            return 0

        df['situacao'] = df['ato'].apply(situacao_comunicacao)
        df['tipo'] = df['ato'].apply(tipo_comunicacao)
        df['meio_real'] = df['ato'].apply(meio_comunicacao)

        # Extrair destinatario string
        df['destinatario_str'] = df['destinatario'].apply(
            lambda x: x.get('nome', str(x)) if isinstance(x, dict) else str(x)
        )

        df_expedidas = df[df['situacao'] == 'expedida'].copy()
        df_lidas = df[df['situacao'].isin(['lida', 'devolvida_sem_leitura', 'ar_juntado',
                                            'mandado_devolvido', 'mandado_assinado'])].copy()

        if df_expedidas.empty:
            return 0

        # Chave: destinatario + data_texto
        df_expedidas['chave'] = (
            df_expedidas['destinatario_str'].str.lower().str.strip()
            + '|' + df_expedidas['data_texto']
        )
        df_lidas['chave'] = (
            df_lidas['destinatario_str'].str.lower().str.strip()
            + '|' + df_lidas['data_referencia_str'].fillna(df_lidas['data_texto'])
        )

        # Merge
        relacoes = df_lidas.merge(
            df_expedidas,
            on=['chave', 'destinatario_str', 'tipo'],
            suffixes=('_lido', '_expedido'),
            how='right'
        )

        # Salvar
        CommunicationTracking.objects.filter(process=processo).delete()
        count = 0
        for _, row in relacoes.iterrows():
            data_exp = None
            try:
                data_exp = datetime.strptime(str(row.get('data_texto_expedido', '')), "%d/%m/%y").date()
            except:
                pass

            data_lido = None
            try:
                dl = row.get('data_leitura_str_lido')
                if dl:
                    data_lido = datetime.strptime(str(dl), "%d/%m/%y").date()
            except:
                pass

            ct_data = {
                'process': processo,
                'type': row.get('tipo', 'outro'),
                'event_expedido': str(row.get('evento_expedido', ''))[:10],
                'date_expedido': data_exp,
                'act_expedido': str(row.get('ato_expedido', ''))[:500],
                'recipient': str(row.get('destinatario_str', ''))[:300],
                'means': str(row.get('meio_real_expedido', ''))[:30],
                'event_lido': str(row.get('evento_lido', ''))[:10] if pd.notna(row.get('evento_lido')) else '',
                'date_lido': data_lido,
                'status': row.get('situacao_lido', 'pendente') if pd.notna(row.get('situacao_lido')) else 'pendente',
                'deadline_days': self._extrair_prazo(str(row.get('ato_expedido', ''))),
            }
            if tenant:
                ct_data['tenant'] = tenant
            CommunicationTracking.objects.create(**ct_data)
            count += 1

        # Para expedidas sem retorno, criar pendente
        expedidas_sem_retorno = df_expedidas[~df_expedidas['evento'].isin(
            relacoes['evento_expedido'].dropna().unique() if not relacoes.empty else []
        )]
        for _, row in expedidas_sem_retorno.iterrows():
            data_exp = None
            try:
                data_exp = datetime.strptime(str(row.get('data_texto', '')), "%d/%m/%y").date()
            except:
                pass
            ct_data = {
                'process': processo,
                'type': row.get('tipo', 'outro'),
                'event_expedido': str(row.get('evento', ''))[:10],
                'date_expedido': data_exp,
                'act_expedido': str(row.get('ato', ''))[:500],
                'recipient': str(row.get('destinatario_str', ''))[:300],
                'means': str(row.get('meio_real', ''))[:30],
                'status': 'pendente',
            }
            if tenant:
                ct_data['tenant'] = tenant
            CommunicationTracking.objects.create(**ct_data)
            count += 1

        return count

    def _extrair_prazo(self, texto: str) -> Optional[int]:
        """Extrai numero de dias de prazo do texto."""
        m = re.search(r'(\d+)\s*dias?', texto, re.I)
        if m:
            return int(m.group(1))
        return None

    def _casar_movimentacoes_no_tempo(self, processo: Process, movimentacoes: List[Dict]) -> List[Dict]:
        """
        Percorre as movimentacoes do mais recente para o mais antigo
        e liga cada uma ao evento original que a originou.

        Exemplos:
        - "certifique-se a tempestividade" -> busca intimacao/despacho anterior
        - "certifique-se o preparo" -> busca intimação de recolhimento anterior
        - "expeça-se alvará" -> busca depósito anterior
        - "expedir oficio requisitorio" -> busca sentença de pagamento anterior
        """
        if not movimentacoes:
            return movimentacoes

        # Ordenar por evento (descendente: mais recente primeiro)
        movs_ordenadas = sorted(movimentacoes, key=lambda m: str(m.get('evento', '')), reverse=True)
        total = len(movs_ordenadas)

        # Palavras-chave que indicam uma movimentação que REFERENCIA algo anterior
        PALAVRAS_REFERENCIA = {
            'certifique-se': ['tempestividade', 'preparo', 'intimacao', 'intimacao', 'juntada',
                              'cumprimento', 'execucao', 'embargos', 'deposito', 'penhora',
                              'arresto', 'sequestro', 'satisfacao', 'quitacao'],
            'expeça-se': ['alvara', 'mandado', 'precatoria', 'cartaprecatoria'],
            'expeda-se': ['alvara', 'mandado', 'precatoria'],
            'oficie-se': ['requisitorio', 'requisicao', 'requisitar', 'penhora',
                         'bloqueio', 'arresto', 'sequestro', 'suspensao'],
            'intime-se': ['sobre', 'referente', 'cumprimento', 'intimacao',
                         'acerca', 'respeito', 'relacao'],
            'intimem-se': ['sobre', 'referente', 'cumprimento', 'acerca'],
        }

        # Palavras-chave que indicam uma movimentação ORIGINAL (é referenciada por outras)
        PALAVRAS_ORIGEM = {
            'intime-se': ['manifestar', 'contrarrazoar', 'recolher', 'pagar',
                         'apresentar', 'depositar', 'intimar', 'impugnar',
                         'regularizar', 'juntar'],
            'intimem-se': ['manifestar', 'contrarrazoar', 'recolher', 'pagar',
                          'apresentar', 'depositar', 'impugnar'],
            'cite-se': ['comparecer', 'contestar', 'manifestar', 'apresentar'],
            'notifique-se': ['comparecer', 'contestar', 'manifestar'],
            'oficie-se': ['informar', 'responder', 'comunicar', 'prestar informacoes'],
            'expeça-se': ['mandado', 'intimacao', 'citacao', 'precatoria'],
            'determino': ['prazo', 'recolhimento', 'pagamento', 'intimacao'],
        }

        for i, mov_atual in enumerate(movs_ordenadas):
            ato_atual = mov_atual.get('ato', '').lower()
            tipo_atual = mov_atual.get('tipo', '')

            # Detectar se esta movimentacao refere a algo anterior
            ato_chave = None
            palavras_contexto = []
            for verbo, contextos in PALAVRAS_REFERENCIA.items():
                if verbo in ato_atual:
                    ato_chave = verbo
                    palavras_contexto = contextos
                    break

            if not ato_chave:
                continue

            # Buscar nos eventos ANTERIORES (i+1 em diante, pois lista está reversa)
            evento_origem = None
            tipo_origem = None

            for j in range(i + 1, total):
                mov_ant = movs_ordenadas[j]
                ato_ant = mov_ant.get('ato', '').lower()
                tipo_ant = mov_ant.get('tipo', '')

                # Verificar se o evento anterior é uma ORIGEM plausível
                eh_origem = False
                for verbo_origem, contextos_origem in PALAVRAS_ORIGEM.items():
                    if verbo_origem in ato_ant:
                        # Verificar se o contexto atual bate com a origem
                        for ctx in contextos_origem:
                            if ctx in ato_atual or ctx in ato_ant:
                                eh_origem = True
                                break
                    if eh_origem:
                        break

                # Se não achou por palavras, verifica por tipo
                if not eh_origem:
                    # intimação/citação são sempre origens potenciais
                    if tipo_ant in ('intimacao', 'citacao', 'despacho'):
                        if tipo_atual in ('certidao', 'mandado'):
                            eh_origem = True
                    # mandado expedido pode ser origem de certidao/alvara
                    if tipo_ant == 'mandado' and 'alvara' in ato_atual:
                        eh_origem = True
                    # sentença de pagamento é origem de alvara/requisitorio
                    if tipo_ant == 'sentenca' and any(x in ato_atual for x in ['alvara', 'requisitorio', 'requisicao']):
                        if 'condeno' in ato_ant or 'pagamento' in ato_ant or 'honorarios' in ato_ant:
                            eh_origem = True

                if eh_origem:
                    evento_origem = mov_ant.get('evento', '')
                    tipo_origem = tipo_ant
                    break

            if evento_origem:
                mov_atual['evento_referenciado'] = str(evento_origem)
                mov_atual['tipo_referenciado'] = tipo_origem
                mov_atual['ato_referenciado'] = mov_ant.get('ato', '')
                # Atualizar no banco
                Movement.objects.filter(
                    process=processo,
                    event_number=mov_atual.get('evento', '')
                ).update(
                    referenced_event=str(evento_origem),
                )

        return movimentacoes

    def _verificar_automatizacao(self, processo: Process) -> Dict:
        """Verifica se processo esta pronto para automatizacao."""
        partes = Party.objects.filter(process=processo)
        if not partes.exists():
            return {'automatizavel': False, 'status': 'sem_partes'}

        autores_ok = all(
            p.has_lawyer or p.has_domicilio_cnj or p.receives_email_intimation
            for p in partes.filter(role__in=['autor', 'exequente'])
        )
        reus_ok = all(
            p.has_lawyer or p.has_domicilio_cnj or p.receives_email_intimation
            for p in partes.filter(role__in=['reu', 'executado'])
        )

        if autores_ok and reus_ok:
            return {'automatizavel': True, 'status': 'automatizar'}
        if autores_ok and not reus_ok:
            return {'automatizavel': False, 'status': 'reu_pendente'}
        if not autores_ok and reus_ok:
            return {'automatizavel': False, 'status': 'autor_pendente'}
        return {'automatizavel': False, 'status': 'ambos_pendentes'}

    def _normalize_process_number(self, numero: str) -> str:
        """Normaliza numero do processo (remove pontos)."""
        return re.sub(r'[^\d]', '', numero)

    # ------------------------------------------------------------------
    # RAG - BUSCA DE SIMILARES
    # ------------------------------------------------------------------
    def buscar_similares(self, texto_movimentacao: str, top_k: int = 3) -> List[Dict]:
        """Busca cumprimentos similares no historico."""
        return buscar_cumprimentos_similares(texto_movimentacao, top_k)

    # ------------------------------------------------------------------
    # UTIL - PREPARAR PROMPT PARA LLM
    # ------------------------------------------------------------------
    def preparar_prompt_cumprimento(self, processo: Process, movement: Movement) -> str:
        """Prepara prompt com contexto do processo para LLM decidir cumprimento."""
        partes = Party.objects.filter(process=processo)
        comandos = MovementCommand.objects.filter(movement=movement)
        similares = self.buscar_similares(movement.act_description, top_k=2)

        contexto_partes = []
        for p in partes:
            canais = []
            if p.has_lawyer: canais.append('advogado')
            if p.has_domicilio_cnj: canais.append('domicilio_cnj')
            if p.receives_email_intimation: canais.append('email_autorizado')
            elif p.email: canais.append('email_cadastrado')
            contexto_partes.append(f"{p.name} ({p.role}): {', '.join(canais) or 'sem canal'}")

        contexto_comandos = []
        for c in comandos:
            contexto_comandos.append(
                f"- {c.act_verb} -> destinatario: {c.recipient}, "
                f"meio: {c.means}, prazo: {c.deadline}, condicoes: {c.conditions}"
            )

        similares_texto = "\n".join([
            f"- Processo {s['processo']}: meio={s['meio_utilizado']}, similaridade={s['similaridade']}"
            for s in similares
        ]) if similares else "Nenhum cumprimento similar encontrado."

        partes_str = "\n".join(contexto_partes)
        comandos_str = "\n".join(contexto_comandos)

        prompt = f"""Você é um assistente da secretaria judiciária.

PROCESSO: {processo.number}
MOVIMENTAÇÃO: {movement.act_description}

PARTES E CANAIS DE COMUNICAÇÃO:
{partes_str}

COMANDOS EXTRAÍDOS:
{comandos_str}

CUMPRIMENTOS SIMILARES:
{similares_texto}

Baseado nas informações acima, responda em JSON:
{{
  "cumprivel": true/false,
  "meio_sugerido": "advogado|domicilio_cnj|email|mandado|oficio|pessoal",
  "justificativa": "...",
  "urgente": true/false
}}"""
        return prompt

    # ------------------------------------------------------------------
    # AVALIAR SE PODE CUMPRIR AGORA OU PRECISA DE MAIS DADOS
    # ------------------------------------------------------------------
    def avaliar_prontidao_cumprimento(self, processo: Process, movement: Movement) -> Dict:
        """
        Avalia se a última movimentação pode ser cumprida IMEDIATAMENTE
        ou se precisa varrer outras movimentações do processo.

        Retorna dict com:
        - pronto_para_cumprir: bool (True = pode cumprir agora)
        - necessita_dados_adicionais: bool (True = precisa varrer histórico)
        - dados_faltantes: list[str] (quais dados faltam)
        - meio_recomendado: str (advogado, email, mandado, oficio, etc)
        - alertas: list[str] (avisos sobre o processo)
        """
        from processes.models import Party, CommunicationTracking

        resposta = {
            'pronto_para_cumprir': False,
            'necessita_dados_adicionais': False,
            'dados_faltantes': [],
            'meio_recomendado': None,
            'alertas': [],
        }

        # --- 1. Verificar se há partes cadastradas ---
        partes = Party.objects.filter(process=processo)
        if not partes.exists():
            resposta['dados_faltantes'].append('Partes do processo não cadastradas')
            resposta['alertas'].append('Processo sem partes — impossível determinar destinatário')
            return resposta

        # --- 2. Pegar o comando da última movimentação ---
        comandos = MovementCommand.objects.filter(movement=movement, is_completable=True)
        if not comandos.exists():
            resposta['alertas'].append('Nenhum comando cumprivel na última movimentação')
            return resposta

        comando = comandos.first()
        ato = comando.act_verb.lower()
        destinatario_raw = comando.recipient if comando.recipient else ['partes']

        # --- 3. Determinar meio recomendado pelos dados das partes ---
        meio = self._determinar_meio_por_partes(ato, destinatario_raw, partes)
        resposta['meio_recomendado'] = meio

        if not meio:
            resposta['dados_faltantes'].append('Nenhum canal de comunicação disponível para as partes')
            resposta['alertas'].append('Partes sem advogado, email autorizado ou domicílio CNJ')

        # --- 4. Verificar se a movimentação faz referência a outra ---
        if movement.referenced_event:
            resposta['alertas'].append(
                f'Movimentação referente ao Evento {movement.referenced_event} — '
                f'verifique se o evento original já foi cumprido'
            )
            # Se o ato for certifique-se/oficie-se e referenciar outro,
            # pode precisar verificar se a intimação anterior foi lida
            if any(x in ato for x in ['certifique', 'oficie', 'intime']):
                ref_comms = CommunicationTracking.objects.filter(
                    process=processo,
                    event_expedido=movement.referenced_event,
                    status__in=['lida', 'pendente']
                )
                if ref_comms.exists():
                    comm = ref_comms.first()
                    if comm.status == 'lida':
                        resposta['alertas'].append(
                            f'Comunicação do evento {movement.referenced_event} foi LIDA em {comm.date_lido} — '
                            f'prazo pode estar em andamento'
                        )
                    elif comm.status == 'pendente':
                        resposta['alertas'].append(
                            f'Comunicação do evento {movement.referenced_event} ainda PENDENTE — '
                            f'pode ser cedo para certificar'
                        )
                else:
                    resposta['dados_faltantes'].append(
                        f'Status da comunicação do Evento {movement.referenced_event} desconhecido'
                    )

        # --- 5. Verificar se há prazo ativo no comando ---
        if comando.deadline:
            # Se tem prazo e é certificação/ofício de tempestividade,
            # precisa saber quando começou o prazo
            if any(x in ato for x in ['certifique', 'oficie']):
                if movement.referenced_event:
                    resposta['dados_faltantes'].append(
                        f'Verificar data da intimação original (Evento {movement.referenced_event}) '
                        f'para calcular tempestividade'
                    )

        # --- 6. Verificar se há condições bloqueantes ---
        if comando.conditions:
            resposta['alertas'].append(
                f'Comando possui condições: {comando.conditions} — '
                f'análise humana recomendada'
            )

        # --- 7. Decisão final ---
        if not resposta['dados_faltantes'] and not resposta['alertas']:
            resposta['pronto_para_cumprir'] = True
        elif not resposta['dados_faltantes'] and resposta['alertas']:
            # Tem alertas mas não faltam dados — pode cumprir com atenção
            resposta['pronto_para_cumprir'] = True
            resposta['necessita_dados_adicionais'] = True
        else:
            resposta['pronto_para_cumprir'] = False
            resposta['necessita_dados_adicionais'] = True

        return resposta

    def _determinar_meio_por_partes(self, ato: str, destinatarios: List[str], partes) -> Optional[str]:
        """
        Determina o meio de comunicação mais adequado baseado nas partes.
        Ordem de prioridade: advogado > email autorizado > domicílio CNJ > mandado
        """
        # Identificar quais partes são destinatárias
        roles_map = {
            'partes': ['autor', 'reu', 'exequente', 'executado'],
            'autora': ['autor', 'exequente'],
            'autor': ['autor', 'exequente'],
            'ré': ['reu', 'executado'],
            'reu': ['reu', 'executado'],
            'réu': ['reu', 'executado'],
            'executada': ['executado'],
            'executadas': ['executado'],
            'executado': ['executado'],
            'exequente': ['exequente'],
            'embargada': ['executado'],
            'embargadas': ['executado'],
            'embargante': ['exequente'],
        }

        roles_alvo = set()
        for d in destinatarios:
            d_norm = str(d).lower().strip().rstrip('s')
            for chave, roles in roles_map.items():
                if chave in d_norm:
                    roles_alvo.update(roles)
        if not roles_alvo:
            roles_alvo = {'autor', 'reu'}

        partes_alvo = [p for p in partes if p.role in roles_alvo]
        if not partes_alvo:
            return None

        # Verificar meios disponíveis
        for p in partes_alvo:
            if p.has_lawyer:
                return 'advogado'  # Prioridade máxima
            if p.receives_email_intimation:
                return 'email_autorizado'
            if p.has_domicilio_cnj:
                return 'domicilio_cnj'
            if p.email:
                return 'email_cadastrado'

        # Se nenhum meio eletronico disponivel, sugere mandado
        if any(x in ato for x in ['cite', 'intime', 'intimem', 'notifique']):
            return 'mandado'

        return None

    # ------------------------------------------------------------------
    # CLASSIFICAR FACILIDADE DO DESPACHO (facil / moderado / dificil)
    # ------------------------------------------------------------------
    def classificar_facilidade_despacho(self, processo: Process, movement: Movement) -> Dict:
        """
        Classifica uma movimentacao como facil, moderado ou dificil.
        Despachos faceis: dados completos, meio claro, sem referencias.
        Despachos dificeis: exigem varredura de historico, tem referencias, valores, condicoes.
        """
        resposta = {
            'nivel': 'facil',           # facil | moderado | dificil
            'cor': 'verde',             # verde | amarelo | vermelho
            'pontuacao': 0,             # 0-100 (maior = mais facil)
            'requer_varredura': False,
            'dados_necessarios': [],
            'justificativa': '',
        }

        # Pegar comando
        comandos = MovementCommand.objects.filter(movement=movement, is_completable=True)
        if not comandos.exists():
            resposta['nivel'] = 'nao_aplicavel'
            resposta['justificativa'] = 'Sem comando cumprivel'
            return resposta

        comando = comandos.first()
        ato = comando.act_verb.lower()
        texto = movement.act_description or ''
        texto_lower = texto.lower()

        # Verificar partes
        partes = Party.objects.filter(process=processo)
        if not partes.exists():
            resposta['nivel'] = 'dificil'
            resposta['cor'] = 'vermelho'
            resposta['pontuacao'] = 0
            resposta['requer_varredura'] = True
            resposta['dados_necessarios'].append('Cadastrar partes do processo')
            resposta['justificativa'] = 'Sem partes cadastradas - impossivel determinar destinatario'
            return resposta

        # Determinar meio
        meio = self._determinar_meio_por_partes(ato, comando.recipient or ['partes'], partes)

        # --- CRITERIOS DE DIFICULDADE ---

        # +30 pontos: tem meio definido
        if meio:
            resposta['pontuacao'] += 30

        # +20 pontos: destinatario claro (nao eh generico "partes")
        destinatario = comando.recipient
        if destinatario and destinatario != ['partes'] and str(destinatario).strip():
            resposta['pontuacao'] += 20
        else:
            resposta['pontuacao'] -= 10
            resposta['dados_necessarios'].append('Identificar destinatario especifico')

        # +20 pontos: sem condicoes
        if comando.conditions:
            resposta['pontuacao'] -= 25
            resposta['dados_necessarios'].append('Analisar condicoes antes de cumprir')
        else:
            resposta['pontuacao'] += 20

        # +10 pontos: sem referencia cruzada
        if movement.referenced_event:
            resposta['pontuacao'] -= 20
            resposta['requer_varredura'] = True
            resposta['dados_necessarios'].append(
                f'Verificar evento {movement.referenced_event}: conteudo, data, status'
            )
        else:
            resposta['pontuacao'] += 10

        # -30 pontos: atos complexos (exigem muita varredura)
        atos_dificeis = {
            'certifique-se', 'oficie-se', 'remeta-se',
            'expeça-se alvara', 'expeda-se alvara',
            'intime-se sobre', 'intimem-se sobre',
        }
        tem_valor = any(x in texto_lower for x in [
            'integral de seguranca', 'penhora', 'deposito',
            'quantia', 'valor', 'r$',
        ])
        tem_tempestividade = any(x in texto_lower for x in [
            'tempestividade', 'prazo', 'embargos',
        ])
        tem_oficio_requisitorio = 'requisitorio' in texto_lower or 'requisicao' in texto_lower
        tem_suspensao = 'suspendo' in texto_lower or 'suspensao' in texto_lower

        if tem_valor or tem_tempestividade or tem_oficio_requisitorio or tem_suspensao:
            resposta['pontuacao'] -= 30
            resposta['requer_varredura'] = True
            if tem_valor:
                resposta['dados_necessarios'].append(
                    'Verificar valores do pedido, depositos e penhoras no historico'
                )
            if tem_tempestividade:
                resposta['dados_necessarios'].append(
                    'Buscar intimação original e calcular prazo'
                )
            if tem_oficio_requisitorio:
                resposta['dados_necessarios'].append(
                    'Verificar sentença de pagamento e valores para requisicao'
                )
            if tem_suspensao:
                resposta['dados_necessarios'].append(
                    'Verificar motivo da suspensao e prazo de retomada'
                )

        # +10 pontos: prazo simples
        if comando.deadline:
            resposta['pontuacao'] += 10

        # Limitar pontuacao entre 0 e 100
        resposta['pontuacao'] = max(0, min(100, resposta['pontuacao']))

        # --- CLASSIFICACAO FINAL ---
        if resposta['pontuacao'] >= 70:
            resposta['nivel'] = 'facil'
            resposta['cor'] = 'verde'
            resposta['justificativa'] = (
                f'Faceil ({resposta["pontuacao"]}/100): meio={meio}, '
                f'sem referencias, sem condicoes. Pode cumprir agora.'
            )
        elif resposta['pontuacao'] >= 40:
            resposta['nivel'] = 'moderado'
            resposta['cor'] = 'amarelo'
            resposta['justificativa'] = (
                f'Moderado ({resposta["pontuacao"]}/100): '
                f'meio={meio}, {len(resposta["dados_necessarios"])} itens para verificar.'
            )
        else:
            resposta['nivel'] = 'dificil'
            resposta['cor'] = 'vermelho'
            resposta['justificativa'] = (
                f'Dificil ({resposta["pontuacao"]}/100): '
                f'requer varredura de {len(resposta["dados_necessarios"])} dados no historico.'
            )

        return resposta

    # ------------------------------------------------------------------
    # RANKEAR MOVIMENTACOES POR FACILIDADE
    # ------------------------------------------------------------------
    def rankear_movimentacoes_por_facilidade(self, processo: Process) -> List[Dict]:
        """
        Rankeia todas as movimentacoes do processo do mais facil para o mais dificil.
        Retorna lista de dicts com evento, descricao, nivel, pontuacao, justificativa.
        """
        movimentacoes = Movement.objects.filter(
            process=processo
        ).prefetch_related('commands').order_by('-event_number')

        ranqueadas = []
        for mov in movimentacoes:
            cmds = mov.commands.filter(is_completable=True)
            if not cmds.exists():
                continue  # Pula movimentacoes sem comando da secretaria

            avaliacao = self.classificar_facilidade_despacho(processo, mov)

            ranqueadas.append({
                'evento': mov.event_number,
                'descricao': mov.act_description[:100] if mov.act_description else '—',
                'ato': cmds.first().act_verb,
                'nivel': avaliacao['nivel'],
                'cor': avaliacao['cor'],
                'pontuacao': avaliacao['pontuacao'],
                'requer_varredura': avaliacao['requer_varredura'],
                'dados_necessarios': avaliacao['dados_necessarios'],
                'justificativa': avaliacao['justificativa'],
                'pronto_para_cumprir': avaliacao['nivel'] == 'facil',
            })

        # Ordenar: faceis primeiro (maior pontuacao)
        ranqueadas.sort(key=lambda x: x['pontuacao'], reverse=True)
        return ranqueadas

    # ------------------------------------------------------------------
    # SUGERIR PROXIMA ACAO (comecar pelos faceis)
    # ------------------------------------------------------------------
    def sugerir_proxima_acao(self, processo: Process) -> Dict:
        """
        Analisa todas as movimentacoes do processo e sugere qual cumprir primeiro.
        Prioridade: faceis > moderados > dificeis.
        """
        ranqueadas = self.rankear_movimentacoes_por_facilidade(processo)

        if not ranqueadas:
            return {
                'tem_acao': False,
                'mensagem': 'Nenhuma movimentacao cumprivel encontrada neste processo.',
            }

        faceis = [m for m in ranqueadas if m['nivel'] == 'facil']
        moderados = [m for m in ranqueadas if m['nivel'] == 'moderado']
        dificeis = [m for m in ranqueadas if m['nivel'] == 'dificil']

        # Prioridade: facil primeiro
        if faceis:
            proxima = faceis[0]
            return {
                'tem_acao': True,
                'prioridade': 'facil',
                'proxima_acao': proxima,
                'alternativas': faceis[1:3],
                'total_faceis': len(faceis),
                'total_moderados': len(moderados),
                'total_dificeis': len(dificeis),
                'mensagem': (
                    f'Sugerido: Evento {proxima["evento"]} ({proxima["ato"]}). '
                    f'Faceil de cumprir - dados completos, meio definido.'
                ),
                'todas': ranqueadas,
            }

        # Se nao tiver facil, tenta moderado
        if moderados:
            proxima = moderados[0]
            return {
                'tem_acao': True,
                'prioridade': 'moderado',
                'proxima_acao': proxima,
                'alternativas': moderados[1:3],
                'total_faceis': len(faceis),
                'total_moderados': len(moderados),
                'total_dificeis': len(dificeis),
                'mensagem': (
                    "Sugerido: Evento " + str(proxima['evento']) + " (" + str(proxima['ato']) + "). "
                    "Moderado - verifique: " + ', '.join(proxima['dados_necessarios'][:2])
                ),
                'todas': ranqueadas,
            }

        # So restou dificil
        proxima = dificeis[0]
        return {
            'tem_acao': True,
            'prioridade': 'dificil',
            'proxima_acao': proxima,
            'alternativas': dificeis[1:3],
            'total_faceis': len(faceis),
            'total_moderados': len(moderados),
            'total_dificeis': len(dificeis),
            'mensagem': (
                "Sugerido: Evento " + str(proxima['evento']) + " (" + str(proxima['ato']) + "). "
                "DIFICIL - Requer varredura extensa: " + ', '.join(proxima['dados_necessarios'][:2])
            ),
            'todas': ranqueadas,
        }
