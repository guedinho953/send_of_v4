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
cnj = '0003099-35.2024.8.05.0191'

with sync_playwright() as pw:
    browser = pw.firefox.launch(headless=False)
    ctx = browser.new_context(viewport={'width': 1400, 'height': 900}, locale='pt-BR')
    for name, value in cookies.items():
        ctx.add_cookies([{'name': name, 'value': value, 'domain': 'projudi.tjba.jus.br', 'path': '/'}])
    page = ctx.new_page()

    # Vai direto para DadosProcesso do JANO (0003099)
    print('\n=== DadosProcesso JANO ===')
    page.goto(f'https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?numeroProcesso={cnj}',
              wait_until='networkidle')
    time.sleep(3)

    page_html = page.content()
    with open('/tmp/pw_dadosproc.html', 'w') as f:
        f.write(page_html)

    # Procura por links relacionados a oficio / cumprimento / expedir
    for term in ['Redigir sem AR', 'Redigir', 'Expedir', 'Oficio', 'Ofício', 'Carta', 'Cumprimento']:
        links = page.locator(f'a:has-text("{term}")').all()
        for l in links:
            if l.is_visible():
                print(f'  VISIVEL: "{l.inner_text()}" href={l.get_attribute("href")}')

    # Tambem procura botoes
    for term in ['Redigir', 'Expedir', 'Ofício', 'Oficio']:
        btns = page.locator(f'input[value*="{term}" i]').all()
        for b in btns:
            if b.is_visible():
                print(f'  BOTAO: value={b.get_attribute("value")}')

    input('\n>>> Enter fechar...')
    browser.close()
