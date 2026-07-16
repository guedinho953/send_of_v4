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

with sync_playwright() as pw:
    browser = pw.firefox.launch(headless=False)
    ctx = browser.new_context(viewport={'width': 1400, 'height': 900}, locale='pt-BR')
    for name, value in cookies.items():
        ctx.add_cookies([{'name': name, 'value': value, 'domain': 'projudi.tjba.jus.br', 'path': '/'}])
    page = ctx.new_page()

    # Abre CumprimentoCartorio
    page.goto(
        'https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=oficio&acao=expedir',
        wait_until='networkidle'
    )
    time.sleep(4)

    # Tenta achar "Redigir sem AR" ao lado do 0003099
    # Procura por qualquer link com "Redigir"
    redigir_links = page.locator("a:text('Redigir')").all()
    print(f'Links \"Redigir\" encontrados: {len(redigir_links)}')
    for link in redigir_links:
        txt = link.inner_text().strip()
        href = link.get_attribute('href') or ''
        print(f'  \"{txt}\" -> {href[:100]}')
        # Pega o tr anterior para ver o numero do processo
        parent_tr = page.evaluate('''(el) => {
            let tr = el.closest('tr');
            if (!tr) return '';
            let prev = tr.previousElementSibling;
            if (!prev) return '';
            let a = prev.querySelector('a');
            return a ? a.innerText.trim() : '';
        }''', link.element_handle())
        print(f'    Processo anterior: {parent_tr}')

    input('>>> Enter para fechar...')
    browser.close()
