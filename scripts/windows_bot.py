#!/usr/bin/env python3
"""
windows_bot.py - Roda no Windows nativo (cmd/powershell)

Captura cookies do Firefox via browser_cookie3 e salva em JSON
para o Django no WSL usar.

Uso:
    python scripts/windows_bot.py

Requisitos Windows:
    - Python instalado
    - browser_cookie3: pip install browser_cookie3
    - Firefox com sessão logada no Projudi
"""

import json
import sys
from pathlib import Path

# Adiciona o projeto ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from projudi_bot import ProjudiBot


def main():
    print("=" * 60)
    print("Projudi Bot - Captura de Cookies para WSL")
    print("=" * 60)
    
    bot = ProjudiBot()
    bot.criar_sessao()
    
    cookies = bot.exportar_cookies()
    print(f"\nCookies capturados: {len(cookies)}")
    print(f"Keys: {list(cookies.keys())}")
    
    # Testa se está autenticado
    if bot.testar_login():
        print("\n[OK] Sessão válida!")
    else:
        print("\n[AVISO] Sessão pode estar expirada. Faça login no Firefox e rode novamente.")
        return 1
    
    # Salva em JSON (usa o novo método do bot)
    caminho = bot.exportar_cookies_para_arquivo()
    print(f"\n[INFO] Cookies salvos em: {caminho}")
    
    # Também salva em local acessível pelo WSL
    wsl_path = Path("D:/Projudi/cookies.json")
    wsl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(wsl_path, 'w', encoding='utf-8') as f:
        json.dump(cookies, f, indent=2, ensure_ascii=False)
    print(f"[INFO] Também salvo em: {wsl_path} (para WSL)")
    
    # Mantém sessão viva
    print("\n[INFO] Iniciando keep-alive...")
    bot.iniciar_keep_alive()
    
    try:
        while bot._keep_alive:
            import time
            print(f"Bot rodando... | Último ping: {int(time.time() - bot.ultimo_ping)}s")
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n[OK] Bot encerrado pelo usuário.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
