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

# Pega o maior sequential_number para template 5 em 2026
from django.db.models import Max
max_seq = GeneratedDocument.objects.filter(template=template, year=2026).aggregate(Max('sequential_number'))['sequential_number__max'] or 0
new_seq = max_seq + 1

doc = GeneratedDocument.objects.create(
    process=proc, template=template, rag_example=None,
    recipient_name=str(party), sequential_number=new_seq, year=2026,
    html_content=html, exported_to_projudi=False, tenant=proc.tenant,
)
print(f'Doc #{doc.id} seq={new_seq} - {doc.recipient_name}')

pnum = '41020261733480'

with sync_playwright() as pw:
    browser = pw.firefox.launch(headless=False)
    ctx = browser.new_context(viewport={'width': 1400, 'height': 900}, locale='pt-BR')
    for name, value in cookies.items():
        ctx.add_cookies([{'name': name, 'value': value, 'domain': 'projudi.tjba.jus.br', 'path': '/'}])
    page = ctx.new_page()

    # ====== PARTE 1: Movimentar Processo (581) ======
    print('\n===== PARTE 1: Movimentar Processo (581) =====')
    page.goto(f'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso={pnum}',
              wait_until='networkidle')
    time.sleep(2)

    # 581
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

    page.select_option('#tipoCumprimento', '2')  # OFICIO
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

    print(f'URL apos Parte 1: {page.url}')

    # ====== PARTE 2: CumprimentoCartorio ======
    print('\n===== PARTE 2: CumprimentoCartorio - Redigir sem AR =====')
    # Abre nova guia
    page2 = ctx.new_page()
    page2.goto(
        'https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=oficio&acao=expedir',
        wait_until='networkidle'
    )
    time.sleep(4)

    # Clica no ultimo "Redigir sem AR" via JS
    result = page2.evaluate('''() => {
        var links = document.querySelectorAll('a');
        for (var i = links.length - 1; i >= 0; i--) {
            if (links[i].innerText.trim() === 'Redigir sem AR') {
                var onclick = links[i].getAttribute('onclick') || links[i].getAttribute('href') || '';
                try {
                    eval(onclick.replace('javascript:', ''));
                    return 'Clicado ' + onclick.substring(0, 80);
                } catch(e) { return 'Erro: ' + e.message; }
            }
        }
        return 'Link nao encontrado';
    }''')
    print(f'Redigir sem AR: {result}')
    time.sleep(5)

    print(f'URL: {page2.url}')

    if 'ExpedirCumprimento' in page2.url:
        print('Pagina de edicao carregada!')

        # FCKeditor via API
        r = page2.evaluate('''(html) => {
            try {
                var ed = FCKeditorAPI.GetInstance('FCKeditor1');
                if (ed) {
                    ed.SwitchToSourceMode();
                    ed.SetHTML(html);
                    ed.SwitchToWysiwygMode();
                    return 'FCKeditorAPI OK';
                }
            } catch(e) {
                try {
                    var ed2 = window.parent.FCKeditorAPI.GetInstance('FCKeditor1');
                    if (ed2) {
                        ed2.SwitchToSourceMode();
                        ed2.SetHTML(html);
                        ed2.SwitchToWysiwygMode();
                        return 'parent.FCKeditorAPI OK';
                    }
                } catch(e2) {}
            }
            // Fallback: textarea
            var ta = document.getElementById('FCKeditor1___TextArea');
            if (ta) { ta.value = html; return 'TextArea OK'; }
            return 'Nada funcionou';
        }''', doc.html_content)
        print(f'SetHTML: {r}')

        time.sleep(2)
        submeter = page2.locator("input[value='Submeter']").first
        if submeter.is_visible():
            submeter.click()
            time.sleep(2)
            print('Submeter clicado!')
    else:
        print('Nao foi pra ExpedirCumprimento')
        page2.screenshot(path='/tmp/pw_erro2.png')

    input('\n>>> Enter para fechar...')
    browser.close()
