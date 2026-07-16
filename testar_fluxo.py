import os, time, sys
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()
from projudi.services import ProjudiService
from django.contrib.auth import get_user_model
from playwright.sync_api import sync_playwright, TimeoutError

# Gera novo documento para JANO (esta na lista de partes)
from processes.models import GeneratedDocument, Process, DocumentTemplate, Party
proc = Process.objects.get(number='0003099-35.2024.8.05.0191')
template = DocumentTemplate.objects.get(id=5)
party = Party.objects.filter(process=proc, name__icontains='jano').first()
print(f'Gerando oficio para: {party}')

from django.template import Template, Context
ctx = Context({'parte': party, 'prazo_prestacao_servico': '', 'valor_prestacao_pecuniaria': '', 'parcelas': '', 'tem_prestacao_pecuniaria': False})
html = Template(template.html_template).render(ctx)

doc = GeneratedDocument.objects.create(
    process=proc,
    template=template,
    rag_example=None,
    recipient_name=str(party),
    sequential_number=6,
    year=2026,
    html_content=html,
    exported_to_projudi=False,
    tenant=proc.tenant,
)
print(f'Doc #{doc.id} gerado!')

User = get_user_model()
user = User.objects.filter(is_superuser=True).first()
service = ProjudiService(user)
session = service._get_session_from_cookie_jar()
cookies = session.cookies.get_dict()
pnum = '41020261733480'

with sync_playwright() as pw:
    browser = pw.firefox.launch(headless=False)
    ctx = browser.new_context(viewport={'width': 1400, 'height': 900}, locale='pt-BR')
    for name, value in cookies.items():
        ctx.add_cookies([{'name': name, 'value': value, 'domain': 'projudi.tjba.jus.br', 'path': '/'}])
    page = ctx.new_page()

    # ABA 1: DadosProcesso
    page.goto(f'https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?numeroProcesso={pnum}',
              wait_until='networkidle')
    print('\n>>> ABA 1: DadosProcesso - movimentacoes do processo')
    time.sleep(2)

    # ABA 2: MovimentarProcesso
    page2 = ctx.new_page()
    page2.goto(f'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso={pnum}',
               wait_until='networkidle')
    print('>>> ABA 2: MovimentarProcesso - formulario em branco')
    time.sleep(2)

    # 1. Preenche 581
    print('\n--- PASSO 1: Preenchendo 581 ---')
    page2.fill('#seqCategoriaMovimentacao', '581')
    time.sleep(1)

    # 2. Preenche 581 + mostra campos ocultos
    print('\n--- PASSO 2: Preenchendo 581 e mostrando campos ---')
    page2.evaluate('''() => {
        document.getElementById('seqCategoriaMovimentacao').value = '581';
        document.getElementById('descCategoriaMovimentacao').value = 'Solicitada a Expedição de Ofício';
        // Mostra Tipo de Documento
        var tr = document.getElementById('trTipoDocumento');
        if (tr) tr.style.display = 'table-row';
        // Mostra painel complemento
        var div = document.getElementById('rowDadosMovimentacaoComplemento');
        if (div) div.style.display = 'block';
        // Mostra painel cumprimento
        var panel = document.getElementById('divPanelCumprimento');
        if (panel) panel.style.display = 'block';
    }''')
    time.sleep(1)

    # 3. Tipo de documento = 53 (Oficio)
    print('\n--- PASSO 3: Tipo de documento = 53 (Oficio) ---')
    page2.select_option('select[name="codTipoDocumento"]', '53', timeout=5000)
    print('  OK')
    time.sleep(0.5)

    # 4. Observacao
    print('\n--- PASSO 4: Observacao ---')
    obs = 'Solicitada a Expedicao de Oficio CIAP - JANO MARCOS FERREIRA SILVA'
    page2.fill('#observacao', obs)
    print(f'  "{obs}"')
    time.sleep(0.5)

    # 5. Abre Cumprimento Cartorio
    print('\n--- PASSO 5: Cumprimento(s) Cartorio ---')
    page2.locator("a:text('Cumprimento')").first.click()
    time.sleep(1)

    # 6. Tipo cumprimento = OFICIO
    print('\n--- PASSO 6: Tipo cumprimento = OFICIO ---')
    page2.select_option('#tipoCumprimento', '2', timeout=5000)
    print('  OK')
    time.sleep(0.5)

    # 7. Destinatario JANO
    print('\n--- PASSO 7: Destinatario JANO ---')
    page2.select_option('#codigoDestinatario', '13809981')
    print('  OK')
    time.sleep(0.5)

    # 8. Adicionar (>>)
    print('\n--- PASSO 8: Adicionar (>>) ---')
    page2.click('#btnAddCumprimento')
    time.sleep(1)

    # 9. Concluir
    print('\n--- PASSO 9: Concluir ---')
    page2.evaluate('window.scrollTo(0, document.body.scrollHeight)')
    time.sleep(0.5)
    page2.click('#Concluir')
    time.sleep(3)

    try:
        alert = page2.wait_for_event('dialog', timeout=5000)
        print(f'  Alerta: "{alert.message}"')
        alert.accept()
        time.sleep(2)
    except:
        print('  Sem alerta')

    print(f'\nURL final: {page2.url}')
    page2.screenshot(path='/tmp/pw_fim.png')
    if 'DadosProcesso' in page2.url or 'Historico' in page2.url:
        print('SUCESSO!')

    input('\nPressione Enter para fechar o Firefox...')
    browser.close()
