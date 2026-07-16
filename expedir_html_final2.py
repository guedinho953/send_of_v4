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

    # 2. Redigir sem AR (ultimo)
    page.locator("a:text('Redigir sem AR')").last.click()
    time.sleep(4)
    print(f'URL: {page.url}')

    # 3. FCKeditor frame - clicar Source (Codigo Fonte), ultimo botao
    time.sleep(2)
    fck = None
    for f in page.frames:
        if 'fckeditor.html' in f.url:
            fck = f
            break

    if fck:
        print('FCKeditor encontrado')

        # Clica Source (ultimo toolbar button - background-position 0px -720px)
        # Tenta via FCKeditor API
        result = page.evaluate('''(html) => {
            try {
                var oEditor = FCKeditorAPI.GetInstance('FCKeditor1');
                oEditor.SwitchToSourceMode();
                oEditor.SetHTML(html);
                return 'OK:SetHTML';
            } catch(e) {
                try {
                    var oEditor2 = window.parent.FCKeditorAPI.GetInstance('FCKeditor1');
                    oEditor2.SwitchToSourceMode();
                    oEditor2.SetHTML(html);
                    return 'OK:parent';
                } catch(e2) {
                    return 'Erro: ' + e2.message;
                }
            }
        }''', doc.html_content)
        print(f'Resultado: {result}')

        if 'OK' in str(result):
            # Volta pra WYSIWYG
            page.evaluate('''() => {
                try {
                    FCKeditorAPI.GetInstance('FCKeditor1').SwitchToWysiwygMode();
                } catch(e) {
                    try {
                        window.parent.FCKeditorAPI.GetInstance('FCKeditor1').SwitchToWysiwygMode();
                    } catch(e2) {}
                }
            }''')
            time.sleep(1)
            print('Voltou pra WYSIWYG')

        # Submeter
        submeter = page.locator("input[value='Submeter']").first
        if submeter.is_visible():
            submeter.click()
            time.sleep(2)
            print('Submeter clicado')
        else:
            print('Submeter nao encontrado')
    else:
        print('FCKeditor frame NAO encontrado')
        page.screenshot(path='/tmp/pw_sem_fck.png')
        print('Screenshot em /tmp/pw_sem_fck.png')

    input('>>> Enter para fechar...')
    browser.close()
