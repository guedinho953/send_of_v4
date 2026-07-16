"""Fluxo Expedir Ofício CIAP - Playwright com perfil Firefox real (herda cookies)"""
import os, sys, time, re, random, math
from datetime import datetime
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()
from django.contrib.auth import get_user_model
from processes.models import GeneratedDocument, DocumentTemplate, RAGExample
from django.template import engines
# ============================================================
# 1. GERAR HTML DO OFICIO CIAP (template id=5)
# ============================================================
print('\n========== 1. GERANDO HTML DO OFICIO ==========')

# Buscar exemplo RAG do Jano (proc 3099)
exemplo = RAGExample.objects.filter(
    process__number__contains='3099'
).first()
if not exemplo:
    exemplo = RAGExample.objects.first()

party = exemplo.process.parties.first()
ctx = exemplo.get_template_context(parte_id=party.id if party else None)
print(f'   RAGExample: {exemplo.id} - process: {exemplo.process.number}')
print(f'   Parte: {ctx.get("parte", {}).get("nome", "N/A")}')

template = DocumentTemplate.objects.get(id=5)
print(f'   Template: {template.name}')

engine = engines['django']
t = engine.from_string(template.html_template)

# Merge com campos de prestacao/servico (do cumprimento ou defaults)
numero_doc = '018/2026'

context = {**ctx,
    'numero_documento': numero_doc,
    'tem_prestacao_pecuniaria': True,
    'valor_prestacao_pecuniaria': 'R$ 1.000,00',
    'parcelas_prestacao_pecuniaria': '6',
    'prazo_prestacao_servico': '6 meses',
}
rendered_html = t.render(context)
print(f'   HTML gerado: {len(rendered_html)} chars')
print(f'   Numero: {numero_doc}')

# Salvar HTML para usar no JS
html_clean = rendered_html.replace('\\', '\\\\').replace("'", "\\'").replace('\n', ' ').replace('\r', '').replace('"', '\\"')

# ============================================================
# 2. ABRIR PLAYWRIGHT COM PERFIL FIREFOX REAL
# ============================================================
print('\n========== 2. PLAYWRIGHT COM PERFIL FIREFOX ==========')

from playwright.sync_api import sync_playwright

# Caminho do perfil Firefox do usuario
FF_PROFILE = '/mnt/c/Users/Ivan/AppData/Roaming/Mozilla/Firefox/Profiles/akugmqxq.default-release'

LINK_BASE = 'https://projudi.tjba.jus.br/projudi/'
PROC_PROJUDI = '41020261733480'  # Proc 3099 (Jano)

def rs(min_s=0.3, max_s=1.5):
    time.sleep(random.uniform(min_s, max_s))

def scroll_slow(page, total_px=None):
    if not total_px:
        total_px = random.randint(300, 700)
    steps = random.randint(3, 6)
    for _ in range(steps):
        step = total_px // steps + random.randint(-20, 20)
        page.evaluate(f'window.scrollBy(0, {step});')
        time.sleep(random.uniform(0.15, 0.5))

def clicar(page, selector, timeout=15000):
    el = page.wait_for_selector(selector, timeout=timeout)
    time.sleep(random.uniform(0.2, 0.7))
    el.click()
    time.sleep(random.uniform(0.3, 0.8))

p = sync_playwright().start()

print('   Iniciando Firefox com perfil real...')
browser = p.firefox.launch_persistent_context(
    user_data_dir=FF_PROFILE,
    headless=False,
    viewport={'width': 1280, 'height': 800},
    locale='pt-BR',
    timezone_id='America/Sao_Paulo',
    args=['--no-sandbox'],
)
page = browser.new_page()

# ============================================================
# 3. VERIFICAR SESSAO
# ============================================================
print('\n========== 3. VERIFICANDO SESSAO ==========')

page.goto(f'{LINK_BASE}listagens/CumprimentoCartorio?tipo=oficio&acao=expedidos',
          wait_until='networkidle')
rs(2, 4)

title = page.title()
print(f'   Title: {title}')
print(f'   URL: {page.url}')

if 'expirou' in title.lower():
    print('\n   ⚠️ SESSÃO EXPIRADA!')
    print('   O Firefox perfil real nao tem sessao valida do Projudi.')
    print('   Vou abrir a pagina de login...')
    page.goto(LINK_BASE, wait_until='networkidle')
    print('\n   👉 Faça login manualmente no navegador que abriu!')
    print('   👉 Depois de logar, volte aqui e pressione ENTER')
    input()
    
    # Verificar de novo
    page.goto(f'{LINK_BASE}movimentacao/MovimentarProcesso?numeroProcesso={PROC_PROJUDI}',
              wait_until='networkidle')
    rs(2, 4)
    if 'expirou' in page.title().lower():
        print('   Ainda expirado. Abortando.')
        browser.close()
        p.stop()
        sys.exit(1)

print('   ✅ Sessao OK!')

# ============================================================
# 4. MOVIMENTAR PROCESSO (581)
# ============================================================
print('\n========== 4. MOVIMENTAR PROCESSO (581) ==========')

page.goto(f'{LINK_BASE}movimentacao/MovimentarProcesso?numeroProcesso={PROC_PROJUDI}',
          wait_until='networkidle')
rs(2, 4)

scroll_slow(page, 400)
rs(0.5, 1)

print('   Preenchendo movimento 581...')

# Campo codigo
codigo = page.wait_for_selector('#seqCategoriaMovimentacao', timeout=10000)
codigo.click()
rs(0.2, 0.4)
codigo.fill('581')
rs(0.5, 1)

# Forcar via JS
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

# Tipo documento = 53 (Ofício)
page.select_option('select[name="codTipoDocumento"]', '53')
print('   Tipo: Ofício (53)')
rs(0.5, 1)

# Observacao
page.fill('#observacao', 'Solicitada a Expedicao de Oficio CIAP - Transacao Penal')
rs(0.5, 1)

scroll_slow(page, 600)
rs(0.5, 1)

# Expandir Cumprimento
try:
    page.click('a:has-text("Cumprimento")')
except:
    try:
        page.evaluate("document.querySelector('a[href*=\"Cumprimento\"]').click();")
    except:
        pass
rs(1, 2)

# Tipo cumprimento = 2 (Ofício)
try:
    page.select_option('#tipoCumprimento', '2')
    print('   Tipo cumprimento: Ofício (2)')
except:
    pass
rs(0.5, 1)

# Destinatario
try:
    dest_options = page.evaluate("""
        Array.from(document.getElementById('codigoDestinatario').options).map(o => o.text)
    """)
    print(f'   Destinatarios: {len(dest_options)}')
    for opt_text in dest_options:
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

# Dialog
try:
    dialog = page.wait_for_event('dialog', timeout=5000)
    print(f'   Dialog: {dialog.message}')
    dialog.accept()
    rs(1, 2)
except:
    pass

# ============================================================
# 5. CUMPRIMENTO CARTORIO - REDIGIR SEM AR
# ============================================================
print('\n========== 5. CUMPRIMENTO CARTORIO ==========')

page.goto(f'{LINK_BASE}listagens/CumprimentoCartorio?tipo=oficio&acao=expedir',
          wait_until='networkidle')
rs(3, 5)

if 'expirou' in page.title().lower():
    print('   Sessao expirou!')
    browser.close()
    p.stop()
    sys.exit(1)

scroll_slow(page, 400)
rs(1, 2)

# Clicar "Redigir sem AR" (ultimo = mais recente)
print('   Buscando link Redigir sem AR...')
try:
    with page.expect_navigation(timeout=15000):
        page.click('a:has-text("Redigir sem AR"):last-of-type')
    print('   Navegou!')
except:
    # Fallback: encontrar por href
    link = page.evaluate("""
        var links = document.querySelectorAll('a[href*="ExpedirCumprimentoCartorio"]');
        if (links.length > 0) {
            links[links.length-1].click();
            return true;
        }
        return false;
    """)
    if not link:
        print('   Nenhum link Redigir sem AR encontrado.')
        
rs(3, 6)
print(f'   URL atual: {page.url}')

# ============================================================
# 6. FCKEDITOR - INJETAR HTML
# ============================================================
print('\n========== 6. INJETANDO HTML NO FCKEDITOR ==========')

scroll_slow(page, 400)
rs(1, 2)

print('   Injetando HTML...')
page.evaluate(f"""
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
print('   HTML injetado!')
rs(2, 3)

scroll_slow(page, 200)
rs(0.5, 1)

# ============================================================
# 7. SUBMETER
# ============================================================
print('\n========== 7. SUBMETER ==========')

try:
    page.click('input[src*="submeter"]', timeout=10000)
    print('   Submeter clicado!')
    rs(3, 6)
except:
    print('   Botao Submeter nao encontrado')

# ============================================================
# 8. REGISTRAR
# ============================================================
print('\n========== 8. REGISTRAR ==========')

try:
    registrar_btn = page.wait_for_selector('a:has-text("Registrar")', timeout=10000)
    registrar_btn.click()
    print('   Registrado!')
    rs(2, 4)
    try:
        dialog = page.wait_for_event('dialog', timeout=5000)
        print(f'   Dialog: {dialog.message}')
        dialog.accept()
    except:
        pass
except:
    print('   Nenhum Registrar (ja registrado?)')

print('\n========== ✅ FLUXO CONCLUIDO ==========')
print(f'   Oficio CIAP gerado para {ctx["parte"]["nome"]} - Proc {PROC_PROJUDI}')
print(f'   Numero Doc: {numero_doc}')
print()
print('   Navegador permanece aberto para voce conferir.')
print('   Pressione Ctrl+C aqui para fechar.')

try:
    while True:
        time.sleep(30)
except KeyboardInterrupt:
    browser.close()
    p.stop()
    print('\n   Navegador fechado.')
