import requests
import browser_cookie3
import threading
import time
import os
import sqlite3
import glob
import shutil
import tempfile

# Suporte a múltiplos navegadores e caminho customizado do Windows via WSL

def get_cookies_from_browser(domain='projudi.tjba.jus.br', browser='auto', profile_path=None):
    """
    Tenta capturar cookies do navegador especificado.
    browser: 'auto', 'firefox', 'chrome', 'edge', 'chromium'
    profile_path: caminho customizado do perfil (ex: Windows no WSL)
    """
    errors = []
    
    # Tenta extrair cookies via SQLite (funciona para cookies comuns, nao para session cookies)
    def _try_sqlite_extract(path, label):
        try:
            c = _extract_firefox_cookies_custom(path, domain)
            if c and 'JSESSIONID' in c:
                print(f"Cookies capturados do Firefox {label}")
                return c
            if c:
                print(f"[INFO] SQLite {label}: achou {len(c)} cookies (sem JSESSIONID)")
        except Exception as e:
            errors.append(f"SQLite {label}: {e}")
        return None

    if profile_path:
        result = _try_sqlite_extract(profile_path, '(path: {profile_path})')
        if result:
            return result

    if browser in ('auto', 'firefox'):
        win_profiles = glob.glob('/mnt/c/Users/*/AppData/Roaming/Mozilla/Firefox/Profiles/*.default*')
        for p in win_profiles:
            result = _try_sqlite_extract(p, f'Windows: {p}')
            if result:
                return result
    
    navegadores = {
        'chrome': browser_cookie3.chrome,
        'chromium': browser_cookie3.chromium,
        'edge': browser_cookie3.edge,
        'firefox': browser_cookie3.firefox,
        'opera': browser_cookie3.opera,
        'brave': browser_cookie3.brave,
    }
    
    if browser != 'auto':
        if browser in navegadores:
            try:
                cj = navegadores[browser](domain_name=domain)
                return {c.name: c.value for c in cj}
            except Exception as e:
                errors.append(f"{browser}: {e}")
    else:
        for name, func in navegadores.items():
            try:
                cj = func(domain_name=domain)
                cookies = {c.name: c.value for c in cj}
                if cookies:
                    print(f"Cookies capturados do {name}")
                    return cookies
            except Exception as e:
                errors.append(f"{name}: {e}")
    
    print(f"Erro ao capturar cookies: {errors}")
    return {}


def _extract_firefox_cookies_custom(profile_path, domain):
    """Extrai cookies de um perfil Firefox customizado (ex: Windows via WSL)"""
    db_path = os.path.join(profile_path, 'cookies.sqlite')
    
    if not os.path.exists(db_path):
        return {}
    
    # Copia SQLite + WAL + SHM para temp (WAL tem dados nao comitados)
    with tempfile.TemporaryDirectory() as tmpdir:
        for suffix in ('', '-wal', '-shm'):
            src = db_path + suffix
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(tmpdir, 'cookies.sqlite' + suffix))
        
        tmp_path = os.path.join(tmpdir, 'cookies.sqlite')
        conn = sqlite3.connect(tmp_path)
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT name, value, host FROM moz_cookies 
            WHERE host LIKE ?
        """, (f'%{domain}%',))
        
        rows = cursor.fetchall()
        cookies = {}
        for name, value, host in rows:
            cookies[name] = value
        
        conn.close()
    
    return cookies


class ProjudiBot:
    BASE_URL = "https://projudi.tjba.jus.br/projudi/cadastros/AnalisarMovimentacao"

    def __init__(self, browser='auto', profile_path=None):
        self.session = requests.Session()
        self.ultimo_ping = time.time()
        self._keep_alive = False
        self.browser = browser
        self.profile_path = profile_path

    def marcar_atividade(self):
        self.ultimo_ping = time.time()

    def get_cookies(self):
        return get_cookies_from_browser(
            domain='projudi.tjba.jus.br',
            browser=self.browser,
            profile_path=self.profile_path
        )

    def criar_sessao(self):
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Connection": "keep-alive",
            "Referer": "https://projudi.tjba.jus.br/projudi/",
            "Origin": "https://projudi.tjba.jus.br"
        })

        cookies = self.get_cookies()
        self.session.cookies.update(cookies)
        return self.session

    #  valida login REAL (não só texto login)
    def testar_login(self):

        r = self.session.get(self.BASE_URL)

        if "login" in r.url.lower():
            print(" Não autenticado")
            return False

        if "login" in r.text.lower():
            print(" Possível sessão inválida")
            return False

        print("Autenticado")
        return True
    
    def _loop_keep_alive(self, intervalo=60):
        while self._keep_alive:
            agora = time.time()

            if agora - self.ultimo_ping >= intervalo:
                try:
                    resp = self.session.get(self.BASE_URL)

                    html = resp.text.lower()

                    if (
                        "login" in html
                        or "senha" in html
                        or "sess" in html  # pega variações
                    ):
                        print(" Sessão expirou REAL")
                        self._keep_alive = False
                        break
                    else:
                        print(" Sessão mantida ativa REAL")

                    self.ultimo_ping = agora

                except Exception as e:
                    print("Erro keep-alive:", e)

            time.sleep(5)#  export seguro (sem conflito)

    def exportar_cookies(self):
        return self.session.cookies.get_dict()
    

    def mostrar_cookies(self):
        print("\n COOKIES:\n")
        for k, v in self.session.cookies.items():
            print(f"{k} = {v}")

    def iniciar_keep_alive(self):
        self._keep_alive = True
        t = threading.Thread(target=self._loop_keep_alive, daemon=True)
        t.start()

    def exportar_cookies_para_arquivo(self, caminho=None):
        """Salva cookies da sessão em um arquivo JSON para uso no WSL."""
        import json
        if caminho is None:
            # Padrao: pasta do projeto ou mnt/d
            from pathlib import Path
            possiveis = [
                Path('/mnt/d/Projudi/cookies.json'),
                Path.home() / '.projudi_cookies.json',
                Path('/tmp/projudi_cookies.json'),
            ]
            for p in possiveis:
                p.parent.mkdir(parents=True, exist_ok=True)
                if p.parent.exists():
                    caminho = str(p)
                    break
        
        cookies = self.exportar_cookies()
        with open(caminho, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, indent=2, ensure_ascii=False)
        print(f"[INFO] Cookies exportados para: {caminho}")
        return caminho

    @staticmethod
    def carregar_cookies_do_arquivo(caminho=None):
        """Carrega cookies de um arquivo JSON (usado no WSL)."""
        import json
        from pathlib import Path
        if caminho is None:
            possiveis = [
                Path('/mnt/d/Projudi/cookies.json'),
                Path.home() / '.projudi_cookies.json',
                Path('/tmp/projudi_cookies.json'),
            ]
            for p in possiveis:
                if p.exists():
                    caminho = str(p)
                    break
        
        if caminho and Path(caminho).exists():
            with open(caminho, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def executar(self):
        self.criar_sessao()

        self.session.get(self.BASE_URL)

        if not self.testar_login():
            return
        print("Status OK")

        # Salva cookies em arquivo para uso no WSL
        self.exportar_cookies_para_arquivo()

        self.iniciar_keep_alive()


if __name__ == "__main__":
    bot = ProjudiBot()
    bot.executar()
    bot.mostrar_cookies()
    try:
        while bot._keep_alive:
            print(f"Bot rodando... | Último ping: {int(time.time() - bot.ultimo_ping)}s")
            time.sleep(180)
    finally:
        print("Programa encerrado (sessão caiu)")