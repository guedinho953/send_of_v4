"""Rastreia movimentações no Projudi + expede ofício CIAP automaticamente.

Uso:
    python rastrear_expedir.py 0003099-35.2024.8.05.0191
    python rastrear_expedir.py                          # modo interativo

Fluxo:
  1. Carrega cookies do arquivo JSON
  2. Busca processo no Django pelo número CNJ
  3. Extrai dados do Projudi (partes, movs, cumprimento)
  4. Gera ofício HTML com template id=5
  5. Playwright: Movimento 581 → CumprimentoCartorio → FCKeditor → Registrar
"""

import os, sys, time, random, re
sys.path.insert(0, '/home/ivan/PythonProjects/send_of_v4')
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

import json
import requests
from playwright.sync_api import sync_playwright
from processes.models import GeneratedDocument, Process, DocumentTemplate, Party
from datetime import date
from django.template import Template, Context
from django.db.models import Max
from processo_parser_ext import ProcessoParserExt

# ====== CONFIG ======
TEMPLATE_ID = 5
SECRETARIO = 'MAURO EMILIO VIANA DA SILVA MOREIRA'

# ====== PARSE ARGS ======
PROC_NUM = None
if len(sys.argv) > 1:
    PROC_NUM = sys.argv[1].strip()

if not PROC_NUM:
    print('=== Rastreador e Expedidor de Ofício CIAP ===')
    print()
    PROC_NUM = input('Número do processo CNJ: ').strip()
    if not PROC_NUM:
        print('   Número obrigatório!')
        sys.exit(1)

print(f'\nProcesso CNJ: {PROC_NUM}')

# ====== 1. CARREGAR COOKIES ======
print('\n========== 1. Carregando cookies ==========')
cookies_paths = [
    '/mnt/d/Projudi/cookies.json',
    os.path.expanduser('~/.projudi_cookies.json'),
    '/tmp/projudi_cookies.json',
]
cookies_dict = {}
for cp in cookies_paths:
    if os.path.exists(cp):
        with open(cp) as f:
            cookies_dict = json.load(f)
        print(f'   Cookies: {cp} ({len(cookies_dict)} cookies)')
        break

if not cookies_dict or not cookies_dict.get('JSESSIONID'):
    print('   ERRO: cookies não encontrados ou sem JSESSIONID!')
    print('   Execute capture_cookies.bat no Windows primeiro.')
    sys.exit(1)
print(f'   JSESSIONID: {cookies_dict["JSESSIONID"][:30]}...')

# Validar sessão
session = requests.Session()
session.cookies.update(cookies_dict)
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9',
})
r = session.get('https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=oficio', timeout=10)
if 'login' in r.url.lower() or 'expirou' in r.text.lower():
    print(f'   Sessão expirada (URL: {r.url}). Recapture os cookies.')
    sys.exit(1)
print('   Sessão OK!')

# ====== 2. LOCALIZAR PROCESSO NO DJANGO ======
print('\n========== 2. Localizando processo ==========')
try:
    proc = Process.objects.get(number=PROC_NUM)
    print(f'   ID: {proc.id}')
    print(f'   CNJ: {proc.number}')
    print(f'   Status: {proc.status}')
    print(f'   Vara: {proc.vara}')
except Process.DoesNotExist:
    print(f'   Processo {PROC_NUM} não encontrado no Django.')
    sys.exit(1)

# ====== 3. OBTER NÚMERO PROJUDI ======
# Verificar se já temos o número Projudi salvo
PROC_PROJUDI = None

# 1. Tentar do 2º argumento CLI
if len(sys.argv) > 2:
    PROC_PROJUDI = sys.argv[2].strip()

# 2. Tentar extrair do projudi_url no banco
if not PROC_PROJUDI and proc.projudi_url:
    match = re.search(r'numeroProcesso=([^&]+)', proc.projudi_url)
    if match:
        PROC_PROJUDI = match.group(1)
        print(f'   Projudi URL: {PROC_PROJUDI}')

# 3. Se não tem, pedir
if not PROC_PROJUDI:
    print()
    print('   Número Projudi não encontrado.')
    print('   Use: python rastrear_expedir.py CNJ_NUMBER PROJUDI_NUMBER')
    print('   Ex:  python rastrear_expedir.py 0003099-35.2024.8.05.0191 41020261733480')
    print()
    sys.exit(1)

# Salvar no banco (se não tinha)
if not proc.projudi_url:
    proc.projudi_url = f'https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?numeroProcesso={PROC_PROJUDI}'
    proc.save(update_fields=['projudi_url'])
    print(f'   Salvo no banco (ID {proc.id})!')

print(f'   Projudi número: {PROC_PROJUDI}')

# ====== 4. EXTRAIR DADOS DO PROJUDI ======
print('\n========== 3. Extraindo dados do Projudi ==========')
proc_url = f'https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?numeroProcesso={PROC_PROJUDI}'
r_proc = session.get(proc_url, timeout=30)

dados_cump = {'tipo': None, 'valor': None, 'parcelas': None, 'prazo': None, 'documentos_ata': [], 'ata_extraida': None}
autor = None

if r_proc.status_code == 200 and 'login' not in r_proc.url.lower():
    parser = ProcessoParserExt(r_proc.text, session=session)
    movs_raw, _ = parser.extrair_movimentacoes()
    partes = parser.extrair_partes()
    dados_cump = parser.buscar_dados_cumprimento(movs_raw)
    autor = parser.buscar_autor_vitima(partes)

    print(f'   Partes: {len(partes)}')
    print(f'   Movimentações: {len(movs_raw)}')
    print(f'   Tipo: {dados_cump.get("tipo")}')

    # Mostrar partes para seleção
    print()
    print('   Partes encontradas:')
    for i, p in enumerate(partes):
        name = p.get('nome', '?')
        cpf = p.get('cpf_cnpj', '')
        print(f'   [{i}] {name} {f"({cpf})" if cpf else ""}')
        # Auto-detectar a parte (réu/executado — pula O ESTADO e MP)
        partido_nome = None
        seen = set()
        for p in partes:
            nome = p.get('nome', '').strip()
            # Limpar sufixos indesejados
            nome_clean = nome.split('Transação')[0].split('Penal')[0].strip()
            if nome_clean and nome_clean not in seen:
                seen.add(nome_clean)
                if nome_clean.upper() not in ('O ESTADO', 'MINISTÉRIO PÚBLICO', ''):
                    partido_nome = nome_clean
                    break

        if not partido_nome:
            partido_nome = partes[0].get('nome', '') if partes else None

        print(f'   Parte selecionada: {partido_nome}')

        # Buscar party no Django
        party = None
        if partido_nome:
            # Tenta match exato ou parcial
            party = Party.objects.filter(process=proc, name__icontains=partido_nome[:30]).first()
        if not party:
            party = Party.objects.filter(process=proc).exclude(name__in=['O ESTADO', 'Ministério Público']).first()
        if not party:
            party = Party.objects.filter(process=proc).first()
        if party:
            print(f'   Party no Django: ID {party.id} - {party.name}')
else:
    print(f'   Aviso: não foi possível acessar o processo ({r_proc.status_code})')
    party = Party.objects.filter(process=proc).first()
    print(f'   Usando party do banco: ID {party.id} - {party.name}' if party else '   Sem party!')

# ====== 5. GERAR HTML DO OFÍCIO ======
print('\n========== 4. Gerando HTML do ofício ==========')
template = DocumentTemplate.objects.get(id=TEMPLATE_ID)
max_seq = GeneratedDocument.objects.filter(template=template, year=date.today().year).aggregate(Max('sequential_number'))['sequential_number__max'] or 0
num = max_seq + 1

# Determinar tipo de cumprimento
tem_pecuniaria = dados_cump.get('sub_tipo') == 'pecuniaria'
tem_servico = dados_cump.get('sub_tipo') in ('servico', 'mista')
eh_sursis = dados_cump.get('tipo') == 'sursis'
print(f'   Pecuniária: {tem_pecuniaria} / Serviço: {tem_servico} / Sursis: {eh_sursis}')
print(f'   Valor: {dados_cump.get("valor")} / Parc: {dados_cump.get("parcelas")} / Prazo: {dados_cump.get("prazo")}')

# Gerar descrição do cumprimento
descricao_cumprimento = ''
if tem_pecuniaria and dados_cump.get('valor'):
    descricao_cumprimento = f'prestação pecuniária no valor de R$ {dados_cump["valor"]}'
    if dados_cump.get('parcelas'):
        descricao_cumprimento += f', em {dados_cump["parcelas"]} parcelas'
elif tem_servico:
    descricao_cumprimento = f'prestação de serviços à comunidade pelo prazo de {dados_cump.get("prazo") or "4 meses"}'

if not descricao_cumprimento:
    if eh_sursis:
        descricao_cumprimento = f'suspensão condicional do processo pelo período de {dados_cump.get("prazo") or "4 meses"}'

print(f'   Descrição: {descricao_cumprimento[:120] if descricao_cumprimento else "(padrão)"}')

ctx = {
    'processo': proc.number,
    'despacho_autor': 'MARTINHO FERRAZ DA NOBREGA JUNIOR',
    'parte': party,
    'numero_documento': f'{num:03d}/{date.today().year}',
    'tem_prestacao_pecuniaria': tem_pecuniaria,
    'tem_prestacao_servico': tem_servico,
    'sursis': eh_sursis,
    'prazo_prestacao_servico': dados_cump.get('prazo') or '4 meses',
    'valor_prestacao_pecuniaria': dados_cump.get('valor') or '',
    'parcelas_prestacao_pecuniaria': str(dados_cump.get('parcelas', '')) if dados_cump.get('parcelas') else '',
    'autor_vitima': autor,
    'descricao_cumprimento': descricao_cumprimento,
    'secretario': SECRETARIO,
}
html = Template(template.html_template).render(Context(ctx))
party_name = party.name if party else 'DESCONHECIDO'
print(f'Ofício Nº {num:03d}/{date.today().year} - SEC/RPA')
print(f'HTML: {len(html)} chars - {party_name}')
print()

# ====== Humanização ======
def rs(mn=0.5, mx=2.5):
    time.sleep(random.uniform(mn, mx))

def scroll_slow(page, y_target, steps=6):
    for i in range(1, steps+1):
        page.evaluate(f'window.scrollTo(0, {int(y_target * (i/steps))})')
        time.sleep(random.uniform(0.08, 0.2))

def move_mouse(page, x1, y1, x2, y2, steps=8):
    for i in range(steps):
        t = (i+1)/steps
        eased = t*t*(3-2*t)
        page.mouse.move(x1+(x2-x1)*eased, y1+(y2-y1)*eased)
        time.sleep(random.uniform(0.02, 0.05))

def clicar(page, seletor):
    el = page.locator(seletor).first
    box = el.bounding_box()
    if box:
        move_mouse(page, 300, 400, box['x']+box['width']/2, box['y']+box['height']/2)
        rs(0.2, 0.5)
    el.click()

# ====== 5. PLAYWRIGHT ======
print(f'\n========== 5. Playwright ==========')

with sync_playwright() as pw:
    browser = pw.firefox.launch(headless=False)
    ctx = browser.new_context(
        viewport={'width': 1400, 'height': 900},
        locale='pt-BR'
    )

    # Injetar cookies
    ctx.add_cookies([{'name': k, 'value': v,
                       'domain': 'projudi.tjba.jus.br', 'path': '/'}
                      for k, v in cookies_dict.items()])

    page = ctx.new_page()

    # ===== 6. MOVIMENTAR PROCESSO (581) =====
    print('\n========== 6. MovimentarProcesso (581) ==========')
    page.goto(f'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso={PROC_PROJUDI}',
              wait_until='networkidle')
    rs(2, 4)

    title = page.title()
    print(f'   Title: {title}')
    if 'expirou' in title.lower():
        print('   Sessão expirada! Abrindo página de login...')
        page.goto('https://projudi.tjba.jus.br/projudi/', wait_until='networkidle')
        rs(1, 2)
        print('   Faça login manual no navegador e aguarde...')
        page.wait_for_url(lambda url: 'projudi' in url and 'login' not in url.lower(), timeout=120000)
        rs(2, 3)
        page.goto(f'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso={PROC_PROJUDI}',
                  wait_until='networkidle')
        rs(2, 4)

    scroll_slow(page, 300)
    rs(0.5, 1)

    el_exists = page.evaluate('!!document.getElementById("seqCategoriaMovimentacao")')
    if not el_exists:
        print(f'   ERRO: seqCategoriaMovimentacao não encontrado! URL: {page.url}')
        page.screenshot(path='/tmp/erro_mov.png')
        input('\n>>> Enter para fechar...')
        browser.close()
        sys.exit(1)

    print('   >> Injetando movimento 581...')
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
    rs(1, 2)

    page.select_option('select[name="codTipoDocumento"]', '53')
    rs(0.3, 0.8)
    page.fill('#observacao', f'Solicitada a Expedicao de Oficio CIAP - {party_name}')
    rs(0.5, 1)

    scroll_slow(page, 600)
    rs(0.5, 1)

    clicar(page, "a:text('Cumprimento')")
    rs(1, 2)

    page.select_option('#tipoCumprimento', '2')
    rs(0.3, 0.7)
    page.select_option('#codigoDestinatario', '13809981')
    rs(0.3, 0.7)

    clicar(page, '#btnAddCumprimento')
    rs(1, 2)
    print('   >> Cumprimento adicionado!')

    scroll_slow(page, 1200)
    rs(0.5, 1)
    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
    rs(0.5, 1)

    clicar(page, '#Concluir')
    rs(4, 6)
    try:
        alert = page.wait_for_event('dialog', timeout=8000)
        print(f'   >> Alerta: "{alert.message}"')
        rs(0.5, 1)
        alert.accept()
        rs(3, 5)
    except:
        pass
    print('   >> Movimento 581 concluído!')

    # ===== 7. CUMPRIMENTO CARTORIO -> REDIGIR SEM AR =====
    print('\n========== 7. CumprimentoCartorio ==========')
    page2 = ctx.new_page()
    page2.goto(
        'https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=oficio&acao=expedir',
        wait_until='networkidle'
    )
    rs(3, 5)
    scroll_slow(page2, 200, 4)
    rs(1, 2)
    print(f'   URL: {page2.url}')

    # Procurar "Redigir sem AR"
    print('   >> Procurando "Redigir sem AR"...')
    link_qtd = page2.evaluate('''() => {
        var links = document.querySelectorAll('a');
        var found = [];
        for (var i = links.length - 1; i >= 0; i--) {
            if (links[i].innerText.trim() === 'Redigir sem AR') {
                found.push(i + ': ' + links[i].href);
            }
        }
        return found;
    }''')
    print(f'   Links: {link_qtd}')

    if link_qtd:
        print('   >> Clicando...')
        try:
            with page2.expect_navigation(timeout=20000):
                page2.evaluate('''() => {
                    var links = document.querySelectorAll('a');
                    for (var i = links.length - 1; i >= 0; i--) {
                        if (links[i].innerText.trim() === 'Redigir sem AR') {
                            links[i].click();
                            return;
                        }
                    }
                }''')
                rs(2, 3)
            print(f'   URL: {page2.url}')
        except Exception as nav_err:
            print(f'   Navigation: {nav_err}')
    else:
        print('   >> Locator...')
        try:
            redigir_link = page2.get_by_text('Redigir sem AR').first
            if redigir_link.is_visible():
                with page2.expect_navigation(timeout=20000):
                    redigir_link.click()
                    rs(2, 3)
                print(f'   URL: {page2.url}')
        except Exception as loc_err:
            print(f'   Erro: {loc_err}')

    # ===== 8. FCKEDITOR =====
    if 'ExpedirCumprimento' in page2.url:
        print('\n========== 8. FCKeditor ==========')
        rs(3, 5)

        print('   >> Preservando brasão e colando HTML...')
        page2.evaluate('''(html) => {
            var ed, cur, img, brasoes = '';
            try { ed = FCKeditorAPI.GetInstance('FCKeditor1'); } catch(e) {
                try { ed = window.parent.FCKeditorAPI.GetInstance('FCKeditor1'); } catch(e2) { ed = null; }
            }
            if (ed) {
                try { ed.SwitchToSourceMode(); } catch(e) {}
                try { cur = ed.GetHTML() || ''; } catch(e) { cur = ''; }
                if (cur) {
                    var imgs = cur.match(/<img[^>]+>/gi) || [];
                    var brasoes = imgs.filter(function(img) {
                        var src = (img.match(/src\\s*=\\s*["']([^"']+)/i) || [])[1] || '';
                        return src.indexOf('brasao') > -1 || src.indexOf('brasão') > -1 || src.indexOf('logo') > -1 || src.indexOf('Logo') > -1;
                    }).map(function(img) {
                        return img.replace(/src\\s*=\\s*"([^"]+)"/gi, function(m, url) {
                            if (url.startsWith('http')) return m;
                            return 'src="https://projudi.tjba.jus.br' + (url.startsWith('/') ? '' : '/') + url + '"';
                        });
                    });
                    if (brasoes.length > 0) {
                        brasoes = '<div style="text-align:center;">' + brasoes.join(' ') + '</div>';
                    } else {
                        brasoes = '';
                    }
                }
                try { ed.SetHTML(brasoes + '<br>' + html); } catch(e) {}
                try { ed.SwitchToWysiwygMode(); } catch(e) {}
            }
        }''', html)
        rs(2, 4)
        print('   >> Brasão preservado + texto colado!')

        scroll_slow(page2, 500)
        rs(0.5, 1)

        print('   >> Submeter...')
        clicar(page2, 'input[src*="bot-submeter"]')
        rs(5, 8)
        print(f'   URL: {page2.url}')

        registrar_btn = page2.locator('input[value="Registrar"]').first
        if registrar_btn.is_visible():
            clicar(page2, 'input[value="Registrar"]')
            rs(3, 5)
            print('   >> Registrar OK!')
        else:
            print('   >> Registrar não encontrado')

        page2.screenshot(path='/tmp/pw_final.png')
        print('   >> Screenshot: /tmp/pw_final.png')
    else:
        print(f'   ERRO: URL = {page2.url}')

    print(f'\n========== FLUXO CONCLUIDO ==========')
    print(f'Ofício CIAP Nº {num:03d}/{date.today().year} - SEC/RPA')
    print(f'Processo: {PROC_NUM}')
    print(f'Parte: {party_name}')
    print('>>> Fechando navegador em 5 segundos...')
    time.sleep(5)
