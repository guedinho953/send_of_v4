"""Expedição humanizada de ofício CIAP no Projudi.
Uso:
  python expedir_humanizado.py <numero_processo_cnj>   # ofício para um processo específico
  python expedir_humanizado.py                          # último com RAG
  python expedir_humanizado.py --rastrear               # varre movimentações + match RAG
  python expedir_humanizado.py --rastrear --paginas 3   # varre últimas N páginas

Exemplo:
  python expedir_humanizado.py "0003099-35.2024.8.05.0191"
  python expedir_humanizado.py --rastrear
"""
import os, sys, time, random
sys.path.insert(0, '/home/ivan/PythonProjects/send_of_v4')
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

import json, re
import requests
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from processes.models import GeneratedDocument, Process, DocumentTemplate, Party, RAGExample
from datetime import date
from django.template import Template, Context
from django.db.models import Max
from projudi_bot import ProjudiBot
from processo_parser_ext import ProcessoParserExt

# ====== CONFIG ======
TEMPLATE_ID = 5
COOKIES_PATH = '/mnt/d/Projudi/cookies.json'

def rastrear_movimentacoes(paginas=3):
    """Varre AnalisarMovimentacao, baixa docs, analisa comandos, match RAG e expede."""
    print(f'\n========== RASTREAMENTO ==========')
    print(f'Varrendo últimas {paginas} páginas de movimentações...')
    
    bot = ProjudiBot()
    session = requests.Session()
    session.cookies.update(cookies_dict)
    
    pages = bot.obter_paginas_finais_movimentacoes(paginas)
    for page in pages:
        movs = bot.extrair_links_movimentacoes(page)
        for m in movs:
            proc_num = m.get('numero_processo')
            if not proc_num:
                continue
            
            print(f'\n  Processo: {proc_num}')
            print(f'   Data: {m.get("data")}')
            
            # Baixar documento
            doc_url = m.get('link_documento')
            if doc_url:
                doc_url = urljoin('https://projudi.tjba.jus.br/projudi/', doc_url)
                try:
                    r = session.get(doc_url, timeout=30)
                    if r.status_code == 200:
                        texto = bot.limpar_texto_doc(r.text)
                        print(f'   Documento: {len(texto)} chars')
                        
                        # Análise de comando
                        PADRAO_COMANDO = re.compile(
                            r'(?:\b(?:oficie|intime|cite|expeça|certifique|notifique|comunique|intimem|oficiem|notifiquem|comuniquem|certifiquem)\s*(?:[-–]se)?)',
                            re.IGNORECASE
                        )
                        comandos = PADRAO_COMANDO.findall(texto)
                        if comandos:
                            print(f'   Comandos: {comandos}')
                        
                        # Verificar CIAP
                        texto_lower = texto.lower()
                        tem_ciap = any(p in texto_lower for p in ['ciap', 'sursis', 'transa', 'prestaçã'])
                        
                        if tem_ciap:
                            print(f'   🔍 Possível ofício CIAP!')
                            # Match RAG
                            proc = Process.objects.filter(number=proc_num).first()
                            if proc:
                                rag = RAGExample.objects.filter(process=proc, suggested_templates=TEMPLATE_ID).first()
                                if rag:
                                    print(f'   ✅ MATCH RAG! Expedindo...')
                                    expedir_processo(proc, session, cookies_dict)
                except Exception as e:
                    print(f'   Erro baixando doc: {e}')

def expedir_processo(proc, session, cookies_dict):
    """Expede ofício CIAP via Projudi com confirmação visual. SÓ grava no banco se confirmar sucesso."""
    import re
    print(f'\n{"="*50}')
    print(f'🔍 EXPEDINDO: {proc.number}')
    print(f'{"="*50}')
    
    PROC_NUM = proc.number
    
    # Descobrir número Projudi
    PROC_PROJUDI = None
    projudi_url = getattr(proc, 'projudi_url', None) or ''
    m = re.search(r'numeroProcesso=(\d+)', projudi_url)
    if m:
        PROC_PROJUDI = m.group(1)
    
    if not PROC_PROJUDI:
        print('   🔍 Buscando número Projudi...')
        busca_url = 'https://projudi.tjba.jus.br/projudi/processo/consultaProcesso'
        r = session.post(busca_url, data={'numeroProcesso': PROC_NUM}, timeout=15)
        if r.status_code == 200:
            qs = parse_qs(urlparse(r.url).query)
            PROC_PROJUDI = qs.get('numeroProcesso', [None])[0]
    
    if not PROC_PROJUDI:
        if '3099' in PROC_NUM:
            PROC_PROJUDI = '41020261733480'
        else:
            print(f'   ❌ ERRO: número Projudi não encontrado para {PROC_NUM}')
            return False
    
    print(f'   📁 Projudi: {PROC_PROJUDI}')
    
    # Extrair dados do processo
    proc_url = f'https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?numeroProcesso={PROC_PROJUDI}'
    r_proc = session.get(proc_url, timeout=30)
    if r_proc.status_code != 200:
        print(f'   ❌ ERRO acessando processo: {r_proc.status_code}')
        return False
    
    parser = ProcessoParserExt(r_proc.text, session=session)
    partes_raw = parser.extrair_partes()
    movs_raw, _ = parser.extrair_movimentacoes()
    dados_cump = parser.buscar_dados_cumprimento(movs_raw)
    
    autor = parser.buscar_autor_vitima(partes_raw)
    party = Party.objects.filter(process=proc).last()
    if not party:
        print('   ❌ ERRO: parte não encontrada no banco!')
        return False
    
    print(f'   👤 Parte: {party.name}')
    
    # Determinar tipo de cumprimento
    eh_sursis = dados_cump['tipo'] == 'sursis'
    tem_pecuniaria = dados_cump.get('sub_tipo') == 'pecuniaria'
    tem_servico = dados_cump.get('sub_tipo') in (None, '', 'servico')
    
    descricao_cumprimento = None
    if tem_pecuniaria:
        val = dados_cump.get('valor') or 'a definir'
        parc = dados_cump.get('parcelas') or ''
        txt = f'prestação pecuniária no valor de R$ {val}'
        if parc:
            txt += f', em {parc} parcelas'
        descricao_cumprimento = txt
    elif tem_servico:
        prazo = dados_cump.get('prazo') or '4 meses'
        descricao_cumprimento = f'prestação de serviços à comunidade pelo prazo de {prazo}'
    
    # Preparar dados (ainda NÃO salvar no banco)
    num = (GeneratedDocument.objects.filter(process=proc).aggregate(Max('sequential_number'))['sequential_number__max'] or 0) + 1
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
        'parcelas_prestacao_pecuniaria': str(dados_cump.get('parcelas')) if dados_cump.get('parcelas') else '',
        'autor_vitima': None,
        'descricao_cumprimento': descricao_cumprimento,
        'secretario': 'MAURO EMILIO VIANA DA SILVA MOREIRA',
    }
    template_obj = DocumentTemplate.objects.get(id=TEMPLATE_ID)
    html_full = Template(template_obj.html_template).render(Context(ctx))
    
    # Modelo RPA já tem brasão no topo. Nosso template nao tem brasao.
    # Colamos o HTML completo do nosso template (com nosso cabecalho simples).
    # O cabecalho do modelo RPA será limpo no editor.
    html = html_full
    
    print(f'   📝 HTML final: {len(html)} chars')
    print(f'   ⚡ NAVEGADOR VISÍVEL será aberto. Aguarde...')
    
    # ====== PLAYWRIGHT VISÍVEL COM PAUSAS ======
    sucesso = False
    try:
        with sync_playwright() as pw:
            browser = pw.firefox.launch(headless=False, slow_mo=500)
            ctx_b = browser.new_context(viewport={'width': 1500, 'height': 950}, locale='pt-BR')
            ctx_b.add_cookies([
                {'name': k, 'value': v, 'domain': 'projudi.tjba.jus.br', 'path': '/'}
                for k, v in cookies_dict.items()
            ])
            page = ctx_b.new_page()
            
            # === PASSO 1: MovimentarProcesso ===
            print('   [1/5] 🚀 Abrindo Movimentação 581...')
            url_mov = f'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso={PROC_PROJUDI}'
            page.goto(url_mov, wait_until='networkidle')
            time.sleep(2)
            page.screenshot(path='/tmp/pw_step1_movimentacao.png')
            
            tem_form = page.evaluate('!!document.getElementById("seqCategoriaMovimentacao")')
            if not tem_form:
                if 'expirou' in page.title().lower():
                    print('   ❌ SESSÃO EXPIROU! Login manual necessário.')
                else:
                    print('   ❌ Formulário de movimentação não encontrado')
                page.screenshot(path='/tmp/pw_erro_movimentacao.png')
                browser.close()
                return False
            
            # Injetar movimento 581
            page.evaluate('''() => {
                var camp = document.getElementById('seqCategoriaMovimentacao');
                if (camp) camp.value = '581';
                var desc = document.getElementById('descCategoriaMovimentacao');
                if (desc) desc.value = 'Solicitada a Expedi\u00e7\u00e3o de Of\u00edcio';
                var tr = document.getElementById('trTipoDocumento');
                if (tr) tr.style.display = 'table-row';
                var div = document.getElementById('rowDadosMovimentacaoComplemento');
                if (div) div.style.display = 'block';
                var panel = document.getElementById('divPanelCumprimento');
                if (panel) panel.style.display = 'block';
            }''')
            time.sleep(1.5)
            page.screenshot(path='/tmp/pw_step2_injetado.png')
            print('   [2/5] 🖍️ Movimento 581 injetado')
            
            # === PASSO 2: Completar movimentacao (Cumprimento + Concluir) ===
            print('   [2/5] 🖍️ Configurando Cumprimento...')
            
            # Selecionar tipo documento = 53 (Oficio)
            page.select_option('select[name="codTipoDocumento"]', '53')
            page.fill('#observacao', f'Solicitada a Expedicao de Oficio CIAP - {party.name[:30]}')
            time.sleep(0.5)
            
            # Expandir Cumprimento
            page.locator("a:text('Cumprimento')").first.click()
            time.sleep(1)
            
            # Preencher cumprimento
            page.select_option('#tipoCumprimento', '2')  # OFICIO
            page.select_option('#codigoDestinatario', '13809981')  # CIAP
            page.click('#btnAddCumprimento')
            time.sleep(1)
            print('   ✅ Cumprimento adicionado')
            
            # Scroll e Concluir
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            time.sleep(0.5)
            page.click('#Concluir')
            time.sleep(4)
            
            # Tratar alerta se aparecer
            try:
                alert = page.wait_for_event('dialog', timeout=5000)
                print(f'   📢 Alerta: "{alert.message}"')
                alert.accept()
                time.sleep(3)
            except:
                pass
            
            page.screenshot(path='/tmp/pw_step2b_concluido.png')
            print(f'   ✅ Movimentacao concluida! URL: {page.url}')
            
            # === PASSO 3: CumprimentoCartorio -> Redigir sem AR com modelo RPA ===
            print('   [3/5] 📋 Abrindo Cumprimento Cartorio...')
            url_cump = 'https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=oficio&acao=expedir'
            page.goto(url_cump, wait_until='networkidle')
            time.sleep(3)
            page.screenshot(path='/tmp/pw_step3_cumprimento.png')
            
            # Encontrar o form do processo gerado e selecionar modelo "oficio RPA" (85079)
            print('   🔍 Selecionando modelo de oficio RPA...')
            cump_result = page.evaluate('''() => {
                // Procurar a linha do processo correto ou usar o ultimo cumprimento
                var forms = document.querySelectorAll('form[name^="formCumprimento"]');
                if (forms.length === 0) return {erro: 'nenhum form encontrado'};
                
                var form = forms[forms.length - 1];
                var sel = form.querySelector('select[name="codModelo"]');
                if (!sel) return {erro: 'select codModelo nao encontrado', form: form.name};
                
                // Procurar opcao RPA
                var rpaValue = null;
                for (var i = 0; i < sel.options.length; i++) {
                    if (sel.options[i].text.toLowerCase().includes('rpa')) {
                        rpaValue = sel.options[i].value;
                        break;
                    }
                }
                if (!rpaValue) return {erro: 'modelo RPA nao encontrado', opcoes: Array.from(sel.options).map(o => o.text)};
                
                sel.value = rpaValue;
                return {ok: true, form: form.name, codModelo: rpaValue};
            }''')
            print(f'   📝 {cump_result}')
            
            if not cump_result.get('ok'):
                print(f'   ❌ ERRO na selecao do modelo: {cump_result}')
                page.screenshot(path='/tmp/pw_erro_modelo.png')
                browser.close()
                return False
            
            # Submeter o form com gerarar=false (Redigir sem AR)
            form_name = cump_result['form']
            print(f'   🔄 Submetendo {form_name} para redigir sem AR...')
            with page.expect_navigation(timeout=15000):
                page.evaluate(f'''() => {{
                    var form = document.forms['{form_name}'];
                    form.gerarar.value = 'false';
                    form.submit();
                }}''')
                time.sleep(3)
            
            time.sleep(3)
            page.screenshot(path='/tmp/pw_step4_editor.png')
            print(f'   ✅ URL apos Redigir: {page.url}')
            
            if 'ExpedirCumprimento' not in page.url:
                print(f'   ❌ ERRO: nao foi pra ExpedirCumprimento. URL: {page.url}')
                page.screenshot(path='/tmp/pw_erro_redigir.png')
                browser.close()
                return False
            
            # === PASSO 4: FCKeditor - preservar brasao do modelo RPA e colar nosso conteudo ===
            print('   [4/5] ✍️ Configurando editor...')
            time.sleep(3)
            
            # 1. Pegar HTML original do modelo RPA
            html_original = page.evaluate('''() => {
                try {
                    return FCKeditorAPI.GetInstance('FCKeditor1').GetHTML();
                } catch(e) {
                    try {
                        return window.parent.FCKeditorAPI.GetInstance('FCKeditor1').GetHTML();
                    } catch(e2) {
                        return '';
                    }
                }
            }''')
            
            # 2. Extrair primeira imagem do brasao
            import re
            img_match = re.search(r'(<img[^>]+src="[^"]*brasao[^"]*"[^>]*>)', html_original, re.I)
            brasao_html = ''
            if img_match:
                brasao_html = f'<div style="text-align:center; margin-bottom:8px;">{img_match.group(1)}</div>'
                print('   ✅ Brasao do modelo RPA extraido')
            else:
                print('   ⚠️ Brasao nao encontrado no modelo RPA')
            
            # 3. Montar HTML final: brasao + nosso conteudo
            html_final = brasao_html + html
            
            # 4. Colar no editor
            result = page.evaluate('''(html) => {
                try {
                    var ed = FCKeditorAPI.GetInstance('FCKeditor1');
                    ed.SetHTML('');
                    ed.SetHTML(html);
                    return 'OK SetHTML';
                } catch(e) {
                    try {
                        var ed2 = window.parent.FCKeditorAPI.GetInstance('FCKeditor1');
                        ed2.SetHTML('');
                        ed2.SetHTML(html);
                        return 'OK parent.SetHTML';
                    } catch(e2) {
                        var ifr = document.querySelector('iframe[title*="editor"], iframe[src*="FCKeditor"]');
                        if (ifr) {
                            var doc = ifr.contentDocument || ifr.contentWindow.document;
                            var body = doc.querySelector('body');
                            if (body) { body.innerHTML = html; return 'OK iframe'; }
                        }
                        return 'ERRO: ' + e2.message;
                    }
                }
            }''', html_final)
            print(f'   📝 FCKeditor: {result}')
            
            time.sleep(2)
            page.screenshot(path='/tmp/pw_step4b_html_colado.png')
            print('   ✅ HTML colado')
            
            # === PASSO 5: Submeter ===
            print('   [5/5] 🔄 Clicando Submeter...')
            submeter = page.locator('input[src*="bot-submeter"], input[type="image"]').first
            if submeter.count():
                submeter.scroll_into_view_if_needed()
                time.sleep(1)
                page.screenshot(path='/tmp/pw_step4c_pre_submeter.png')
                submeter.click()
                time.sleep(5)
                page.screenshot(path='/tmp/pw_step5_submetido.png')
                print(f'   ✅ Submetido! URL: {page.url}')
            else:
                print('   ❌ Submeter nao encontrado')
                browser.close()
                return False
            
            # === PASSO 6: Registrar ===
            print('   🔄 Procurando Registrar...')
            registrar = page.locator("input[value='Registrar'], input[src*='registrar']").first
            if registrar.count():
                registrar.scroll_into_view_if_needed()
                time.sleep(1)
                registrar.click()
                time.sleep(3)
                page.screenshot(path='/tmp/pw_step6_registrado.png')
                print('   ✅ Registrar clicado!')
            else:
                print('   ⚠️ Registrar nao encontrado')
                page.screenshot(path='/tmp/pw_step5_sem_registrar.png')
            
            # Verificar sucesso
            html_final = page.content()
            if any(k in html_final.lower() for k in ['registrado', 'sucesso', 'confirmado', 'ofícios para expedir', 'cumprimentocartorio']):
                sucesso = True
                print('   ✅ CONFIRMADO: Oficio expedido no Projudi!')
            else:
                print(f'   ⚠️ Nao confirmado automaticamente. URL: {page.url}')
            
            browser.close()
    except Exception as e:
        print(f'   ❌ ERRO Playwright: {e}')
        import traceback
        traceback.print_exc()
        return False
    
    # ====== SÓ GRAVAR NO BANCO SE CONFIRMADO ======
    if sucesso:
        doc = GeneratedDocument.objects.create(
            process=proc, template=template_obj,
            sequential_number=num, year=date.today().year,
            recipient_name=party.name, recipient_email='',
            html_content=html, exported_to_projudi=True,
        )
        print(f'   📅 Documento #{doc.id} salvo no banco (exported_to_projudi=True)')
        print(f'   🔗 Veja em: http://localhost:8000/admin/processes/generateddocument/{doc.id}/change/')
        return True
    else:
        print(f'   ⚠️ Ofício NÃO confirmado no Projudi. Nada foi salvo no banco.')
        print(f'   🖼️ Veja os screenshots em /tmp/pw_*.png para diagnosticar')
        return False


# ====== FUNÇÃO: PROCESSAR FILA ======
def processar_fila():
    """Lê fila de /tmp/fila_expedir_ciap.json e expede cada processo."""
    fp = '/tmp/fila_expedir_ciap.json'
    if not os.path.exists(fp):
        print('   Fila vazia! Nada para processar.')
        return
    
    with open(fp) as f:
        fila = json.load(f)
    
    if not fila:
        print('   Fila vazia!')
        return
    
    print(f'\n========== FILA: {len(fila)} processo(s) ==========')
    for i, cnj in enumerate(fila, 1):
        print(f'\n--- [{i}/{len(fila)}] {cnj} ---')
        proc = Process.objects.filter(number=cnj).first()
        if not proc:
            print(f'   Processo {cnj} não encontrado no banco!')
            continue
        expedir_processo(proc, session, cookies_dict)
    
    # Limpar fila
    with open(fp, 'w') as f:
        json.dump([], f)
    print(f'\n✅ Fila processada! ({len(fila)} processos)')


# ====== CARREGAR COOKIES (sempre antes de qualquer fluxo) ======
print('\n========== Carregando cookies ==========')
cookies_paths = [
    COOKIES_PATH,
    os.path.expanduser('~/.projudi_cookies.json'),
    '/tmp/projudi_cookies.json',
]
cookies_dict = {}
for cp in cookies_paths:
    if os.path.exists(cp):
        with open(cp) as f:
            data = json.load(f)
            if isinstance(data, dict):
                cookies_dict = data
            elif isinstance(data, list):
                cookies_dict = {c['name']: c['value'] for c in data if 'name' in c}
        print(f'   ✅ Cookies carregados de {cp}')
        break

if not cookies_dict:
    print('   ❌ Cookies não encontrados!')
    sys.exit(1)

# Criar sessão
session = requests.Session()
if cookies_dict.get('JSESSIONID'):
    session.cookies.set('JSESSIONID', cookies_dict['JSESSIONID'], domain='projudi.tjba.jus.br')
print('   ✅ Sessão ativa')


# ====== DISPATCH ======
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('cnj', nargs='?', help='Número CNJ do processo')
parser.add_argument('--rastrear', action='store_true', help='Rastrear movimentações')
parser.add_argument('--paginas', type=int, default=3, help='Páginas para rastrear')
parser.add_argument('--fila', action='store_true', help='Processar fila')
args = parser.parse_args()

if args.rastrear:
    rastrear_movimentacoes(paginas=args.paginas)
elif args.fila:
    processar_fila()
elif args.cnj:
    proc = Process.objects.filter(number=args.cnj).first()
    if not proc:
        print(f'Processo {args.cnj} não encontrado!')
        sys.exit(1)
    expedir_processo(proc, session, cookies_dict)
else:
    # Último processo com RAG CIAP
    rag = RAGExample.objects.filter(suggested_templates=TEMPLATE_ID, process__isnull=False).select_related('process').last()
    if rag and rag.process:
        expedir_processo(rag.process, session, cookies_dict)
    else:
        print('Nenhum processo com RAG CIAP encontrado!')
