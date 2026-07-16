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
if not doc:
    doc = GeneratedDocument.objects.last()
print(f'>>> Doc #{doc.id} - {doc.recipient_name} - HTML: {len(doc.html_content)} chars')

with sync_playwright() as pw:
    browser = pw.firefox.launch(headless=False)
    ctx = browser.new_context(viewport={'width': 1400, 'height': 900}, locale='pt-BR')
    for name, value in cookies.items():
        ctx.add_cookies([{'name': name, 'value': value, 'domain': 'projudi.tjba.jus.br', 'path': '/'}])
    page = ctx.new_page()

    print('\n--- PASSO 1: Abrindo CumprimentoCartorio > Para Expedir > Oficios ---')
    page.goto(
        'https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=oficio&acao=expedir',
        wait_until='networkidle'
    )
    time.sleep(5)

    print('\n--- Links na pagina: ---')
    links = page.locator('a').all()
    for i, link in enumerate(links):
        txt = link.inner_text().strip()
        href = link.get_attribute('href') or ''
        if txt and len(txt) > 3 and i < 30:
            print(f'  [{i}] \"{txt[:60]}\"')

    print('\n--- PASSO 2: Buscando link do processo 41020261733480 ---')
    link = page.locator("a").filter(has_text="41020261733480")
    count = link.count()
    print(f'  Encontrados: {count}')
    if count > 0:
        link.first.scroll_into_view_if_needed()
        time.sleep(1)
        link.first.click()
        print('  Clicou!')
        time.sleep(3)
        print(f'  URL: {page.url}')

        print('\n--- PASSO 3: Clicando btnCodigoFonte ---')
        btn = page.locator('#btnCodigoFonte')
        if btn.is_visible():
            btn.scroll_into_view_if_needed()
            time.sleep(0.5)
            btn.click()
            time.sleep(1)
            print('  Clicou!')

            print('\n--- PASSO 4: Colando HTML ---')
            fonte = page.locator('#codigoFonte')
            if fonte.is_visible():
                fonte.fill(doc.html_content)
                time.sleep(1)
                print('  HTML colado!')

                print('\n--- PASSO 5: Salvando ---')
                page.locator('#btnSalvarCodigoFonte').click()
                time.sleep(1)
                print('  Salvo!')
            else:
                print('  #codigoFonte nao encontrado')
        else:
            print('  #btnCodigoFonte nao visivel, verificando se existe...')
            exists = page.evaluate("!!document.getElementById('btnCodigoFonte')")
            print(f'  Existe no DOM: {exists}')
            if exists:
                page.evaluate("document.getElementById('btnCodigoFonte').click()")
                time.sleep(1)
                print('  Clicado via JS')
    else:
        print('  Nao encontrado. Tentando listar todos os links:')
        for link in page.locator('a').all():
            txt = link.inner_text().strip()
            href = link.get_attribute('href') or ''
            if txt:
                print(f'  \"{txt[:60]}\"')

    input('\n>>> Pressione Enter para fechar...')
    browser.close()
