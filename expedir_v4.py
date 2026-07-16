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

from processes.models import GeneratedDocument, Process, DocumentTemplate, Party
proc = Process.objects.get(number='0003099-35.2024.8.05.0191')
template = DocumentTemplate.objects.get(id=5)
party = Party.objects.filter(process=proc, name__icontains='jano').first()

from django.template import Template, Context
ctx = Context({'parte': party, 'prazo_prestacao_servico': '', 'valor_prestacao_pecuniaria': '', 'parcelas': '', 'tem_prestacao_pecuniaria': False})
html = Template(template.html_template).render(ctx)

from django.db.models import Max
max_seq = GeneratedDocument.objects.filter(template=template, year=2026).aggregate(Max('sequential_number'))['sequential_number__max'] or 0
doc = GeneratedDocument.objects.create(
    process=proc, template=template, rag_example=None,
    recipient_name=str(party), sequential_number=max_seq + 1, year=2026,
    html_content=html, exported_to_projudi=False, tenant=proc.tenant,
)
print(f'Doc #{doc.id} seq={max_seq+1} - {doc.recipient_name}')

pnum = '41020261733480'

with sync_playwright() as pw:
    browser = pw.firefox.launch(headless=False)
    ctx = browser.new_context(viewport={'width': 1400, 'height': 900}, locale='pt-BR')
    for name, value in cookies.items():
        ctx.add_cookies([{'name': name, 'value': value, 'domain': 'projudi.tjba.jus.br', 'path': '/'}])
    page = ctx.new_page()

    # ====== MOVIMENTAR PROCESSO (581) ======
    print('\n=== 1. MovimentarProcesso (581) ===')
    page.goto(f'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso={pnum}',
              wait_until='networkidle')
    time.sleep(2)

    page.evaluate('''() => {
        document.getElementById('seqCategoriaMovimentacao').value = '581';
        document.getElementById('descCategoriaMovimentacao').value = 'Solicitada a Expedição de Ofício';
        var tr = document.getElementById('trTipoDocumento');
        if (tr) tr.style.display = 'table-row';
        var div = document.getElementById('rowDadosMovimentacaoComplemento');
        if (div) div.style.display = 'block';
        var panel = document.getElementById('divPanelCumprimento');
        if (panel) panel.style.display = 'block';
    }''')
    time.sleep(1)

    page.select_option('select[name="codTipoDocumento"]', '53')
    page.fill('#observacao', 'Solicitada a Expedicao de Oficio CIAP - JANO MARCOS FERREIRA SILVA')
    time.sleep(0.5)

    page.locator("a:text('Cumprimento')").first.click()
    time.sleep(1)
    page.select_option('#tipoCumprimento', '2')
    page.select_option('#codigoDestinatario', '13809981')
    time.sleep(0.5)
    page.click('#btnAddCumprimento')
    time.sleep(1)

    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
    time.sleep(0.5)
    page.click('#Concluir')
    time.sleep(3)
    try:
        alert = page.wait_for_event('dialog', timeout=5000)
        print(f'Alerta: "{alert.message}"')
        alert.accept()
        time.sleep(2)
    except:
        pass
    print('581 OK')

    # ====== CumprimentoCartorio -> Redigir sem AR ======
    print('\n=== 2. CumprimentoCartorio -> Redigir sem AR ===')
    page2 = ctx.new_page()
    page2.goto(
        'https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=oficio&acao=expedir',
        wait_until='networkidle'
    )
    time.sleep(3)

    # Clica Redigir sem AR com wait_for_navigation e timeout maior
    with page2.expect_navigation(timeout=15000):
        page2.evaluate('''() => {
            var links = document.querySelectorAll('a');
            for (var i = links.length - 1; i >= 0; i--) {
                if (links[i].innerText.trim() === 'Redigir sem AR') {
                    links[i].click();
                    return;
                }
            }
        }''')
        time.sleep(1)
    print(f'URL navegou para: {page2.url}')

    if 'ExpedirCumprimento' not in page2.url:
        print('Tentando eval onclick...')
        page2.goto('https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=oficio&acao=expedir',
                   wait_until='networkidle')
        time.sleep(3)
        with page2.expect_navigation(timeout=15000):
            page2.evaluate('''() => {
                var links = document.querySelectorAll('a');
                for (var i = links.length - 1; i >= 0; i--) {
                    if (links[i].innerText.trim() === 'Redigir sem AR') {
                        var onclick = links[i].getAttribute('onclick').replace('javascript:', '');
                        eval(onclick);
                        return;
                    }
                }
            }''')
            time.sleep(2)
        print(f'URL navegou para: {page2.url}')

    # ====== FCKeditor ======
    if 'ExpedirCumprimento' in page2.url:
        print('\n=== 3. FCKeditor - Codigo Fonte -> colar HTML ===')
        time.sleep(3)

        page2.evaluate('''(html) => {
            try { FCKeditorAPI.GetInstance('FCKeditor1').SwitchToSourceMode(); } catch(e) {}
            try { window.parent.FCKeditorAPI.GetInstance('FCKeditor1').SwitchToSourceMode(); } catch(e) {}
            try { FCKeditorAPI.GetInstance('FCKeditor1').SetHTML(html); } catch(e) {}
            try { window.parent.FCKeditorAPI.GetInstance('FCKeditor1').SetHTML(html); } catch(e) {}
            try { FCKeditorAPI.GetInstance('FCKeditor1').SwitchToWysiwygMode(); } catch(e) {}
            try { window.parent.FCKeditorAPI.GetInstance('FCKeditor1').SwitchToWysiwygMode(); } catch(e) {}
        }''', doc.html_content)
        print('HTML colado!')
        time.sleep(2)

        submeter = page2.locator("input[value='Submeter']").first
        if submeter.is_visible():
            submeter.click()
            time.sleep(2)
            print('Submeter OK')
    else:
        print(f'ERRO: URL = {page2.url}')
        page2.screenshot(path='/tmp/pw_erro_v4.png')

    input('\n>>> Enter fechar...')
    browser.close()
