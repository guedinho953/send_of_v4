"""Leitura/gravação dos HTMLs de certidão em Latin-1.

O Projudi/editor da Vara trabalha melhor com ISO-8859-1. Caracteres que
não existem nessa tabela (ex.: travessão) são gravados como entidades
HTML (``&#8212;``), preservando a aparência no navegador.
"""

from pathlib import Path

ENCODING_CERTIDAO = 'latin-1'


def escrever_certidao(caminho, html: str) -> None:
    """Grava o HTML da certidão em Latin-1, com fallback para entidades."""
    Path(caminho).write_text(
        html,
        encoding=ENCODING_CERTIDAO,
        errors='xmlcharrefreplace',
    )


def ler_certidao(caminho) -> str:
    """Lê HTML antigo (UTF-8) ou novo (Latin-1) sem perder acentos."""
    dados = Path(caminho).read_bytes()
    try:
        return dados.decode('utf-8')
    except UnicodeDecodeError:
        return dados.decode(ENCODING_CERTIDAO, errors='replace')
