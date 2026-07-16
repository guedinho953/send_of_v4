"""Fluxo Expedir Ofício CIAP - Playwright com login manual + humanização"""
import os, sys, time, random, json
from datetime import datetime
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()
from processes.models import DocumentTemplate, RAGExample
from django.template import engines
from playwright.sync_api import sync_playwright

# ============================================================
# 1. GERAR HTML
# ============================================================
print('========== 1. GERANDO HTML DO OFICIO ==========')
exemplo = RAGExample.objects.filter(process__number__contains='3099').first() or RAGExample.objects.first()
party = exemplo.process.parties.first()
ctx = exemplo.get_template_context(parte_id=party.id if party else None)

template = DocumentTemplate.objects.get(id=5)
engine = engines['django']
t = engine.from_string(template.html_template)

context = {**ctx,
    'numero_documento': '018/2026',
    'tem_prestacao_pecuniaria': True,
    'valor_prestacao_pecuniaria': 'R$ 1.000,00',
    'parcelas_prestacao_pecuniaria': '6',
    'prazo_prestacao_servico': '6 meses',
}
rendered_html = t.render(context)
html_clean = rendered_html.replace('\\', '\\\\').replace("'", "\\'").replace('\n', ' ').replace('\r', '').replace('"', '\\"')

print(f'   Processo: {exemplo.process.number}')
print(f'   Parte: {ctx["parte"]["nome"]}')
print(f'   HTML: {len(rendered_html)} chars')

# ============================================================
# 2. PLAYWRIGHT + LOGIN MANUAL
# ============================================================
print('\n========== 2. ABRINDO PLAYWRIGHT FIREFOX ==========')
LINK_BASE = 'https://projudi.tjba.jus.br/projudi/'
PROC_PROJUDI = '41020261733480'

p = sync_playwright().start()
browser = p.firefox.launch_persistent_context(
    user_data_dir='/tmp/projudi_playwright_profile',
    headless=False,
    viewport={'width': 1280, 'height': 800},
    locale='pt-BR',
)
page = browser.new_page()

def rs(a=0.3, b=1.5):
    time.sleep(random.uniform(a, b))

def scroll_slow(page, total=None):
    if not total: total = random.randint(300, 700)
    steps = random.randint(3, 6)
    for _ in range(steps):
        page.evaluate(f'window.scrollBy(0, {total // steps + random.randint(-20, 20)});')
        time.sleep(random.uniform(0.15, 0.5))

# ============================================================
# 3. LOGIN
# ============================================================
print('\n========== 3. LOGIN NO PROJUDI ==========')
page.goto(f'{LINK_BASE}listagens/CumprimentoCartorio?tipo=oficio&acao=expedidos', wait_until='networkidle')
rs(2, 4)

if 'expirou' in page.title().lower():
    print('   ⚠️ Sessão expirada. Indo para login...')
    page.goto(LINK_BASE, wait_until='networkidle')
    rs(1, 2)
    print()
    print('   ╔══════════════════════════════════════════╗')
    print('   ║   👉 FAÇA LOGIN MANUAL NO PROJUDI        ║')
    print('   ║   👉 NO NAVEGADOR QUE ACABOU DE ABRIR    ║')
    print('   ║   ⏳ AGUARDANDO LOGIN AUTOMATICAMENTE...  ║')
    print('   ╚══════════════════════════════════════════╝')
    print()
    
    # Polling: aguarda ate ter JSESSIONID no cookie
    for i in range(300):  # 5 min max
        try:
            ck = browser.cookies()
            has_session = any(c['name'] == 'JSESSIONID' and 'projudi' in c.get('domain', '') for c in ck)
            if has_session:
                print(f'   ✅ Login detectado! JSESSIONID presente (apos ~{i*2}s)')
                break
        except:
            pass
        if i % 15 == 0:
            print(f'   Aguardando login... ({i//15 * 30}s)')
        time.sleep(2)
    else:
        print('   ❌ Timeout aguardando login (5 min)')
        browser.close(); p.stop(); sys.exit(1)
    
    page.goto(f'{LINK_BASE}movimentacao/MovimentarProcesso?numeroProcesso={PROC_PROJUDI}', wait_until='networkidle')
    rs(2, 4)
    if 'expirou' in page.title().lower():
        print('   ❌ Ainda expirado. Abortando.')
        browser.close(); p.stop(); sys.exit(1)

print('   ✅ LOGADO!')

# Salvar cookies pro resto do script
cookies_playwright = {c['name']: c['value'] for c in browser.cookies() if 'projudi' in c.get('domain', '')}
print(f'   Cookies: {len(cookies_playwright)} (JSESSIONID: {"SIM" if cookies_playwright.get("JSESSIONID") else "NAO"})')

# ============================================================
# 4. MOVIMENTAR PROCESSO (581)
# ============================================================
print('\n========== 4. MOVIMENTAR PROCESSO (581) ==========')
page.goto(f'{LINK_BASE}movimentacao/MovimentarProcesso?numeroProcesso={PROC_PROJUDI}', wait_until='networkidle')
rs(2, 4)
scroll_slow(page, 400)
rs(0.5, 1)

print('   Preenchendo 581...')

# Campo seqCategoriaMovimentacao
page.fill('#seqCategoriaMovimentacao', '581')
rs(0.5, 1)

# Forcar via JS (DWR validation)
page.evaluate("""
    document.getElementById('descCategoriaMovimentacao').value = 'Solicitada a Expedição de Ofício';
    var tr = document.getElementById('trTipoDocumento');
    if (tr) tr.style.display = 'table-row';
    var div = document.getElementById('rowDadosMovimentacaoComplemento');
    if (div) div.style.display = 'block';
    var panel = document.getElementById('divPanelCumprimento');
    if (panel) panel.style.display = 'block';
""")
rs(1, 2)

# Tipo documento = 53
page.select_option('select[name="codTipoDocumento"]', '53')
print('   Tipo: Ofício (53)')
rs(0.5, 1)

# Observacao
page.fill('#observacao', 'Solicitada a Expedicao de Oficio CIAP - Transacao Penal')
rs(0.5, 1)
scroll_slow(page, 600)
rs(0.5, 1)

# Cumprimento
try:
    page.click('a:has-text("Cumprimento")')
except:
    page.evaluate("document.querySelector('a[href*=\"Cumprimento\"]').click();")
rs(1, 2)

# Tipo cumprimento = 2
try:
    page.select_option('#tipoCumprimento', '2')
    print('   Tipo cumprimento: Ofício (2)')
except:
    pass
rs(0.5, 1)

# Destinatario
try:
    dests = page.evaluate("Array.from(document.getElementById('codigoDestinatario').options).map(o => o.text)")
    print(f'   Destinatarios: {len(dests)}')
    for opt_text in dests:
        if 'CIAP' in opt_text.upper() or 'SEAP' in opt_text.upper():
            page.select_option('#codigoDestinatario', label=opt_text)
            print(f'   Destinatario: {opt_text}')
            break
except:
    pass
rs(0.5, 1)

# Adicionar cumprimento
try:
    page.click('#btnAddCumprimento')
except:
    pass
rs(1, 2)
scroll_slow(page, 300)
rs(0.5, 1)

# Concluir
print('   Clicando Concluir...')
try:
    page.click('#Concluir')
except:
    page.evaluate("document.getElementById('Concluir').click();")
rs(2, 4)

try:
    dialog = page.wait_for_event('dialog', timeout=5000)
    print(f'   Dialog: {dialog.message}')
    dialog.accept()
    rs(1, 2)
except:
    pass

# ============================================================
# 5. CUMPRIMENTO CARTORIO
# ============================================================
print('\n========== 5. CUMPRIMENTO CARTORIO ==========')
page.goto(f'{LINK_BASE}listagens/CumprimentoCartorio?tipo=oficio&acao=expedir', wait_until='networkidle')
rs(3, 5)

if 'expirou' in page.title().lower():
    print('   Sessao expirou!')
    browser.close(); p.stop(); sys.exit(1)

scroll_slow(page, 400)
rs(1, 2)

print('   Clicando Redigir sem AR...')
try:
    with page.expect_navigation(timeout=15000):
        page.click('a:has-text("Redigir sem AR")')
    print('   Navegou!')
except:
    clicked = page.evaluate("""
        var links = document.querySelectorAll('a[href*="ExpedirCumprimentoCartorio"]');
        if (links.length > 0) { links[links.length-1].click(); return true; }
        return false;
    """)
    if not clicked:
        print('   Nenhum link Redigir sem AR encontrado!')
        browser.close(); p.stop(); sys.exit(1)

rs(3, 6)
print(f'   URL: {page.url[:120]}')

# ============================================================
# 6. FCKEDITOR
# ============================================================
print('\n========== 6. INJETANDO HTML NO FCKEDITOR ==========')
scroll_slow(page, 400)
rs(1, 2)

result = page.evaluate(f"""
    try {{
        var editor = FCKeditorAPI.GetInstance('FCKeditor1');
        editor.SwitchToSourceMode();
        editor.SetHTML('{html_clean}');
        editor.SwitchToWysiwygMode();
        return 'OK';
    }} catch(e) {{
        return 'ERRO: ' + e.message;
    }}
""")
print(f'   Resultado: {result}')
rs(2, 3)
scroll_slow(page, 200)
rs(0.5, 1)

# ============================================================
# 7. SUBMETER
# ============================================================
print('\n========== 7. SUBMETER ==========')
try:
    page.click('input[src*="submeter"]', timeout=10000)
    print('   Submetido!')
    rs(3, 6)
except:
    print('   Botao Submeter nao encontrado')

# ============================================================
# 8. REGISTRAR
# ============================================================
print('\n========== 8. REGISTRAR ==========')
try:
    reg = page.wait_for_selector('a:has-text("Registrar")', timeout=10000)
    reg.click()
    print('   Registrado!')
    rs(2, 4)
    try:
        d = page.wait_for_event('dialog', timeout=5000)
        print(f'   Dialog: {d.message}'); d.accept()
    except:
        pass
except:
    print('   Nenhum Registrar')

print(f'\n========== ✅ CONCLUIDO ==========')
print(f'   Oficio CIAP - {ctx["parte"]["nome"]}')
print(f'   Proc {PROC_PROJUDI} - Num Doc 018/2026')
print()
print('   Navegador aberto. Pressione Ctrl+C para fechar.')
try:
    while True: time.sleep(30)
except KeyboardInterrupt:
    browser.close(); p.stop()
    print('   Fechado.')
