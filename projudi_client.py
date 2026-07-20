import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import pandas as pd
import re
from collections import defaultdict

import os
import csv
import sys

from itertools import zip_longest
import time
import random
from datetime import datetime
import importlib

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import Select
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
from urllib.parse import urlparse
from projudi_bot import ProjudiBot



class ProjudiClient:
    #links
    LINK_BASE = "https://projudi.tjba.jus.br/projudi/"

    PATH_OFICIOS = "listagens/CumprimentoCartorio?tipo=oficio&acao=expedidos"
    PATH_MANDADOS = "listagens/CumprimentoCartorio?tipo=mandado&acao=expedir"
    PATH_PETICOES = "listagens/JuntadaPeticao"
    PATH_MOVIMENTACOES = "cadastros/AnalisarMovimentacao"

    URL_OFICIOS = urljoin(LINK_BASE, PATH_OFICIOS)
    URL_MANDADOS = urljoin(LINK_BASE, PATH_MANDADOS)
    URL_PETICOES = urljoin(LINK_BASE, PATH_PETICOES)
    URL_MOVIMENTACOES = urljoin(LINK_BASE, PATH_MOVIMENTACOES)

  
    def __init__(self):
        self.session = None
        self.cookies = None
        self.bot = None  # boa prática
        self.ultimo_ping = time.time()
        self._driver = None  # 👈 privado
        self.options = Options()
        self.profile = FirefoxProfile()
       

    def iniciar(self):
        self.bot = ProjudiBot()
        self.bot.executar()
        self.bot.marcar_atividade()
        self.session = self.bot.session
        self.cookies = self.bot.exportar_cookies() 
        self.ultimo_ping = time.time()
        self.bot.iniciar_keep_alive()  # ativa automático

    def _criar_profile(self):
        profile = FirefoxProfile()
        # idioma
        profile.set_preference("intl.accept_languages", "pt-BR,pt")

        # 👉 já deixa preparado pra download futuro
        profile.set_preference("browser.download.folderList", 2)
        profile.set_preference("browser.download.manager.showWhenStarting", False)

        # exemplo: pdf automático (só ativa se precisar)
        # profile.set_preference("browser.helperApps.neverAsk.saveToDisk", "application/pdf")
        return profile
    
    def _criar_driver(self):
        options = Options()
         # 👇 aqui você pluga o profile
        options.profile = self._criar_profile()

        driver = webdriver.Firefox(
            service=Service(GeckoDriverManager().install()),
            options=options
        )

        driver.set_window_size(1280, 800)

        # 🔥 abre domínio antes
        driver.get(self.LINK_BASE)

        # 🔥 injeta cookies
        for name, value in self.cookies.items():
            try:
                driver.add_cookie({
                    "name": name,
                    "value": value,
                    "path": "/"
                })
            except:
                pass

        # 🔥 ativa sessão
        driver.refresh()
        return driver
    
    def get_driver(self):
        if self._driver is None:
            print("🚀 Criando driver Selenium...")
            self._driver = self._criar_driver()
        return self._driver
    
    def abrir(self, url):
        driver = self.get_driver()
        driver.get(url)
        return driver


    def get_sopa(self, url):
        response = self.session.get(url)
        if self.bot:
            self.bot.marcar_atividade()
       
        soup = BeautifulSoup(response.text, 'html.parser')
        print(soup.prettify()[:200])
        return soup
    
    def obter_ultima_pagina(self, soup):
        links_paginas = soup.find_all('a', href=re.compile(r'goToPage\(\d+\)'))

        if not links_paginas:
            print("Nenhuma paginação encontrada.")
            return 1

        # debug opcional
        for link in links_paginas:
            print(f"Link encontrado: {link.get('href')}")

        ultimo_link = links_paginas[-1]

        match = re.search(r'goToPage\((\d+)\)', ultimo_link['href'])

        if match:
            ultima_pagina = int(match.group(1))
            print(f"Última página encontrada: {ultima_pagina}")
            return ultima_pagina

        return 1
    
    def get_movimentacoes_pagina(self, pagina):
        data = {
            'pagina': str(pagina),
            'acao': 'AnalisarMovimentacao'
        }

        response = self.session.post(self.URL_MOVIMENTACOES, data=data)
        if self.bot:
            self.bot.marcar_atividade()

        soup = BeautifulSoup(response.text, 'html.parser')
        return soup

    def url_oficios(self):
        return self.URL_OFICIOS

    def gerar_paginas_finais(self, ultima_pagina, quantidade=2):
        inicio = max(1, ultima_pagina - quantidade + 1)
        return list(range(inicio, ultima_pagina + 1))[::-1]


    def obter_paginas_finais(self, quantidade=1):
        response = self.session.get(self.url_oficios())
        soup = BeautifulSoup(response.text, 'html.parser')


        ultima = self.obter_ultima_pagina(soup)
        return self.gerar_paginas_finais(ultima, quantidade)
    

    def obter_paginas_finais_movimentacoes(self, quantidade=3):
        response = self.session.get(self.URL_MOVIMENTACOES)
        soup = BeautifulSoup(response.text, 'html.parser')
        

        ultima = self.obter_ultima_pagina(soup)
        return self.gerar_paginas_finais(ultima, quantidade)
    
    def extrair_links_movimentacoes(self, soup):

        itens = []

        for tr in soup.find_all('tr'):
            tds = tr.find_all('td')

            # 🔹 pega tipo da movimentação (ajuste o índice se necessário)
            tipo = None
            

            numero = None
            link_processo = None
            link_documento = None
            link_movimentar = None
            link_dispensar = None
            
            td_tipo = tr.find('td', align='center')
            if td_tipo:
                tipo = td_tipo.get_text(strip=True)

            for a in tr.find_all('a', href=True):
                href = a['href']

                # 🔹 PROCESSO
                if 'DadosProcesso?numeroProcesso=' in href:
                    numero = a.get_text(strip=True)
                    link_processo = urljoin(self.LINK_BASE, href)

                # 🔹 DOCUMENTO
                elif 'DownloadArquivo' in href:
                    link_documento = urljoin(self.LINK_BASE, href)

                # 🔹 MOVIMENTAÇÃO
                elif 'MovimentarAnalise' in href:
                    link_movimentar = urljoin(self.LINK_BASE, href)

                    # pega o código da análise
                    cod = href.split('codAnalise=')[1]

                    link_dispensar = urljoin(
                        self.LINK_BASE,
                        f"/projudi/cadastros/MovimentarAnalise?dispensar=true&codAnalise={cod}&codAalises={cod}"
                    )

            # 🔹 só adiciona se for uma linha válida
            if numero:
                itens.append({
                    "processo": numero,
                    "tipo": tipo,
                    "link_processo": link_processo,
                    "link_documento": link_documento,
                    "movimentar": link_movimentar,
                    "dispensar": link_dispensar,
                })

        return itens
        

    def extrair_links_oficios(self, soup):
        links_oficios = []
        links_processos = []
        textos_processos = []  # <-- numero CNJ visivel no link
        links_recebimento = []
        links_baixa = []

        for a in soup.find_all('a', href=True):
            href = a['href'].replace('&amp;', '&')
            texto = a.get_text(strip=True)

            if href.startswith('/projudi/acoes/VerCumprimento'):
                links_oficios.append(urljoin(self.LINK_BASE, href))

            elif href.startswith('/projudi/listagens/DadosProcesso'):
                links_processos.append(urljoin(self.LINK_BASE, href))
                textos_processos.append(texto)  # <-- ex: 0001306-27.2025.8.05.0191

            elif href.startswith('/projudi/movimentacao/MovimentarProcesso'):
                links_recebimento.append(urljoin(self.LINK_BASE, href))

            elif href.startswith('/projudi/movimentacao/MarcaRecebimento'):
                links_baixa.append(urljoin(self.LINK_BASE, href))
        if self.bot:
            self.bot.marcar_atividade()

        return {
            "oficios": links_oficios,
            "processos": links_processos,
            "textos_processos": textos_processos,  # <-- numero CNJ
            "recebimentos": links_recebimento,
            "baixas": links_baixa
        }

    def get_documento(self, url):
        resp = self.session.get(urljoin(self.LINK_BASE, url ))
        resp.raise_for_status()
        if self.bot:
            self.bot.marcar_atividade()
        
        return resp.text
    

    def buscar_oficios(self, paginas):
        resultados = []

        print("Iniciando o processo de buscar ofícios...")  # Verifica que o processo começou

        for pagina in paginas:  # Loop por cada página
            data = {
                'tipo': 'oficio',
                'acao': 'expedidos',
                'codTipoJustica': "2",
                'pagina': str(pagina),
                'coluna': 'CumprimentoCartorio.CODCUMPRIMENTO',
                'ordem': "ASC"
            }

            # Envia a requisicao POST
            response = self.session.post(self.URL_OFICIOS, data=data)

            # Verifica se a resposta foi bem-sucedida
            if response.status_code != 200:
                print(f"Erro ao acessar a pagina {pagina}. Status code: {response.status_code}")
                continue  # Se a resposta nao for 200, passa para a proxima pagina

            # Caso a resposta seja 200, vamos imprimir para verificar o que veio da requisicao
            print(f"Pagina {pagina} -> Status code: {response.status_code}")

            # Verifica o conteudo retornado na pagina
            # print(f"Conteudo da pagina {pagina}: {response.text[:500]}")  # Mostra os primeiros 500 caracteres

            # Faz o parsing do HTML com BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')

            # Extrai os links da pagina
            links = self.extrair_links_oficios(soup)

            if not links:  # Se não encontrar links, pula para a próxima página
                print(f"Nenhum link encontrado para a página {pagina}")
                continue  # Continua o loop, indo para a próxima iteração do loop

            # Caso tenha encontrado links, imprime-os para depuração
            # print(f"Links encontrados na página {pagina}: {links}")

            # Adiciona o resultado da página no array de resultados
            resultados.append({
                "pagina": pagina,
                "links": links
            })

        # Retorna o resultado final com todos os links encontrados
        print(f"Processo concluído, total de {len(resultados)} resultados encontrados.")
        return resultados
