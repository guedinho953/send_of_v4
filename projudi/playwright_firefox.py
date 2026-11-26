"""Lançamento centralizado do Firefox usado pela automação (Playwright).

O Playwright usa um build próprio do Firefox (com patches) e NÃO controla o
Firefox instalado no sistema. O Firefox local é usado para login/cookies; a
automação abre o Firefox do Playwright já com os cookies injetados.

Variáveis de ambiente suportadas:

* ``PLAYWRIGHT_HEADLESS=1``       abre sem janela (padrão: com janela);
* ``PLAYWRIGHT_FIREFOX_EXECUTABLE`` caminho de um build compatível do Firefox
  (normalmente não é necessário — deixe vazio para usar o build do Playwright);
* ``PLAYWRIGHT_BROWSERS_PATH``    pasta dos navegadores (use ``0`` no portátil
  para guardar dentro do pacote do Playwright).
"""

from __future__ import annotations

import os
from typing import Any, Dict

try:
    # Garante que o .env seja carregado mesmo em scripts executados fora do
    # Django (o módulo lê PLAYWRIGHT_HEADLESS etc.).
    import firefox_config  # noqa: F401
except ImportError:
    pass


def _env_bool(nome: str, padrao: bool = False) -> bool:
    valor = os.environ.get(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in ('1', 'true', 'sim', 'yes', 'on')


def firefox_launch_options(**overrides: Any) -> Dict[str, Any]:
    """Monta os argumentos de ``pw.firefox.launch`` para o sistema atual."""
    opcoes: Dict[str, Any] = {
        'headless': _env_bool('PLAYWRIGHT_HEADLESS', False),
    }

    slow_mo = overrides.pop('slow_mo', None)
    if slow_mo is not None:
        opcoes['slow_mo'] = slow_mo

    # Ajustes de renderização só fazem sentido em Linux/WSL. No Windows eles
    # são desnecessários e podem até atrapalhar.
    if os.name != 'nt':
        opcoes['env'] = {
            **os.environ,
            'MOZ_DISABLE_GPU_SANDBOX': '1',
            'LIBGL_ALWAYS_SOFTWARE': '1',
        }
        opcoes['firefox_user_prefs'] = {'gfx.webrender.software': True}

    executavel = os.environ.get('PLAYWRIGHT_FIREFOX_EXECUTABLE')
    if executavel and os.path.isfile(executavel):
        opcoes['executable_path'] = executavel

    opcoes.update(overrides)
    return opcoes


def launch_firefox(pw, **overrides: Any):
    """Abre o Firefox do Playwright com as opções adequadas ao sistema."""
    return pw.firefox.launch(**firefox_launch_options(**overrides))
