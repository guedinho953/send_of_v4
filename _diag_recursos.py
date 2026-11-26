import os, re
os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings')
os.environ['PLAYWRIGHT_HEADLESS']='1'
import django; django.setup()
import expedir_oficios_por_tipo as E
from playwright.sync_api import sync_playwright
from projudi.playwright_firefox import launch_firefox
from projudiProcessNavigator import ProcessoParser

u=E._carregar_usuario(None); c=E._carregar_cookies(u); http=E._criar_sessao_http(c)
with sync_playwright() as pw:
    b=launch_firefox(pw); ctx=b.new_context(viewport={'width':1500,'height':950},locale='pt-BR')
    ctx.add_cookies([{'name':k,'value':v,'domain':'projudi.tjba.jus.br','path':'/'} for k,v in c.items()])
    pg=ctx.new_page(); pg.goto(E.URL_CUMPRIMENTO, wait_until='networkidle', timeout=60000)
    itens=pg.evaluate(E.JS_SCAN); b.close()

for it in itens:
    href=it.get('procHref')
    if not href: continue
    print('\n'+'='*100); print(it.get('rowText','')[:150]); print(href)
    try:
        r=http.get(href, timeout=30)
        if r.status_code!=200: print('status',r.status_code); continue
        parser=ProcessoParser(r.text); movs,_=parser.extrair_movimentacoes()
    except Exception as e:
        print('erro',e); continue
    for m in movs:
        txt=' '.join(str(m.get(k) or '') for k in ('ato','observacao','ato_normalizado'))
        up=txt.upper()
        if 'RECURSO INOMINADO' in up or 'DISPONIBILIZA' in up or 'DJEN' in up:
            print(f"  ev={m.get('evento')} data={m.get('data_texto')} data_obj={m.get('data_obj')} djen={m.get('data_djen')} cat={m.get('categoria')} :: {txt[:300]}")
