#!/usr/bin/env python3
"""
capture_cookies_windows.py - Captura cookies do Projudi

Captura cookies do Firefox e salva em JSON para o Django usar.

IMPORTANTE:
- Pode rodar no Windows nativo ou no WSL. No WSL, procura o Firefox do
  Windows em /mnt/c e grava em /mnt/d/Projudi/cookies.json.
- O Firefox pode estar aberto. O script le tambem o arquivo -wal do
  cookies.sqlite; sem isso o browser_cookie3 nao enxerga os cookies
  recentes enquanto o Firefox esta aberto.

INSTALACAO Windows:
    pip install browser_cookie3

USO:
    python scripts/capture_cookies_windows.py
    python scripts/capture_cookies_windows.py --quiet
"""

import glob
import json
import os
import sys
import time
import shutil
import sqlite3
import tempfile
from pathlib import Path

try:
    import browser_cookie3
except ImportError:
    print("[ERRO] browser_cookie3 nao instalado.")
    print("       Instale com: python -m pip install browser_cookie3")
    raise SystemExit(1)

DOMAIN = 'projudi.tjba.jus.br'

# Windows nativo grava em D:\Projudi. No WSL, a mesma pasta aparece como
# /mnt/d/Projudi (o Django le esse caminho).
if os.name == 'nt':
    OUTPUT_DIR = Path("D:/Projudi")
elif Path('/mnt/d/Projudi').exists():
    OUTPUT_DIR = Path('/mnt/d/Projudi')
else:
    OUTPUT_DIR = Path.home() / '.projudi'
OUTPUT_FILE = OUTPUT_DIR / "cookies.json"


def _log(message, quiet=False):
    if not quiet:
        print(message)


def _firefox_profile_cookie_files():
    """
    Descobre os cookies.sqlite do Firefox.

    No Windows, usa o perfil padrao do browser_cookie3. No WSL, inclui
    tambem os perfis do Firefox do Windows vistos em /mnt/c. Assim o
    script funciona tanto no Windows nativo quanto dentro do WSL.
    """
    arquivos = []

    try:
        # A classe apenas localiza o arquivo; a leitura e feita abaixo.
        padrao = Path(browser_cookie3.Firefox(domain_name=DOMAIN).cookie_file)
        if padrao.exists():
            arquivos.append(padrao)
    except Exception:
        pass

    if os.name != 'nt':
        for caminho in glob.glob(
            '/mnt/c/Users/*/AppData/Roaming/Mozilla/Firefox/Profiles/*/cookies.sqlite'
        ):
            p = Path(caminho)
            if p.exists() and p not in arquivos:
                arquivos.append(p)

    return arquivos


def _read_firefox_sqlite(cookie_file):
    """Le um cookies.sqlite junto com -wal e -shm."""
    with tempfile.TemporaryDirectory() as tmpdir:
        destino = Path(tmpdir) / 'cookies.sqlite'
        for suffix in ('', '-wal', '-shm'):
            origem = Path(str(cookie_file) + suffix)
            if origem.exists():
                shutil.copy2(origem, Path(str(destino) + suffix))

        con = sqlite3.connect(str(destino))
        try:
            rows = con.execute(
                "SELECT name, value FROM moz_cookies WHERE host LIKE ?",
                (f'%{DOMAIN}%',),
            ).fetchall()
        finally:
            con.close()

    return {name: value for name, value in rows}


def _extract_firefox_sqlite():
    """
    Le o cookies.sqlite do Firefox junto com -wal e -shm.

    O browser_cookie3 copia apenas o banco principal. Com o Firefox
    aberto, o cookie JSESSIONID pode estar somente no WAL. Essa leitura
    direta resolve exatamente esse caso.
    """
    encontrados = {}

    for cookie_file in _firefox_profile_cookie_files():
        try:
            cookies = _read_firefox_sqlite(cookie_file)
        except Exception as e:
            _log(f"[IGNORADO] Firefox {cookie_file}: {e}", quiet=True)
            continue

        if cookies:
            encontrados.update(cookies)
            if 'JSESSIONID' in cookies:
                return encontrados

    return encontrados


def capture_cookies(quiet=False):
    """Captura cookies do Firefox, Chrome ou Edge."""
    _log("=" * 60, quiet)
    _log("Captura de Cookies - Projudi", quiet)
    _log("=" * 60, quiet)

    cookies = {}

    # 1) Firefox direto do SQLite + WAL. Funciona com o Firefox aberto.
    try:
        firefox_cookies = _extract_firefox_sqlite()
        if firefox_cookies:
            cookies.update(firefox_cookies)
            _log(
                f"\n[OK] {len(firefox_cookies)} cookies do Firefox "
                "(SQLite + WAL)",
                quiet,
            )
            _log(f"     Keys: {list(firefox_cookies.keys())}", quiet)
            if 'JSESSIONID' in firefox_cookies:
                return cookies
    except Exception as e:
        _log(f"\n[IGNORADO] Firefox SQLite: {e}", quiet)

    # 2) browser_cookie3: cobre cookies de sessao no sessionstore.
    try:
        cj = browser_cookie3.firefox(domain_name=DOMAIN)
        extras = {c.name: c.value for c in cj}
        if extras:
            _log(
                f"\n[OK] {len(extras)} cookies extras do Firefox "
                "(browser_cookie3)",
                quiet,
            )
            _log(f"     Keys: {list(extras.keys())}", quiet)
            for name, value in extras.items():
                cookies.setdefault(name, value)
            if 'JSESSIONID' in cookies:
                return cookies
    except Exception as e:
        _log(f"\n[IGNORADO] Firefox browser_cookie3: {e}", quiet)

    # 3) Chrome/Edge. Em geral exigem execucao como administrador.
    for browser_name in ('chrome', 'edge'):
        try:
            cj = getattr(browser_cookie3, browser_name)(domain_name=DOMAIN)
            extras = {c.name: c.value for c in cj}
            if extras:
                _log(
                    f"\n[OK] {len(extras)} cookies do {browser_name}",
                    quiet,
                )
                _log(f"     Keys: {list(extras.keys())}", quiet)
                for name, value in extras.items():
                    cookies.setdefault(name, value)
                if 'JSESSIONID' in cookies:
                    return cookies
        except Exception as e:
            _log(f"\n[IGNORADO] {browser_name}: {e}", quiet)

    return cookies


def save_cookies(cookies, quiet=False):
    """Salva cookies em JSON."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(cookies, f, indent=2, ensure_ascii=False)

    _log(f"\n[INFO] Cookies salvos em: {OUTPUT_FILE}", quiet)


def main():
    quiet = '--quiet' in sys.argv

    cookies = capture_cookies(quiet=quiet)

    if not cookies:
        if quiet:
            return 1  # silent exit for automation
        print("\n[ERRO] Nenhum cookie encontrado!")
        print("       Certifique-se de estar logado no Projudi no Firefox.")
        return 1

    if 'JSESSIONID' not in cookies:
        if not quiet:
            print("\n[AVISO] JSESSIONID nao encontrado!")
            print("        A sessao pode estar expirada ou o navegador nao esta logado.")
        return 1

    save_cookies(cookies, quiet=quiet)

    # Keep-alive loop (apenas em modo interativo)
    if not quiet:
        print("\n[INFO] Rodando keep-alive (Ctrl+C para parar)...")
        try:
            while True:
                time.sleep(60)
                new_cookies = capture_cookies(quiet=True)
                if new_cookies and 'JSESSIONID' in new_cookies:
                    save_cookies(new_cookies, quiet=True)
                    print("[OK] Cookies renovados")
        except KeyboardInterrupt:
            print("\n[OK] Encerrado.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
