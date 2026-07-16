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
print(f'Doc #{doc.id} - {doc.recipient_name}')

pnum = '41020261733480'

with sync_playwright() as pw:
    browser = pw.firefox.launch(headless=False)
    ctx = browser.new_context(viewport={'width': 1400, 'height': 900}, locale='pt-BR')
    for name, value in cookies.items():
        ctx.add_cookies([{'name': name, 'value': value, 'domain': 'projudi.tjba.jus.br', 'path': '/'}])
    page = ctx.new_page()

    print('\n=== MovimentarProcesso (581) ===')
    page.goto(f'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso={pnum}',
              wait_until='networkidle')
    time.sleep(2)

    # Preenche 581
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
    page.fill('#observacao', 'Solicitada a Expedicao de Oficio CIAP - JANO')
    time.sleep(0.5)

    # Adiciona cumprimento
    page.locator("a:text('Cumprimento')").first.click()
    time.sleep(1)
    page.select_option('#tipoCumprimento', '2')
    page.select_option('#codigoDestinatario', '13809981')
    page.click('#btnAddCumprimento')
    time.sleep(1)
    print('Cumprimento adicionado!')

    # Mostra a div DigitarDoc
    page.evaluate('''() => {
        var dd = document.getElementById('DigitarDoc');
        if (dd) dd.style.display = 'block';
    }''')
    time.sleep(1)

    # Seleciona "Ofício" em codDescricao1
    # Procura qual option tem "Ofício"
    desc_value = page.evaluate('''() => {
        var sel = document.getElementById('codDescricao1');
        for (var i = 0; i < sel.options.length; i++) {
            if (sel.options[i].text.toLowerCase().includes('ofício') || 
                sel.options[i].text.toLowerCase().includes('oficio') ||
                sel.options[i].text.toLowerCase().includes('of' + String.fromCharCode(237) + 'cio')) {
                return sel.options[i].value;
            }
        }
        return null;
    }''')
    print(f'codDescricao1 para Oficio: {desc_value}')
    
    if desc_value:
        page.select_option('#codDescricao1', desc_value)
        time.sleep(0.5)

    # Clica Digitar Diretamente o Texto (da div DigitarDoc)
    print('Clicando Digitar Diretamente o Texto...')
    with page.expect_navigation(timeout=15000):
        page.evaluate('''() => {
            // Preenche formRedigirText com dados do formDitar
            var formDitar = document.getElementById('formDitar');
            var sel = formDitar.codDescricao1;
            document.formRedigirText.codDescricao.value = sel.value;
            document.formRedigirText.descricao.value = formDitar.descricao.value;
            document.formRedigirText.codModelo.value = formDitar.modelo.value;
            document.formRedigirText.submit();
        }''')
        time.sleep(2)

    print(f'URL: {page.url}')

    # Deve estar no DigitarTexto
    if 'DigitarTexto' in page.url:
        print('No DigitarTexto!')
        time.sleep(3)

        # FCKeditor
        r = page.evaluate('''(html) => {
            try { FCKeditorAPI.GetInstance('FCKeditor1').SwitchToSourceMode(); } catch(e) {}
            try { window.parent.FCKeditorAPI.GetInstance('FCKeditor1').SwitchToSourceMode(); } catch(e) {}
            try { FCKeditorAPI.GetInstance('FCKeditor1').SetHTML(html); } catch(e) {}
            try { window.parent.FCKeditorAPI.GetInstance('FCKeditor1').SetHTML(html); } catch(e) {}
            try { FCKeditorAPI.GetInstance('FCKeditor1').SwitchToWysiwygMode(); } catch(e) {}
            try { window.parent.FCKeditorAPI.GetInstance('FCKeditor1').SwitchToWysiwygMode(); } catch(e) {}
            return 'OK';
        }''', doc.html_content)
        print(f'SetHTML: {r}')

        time.sleep(2)

        # Submeter (salva texto)
        submeter = page.locator("input[value='Submeter']").first
        if submeter.is_visible():
            submeter.click()
            time.sleep(4)
            print(f'Submeter OK - URL: {page.url}')
        else:
            print('Submeter nao encontrado')

        # DEPOIS do Submeter, busca Registrar
        registrar = page.locator("input[value='Registrar']").first
        if registrar.is_visible():
            registrar.click()
            time.sleep(3)
            print('Registrar OK')
        else:
            print('Registrar nao encontrado apos Submeter')
    else:
        print(f'URL inesperada: {page.url}')
        page.screenshot(path='/tmp/pw_erro_direto.png')

    input('\n>>> Enter fechar...')
    browser.close()
