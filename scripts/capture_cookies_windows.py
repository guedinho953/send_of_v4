#!/usr/bin/env python3
"""Captura cookies do Firefox local e salva em JSON para o Django.

Funciona em Windows nativo, WSL e Linux:

* Descobre os perfis do Firefox (profiles.ini / %APPDATA% / ~/.mozilla);
* Lê o ``cookies.sqlite`` junto com ``-wal`` e ``-shm`` (o que faz funcionar
  com o Firefox aberto);
* Usa ``browser_cookie3`` como complemento;
* Grava no mesmo caminho que o Django lê (veja ``firefox_config``).

USO:
    python scripts/capture_cookies_windows.py
    python scripts/capture_cookies_windows.py --quiet
"""

import sys
import time
from pathlib import Path

# Garante que o módulo firefox_config (na raiz do projeto) seja encontrado
# mesmo quando o script é chamado de outro diretório.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import firefox_config


def _log(message, quiet=False):
    if not quiet:
        print(message)


def capture_cookies(quiet=False):
    """Captura cookies do Firefox, Chrome ou Edge."""
    _log("=" * 60, quiet)
    _log("Captura de Cookies - Projudi", quiet)
    _log("=" * 60, quiet)

    _log(f"[INFO] Firefox: {firefox_config.find_firefox() or 'nao encontrado'}", quiet)
    _log(f"[INFO] Perfil:  {firefox_config.default_firefox_profile() or 'nao encontrado'}", quiet)

    cookies = firefox_config.capture_cookies()

    if cookies:
        _log(f"\n[OK] {len(cookies)} cookies do Firefox local", quiet)
        _log(f"     Keys: {list(cookies.keys())}", quiet)
        if 'JSESSIONID' in cookies:
            return cookies
        _log("[AVISO] JSESSIONID nao encontrado nos cookies do Firefox.", quiet)

    # Complemento: Chrome/Edge (nem sempre disponíveis)
    try:
        import browser_cookie3
    except ImportError:
        browser_cookie3 = None

    if browser_cookie3:
        for browser_name in ('chrome', 'edge'):
            try:
                jar = getattr(browser_cookie3, browser_name)(
                    domain_name=firefox_config.DOMAIN)
                extras = {c.name: c.value for c in jar}
                if extras:
                    _log(f"\n[OK] {len(extras)} cookies do {browser_name}", quiet)
                    _log(f"     Keys: {list(extras.keys())}", quiet)
                    for name, value in extras.items():
                        cookies.setdefault(name, value)
                    if 'JSESSIONID' in cookies:
                        return cookies
            except Exception as e:
                _log(f"\n[IGNORADO] {browser_name}: {e}", quiet)

    return cookies


def save_cookies(cookies, quiet=False):
    destino = firefox_config.write_cookies(cookies)
    _log(f"\n[INFO] Cookies salvos em: {destino}", quiet)
    return destino


def main():
    quiet = '--quiet' in sys.argv

    cookies = capture_cookies(quiet=quiet)

    if not cookies:
        if quiet:
            return 1  # saída silenciosa para automação
        print("\n[ERRO] Nenhum cookie encontrado!")
        print("       Certifique-se de estar logado no Projudi no Firefox.")
        return 1

    if 'JSESSIONID' not in cookies:
        if not quiet:
            print("\n[AVISO] JSESSIONID nao encontrado!")
            print("        A sessao pode estar expirada ou o navegador nao esta logado.")
        return 1

    save_cookies(cookies, quiet=quiet)

    # Keep-alive apenas no modo interativo
    if not quiet:
        print("\n[INFO] Rodando keep-alive (Ctrl+C para parar)...")
        try:
            while True:
                time.sleep(60)
                novos = firefox_config.capture_cookies()
                if novos and 'JSESSIONID' in novos:
                    save_cookies(novos, quiet=True)
                    print("[OK] Cookies renovados")
        except KeyboardInterrupt:
            print("\n[OK] Encerrado.")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
