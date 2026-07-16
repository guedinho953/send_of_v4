import requests
import browser_cookie3
import threading
import time
# import sys

# sys.stdout.reconfigure(encoding='utf-8')


class ProjudiBot:

    BASE_URL = "https://projudi.tjba.jus.br/projudi/cadastros/AnalisarMovimentacao"

    def __init__(self):
        self.session = requests.Session()
        self.ultimo_ping = time.time()
        self._keep_alive = False

    def marcar_atividade(self):
        self.ultimo_ping = time.time()

    # pega cookies do Firefox mas LIMPA duplicados
    def get_cookies(self):
        cj = browser_cookie3.firefox(domain_name='projudi.tjba.jus.br')

        cookies = {}

        for c in cj:
            # sempre sobrescreve → mantém só o último valor
            cookies[c.name] = c.value

        return cookies

    # aplica sessão corretamente
    def criar_sessao(self):

        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Connection": "keep-alive",
            "Referer": "https://projudi.tjba.jus.br/projudi/",
            "Origin": "https://projudi.tjba.jus.br"
        })

        cookies = self.get_cookies()

        # MELHOR PRÁTICA: usa update (não set)
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

    def executar(self):
        self.criar_sessao()

        self.session.get(self.BASE_URL)

        if not self.testar_login():
            return
        print("Status OK")

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