from .movimentacoes_service import extrair_comandos, DEST_MAP

ATO_TO_TIPO = {
    'oficie-se': 'oficio',
    'cite-se': 'mandado',
    'intime-se': 'intimacao',
    'intimem-se': 'intimacao',
    'notifique-se': 'intimacao',
}


def analisar_decisao(texto: str) -> list[dict]:
    return extrair_comandos(texto, 'despacho')


def sugerir_tipo_documento(comandos: list[dict]) -> str | None:
    for cmd in comandos:
        ato = cmd.get('ato', '').lower().strip().rstrip('.')
        for key, tipo in ATO_TO_TIPO.items():
            if key in ato:
                return tipo
    return None


def mapear_destinatarios(comandos: list[dict], parties) -> list[int]:
    selecionadas = set()
    for cmd in comandos:
        for dest in cmd.get('destinatario', []):
            dest_norm = dest.lower().strip().rstrip('.')
            role = DEST_MAP.get(dest_norm)
            if not role:
                for chave, mapped_role in DEST_MAP.items():
                    if chave in dest_norm:
                        role = mapped_role
                        break
            if role == 'todos':
                for p in parties:
                    selecionadas.add(p.id)
            elif role == 'mp':
                pass
            elif role:
                for p in parties:
                    if p.role == role:
                        selecionadas.add(p.id)
    return list(selecionadas)


def achar_template_por_tipo(rag, tipo: str):
    for t in rag.suggested_templates.all():
        if t.template_type == tipo:
            return t
    return rag.suggested_templates.first()


import re

# Extrair prazos/vagas de transação penal de atas de audiência
RE_PRAZO_SERVICO = re.compile(
    r'presta[çc][ãa]o\s+de\s+servi[çc]os\s+(?:à|a)\s+comunidade'
    r'(?:\s+por\s+|\s+d[eo]\s+|\s+no\s+prazo\s+de\s+)?'
    r'(\d+\s*(?:\([^)]+\))?\s*(?:m[eê]s(?:es)?|ano(?:s)?|dias?))',
    re.I
)

RE_PRAZO_PECUNIARIA = re.compile(
    r'presta[çc][ãa]o\s+pecuni[aá]ria'
    r'(?:\s+(?:no\s+)?valor\s+(?:de\s+)?)?'
    r'(R?\$?\s*[\d.,]+(?:\s*\([^)]+\))?(?:\s*s[aá]l[aá]rio[s]?\s+m[ií]nimo[s]?)?)'
    r'(?:.*?em\s+(\d+)\s*(?:parcela[s]?|vez[es]?))?',
    re.I
)

RE_PARCELAS = re.compile(
    r'em\s+(\d+)\s*(?:parcela[s]?|vez[es]?|presta[çc][õo]es?)',
    re.I
)

RE_CUMPRIMENTO_PRAZO = re.compile(
    r'(?:pelo\s+prazo\s+de|prazo\s+de)\s+(\d+\s*(?:\([^)]+\))?\s*(?:m[eê]s(?:es)?|ano(?:os)?|dias?))',
    re.I
)


def extrair_dados_audiencia(process) -> dict:
    from .models import Movement

    dados = {
        'prazo_prestacao_servico': '',
        'prazo_prestacao_pecuniaria': '',
        'valor_prestacao_pecuniaria': '',
        'parcelas_prestacao_pecuniaria': '',
    }

    movimentos = Movement.objects.filter(
        process=process
    ).exclude(
        category__in=['citacao', 'intimacao', 'certidao', 'mandado', 'outro']
    ).values_list('act_description', 'observation', 'act_normalized')

    textos = []
    for desc, obs, norm in movimentos:
        if desc:
            textos.append(desc)
        if obs:
            textos.append(obs)
        if norm:
            textos.append(norm)

    # Também busca em todos os movimentos que mencionam audiência/penal
    mov_penais = Movement.objects.filter(
        process=process,
        act_description__icontains='audiência'
    ) | Movement.objects.filter(
        process=process,
        act_description__icontains='transação'
    ) | Movement.objects.filter(
        process=process,
        act_description__icontains='penal'
    ) | Movement.objects.filter(
        process=process,
        observation__icontains='transação'
    )
    for m in mov_penais:
        if m.act_description:
            textos.append(m.act_description)
        if m.observation:
            textos.append(m.observation)
        if m.act_normalized:
            textos.append(m.act_normalized)

    for texto in textos:
        if not texto:
            continue
        texto = re.sub(r'\s+', ' ', texto).strip()

        # Prestação de serviços
        m = RE_PRAZO_SERVICO.search(texto)
        if m and not dados['prazo_prestacao_servico']:
            dados['prazo_prestacao_servico'] = m.group(1).strip()

        # Prestação pecuniária
        m = RE_PRAZO_PECUNIARIA.search(texto)
        if m:
            if m.group(1) and not dados['valor_prestacao_pecuniaria']:
                dados['valor_prestacao_pecuniaria'] = m.group(1).strip()
            if m.group(2) and not dados['parcelas_prestacao_pecuniaria']:
                dados['parcelas_prestacao_pecuniaria'] = m.group(2).strip()
            if not dados['prazo_prestacao_pecuniaria']:
                dados['prazo_prestacao_pecuniaria'] = m.group(0).strip()

        # Parcelas avulsas
        m = RE_PARCELAS.search(texto)
        if m and not dados['parcelas_prestacao_pecuniaria']:
            dados['parcelas_prestacao_pecuniaria'] = m.group(1).strip()

    return dados
