"""Caminhos temporários portáveis (Windows, WSL e Linux).

Vários fluxos do projeto gravavam screenshots e filas em ``/tmp``, que no
Windows aponta para ``\\tmp`` na raiz do drive atual (quase sempre sem
permissão ou inexistente). Este módulo concentra esses caminhos.

Pode ser configurado com a variável de ambiente ``SEND_OF_TMP_DIR``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def temp_dir() -> Path:
    """Pasta temporária do projeto, criada se necessário."""
    configurado = os.environ.get('SEND_OF_TMP_DIR')
    if configurado:
        pasta = Path(configurado).expanduser()
    else:
        pasta = Path(tempfile.gettempdir()) / 'send_of_v4'
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def temp_file(nome: str) -> Path:
    return temp_dir() / nome


def temp_subdir(nome: str) -> Path:
    pasta = temp_dir() / nome
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def queue_file(nome: str) -> Path:
    """Arquivos de fila/sinal compartilhados entre views e scripts."""
    return temp_file(nome)
