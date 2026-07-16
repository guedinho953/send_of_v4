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

    # Vai direto pro MovimentarProcesso (movimentacao generica)
    page.goto(
        'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso=41020261733480',
        wait_until='networkidle'
    )
    time.sleep(3)
    print(f'URL: {page.url}')

    # Tira screenshot
    page.screenshot(path='/tmp/pw_movimentar.png')

    # Lista tudo na pagina
    body = page.locator('body').inner_text()
    print(body[:2000])

    input('>>> Enter para fechar...')
    browser.close()
