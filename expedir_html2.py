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
print(f'>>> Doc #{doc.id} - {doc.recipient_name}')

with sync_playwright() as pw:
    browser = pw.firefox.launch(headless=False)
    ctx = browser.new_context(viewport={'width': 1400, 'height': 900}, locale='pt-BR')
    for name, value in cookies.items():
        ctx.add_cookies([{'name': name, 'value': value, 'domain': 'projudi.tjba.jus.br', 'path': '/'}])
    page = ctx.new_page()

    page.goto(
        'https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=oficio&acao=expedir',
        wait_until='networkidle'
    )
    time.sleep(5)

    # Scopa toda a pagina
    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
    time.sleep(2)

    # Pega todos os links com numeros de processo
    all_links = page.locator('a').all()
    proc_links = []
    for link in all_links:
        txt = link.inner_text().strip()
        href = link.get_attribute('href') or ''
        # Filtra links que parecem numeros de processo (tem digitos e hifen)
        if txt and ('-' in txt or txt.isdigit()):
            proc_links.append((txt, link))
            print(f'  Proc: \"{txt}\"')

    # Ultimo processo da lista
    if proc_links:
        last_txt, last_link = proc_links[-1]
        print(f'\n>>> Ultimo processo: \"{last_txt}\"')
        if 'jano' in last_txt.lower() or '3099' in last_txt:
            print('>>> Este e o JANO! Clicando...')
        else:
            print(f'>>> Nao parece JANO. Clicando mesmo assim...')
        
        last_link.scroll_into_view_if_needed()
        time.sleep(1)
        last_link.click()
        time.sleep(3)
        print(f'URL: {page.url}')

        # Agora na pagina de edicao do oficio
        # Clica no botao para editar HTML (codigo fonte)
        btn_html = page.locator('#btnCodigoFonte')
        if btn_html.is_visible():
            btn_html.scroll_into_view_if_needed()
            time.sleep(0.5)
            btn_html.click()
            time.sleep(1)
            print('>>> Botao CodigoFonte clicado')
        else:
            print('>>> btnCodigoFonte nao visivel')
            # Tenta achar pelo texto
            for b in ['Editar HTML', 'Código Fonte', 'Codigo Fonte', 'HTML']:
                btn2 = page.locator(f"a:text('{b}'), button:text('{b}')").first
                if btn2.is_visible():
                    btn2.click()
                    time.sleep(1)
                    print(f'>>> Clicou em \"{b}\"')
                    break

        # Cola o HTML
        fonte = page.locator('#codigoFonte')
        if fonte.is_visible():
            fonte.fill(doc.html_content)
            time.sleep(1)
            print('>>> HTML colado!')
            page.locator('#btnSalvarCodigoFonte').click()
            time.sleep(1)
            print('>>> Salvo!')
        else:
            print('>>> #codigoFonte nao encontrado')
    else:
        print('>>> Nenhum processo encontrado')

    input('>>> Enter para fechar...')
    browser.close()
