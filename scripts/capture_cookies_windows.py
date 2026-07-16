#!/usr/bin/env python3
"""
capture_cookies_windows.py - Roda no Windows nativo

Captura cookies do Firefox via browser_cookie3 e salva em JSON
para o Django no WSL usar.

INSTALACAO Windows:
    pip install browser_cookie3

USO:
    python scripts/capture_cookies_windows.py

Requisitos:
    - Firefox aberto e logado no Projudi
    - Windows (browser_cookie3 usa criptografia nativa do SO)
"""

import json
import time
from pathlib import Path
import browser_cookie3

DOMAIN = 'projudi.tjba.jus.br'
OUTPUT_DIR = Path("D:/Projudi")
OUTPUT_FILE = OUTPUT_DIR / "cookies.json"


def capture_cookies():
    """Captura cookies do Firefox via browser_cookie3."""
    print("=" * 60)
    print("Captura de Cookies - Projudi")
    print("=" * 60)
    
    # Tenta Firefox primeiro (mais comum)
    browsers = ['firefox', 'chrome', 'edge']
    
    for browser_name in browsers:
        try:
            cj = getattr(browser_cookie3, browser_name)(domain_name=DOMAIN)
            cookies = {c.name: c.value for c in cj}
            
            if cookies:
                print(f"\n[OK] {len(cookies)} cookies capturados do {browser_name}")
                print(f"     Keys: {list(cookies.keys())}")
                return cookies
        except Exception as e:
            print(f"\n[IGNORADO] {browser_name}: {e}")
    
    return {}


def save_cookies(cookies):
    """Salva cookies em JSON."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(cookies, f, indent=2, ensure_ascii=False)
    
    print(f"\n[INFO] Cookies salvos em: {OUTPUT_FILE}")


def main():
    cookies = capture_cookies()
    
    if not cookies:
        print("\n[ERRO] Nenhum cookie encontrado!")
        print("       Certifique-se de estar logado no Projudi no navegador.")
        return 1
    
    if 'JSESSIONID' not in cookies:
        print("\n[AVISO] JSESSIONID nao encontrado!")
        print("        A sessao pode estar expirada ou o navegador nao esta logado.")
    
    save_cookies(cookies)
    
    # Mantem rodando com keep-alive (opcional)
    print("\n[INFO] Rodando keep-alive (Ctrl+C para parar)...")
    try:
        while True:
            time.sleep(60)
            # Re-captura a cada minuto
            new_cookies = capture_cookies()
            if new_cookies and 'JSESSIONID' in new_cookies:
                save_cookies(new_cookies)
                print("[OK] Cookies renovados")
    except KeyboardInterrupt:
        print("\n[OK] Encerrado.")
    
    return 0


if __name__ == "__main__":
    exit(main())
