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

    # 1. CumprimentoCartorio
    page.goto(
        'https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=oficio&acao=expedir',
        wait_until='networkidle'
    )
    time.sleep(4)

    # 2. Clica "Redigir sem AR" do ultimo processo
    redigir = page.locator("a:text('Redigir sem AR')").last
    if redigir.is_visible():
        print('>>> Clicando no ultimo "Redigir sem AR"')
        redigir.scroll_into_view_if_needed()
        time.sleep(0.5)
        redigir.click()
        time.sleep(4)
        print(f'URL: {page.url}')

        # 3. Clica Codigo Fonte
        btn = page.locator('#btnCodigoFonte')
        if btn.is_visible():
            btn.scroll_into_view_if_needed()
            time.sleep(0.5)
            btn.click()
            time.sleep(1)
            print('>>> Codigo Fonte clicado')

            # 4. Cola HTML
            fonte = page.locator('#codigoFonte')
            if fonte.is_visible():
                fonte.fill(doc.html_content)
                time.sleep(1)
                print('>>> HTML colado')

                # 5. Salva
                page.locator('#btnSalvarCodigoFonte').click()
                time.sleep(2)
                print('>>> Salvo!')
            else:
                print('>>> #codigoFonte nao encontrado')
        else:
            print('>>> #btnCodigoFonte nao encontrado')
            # Tenta achar por texto alternativo
            for txt in ['Código Fonte', 'Codigo Fonte', 'HTML']:
                alt = page.locator(f"a, button, input").filter(has_text=txt).first
                if alt.is_visible():
                    alt.click()
                    time.sleep(1)
                    print(f'>>> Clicou em \"{txt}\"')
                    break
    else:
        print('>>> Nenhum "Redigir sem AR" encontrado')

    input('>>> Enter para fechar...')
    browser.close()
