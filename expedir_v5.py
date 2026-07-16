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
    print('\n=== MovimentarProcesso (581) ===')
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

    # Abre Cumprimento
    page.locator("a:text('Cumprimento')").first.click()
    time.sleep(1)
    page.select_option('#tipoCumprimento', '2')
    page.select_option('#codigoDestinatario', '13809981')
    time.sleep(0.5)
    page.click('#btnAddCumprimento')
    time.sleep(2)

    print('Cumprimento adicionado!')
    page.screenshot(path='/tmp/pw_apos_cumprimento.png')

    # Procura link "Expedir" ou "Redigir" na pagina
    links = page.locator('a').all()
    for l in links:
        txt = l.inner_text()
        if 'exped' in txt.lower() or 'redig' in txt.lower():
            print(f'Link encontrado: "{txt}"')

    input('\n>>> Enter para continuar...')
    browser.close()
