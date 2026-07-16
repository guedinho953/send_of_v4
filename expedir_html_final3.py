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
        'https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=oficio&acao=expedir',
        wait_until='networkidle'
    )
    time.sleep(4)

    # Clica "Redigir sem AR" do ultimo usando JavaScript
    # O link tem: javascript: document.formCumprimento6071222.gerarar.value=false; document.formCumprimento6071222.submit();
    # Descobre qual o ultimo form
    print('Clicando no ultimo Redigir sem AR via JavaScript...')
    result = page.evaluate('''() => {
        var links = document.querySelectorAll('a');
        var lastRedigir = null;
        for (var i = links.length - 1; i >= 0; i--) {
            if (links[i].innerText.trim() === 'Redigir sem AR') {
                lastRedigir = links[i];
                break;
            }
        }
        if (!lastRedigir) return 'Nao encontrado';
        var onclick = lastRedigir.getAttribute('onclick') || lastRedigir.getAttribute('href') || '';
        // Extrai o form name do onclick
        var match = onclick.match(/document\\.(\\w+)\\.submit/);
        if (match) {
            var formName = match[1];
            var form = document.forms[formName] || document.getElementById(formName);
            if (form) {
                form.gerarar ? form.gerarar.value = 'false' : null;
                form.submit();
                return 'Submit: ' + formName;
            }
        }
        // Tenta executar o onclick direto
        try {
            eval(onclick.replace('javascript:', ''));
            return 'Eval: ' + onclick.substring(0, 100);
        } catch(e) {
            return 'Erro: ' + e.message;
        }
    }''')
    print(f'Resultado: {result}')
    time.sleep(5)

    print(f'URL: {page.url}')

    # Se foi pra pagina de edicao
    if 'ExpedirCumprimento' in page.url:
        print('Na pagina de edicao!')

        fck = None
        for f in page.frames:
            if 'fckeditor.html' in f.url:
                fck = f
                break

        if fck:
            print('FCKeditor encontrado!')
            # Troca pra Source mode e seta HTML
            page.evaluate('''(html) => {
                try { FCKeditorAPI.GetInstance('FCKeditor1').SwitchToSourceMode(); } catch(e) {}
                try { window.parent.FCKeditorAPI.GetInstance('FCKeditor1').SwitchToSourceMode(); } catch(e) {}
                try { FCKeditorAPI.GetInstance('FCKeditor1').SetHTML(html); } catch(e) {}
                try { window.parent.FCKeditorAPI.GetInstance('FCKeditor1').SetHTML(html); } catch(e) {}
            }''', doc.html_content)
            time.sleep(2)

            # Submeter
            submeter = page.locator("input[value='Submeter']").first
            if submeter.is_visible():
                submeter.click()
                time.sleep(2)
                print('Submeter clicado!')
        else:
            print('FCKeditor frame NAO encontrado')
            page.screenshot(path='/tmp/pw_edicao.png')
    else:
        print('Nao foi pra pagina de edicao')

    input('>>> Enter para fechar...')
    browser.close()
