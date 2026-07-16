import os, time
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()
from projudi.services import ProjudiService
from django.contrib.auth import get_user_model
from playwright.sync_api import sync_playwright

User = get_user_model()
user = User.objects.filter(is_superuser=True).first()
service = ProjudiService(user)
session = service._get_session_from_cookie_jar()
cookies = session.cookies.get_dict()

from processes.models import GeneratedDocument
doc = GeneratedDocument.objects.filter(recipient_name__icontains='jano').last()
print(f'Doc #{doc.id} - {doc.recipient_name}')

with sync_playwright() as pw:
    browser = pw.firefox.launch(headless=False)
    ctx = browser.new_context(viewport={'width': 1400, 'height': 900}, locale='pt-BR')
    for name, value in cookies.items():
        ctx.add_cookies([{'name': name, 'value': value, 'domain': 'projudi.tjba.jus.br', 'path': '/'}])
    page = ctx.new_page()

    page.goto(
        'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso=41020261733480',
        wait_until='networkidle'
    )
    time.sleep(3)
    print('>>> MovimentarProcesso carregado')

    # Expande "Cumprimento(s) Cartorio"
    cumpr_link = page.locator("a:text('Cumprimento')").first
    if cumpr_link.is_visible():
        cumpr_link.scroll_into_view_if_needed()
        time.sleep(0.5)
        cumpr_link.click()
        time.sleep(1)
        print('>>> Painel Cumprimento expandido')

        # Procura por "Redigir"
        page.screenshot(path='/tmp/pw_cumpr_painel.png')
        body = page.locator('#divPanelCumprimento').inner_text() if page.locator('#divPanelCumprimento').is_visible() else page.locator('body').inner_text()
        print(f'Conteudo: {body[:1000]}' if body else 'Vazio')

        redigir = page.locator("a:text('Redigir')").first
        if redigir.is_visible():
            print(f'>>> \"Redigir\" encontrado: {redigir.inner_text()}')
            redigir.scroll_into_view_if_needed()
            time.sleep(0.5)
            redigir.click()
            time.sleep(3)
            print(f'URL apos Redigir: {page.url}')

            # Clica Codigo Fonte
            btn = page.locator('#btnCodigoFonte')
            if btn.is_visible():
                btn.scroll_into_view_if_needed()
                time.sleep(0.5)
                btn.click()
                time.sleep(1)
                print('>>> CodigoFonte clicado')

                # Cola HTML
                fonte = page.locator('#codigoFonte')
                if fonte.is_visible():
                    fonte.fill(doc.html_content)
                    time.sleep(1)
                    page.locator('#btnSalvarCodigoFonte').click()
                    time.sleep(1)
                    print('>>> HTML substituido e salvo!')
                else:
                    print('>>> #codigoFonte nao encontrado')
            else:
                print('>>> #btnCodigoFonte nao encontrado')
                # Tenta achar por texto
                for texto in ['Codigo Fonte', 'Código Fonte', 'HTML', 'Fonte']:
                    alt = page.locator(f"a:text('{texto}')").first
                    if alt.is_visible():
                        alt.click()
                        time.sleep(1)
                        print(f'>>> Clicou em \"{texto}\"')
                        break
        else:
            print('>>> \"Redigir\" nao encontrado no painel')
            # Lista tudo no painel
            panel = page.locator('#divPanelCumprimento')
            if panel.is_visible():
                links = panel.locator('a').all()
                for l in links:
                    print(f'  Link: \"{l.inner_text().strip()[:60]}\"')
    else:
        print('>>> Link Cumprimento nao encontrado')

    input('>>> Enter para fechar...')
    browser.close()
