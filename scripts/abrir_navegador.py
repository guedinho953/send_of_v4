#!/usr/bin/env python3
"""Abre uma URL no Firefox local (ou no navegador padrão).

Uso:
    python scripts/abrir_navegador.py http://127.0.0.1:8000/ --delay 3
    python scripts/abrir_navegador.py https://projudi.tjba.jus.br/projudi/
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import firefox_config


def main() -> int:
    args = sys.argv[1:]
    delay = 0.0
    if '--delay' in args:
        indice = args.index('--delay')
        try:
            delay = float(args[indice + 1])
            del args[indice:indice + 2]
        except (IndexError, ValueError):
            pass

    url = args[0] if args else 'http://127.0.0.1:8000/'

    atraso_env = os.environ.get('ABRIR_NAVEGADOR_DELAY')
    if atraso_env and not delay:
        try:
            delay = float(atraso_env)
        except ValueError:
            pass

    if delay > 0:
        time.sleep(delay)

    firefox = firefox_config.find_firefox()
    if firefox:
        if os.name == 'nt':
            subprocess.Popen([str(firefox), url], close_fds=True)
        else:
            subprocess.Popen(
                [str(firefox), url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        print(f'Abrindo no Firefox: {url}')
    else:
        print('Firefox nao encontrado; abrindo no navegador padrao.')
        webbrowser.open(url)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
