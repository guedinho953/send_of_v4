import threading
import time
from pathlib import Path

import requests

import firefox_config

# Suporte a múltiplos navegadores e caminho customizado do perfil.
# A detecção de Windows/WSL/Linux fica centralizada em firefox_config.py.


def get_cookies_from_browser(domain='projudi.tjba.jus.br', browser='auto', profile_path=None):
    """
    Tenta capturar cookies do navegador especificado.

    browser: 'auto', 'firefox', 'chrome', 'edge', 'chromium'
    profile_path: caminho customizado do perfil do Firefox
    """
    errors = []

    if browser in ('auto', 'firefox'):
        if profile_path:
            try:
                cookies = firefox_config.read_firefox_sqlite(
                    Path(profile_path) / 'cookies.sqlite',
                    domain,
                )
                if cookies and 'JSESSIONID' in cookies:
                    print(f'Cookies capturados do Firefox (path: {profile_path})')
                    return cookies
                if cookies:
                    print(f'[INFO] SQLite {profile_path}: achou '
                          f'{len(cookies)} cookies (sem JSESSIONID)')
            except Exception as e:
                errors.append(f'SQLite {profile_path}: {e}')

        for perfil in firefox_config.firefox_profiles():
            try:
                cookies = firefox_config.read_firefox_sqlite(
                    perfil / 'cookies.sqlite', domain)
                if cookies and 'JSESSIONID' in cookies:
                    print(f'Cookies capturados do Firefox: {perfil}')
                    return cookies
                if cookies:
                    print(f'[INFO] SQLite {perfil}: achou '
                          f'{len(cookies)} cookies (sem JSESSIONID)')
            except Exception as e:
                errors.append(f'SQLite {perfil}: {e}')

    if browser != 'auto':
        return _cookies_browser_cookie3(browser, domain, errors)

    return _cookies_browser_cookie3('auto', domain, errors)


def _cookies_browser_cookie3(browser, domain, errors):
    try:
        import browser_cookie3
    except ImportError:
        print('[ERRO] browser_cookie3 nao instalado.')
        return {}

    navegadores = {
        'chrome': browser_cookie3.chrome,
        'chromium': browser_cookie3.chromium,
        'edge': browser_cookie3.edge,
        'firefox': browser_cookie3.firefox,
        'opera': browser_cookie3.opera,
        'brave': browser_cookie3.brave,
    }

    if browser != 'auto':
        func = navegadores.get(browser)
        if func is None:
            return {}
        try:
            jar = func(domain_name=domain)
            return {c.name: c.value for c in jar}
        except Exception as e:
            errors.append(f'{browser}: {e}')
            print(f'Erro ao capturar cookies: {errors}')
            return {}

    for nome in ('firefox', 'edge', 'chrome', 'chromium', 'brave', 'opera'):
        try:
            jar = navegadores[nome](domain_name=domain)
            cookies = {c.name: c.value for c in jar}
            if cookies:
                print(f'Cookies capturados do {nome}')
                return cookies
        except Exception as e:
            errors.append(f'{nome}: {e}')

    print(f'Erro ao capturar cookies: {errors}')
    return {}


def _extract_firefox_cookies_custom(profile_path, domain):
    """Extrai cookies de um perfil Firefox customizado (compatibilidade)."""
    try:
        return firefox_config.read_firefox_sqlite(
            Path(profile_path) / 'cookies.sqlite', domain)
    except Exception:
        return {}


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
        r = self.session.get(self.BASE_URL, allow_redirects=True)
        url = r.url.lower()
        texto = r.text.lower()

        if "login" in url:
            print(" Não autenticado")
            return False

        # A página autenticada pode conter a palavra "login" em links,
        # scripts ou menus. Só trate como login se houver os campos do
        # formulário de autenticação.
        campos_login = (
            'name="login"', "name='login'",
            'name="senha"', "name='senha'",
        )
        if any(campo in texto for campo in campos_login):
            print(" Possível sessão inválida")
            return False

        if "expirou" in texto[:800]:
            print(" Sessão expirada")
            return False

        if len(r.text) < 500:
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
        """Salva cookies da sessão em um arquivo JSON compartilhado."""
        cookies = self.exportar_cookies()
        destino = firefox_config.write_cookies(cookies, caminho)
        print(f'[INFO] Cookies exportados para: {destino}')
        return str(destino)

    @staticmethod
    def carregar_cookies_do_arquivo(caminho=None):
        """Carrega cookies do arquivo JSON compartilhado."""
        return firefox_config.read_cookies(caminho)

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