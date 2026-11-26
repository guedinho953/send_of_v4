"""Texto da certidão de recurso inominado (Ofício Circular 034/2015/COJE)."""

from __future__ import annotations

EVENTO_PADRAO = 'infra'

PREPARO_LABELS = {
    'gratuidade': 'Gratuidade / assistência judiciária',
    'completo': 'Preparo completo',
    'incompleto': 'Preparo incompleto',
    'nao_pago': 'Não houve preparo',
    'nao_verificado': 'Não verificado',
}


def texto_certidao_inominado(
    *,
    evento_recurso: str = EVENTO_PADRAO,
    tempestivo: bool,
    preparo_status: str = 'nao_verificado',
    habilitacao_regular: bool = True,
) -> str:
    """Gera o texto exato conforme a tempestividade e o preparo.

    Regra: se intempestivo, o preparo NÃO é verificado/mencionado.
    """
    evento = (evento_recurso or EVENTO_PADRAO).strip()
    base = (
        'Certifico, para os devidos fins, conforme as determinações do '
        'Ofício Circular nº 034/2015/COJE, de 10 de julho de 2015, que o '
        f'recurso inominado interposto no evento {evento} afigura-se '
    )

    if not tempestivo:
        texto = base + 'INTEMPESTIVO.'
    elif preparo_status == 'gratuidade':
        texto = base + (
            'TEMPESTIVO. Não houve o PREPARO, em razão do pedido de '
            'assistência judiciária gratuita.'
        )
    elif preparo_status == 'completo':
        texto = base + 'TEMPESTIVO e regularmente PREPARADO.'
    elif preparo_status == 'incompleto':
        texto = base + 'TEMPESTIVO, porém o PREPARO está INCOMPLETO.'
    elif preparo_status == 'nao_pago':
        texto = base + 'TEMPESTIVO, porém NÃO HOUVE O PREPARO.'
    else:
        texto = base + 'TEMPESTIVO. (Preparo não verificado.)'

    if habilitacao_regular:
        texto += (
            ' Certifico ainda a regularidade da habilitação dos advogados '
            'das partes, consoante pedidos realizados até a presente data, '
            'nos termos do art. 17 do Provimento nº CGJ 03/2010.'
        )

    return texto
