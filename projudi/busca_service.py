"""
BuscaService — Busca processos no Projudi por nome da parte.
"""

import time
import re
from typing import List, Dict, Optional


class BuscaService:
    def __init__(self, user):
        self.user = user
        from .services import ProjudiService
        self.projudi_service = ProjudiService(user)

    BASE = 'https://projudi.tjba.jus.br/projudi'
    URL_BUSCA = f'{BASE}/buscas/ProcessosParte'

    def buscar_por_nome(
        self,
        nome_parte: str,
        cod_natureza: str = '2',
        cod_vara: str = '-1',
    ) -> List[Dict]:
        """
        Busca processos no Projudi pelo nome da parte.

        Args:
            nome_parte: Nome completo ou parcial.
            cod_natureza: '2' = Criminal, '1' = Cível.
            cod_vara: '-1' = todas.

        Retorna:
            Lista de dicts com processos encontrados.
        """
        result = self.projudi_service._get_session_from_cookies()
        if not result:
            print('   ❌ Sessão do Projudi não disponível.')
            return []

        _, cookies_dict = result
        resultados = []

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                browser = pw.firefox.launch(headless=False, slow_mo=500)
                ctx_b = browser.new_context(
                    viewport={'width': 1500, 'height': 950}, locale='pt-BR')
                ctx_b.add_cookies([
                    {'name': k, 'value': v,
                     'domain': 'projudi.tjba.jus.br', 'path': '/'}
                    for k, v in cookies_dict.items()
                ])
                page = ctx_b.new_page()

                # Abre página de busca diretamente
                print(f'   🔍 Abrindo busca de processos...')
                page.goto(self.URL_BUSCA, wait_until='networkidle')
                time.sleep(2)

                if 'login' in page.url.lower():
                    print('   ❌ Sessão expirada')
                    browser.close()
                    return []

                print(f'   👤 Buscando: {nome_parte}')

                # Natureza = Criminal
                try:
                    sel = page.locator('select[name="codNatureza"]')
                    if sel.count():
                        sel.select_option(cod_natureza)
                        print(f'   ✅ Natureza: Criminal')
                        time.sleep(0.3)
                except Exception as e:
                    print(f'   ⚠️ codNatureza: {e}')

                # Nome da parte (campo 'nome')
                try:
                    campo = page.locator('input[name="nome"]')
                    if campo.count():
                        campo.fill(nome_parte)
                        print(f'   ✅ Nome preenchido')
                        time.sleep(0.3)
                except Exception as e:
                    print(f'   ⚠️ nome: {e}')

                # Submeter
                try:
                    btn = page.locator('input[name="Buscar"]')
                    if btn.count():
                        btn.first.click()
                        print(f'   🔍 Buscando...')
                        time.sleep(3)
                except Exception as e:
                    print(f'   ⚠️ Buscar: {e}')

                try:
                    page.wait_for_load_state('networkidle', timeout=15000)
                except Exception:
                    pass
                time.sleep(2)

                resultados = self._extrair_resultados(page)
                browser.close()

        except Exception as e:
            print(f'   ❌ Erro: {e}')
            import traceback
            traceback.print_exc()

        return resultados

    def _extrair_resultados(self, page) -> List[Dict]:
        """Extrai resultados da página."""
        from bs4 import BeautifulSoup
        resultados = []

        for f in [page] + page.frames:
            try:
                html = f.content()
            except Exception:
                continue
            soup = BeautifulSoup(html, 'html.parser')

            # Tabela de resultados
            for tabela in soup.find_all('table', class_='tabelaLista'):
                for linha in tabela.find_all('tr'):
                    tds = linha.find_all('td')
                    if len(tds) < 2:
                        continue
                    num_proc = None
                    link = None
                    for td in tds:
                        a = td.find('a', href=True)
                        if a and 'numeroProcesso=' in str(a.get('href', '')):
                            num_proc = a.get_text(strip=True) or self._extrair_numero(a['href'])
                            link = a['href']
                            break
                    if num_proc:
                        r = {'numero': num_proc, 'link': self._ajustar_url(link)}
                        for td in tds:
                            txt = td.get_text(' ', strip=True)
                            if txt and txt != num_proc:
                                if 'parte' not in r:
                                    r['parte'] = txt
                                elif 'vara' not in r:
                                    r['vara'] = txt
                        resultados.append(r)

            # Fallback: qualquer link com numeroProcesso
            if not resultados:
                for a in soup.find_all('a', href=True):
                    href = str(a.get('href', ''))
                    if 'numeroProcesso=' not in href:
                        continue
                    num = self._extrair_numero(href)
                    if num:
                        resultados.append({
                            'numero': num,
                            'link': self._ajustar_url(href),
                            'texto': a.get_text(' ', strip=True),
                        })

        # Deduplica
        vistos = set()
        unicos = []
        for r in resultados:
            chave = r.get('numero', '')
            if chave and chave not in vistos:
                vistos.add(chave)
                unicos.append(r)

        return unicos

    def _extrair_numero(self, href: str) -> Optional[str]:
        m = re.search(r'numeroProcesso=(\d+)', str(href))
        return m.group(1) if m else None

    def _ajustar_url(self, href: str) -> str:
        h = str(href or '')
        if not h:
            return ''
        if h.startswith('http'):
            return h
        if h.startswith('/'):
            return f'https://projudi.tjba.jus.br{h}'
        return f'{self.BASE}/{h}'

    def exibir_resultados(self, resultados: List[Dict]):
        if not resultados:
            print('   📭 Nenhum processo encontrado.')
            return

        print(f'\n   📋 Processos encontrados: {len(resultados)}\n')
        for i, r in enumerate(resultados, 1):
            num = r.get('numero', '?')
            parte = r.get('parte', r.get('texto', ''))
            vara = r.get('vara', '')
            print(f'   {i}. {num}')
            if parte:
                print(f'      Parte: {parte}')
            if vara:
                print(f'      Vara: {vara}')
