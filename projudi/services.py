"""
Projudi Service - Integra com modulos existentes

Este servico orquestra a integracao com o sistema Projudi usando
os modulos existentes: projudi_bot, projudi_client, etc.
"""

import sys
from pathlib import Path
from django.conf import settings
import glob
import os

# Detecta automaticamente perfil Firefox do Windows via WSL
WIN_FIREFOX_PROFILES = glob.glob('/mnt/c/Users/*/AppData/Roaming/Mozilla/Firefox/Profiles/*.default*')
DEFAULT_FIREFOX_PROFILE = WIN_FIREFOX_PROFILES[0] if WIN_FIREFOX_PROFILES else None


class ProjudiService:
    def __init__(self, user, browser='auto', profile_path=None):
        self.user = user
        self.browser = browser
        self.profile_path = profile_path or DEFAULT_FIREFOX_PROFILE
        self._bot = None
        self._client = None

    # ------------------------------------------------------------------
    # BOT / SESSAO
    # ------------------------------------------------------------------
    def get_bot(self):
        if self._bot is None:
            sys.path.insert(0, str(settings.BASE_DIR))
            from projudi_bot import ProjudiBot
            self._bot = ProjudiBot(
                browser=self.browser,
                profile_path=self.profile_path
            )
        return self._bot

    def get_client(self):
        if self._client is None:
            sys.path.insert(0, str(settings.BASE_DIR))
            from projudi_client import ProjudiClient
            self._client = ProjudiClient()
        return self._client

    def check_session(self):
        bot = self.get_bot()
        bot.criar_sessao()
        return bot.testar_login()

    def get_cookies(self):
        bot = self.get_bot()
        bot.criar_sessao()
        return bot.exportar_cookies()

    # ------------------------------------------------------------------
    # MOVIMENTACOES
    # ------------------------------------------------------------------
    def list_movimentacoes(self):
        client = self.get_client()
        client.iniciar()
        soup = client.get_sopa(client.URL_MOVIMENTACOES)
        return client.extrair_links_movimentacoes(soup)

    # ------------------------------------------------------------------
    # OFICIOS  (usa cookies salvos no Django -> acesso direto via requests)
    # ------------------------------------------------------------------
    def _get_session_from_cookies(self):
        """
        Cria um requests.Session a partir dos cookies.
        Prioridade:
        1. /mnt/d/Projudi/cookies.json (capturado pelo Windows)
        2. Captura automática via powershell.exe (Windows nativo)
        3. ProjudiSession no banco Django
        """
        import requests
        from .models import ProjudiSession
        import json
        from pathlib import Path
        import subprocess

        def _criar_session(cookies_dict):
            session = requests.Session()
            for name, value in cookies_dict.items():
                session.cookies.set(name, value)
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9",
                "Connection": "keep-alive",
            })
            return session, cookies_dict

        # 1) Tenta o arquivo JSON (mais confiável - capturado pelo Windows)
        caminhos_json = [
            Path('/mnt/d/Projudi/cookies.json'),
            Path('/mnt/c/Projudi/cookies.json'),
            Path.home() / '.projudi_cookies.json',
            Path('/tmp/projudi_cookies.json'),
        ]

        for caminho in caminhos_json:
            if caminho.exists():
                try:
                    with open(caminho, 'r', encoding='utf-8') as f:
                        cookies_dict = json.load(f)
                    if 'JSESSIONID' in cookies_dict:
                        # Atualiza sessão no banco
                        ProjudiSession.objects.update_or_create(
                            user=self.user,
                            defaults={
                                'cookies': cookies_dict,
                                'status': 'active',
                                'tenant': self.user.tenant if hasattr(self.user, 'tenant') else None,
                            }
                        )
                        # Aquecer sessão
                        session, _ = _criar_session(cookies_dict)
                        session.get("https://projudi.tjba.jus.br/projudi/cadastros/AnalisarMovimentacao", timeout=10)
                        return session, cookies_dict
                except Exception:
                    pass

        # 2) Tenta capturar automaticamente via powershell.exe
        try:
            script_path = 'D:\\Projudi\\capture_cookies_windows.py'
            result = subprocess.run(
                ['powershell.exe', '-Command',
                 f'python "{script_path}" --quiet'],
                capture_output=True, text=True, timeout=30,
            )
            # Re-tenta ler após captura
            for caminho in caminhos_json:
                if caminho.exists():
                    try:
                        with open(caminho, 'r', encoding='utf-8') as f:
                            cookies_dict = json.load(f)
                        if 'JSESSIONID' in cookies_dict:
                            ProjudiSession.objects.update_or_create(
                                user=self.user,
                                defaults={
                                    'cookies': cookies_dict,
                                    'status': 'active',
                                    'tenant': self.user.tenant if hasattr(self.user, 'tenant') else None,
                                }
                            )
                            session, _ = _criar_session(cookies_dict)
                            session.get("https://projudi.tjba.jus.br/projudi/cadastros/AnalisarMovimentacao", timeout=10)
                            return session, cookies_dict
                    except Exception:
                        pass
        except Exception:
            pass

        # 3) Fallback: browser_cookie3 direto (pode funcionar no Windows)
        try:
            import browser_cookie3
            cj = browser_cookie3.firefox(domain_name='projudi.tjba.jus.br')
            cookies_ff = {c.name: c.value for c in cj}
            if cookies_ff and 'JSESSIONID' in cookies_ff:
                # Salvou no arquivo e no banco
                for caminho in caminhos_json:
                    if caminho.parent.exists():
                        with open(caminho, 'w') as f:
                            json.dump(cookies_ff, f)
                        break
                ProjudiSession.objects.update_or_create(
                    user=self.user,
                    defaults={
                        'cookies': cookies_ff,
                        'status': 'active',
                        'tenant': self.user.tenant if hasattr(self.user, 'tenant') else None,
                    }
                )
                session, _ = _criar_session(cookies_ff)
                session.get("https://projudi.tjba.jus.br/projudi/cadastros/AnalisarMovimentacao", timeout=10)
                return session, cookies_ff
        except Exception:
            pass

        # 4) Fallback: sessão salva no banco
        sessao = ProjudiSession.objects.filter(user=self.user, status='active').first()
        if sessao and sessao.cookies:
            cookies_dict = sessao.cookies if isinstance(sessao.cookies, dict) else {}
            if 'JSESSIONID' in cookies_dict:
                session, _ = _criar_session(cookies_dict)
                return session, cookies_dict

        print("[WARN] _get_session_from_cookies: JSESSIONID não encontrado em nenhuma fonte")
        return None

    def list_oficios(self, quantidade=3):
        """
        Lista ofícios expedidos.
        
        Estratégia de cookies (ordem de prioridade):
        1. Arquivo JSON gerado pelo script Windows: scripts/capture_cookies_windows.py
        2. ProjudiBot (browser_cookie3 no Linux - funciona se cookies desbloqueados)
        3. ProjudiSession (sessão salva no banco Django)
        
        O cookie JSESSIONID é obrigatório e só existe na memória do navegador logado.
        """
        client = self.get_client()

        import sys
        sys.path.insert(0, str(settings.BASE_DIR))
        from projudi_bot import ProjudiBot
        
        cookies = ProjudiBot.carregar_cookies_do_arquivo()
        
        if not cookies or 'JSESSIONID' not in cookies:
            print("[INFO] Sem cookies JSON válido. Tentando browser_cookie3...")
            bot = self.get_bot()
            bot.criar_sessao()
            cookies = bot.exportar_cookies()

        # 3) Fallback: sessao salva no banco Django
        if not cookies or 'JSESSIONID' not in cookies:
            print("[INFO] Tentando sessao salva no banco (ProjudiSession)...")
            from .models import ProjudiSession
            sessao = ProjudiSession.objects.filter(status='active').first()
            if sessao and sessao.cookies and 'JSESSIONID' in sessao.cookies:
                cookies = sessao.cookies if isinstance(sessao.cookies, dict) else {}

        if not cookies or 'JSESSIONID' not in cookies:
            raise Exception(
                "Não foi possível capturar a sessão do Projudi.\n\n"
                "SOLUÇÕES:\n"
                "1. (Recomendado) No Windows, rode:\n"
                "   python scripts/capture_cookies_windows.py\n\n"
                "2. Ou no Linux, desbloqueie os cookies do Firefox:\n"
                "   about:config -> set 'network.cookie.cookieBehavior' = 0\n\n"
                "Certifique-se de estar logado no Projudi no Firefox antes."
            )

        print(f"[INFO] Usando {len(cookies)} cookies (JSESSIONID presente: {'JSESSIONID' in cookies})")

        # Cria session requests com os cookies
        import requests
        from bs4 import BeautifulSoup
        session = requests.Session()
        for name, value in cookies.items():
            session.cookies.set(name, value)
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Connection": "keep-alive",
            "Referer": "https://projudi.tjba.jus.br/projudi/",
            "Origin": "https://projudi.tjba.jus.br"
        })
        client.session = session
        client.cookies = cookies

        # Aquece a sessão com BASE_URL primeiro (crucial!)
        print("[INFO] Aquecendo sessão...")
        session.get("https://projudi.tjba.jus.br/projudi/cadastros/AnalisarMovimentacao")

        # Agora acessa URL_OFICIOS
        print("[INFO] Buscando ofícios...")
        resp = session.get(client.URL_OFICIOS)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Verifica se retornou página válida
        expirou = 'sess\u00e3o expirou' in resp.text.lower()
        if expirou or len(resp.text) < 1000:
            raise Exception(
                "Sessão do Projudi expirada.\n\n"
                "Os cookies capturados não são mais válidos.\n"
                "1. Verifique se ainda está logado no Firefox\n"
                "2. Re-execute o script de captura de cookies\n"
                "3. Tente sincronizar novamente"
            )

        # Navegação paginada
        ultima = client.obter_ultima_pagina(soup)
        paginas = client.gerar_paginas_finais(ultima, quantidade=quantidade)
        resultados = client.buscar_oficios(paginas)

        # Extrai links por posição
        oficios = []
        import re
        for pagina_result in resultados:
            links = pagina_result.get('links', {})
            oficios_links = links.get('oficios', [])
            processos_links = links.get('processos', [])
            recebimentos = links.get('recebimentos', [])
            baixas = links.get('baixas', [])

            for i, url_oficio in enumerate(oficios_links):
                url_proc = processos_links[i] if i < len(processos_links) else ''
                url_rec = recebimentos[i] if i < len(recebimentos) else ''
                url_baixa = baixas[i] if i < len(baixas) else ''

                match = re.search(r'numeroProcesso=([^&]+)', url_proc)
                processo = match.group(1) if match else ''
                
                # Numero CNJ visivel no texto do link
                textos = links.get('textos_processos', [])
                processo_cnj = textos[i] if i < len(textos) else ''

                oficios.append({
                    'processo': processo,
                    'processo_cnj': processo_cnj,
                    'url_oficio': url_oficio,
                    'url_processo': url_proc,
                    'url_recebimento': url_rec,
                    'url_baixa': url_baixa,
                })

        # Salva cookies atualizados
        self._salvar_cookie_jar(session.cookies.get_dict())
        
        return oficios

    # ---------------------------------------------------------------
    # COOKIE JAR PERSISTENTE
    # ---------------------------------------------------------------
    def _get_session_from_cookie_jar(self):
        """Carrega cookies salvos no ProjudiSession e cria requests.Session."""
        import requests
        from .models import ProjudiSession
        
        sessao = ProjudiSession.objects.filter(user=self.user).first()
        if not sessao or not sessao.cookies:
            return None

        cookies_dict = sessao.cookies if isinstance(sessao.cookies, dict) else {}
        if not cookies_dict:
            return None

        session = requests.Session()
        for name, value in cookies_dict.items():
            session.cookies.set(name, value)
        
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Connection": "keep-alive",
            "Referer": "https://projudi.tjba.jus.br/projudi/",
            "Origin": "https://projudi.tjba.jus.br"
        })
        
        return session

    def _salvar_cookie_jar(self, cookies_dict):
        """Salva/atualiza cookies no ProjudiSession do Django."""
        from .models import ProjudiSession
        sessao = ProjudiSession.objects.filter(user=self.user).first()
        if sessao:
            sessao.cookies = cookies_dict
            sessao.status = 'active'
            sessao.save()
        else:
            ProjudiSession.objects.create(user=self.user, cookies=cookies_dict, status='active')

    def _capturar_cookies_fresh(self):
        """
        Captura cookies frescos do Firefox.
        Estratégia:
        1. Tenta arquivo JSON (bot rodando no Windows)
        2. Tenta browser_cookie3 (ProjudiBot)
        3. Fallback Selenium (memória do Firefox)
        """
        import requests
        from bs4 import BeautifulSoup

        # Estratégia 1: Arquivo JSON
        sys.path.insert(0, str(settings.BASE_DIR))
        from projudi_bot import ProjudiBot
        
        cookies_json = ProjudiBot.carregar_cookies_do_arquivo()
        if cookies_json:
            print(f"[INFO] Cookies JSON: {list(cookies_json.keys())}")
            session = self._criar_session_com_cookies(cookies_json)
            if self._testar_sessao(session):
                print("[OK] Sessão válida via JSON")
                return session
            print("[WARN] JSON expirado")

        # Estratégia 2: browser_cookie3 (ProjudiBot)
        bot = self.get_bot()
        bot.criar_sessao()
        cookies_bot = bot.exportar_cookies()
        print(f"[INFO] Cookies Bot: {list(cookies_bot.keys())}")
        
        if 'JSESSIONID' in cookies_bot or bot.testar_login():
            print("[OK] Sessão válida via ProjudiBot")
            return bot.session
        print("[WARN] Bot sem JSESSIONID, tentando Selenium...")

        # Estratégia 3: Selenium (memória do Firefox)
        try:
            import time
            from selenium import webdriver
            from selenium.webdriver.firefox.options import Options
            from selenium.webdriver.firefox.service import Service
            from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
            from webdriver_manager.firefox import GeckoDriverManager
            import glob

            win_profiles = glob.glob('/mnt/c/Users/*/AppData/Roaming/Mozilla/Firefox/Profiles/*.default*')
            if not win_profiles:
                raise Exception("Nenhum perfil Firefox encontrado")
            
            profile = FirefoxProfile(win_profiles[0])
            options = Options()
            options.profile = profile
            
            driver = webdriver.Firefox(
                service=Service(GeckoDriverManager().install()),
                options=options
            )
            driver.set_window_size(1280, 800)
            driver.get("https://projudi.tjba.jus.br/projudi/")
            time.sleep(3)
            
            raw_cookies = driver.get_cookies()
            selenium_cookies = {c['name']: c['value'] for c in raw_cookies}
            print(f"[INFO] Selenium cookies: {list(selenium_cookies.keys())}")
            
            driver.quit()
            
            session = self._criar_session_com_cookies(selenium_cookies)
            if self._testar_sessao(session):
                print("[OK] Sessão válida via Selenium")
                return session
            print("[WARN] Selenium também expirado")
            
        except Exception as e:
            print(f"[ERRO] Selenium: {e}")

        return None

    def _criar_session_com_cookies(self, cookies_dict):
        """Cria requests.Session com cookies e headers realistas."""
        import requests
        session = requests.Session()
        for name, value in cookies_dict.items():
            session.cookies.set(name, value)
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Connection": "keep-alive",
            "Referer": "https://projudi.tjba.jus.br/projudi/",
            "Origin": "https://projudi.tjba.jus.br"
        })
        return session

    def _testar_sessao(self, session):
        """Testa se a sessão requests é válida no Projudi."""
        try:
            # Primeiro acessa BASE_URL (estabelece a sessão)
            session.get("https://projudi.tjba.jus.br/projudi/cadastros/AnalisarMovimentacao")
            # Depois testa URL_OFICIOS
            resp = session.get("https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=oficio&acao=expedidos")
            expirou = 'sess\u00e3o expirou' in resp.text.lower()
            return not expirou and len(resp.text) > 1000
        except:
            return False

    def _salvar_cookies(self, cookies_dict):
        """Atualiza cookies no ProjudiSession do Django."""
        from .models import ProjudiSession
        sessao = ProjudiSession.objects.filter(user=self.user).first()
        if sessao:
            sessao.cookies = cookies_dict
            sessao.save()
            print("[OK] Cookies renovados e salvos no Django.")
        else:
            ProjudiSession.objects.create(user=self.user, cookies=cookies_dict, status='active')

    def get_process_data(self, process_number):
        sys.path.insert(0, str(settings.BASE_DIR))
        from projudiProcessNavigator import ProcessoParser
        client = self.get_client()
        client.iniciar()
        url = f'{client.LINK_BASE}listagens/DadosProcesso?numeroProcesso={process_number}'
        soup = client.get_sopa(url)
        parser = ProcessoParser(soup.prettify())
        return parser.parse_processo(soup, client.LINK_BASE)

    def analyze_document(self, html_content):
        sys.path.insert(0, str(settings.BASE_DIR))
        from projudiDocReader import DocumentAnalyzer
        analyzer = DocumentAnalyzer()
        return analyzer.analisar_movimentacao(html_content, {})

    def perform_juntada(self, url_recebimento, codigo_movimentacao, observacao):
        sys.path.insert(0, str(settings.BASE_DIR))
        from exemplo_refatoracao_oo import ProjudiJuntada, ProjudiConfig
        cookies = self.get_cookies()
        config = ProjudiConfig()
        juntada = ProjudiJuntada(config, cookies)
        try:
            result = juntada.realizar_juntada(
                url_recebimento=url_recebimento,
                codigo_movimentacao=codigo_movimentacao,
                observacao=observacao,
                numero_oficio='',
                data_envio='',
                hora_envio='',
                destinatario='',
                url_oficio=''
            )
            return result
        finally:
            juntada.close()
