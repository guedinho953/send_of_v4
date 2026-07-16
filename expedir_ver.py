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

with sync_playwright() as pw:
    browser = pw.firefox.launch(headless=False)
    ctx = browser.new_context(viewport={'width': 1400, 'height': 900}, locale='pt-BR')
    for name, value in cookies.items():
        ctx.add_cookies([{'name': name, 'value': value, 'domain': 'projudi.tjba.jus.br', 'path': '/'}])
    page = ctx.new_page()

    # Vai pro CumprimentoCartorio e clica Redigir sem AR
    page.goto('https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=oficio&acao=expedir',
              wait_until='networkidle')
    time.sleep(3)

    with page.expect_navigation(timeout=15000):
        page.evaluate('''() => {
            var links = document.querySelectorAll('a');
            for (var i = links.length - 1; i >= 0; i--) {
                if (links[i].innerText.trim() === 'Redigir sem AR') {
                    links[i].click();
                    return;
                }
            }
        }''')
        time.sleep(2)

    print(f'URL: {page.url}')
    time.sleep(4)

    # Salva HTML
    html_content = page.content()
    with open('/tmp/pw_expedir.html', 'w') as f:
        f.write(html_content)
    print('HTML salvo em /tmp/pw_expedir.html')

    # Procura botoes
    btns = page.locator('input[type="submit"], input[type="button"], button').all()
    for b in btns:
        if b.is_visible():
            val = b.get_attribute('value') or b.inner_text()
            print(f'  Botao visivel: "{val}"')

    input('\n>>> Enter fechar...')
    browser.close()
