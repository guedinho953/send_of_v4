"""
Projudi Service - Integra com modulos existentes

Este servico orquestra a integracao com o sistema Projudi usando
os modulos existentes: projudi_bot, projudi_client, etc.
"""

import subprocess
import sys
from pathlib import Path

from django.conf import settings

import firefox_config

# Perfil do Firefox local (Windows nativo, WSL ou Linux). O próprio módulo
# firefox_config resolve os caminhos de cada sistema.
DEFAULT_FIREFOX_PROFILE = firefox_config.default_firefox_profile()


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
        """Cria um requests.Session a partir dos cookies do Firefox local.

        Ordem de prioridade (funciona em Windows nativo, WSL e Linux):
        1. JSON de cookies capturado anteriormente;
        2. captura direta do cookies.sqlite (+ WAL) do Firefox local;
        3. script de captura em subprocesso;
        4. browser_cookie3;
        5. sessão salva no banco Django.
        """
        import requests
        from .models import ProjudiSession

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

        def _session_valida(session):
            """Verifica se a sessão realmente está autenticada no Projudi."""
            try:
                r = session.get(
                    "https://projudi.tjba.jus.br/projudi/cadastros/AnalisarMovimentacao",
                    timeout=10, allow_redirects=False
                )
                # Se redirecionou para login ou contém "expirou" no texto, está inválida
                if r.status_code == 302:
                    location = r.headers.get('Location', '')
                    if 'login' in location.lower():
                        return False
                if 'login' in r.url.lower():
                    return False
                if 'expirou' in r.text[:500].lower():
                    return False
                if len(r.text) < 500:
                    return False
                return True
            except Exception:
                return False

        def _salvar_no_banco(cookies_dict):
            ProjudiSession.objects.update_or_create(
                user=self.user,
                defaults={
                    'cookies': cookies_dict,
                    'status': 'active',
                    'tenant': getattr(self.user, 'tenant', None),
                }
            )

        def _tentar(cookies_dict, origem):
            if not cookies_dict or 'JSESSIONID' not in cookies_dict:
                return None
            session, _ = _criar_session(cookies_dict)
            if not _session_valida(session):
                print(f'[INFO] Cookies de {origem} expirados.')
                return None
            firefox_config.write_cookies(cookies_dict)
            _salvar_no_banco(cookies_dict)
            return session, cookies_dict

        # 1) JSON gravado pela captura anterior
        for caminho in firefox_config.cookies_file_candidates():
            cookies_dict = firefox_config.read_cookies(caminho)
            resultado = _tentar(cookies_dict, str(caminho))
            if resultado:
                return resultado

        # 2) Captura direta no processo (melhor caminho no Windows nativo)
        try:
            cookies_dict = firefox_config.capture_cookies()
            resultado = _tentar(cookies_dict, 'captura direta do Firefox')
            if resultado:
                return resultado
            if cookies_dict:
                print(f'[INFO] Firefox local: {len(cookies_dict)} cookies, '
                      'mas sem JSESSIONID. Faca login no Projudi.')
        except Exception as e:
            print(f'[INFO] Captura direta do Firefox falhou: {e}')

        # 3) Script de captura em subprocesso (util no WSL e em casos de
        #    permissao/encoding diferentes).
        try:
            script = Path(settings.BASE_DIR) / 'scripts' / 'capture_cookies_windows.py'
            if script.is_file():
                subprocess.run(
                    [sys.executable, str(script), '--quiet'],
                    capture_output=True, text=True, encoding='utf-8',
                    errors='replace', timeout=60,
                )
                for caminho in firefox_config.cookies_file_candidates():
                    resultado = _tentar(
                        firefox_config.read_cookies(caminho), str(caminho))
                    if resultado:
                        return resultado
        except Exception:
            pass

        # 4) Fallback: browser_cookie3 direto
        try:
            import browser_cookie3
            jar = browser_cookie3.firefox(domain_name='projudi.tjba.jus.br')
            cookies_ff = {c.name: c.value for c in jar}
            resultado = _tentar(cookies_ff, 'browser_cookie3')
            if resultado:
                return resultado
        except Exception:
            pass

        # 5) Fallback: sessão salva no banco
        sessao = ProjudiSession.objects.filter(
            user=self.user, status='active').first()
        if sessao and sessao.cookies:
            cookies_dict = sessao.cookies if isinstance(sessao.cookies, dict) else {}
            if 'JSESSIONID' in cookies_dict:
                session, _ = _criar_session(cookies_dict)
                if _session_valida(session):
                    return session, cookies_dict
                print('[INFO] Sessão do banco expirada. '
                      'Re-sincronize em /projudi/sessoes/')

        print("[WARN] _get_session_from_cookies: JSESSIONID não encontrado em nenhuma fonte")
        return None

    def list_oficios(self, quantidade=3):
        """
        Lista ofícios expedidos.
        
        Estratégia de cookies (ordem de prioridade):
        1. JSON gerado pela captura (caminho multiplataforma)
        2. Captura direta do Firefox local (SQLite + WAL)
        3. ProjudiBot / browser_cookie3
        4. ProjudiSession (sessão salva no banco Django)

        O cookie JSESSIONID é obrigatório.
        """
        client = self.get_client()

        import sys
        sys.path.insert(0, str(settings.BASE_DIR))
        from projudi_bot import ProjudiBot

        cookies = ProjudiBot.carregar_cookies_do_arquivo()

        if not cookies or 'JSESSIONID' not in cookies:
            print("[INFO] Sem cookies JSON válido. Capturando do Firefox local...")
            cookies = firefox_config.capture_cookies()

        if not cookies or 'JSESSIONID' not in cookies:
            print("[INFO] Tentando ProjudiBot/browser_cookie3...")
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
                "1. Abra o Firefox local e faca login no Projudi;\n"
                "2. Rode a captura de cookies:\n"
                "   python scripts/capture_cookies_windows.py\n"
                "   (no Windows tambem existe CAPTURAR_COOKIES.bat)\n\n"
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
        """Captura cookies frescos do Firefox local.

        Estratégias: arquivo JSON, captura direta do SQLite (Windows/Linux),
        ProjudiBot/browser_cookie3 e, por último, Selenium com o perfil local.
        """
        # Estratégia 1: arquivo JSON
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

        # Estratégia 2: captura direta do Firefox (SQLite + WAL)
        cookies_diretos = firefox_config.capture_cookies()
        if cookies_diretos:
            print(f"[INFO] Cookies Firefox: {list(cookies_diretos.keys())}")
            session = self._criar_session_com_cookies(cookies_diretos)
            if self._testar_sessao(session):
                firefox_config.write_cookies(cookies_diretos)
                print("[OK] Sessão válida via Firefox local")
                return session
            print("[WARN] Cookies do Firefox expirados")

        # Estratégia 3: browser_cookie3 (ProjudiBot)
        bot = self.get_bot()
        bot.criar_sessao()
        cookies_bot = bot.exportar_cookies()
        print(f"[INFO] Cookies Bot: {list(cookies_bot.keys())}")

        if 'JSESSIONID' in cookies_bot or bot.testar_login():
            print("[OK] Sessão válida via ProjudiBot")
            return bot.session
        print("[WARN] Bot sem JSESSIONID, tentando Selenium...")

        # Estratégia 4: Selenium com o perfil do Firefox local
        try:
            import time
            from selenium import webdriver
            from selenium.webdriver.firefox.options import Options
            from selenium.webdriver.firefox.service import Service
            from webdriver_manager.firefox import GeckoDriverManager

            perfil = firefox_config.default_firefox_profile()
            if not perfil:
                raise Exception("Nenhum perfil Firefox encontrado")

            options = Options()
            options.add_argument('-profile')
            options.add_argument(str(perfil))

            firefox_bin = firefox_config.find_firefox()
            if firefox_bin:
                options.binary_location = str(firefox_bin)

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
                firefox_config.write_cookies(selenium_cookies)
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
