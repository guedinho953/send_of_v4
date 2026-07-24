"""Executa intimação via MovimentarAnalise (igual ao seu fluxo manual).

Uso:
  source .venv/bin/activate
  python test_intimar_codanalise.py
"""

import os, sys, json, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from django.apps import apps
User = apps.get_model('accounts.User')
from projudi.services import ProjudiService
from projudi_client import ProjudiClient
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright, expect

# ─── Config ───
PROCESSO_CNJ = '0002223-12.2026.8.05.0191'
LINK_BASE = 'https://projudi.tjba.jus.br/projudi/'

print('=' * 68)
print(f'  INTIMAÇÃO VIA MOVIMENTARANALISE')
print(f'  Processo: {PROCESSO_CNJ}')
print('=' * 68)

# ─── 1. Sessão ───
print('\n[1/4] Conectando ao Projudi...')
user = User.objects.filter(is_active=True).first()
service = ProjudiService(user)
result = service._get_session_from_cookies()
if not result:
    print('❌ Sessão não disponível.')
    sys.exit(1)
session, cookies_dict = result
print(f'   ✅ Sessão OK — {user.email}')

# ─── 2. Buscar movimentações e achar codAnalise ───
print(f'\n[2/4] Buscando movimentações do processo...')
client = ProjudiClient()
client.session = session
client.cookies = cookies_dict

cod_analise = None
url_movimentar = None

pages = client.obter_paginas_finais_movimentacoes(quantidade=3)
for p in pages:
    data = {'pagina': str(p), 'loginJuiz': ''}
    rp = session.post(client.URL_MOVIMENTACOES, data=data, timeout=15)
    if len(rp.text) <= 1000:
        continue
    sp = BeautifulSoup(rp.text, 'html.parser')
    movs = client.extrair_links_movimentacoes(sp)
    for m in movs:
        if PROCESSO_CNJ not in m.get('processo', ''):
            continue
        mov_link = m.get('movimentar', '')
        if mov_link and 'codAnalise=' in mov_link:
            cod_analise = mov_link.split('codAnalise=')[1].split('&')[0]
            url_movimentar = mov_link
            print(f'   📄 Mov: {m.get("tipo", "?")}')
            print(f'   🔗 codAnalise: {cod_analise}')
            print(f'   🔗 URL: {url_movimentar}')
            break
    if cod_analise:
        break

if not cod_analise:
    print('❌ codAnalise não encontrado para esse processo')
    sys.exit(1)

# ─── 3. Executar via Playwright ───
print(f'\n[3/4] Abrindo Firefox via Playwright...')
print()
print('   🔴 Abrindo navegador...')
print()
time.sleep(2)

sucesso = False
try:
    with sync_playwright() as pw:
        browser = pw.firefox.launch(headless=False, slow_mo=400)
        ctx = browser.new_context(
            viewport={'width': 1500, 'height': 950},
            locale='pt-BR'
        )
        # Injeta cookies
        ctx.add_cookies([
            {'name': k, 'value': v,
             'domain': 'projudi.tjba.jus.br', 'path': '/'}
            for k, v in cookies_dict.items()
        ])
        page = ctx.new_page()

        # ── PASSO 1: Abrir MovimentarAnalise ──
        print('\n   🚀 Abrindo MovimentarAnalise...')
        page.goto(url_movimentar, wait_until='networkidle')
        time.sleep(2)

        # ── PASSO 2: pipeline_final (mov + observação) ──
        print('   📝 Pipeline Final (mov + observação)...')
        
        # Código da movimentação = 581 (Intimação / Cumprimento)
        page.evaluate('''() => {
            var c = document.getElementById('seqCategoriaMovimentacao');
            if (c) { c.value = '581'; c.dispatchEvent(new Event('change', {bubbles:true})); }
        }''')
        time.sleep(1)

        # Clicar btnBuscaMovimentacao
        try:
            page.click('#btnBuscaMovimentacao', timeout=5000)
            time.sleep(2)
        except:
            print('   ⚠️ btnBuscaMovimentacao não encontrado')

        # Fechar alerta se aparecer
        try:
            alert = page.wait_for_event('dialog', timeout=5000)
            print(f'   ⚠️ Alerta: {alert.message}')
            alert.accept()
            time.sleep(2)
        except:
            pass

        # Selecionar intimação no grid que aparece
        # Após a busca, aparece uma tabela/grid com opções - clicar em "Intimação"
        try:
            # Tenta clicar no link/linha que contém "Intimação"
            link_intimacao = page.query_selector('a:has-text("Intimação")')
            if link_intimacao:
                link_intimacao.click()
                print('   ✅ Intimação selecionada no grid')
                time.sleep(1)
            else:
                # Tenta via célula da tabela
                celula = page.query_selector('td:has-text("Intimação")')
                if celula:
                    celula.click()
                    print('   ✅ Intimação selecionada (célula)')
                    time.sleep(1)
                else:
                    print('   ⚠️ Link Intimação não encontrado no grid')
        except Exception as e:
            print(f'   ⚠️ Erro ao selecionar intimação: {e}')

        # Preencher observação
        try:
            # Aguarda campo habilitar
            time.sleep(1)
            page.fill('#observacao', 'Intimem-se as partes para ciência da Liminar Não Concedida')
            time.sleep(0.5)
            print('   ✅ Observação preenchida')
        except Exception as e:
            print(f'   ⚠️ Observação: {e}')

        # ── PASSO 3: pipeline_intimacao ──
        print('   🔔 Pipeline Intimação...')
        
        # Clicar painel de intimação
        try:
            page.click('#imgBotao_painelIntimacao', timeout=5000)
            time.sleep(1)
            print('   ✅ Painel de intimação aberto')
        except:
            print('   ⚠️ Botão painel de intimação não encontrado')

        # Autoras
        try:
            # Primeiro clica na aba Autoras se existir
            autoras_click = page.query_selector('#Autoras')
            if autoras_click:
                # Pode ser um link ou botão
                page.evaluate('''() => {
                    var el = document.getElementById('Autoras');
                    if (el) el.click();
                }''')
                time.sleep(0.5)
            
            # Seleciona motivo e prazo
            page.evaluate('''() => {
                var sel = document.getElementById('codMotivoAutor');
                if (sel) { sel.value = '3'; sel.dispatchEvent(new Event('change', {bubbles:true})); }
                var sel2 = document.getElementById('codPrazoAutor');
                if (sel2) { sel2.value = '3'; sel2.dispatchEvent(new Event('change', {bubbles:true})); }
            }''')
            time.sleep(0.5)
            print('   ✅ Autoras configuradas')
        except Exception as e:
            print(f'   ⚠️ Autoras: {e}')

        # Rés
        try:
            res_click = page.query_selector('#Res')
            if res_click:
                page.evaluate('''() => {
                    var el = document.getElementById('Res');
                    if (el) el.click();
                }''')
                time.sleep(0.5)
            
            page.evaluate('''() => {
                var sel = document.getElementById('codMotivoReu');
                if (sel) { sel.value = '3'; sel.dispatchEvent(new Event('change', {bubbles:true})); }
                var sel2 = document.getElementById('codPrazoReu');
                if (sel2) { sel2.value = '3'; sel2.dispatchEvent(new Event('change', {bubbles:true})); }
            }''')
            time.sleep(0.5)
            print('   ✅ Rés configurados')
        except Exception as e:
            print(f'   ⚠️ Rés: {e}')

        time.sleep(2)

        # ── PASSO 4: Concluir ──
        print('   🔻 Concluindo...')
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        time.sleep(0.5)
        
        try:
            page.click('#Concluir', timeout=10000)
            time.sleep(3)
            # Alerta opcional
            try:
                alert = page.wait_for_event('dialog', timeout=5000)
                print(f'   ⚠️ Alerta: {alert.message}')
                alert.accept()
                time.sleep(2)
            except:
                pass
            print('   ✅ Concluído!')
            sucesso = True
        except Exception as e:
            print(f'   ❌ Erro ao concluir: {e}')

        time.sleep(3)
        browser.close()

except Exception as e:
    print(f'   ❌ Erro no Playwright: {e}')
    import traceback; traceback.print_exc()

# ─── 4. Resultado ───
print(f'\n[4/4] Resultado')
print()
if sucesso:
    print('   ✅ INTIMAÇÃO CONCLUÍDA COM SUCESSO')
else:
    print('   ❌ INTIMAÇÃO FALHOU')

print(f'\n{"="*68}')
