"""Diagnóstico do grid de tipo documental na intimação (FLUXO B).

Abre MovimentarProcesso (número interno), clica em "Movimentar
Genericamente", injeta 581, clica em Buscar e despeja no terminal TODOS os
elementos com texto contendo 'Intim' (tag/class/id/texto), além de tirar
screenshot. NÃO clica em Concluir — sem efeito legal.

Uso:
  source .venv/bin/activate
  python diag_grid.py 41020262339469
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from django.apps import apps
User = apps.get_model('accounts.User')
from projudi.services import ProjudiService
from playwright.sync_api import sync_playwright

NUMERO_INTERNO = sys.argv[1] if len(sys.argv) > 1 else '41020262339469'

user = User.objects.filter(is_active=True).first()
result = ProjudiService(user)._get_session_from_cookies()
if not result:
    print('❌ Sessão indisponível.')
    sys.exit(1)
session, cookies = result

with sync_playwright() as pw:
    browser = pw.firefox.launch(headless=False, slow_mo=300)
    ctx = browser.new_context(viewport={'width': 1500, 'height': 950}, locale='pt-BR')
    ctx.add_cookies([{'name': k, 'value': v,
                      'domain': 'projudi.tjba.jus.br', 'path': '/'}
                     for k, v in cookies.items()])
    page = ctx.new_page()

    url = (f'https://projudi.tjba.jus.br/projudi/movimentacao/'
           f'MovimentarProcesso?numeroProcesso={NUMERO_INTERNO}')
    print(f'🌐 Abrindo {url}')
    page.goto(url, wait_until='networkidle')
    time.sleep(2)

    # Clicar "Movimentar Genericamente"
    for sel in ['a:has-text("Movimentar Genericamente")',
                'a:has-text("Movimentar genericamente")',
                'a:has-text("Movimentar Processo Genericamente")',
                'a:has-text("Movimentar Processo")',
                'a:has-text("Movimentar")']:
        el = page.query_selector(sel)
        if el:
            el.click()
            time.sleep(2)
            print(f'✅ Clicado: {sel}')
            break
    else:
        print('⚠️ Nenhum link "Movimentar" encontrado')

    # Injeta 581
    page.evaluate('''() => {
        var c = document.getElementById('seqCategoriaMovimentacao');
        if (c) { c.value = '581'; c.dispatchEvent(new Event('change', {bubbles:true})); }
    }''')
    time.sleep(1)

    # Clicar Buscar
    try:
        page.click('#btnBuscaMovimentacao', timeout=5000)
        time.sleep(2)
        print('✅ Busca clicada')
    except Exception as e:
        print(f'⚠️ btnBuscaMovimentacao: {e}')
    try:
        alert = page.wait_for_event('dialog', timeout=5000)
        print(f'⚠️ Alerta: {alert.message}')
        alert.accept()
        time.sleep(1)
    except Exception:
        pass

    # Despeja elementos com "Intim"
    print()
    print('═══ ELEMENTOS COM "Intim" NO DOM ═══')
    dados = page.evaluate('''() => {
        const out = [];
        const all = document.querySelectorAll('a, td, tr, span, div, button, option, input, li');
        for (const el of all) {
            const t = (el.innerText || el.value || '').trim();
            if (t && /intim/i.test(t) && t.length < 200) {
                out.push({
                    tag: el.tagName,
                    id: el.id || '',
                    cls: (el.className || '').toString().slice(0, 60),
                    href: el.href ? el.href.slice(0, 90) : '',
                    tipo: el.type || '',
                    checked: el.checked === true,
                    text: t.slice(0, 120)
                });
            }
        }
        return out;
    }''')
    # Dedupe por tag+texto
    vistos = set()
    for d in dados:
        chave = (d['tag'], d['text'][:50])
        if chave in vistos:
            continue
        vistos.add(chave)
        print(f"  <{d['tag'].lower()} id='{d['id']}' cls='{d['cls']}'"
              f" href='{d['href']}' tipo='{d['tipo']}' checked={d['checked']}>"
              f" {d['text'][:100]}")
    print(f'\nTotal únicos: {len(vistos)}')

    # Selects com opção Intimação?
    print()
    print('═══ SELECTS (name + options) ═══')
    selects = page.evaluate('''() => {
        const out = [];
        for (const s of document.querySelectorAll('select')) {
            out.push({name: s.name || s.id || '?', opts: Array.from(s.options).map(o => o.text.trim() + '=' + o.value).slice(0, 25)});
        }
        return out;
    }''')
    for s in selects:
        print(f"  select name='{s['name']}': {s['opts']}")

    page.screenshot(path='/tmp/diag_grid.png', full_page=False)
    print('\n📸 Screenshot: /tmp/diag_grid.png')
    print('⏸️  Página aberta p/ inspeção (não fechei nada). Ctrl+C p/ sair.')
    time.sleep(90)
    browser.close()