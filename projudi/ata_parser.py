"""
Parser de Ata de Audiência (Transação Penal / Sursis).
Extrai dados estruturados de cumprimento a partir do texto da ata.
"""
import re


def parse_ata_audiencia(texto):
    """
    Analisa o texto de uma ata de audiência e extrai:
    - Tipo: transacao_penal | sursis | outro
    - Modalidade: servico | pecuniaria | mista
    - Valor, parcelas, prazo
    - Condições e detalhes
    
    Args:
        texto: str - conteúdo da ata de audiência
        
    Returns:
        dict com dados estruturados
    """
    texto_lower = texto.lower()
    dados = {
        'tipo': None,           # 'transacao_penal' | 'sursis'
        'modalidade': None,     # 'servico' | 'pecuniaria' | 'mista'
        'valor_total': None,
        'valor_parcela': None,
        'parcelas': None,
        'prazo_meses': None,
        'prazo_dias': None,
        'condicoes': [],
        'beneficiario': None,   # entidade beneficiada (prest. serviço)
        'observacao': '',
    }
    
    # ===== 1. DETECTAR TIPO =====
    if re.search(r'suspens[ãa]o condicional do processo', texto_lower):
        dados['tipo'] = 'sursis'
        # Extrair período do sursis
        m = re.search(r'(?:per[ií]odo\s+(?:de\s+)?)?prova\s*(?:de\s+)?(\d+)\s*(?:anos?|meses?)', texto_lower, re.I)
        if m:
            dados['prazo_meses'] = int(m.group(1)) * 12 if 'ano' in m.group(0).lower() else int(m.group(1))
        
    elif re.search(r'transa[çc][ãa]o penal', texto_lower) or \
         re.search(r'proposta\s+de\s+transa[çc][ãa]o', texto_lower) or \
         re.search(r'homologa[çc][ãa]o\s+da\s+transa[çc][ãa]o', texto_lower):
        dados['tipo'] = 'transacao_penal'
    
    # ===== 2. DETECTAR MODALIDADE =====
    tem_servico = bool(re.search(
        r'presta[çc][ãa]o\s+de\s+servi[çc][oa][sl]?\s*(?:à|a)\s*(?:comunidade|entidade)',
        texto_lower, re.I
    ))
    tem_pecuniaria = bool(re.search(
        r'presta[çc][ãa]o\s+(?:pecuni[áa]ria|pe[cc]uni[áa]ria)',
        texto_lower, re.I
    ))
    
    if tem_servico and tem_pecuniaria:
        dados['modalidade'] = 'mista'
    elif tem_servico:
        dados['modalidade'] = 'servico'
    elif tem_pecuniaria:
        dados['modalidade'] = 'pecuniaria'
    elif dados['tipo'] == 'transacao_penal':
        # Verificar termos alternativos
        if re.search(r'multa', texto_lower, re.I):
            dados['modalidade'] = 'pecuniaria'
        elif re.search(r'servi[çc]o', texto_lower, re.I):
            dados['modalidade'] = 'servico'
    
    # ===== 3. EXTRAIR VALORES =====
    # Valor total da prestação (sem R$)
    val_total = re.search(
        r'(?:presta[çc][ãa]o\s+pecuni[áa]ria\s+(?:no\s+)?valor\s+(?:total\s+)?(?:de\s+)?|'
        r'valor\s+(?:total\s+)?(?:da\s+)?presta[çc][ãa]o\s+pecuni[áa]ria\s+(?:de\s+)?)'
        r'(?:R\$\s*)?([\d]+(?:[.,][\d]+)*)',
        texto, re.I
    )
    if not val_total:
        # Fallback: encontrar qualquer R$ seguido de valor
        val_total = re.search(
            r'R\$\s*([\d]+(?:[.,][\d]+)*)',
            texto
        )
    if val_total:
        dados['valor_total'] = val_total.group(1).strip()
    
    # Parcelas (aceita texto entre número e "parcelas")
    parc = re.search(r'(\d+)\s*(?:[\(\w\s\)]*\s*)?(?:parcelas?|vezes\s*de)', texto_lower, re.I)
    if parc:
        dados['parcelas'] = int(parc.group(1))
    
    # Valor da parcela (aceita texto entre "parcelas" e "de")
    val_parc = re.search(
        r'(?:parcelas?\s+(?:\w+\s+)*de\s+|vezes\s+de\s+)(?:R\$\s*)?([\d]+(?:[.,][\d]+)*)',
        texto, re.I
    )
    if val_parc:
        dados['valor_parcela'] = val_parc.group(1).strip()
    
    # ===== 4. EXTRAIR PRAZOS =====
    # Prazo em meses
    prazo_m = re.search(r'prazo\s+(?:de\s+)?(\d+)\s*mes(?:es)?', texto_lower, re.I)
    if prazo_m:
        dados['prazo_meses'] = int(prazo_m.group(1))
    
    # Prazo em dias
    prazo_d = re.search(r'prazo\s+(?:de\s+)?(\d+)\s*dias?', texto_lower, re.I)
    if prazo_d:
        dados['prazo_dias'] = int(prazo_d.group(1))
    
    # ===== 5. EXTRAIR CONDIÇÕES =====
    # Condições/obrigações
    cond_map = {
        'não praticar novo fato delituoso': 'nao_praticar_delito',
        'proibido de frequentar': 'nao_frequentar_locais',
        'não se ausentar da comarca': 'nao_ausentar_comarca',
        'comparecimento mensal': 'comparecimento_juizo',
        'comparecer mensalmente': 'comparecimento_juizo',
        'reparar o dano': 'reparar_dano',
        'proibido de portar armas': 'nao_portar_armas',
        'nos termos do art. 28': 'artigo_28_lei_11343',
    }
    for cond, key in cond_map.items():
        if cond in texto_lower:
            dados['condicoes'].append(key)
    
    # ===== 6. BENEFICIÁRIO (prestação de serviços) =====
    ben = re.search(
        r'(?:servi[çc]os?\s+(?:à|a)\s+|entidade\s+(?:benefici[áa]ria\s+)?)([\w\s]+?)(?:\.|\s+e\s+|,|\s*$)',
        texto, re.I
    )
    if ben:
        dados['beneficiario'] = ben.group(1).strip()
    
    # ===== 7. OBSERVAÇÕES ADICIONAIS =====
    # Dados do autor do fato (réu)
    # Normalmente: nome, CPF, etc. - extraídos do contexto da ata
    
    return dados


def formatar_cumprimento_para_oficio(dados):
    """
    Formata os dados extraídos para uso no ofício.
    Retorna dict com variáveis para o template.
    """
    ctx = {}
    
    if dados.get('modalidade') == 'pecuniaria':
        ctx['tem_prestacao_pecuniaria'] = True
        ctx['tem_prestacao_servico'] = False
        ctx['tipo_pena'] = 'prestação pecuniária'
        
        if dados['valor_total']:
            ctx['descricao_pecuniaria'] = f'prestação pecuniária no valor de R$ {dados["valor_total"]}'
        elif dados['valor_parcela'] and dados['parcelas']:
            ctx['descricao_pecuniaria'] = f'prestação pecuniária em {dados["parcelas"]} parcelas de R$ {dados["valor_parcela"]}'
        else:
            ctx['descricao_pecuniaria'] = 'prestação pecuniária'
            
    elif dados.get('modalidade') == 'servico':
        ctx['tem_prestacao_pecuniaria'] = False
        ctx['tem_prestacao_servico'] = True
        ctx['tipo_pena'] = 'prestação de serviços à comunidade'
        
        prazo = ''
        if dados['prazo_meses']:
            prazo = f' pelo prazo de {dados["prazo_meses"]} meses'
        elif dados['prazo_dias']:
            prazo = f' pelo prazo de {dados["prazo_dias"]} dias'
        
        ben = f' em benefício de {dados["beneficiario"]}' if dados.get('beneficiario') else ''
        ctx['descricao_servico'] = f'prestação de serviços à comunidade{ben}{prazo}'
    
    elif dados.get('modalidade') == 'mista':
        ctx['tem_prestacao_pecuniaria'] = True
        ctx['tem_prestacao_servico'] = True
        ctx['tipo_pena'] = 'prestação pecuniária e prestação de serviços à comunidade'
        
        if dados['valor_total']:
            ctx['descricao_pecuniaria'] = f'prestação pecuniária no valor de R$ {dados["valor_total"]}'
    
    if dados.get('parcelas'):
        ctx['parcelas_prestacao_pecuniaria'] = str(dados['parcelas'])
    if dados.get('valor_total'):
        ctx['valor_prestacao_pecuniaria'] = dados['valor_total']
    if dados.get('prazo_meses'):
        ctx['prazo_prestacao_servico'] = f'{dados["prazo_meses"]} meses'
    
    return ctx
