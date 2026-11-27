"""Assinantes padrão das certidões."""

ASSINANTES = {
    'ivan': (
        'IVAN GUEDES DA SILVA',
        'Secretário em Substituição',
    ),
    'ivan_servidor': (
        'IVAN GUEDES DA SILVA',
        'Servidor Secretaria 2',
    ),
    'mauro': (
        'MAURO EMÍLIO VIANA DA SILVA MOREIRA',
        'Secretário',
    ),
}

ASSINANTE_PADRAO = 'ivan_servidor'


def resolver_assinante(chave=None, nome='', cargo=''):
    """Resolve a assinatura escolhida na tela (inclui a opção 'outro')."""
    chave = (chave or ASSINANTE_PADRAO).strip()
    if chave == 'outro':
        padrao = ASSINANTES[ASSINANTE_PADRAO]
        return (nome.strip() or padrao[0], cargo.strip() or padrao[1])
    return ASSINANTES.get(chave, ASSINANTES[ASSINANTE_PADRAO])
