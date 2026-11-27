"""Assinantes padrão das certidões."""

ASSINANTES = {
    'ivan': (
        'Ivan Guedes da Silva',
        'Secretário em Substituição',
    ),
    'ivan_servidor': (
        'Ivan Guedes da Silva',
        'Servidor de Secretaria 2',
    ),
    'mauro': (
        'Mauro Emílio Viana da Silva Moreira',
        'Secretário',
    ),
}

ASSINANTE_PADRAO = 'ivan'


def resolver_assinante(chave=None, nome='', cargo=''):
    """Resolve a assinatura escolhida na tela (inclui a opção 'outro')."""
    chave = (chave or ASSINANTE_PADRAO).strip()
    if chave == 'outro':
        padrao = ASSINANTES[ASSINANTE_PADRAO]
        return (nome.strip() or padrao[0], cargo.strip() or padrao[1])
    return ASSINANTES.get(chave, ASSINANTES[ASSINANTE_PADRAO])
