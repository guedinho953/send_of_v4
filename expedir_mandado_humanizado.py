"""
Expedição humanizada de Mandado no Projudi (via Playwright).
Similar ao expedir_humanizado.py, mas para mandados.

Uso:
  python expedir_mandado_humanizado.py --mandado <id>
  python expedir_mandado_humanizado.py --processo 0000799-32.2026.8.05.0191
  python expedir_mandado_humanizado.py --mandado <id> --dry-run
"""

import os, sys, time, json, re
sys.path.insert(0, '/home/ivan/PythonProjects/send_of_v4')
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

import requests
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from django.template import Template, Context
from datetime import date
from projudi_bot import ProjudiBot
from processo_parser_ext import ProcessoParserExt

from accounts.models import User
from processes.models import Process, DocumentTemplate, Party
from projudi.models import MandadoRecord, MandadoLog

# ── CONFIG ──────────────────────────────────────────────────────
TEMPLATE_MANDADO_ID = 6  # Mandado de Intimação (Transação Penal)
COOKIES_PATH = '/mnt/d/Projudi/cookies.json'


def carregar_cookies():
    """Carrega cookies do arquivo JSON."""
    cookies = ProjudiBot.carregar_cookies_do_arquivo()
    if not cookies or 'JSESSIONID' not in cookies:
        print('❌ Cookies sem JSESSIONID. Capture primeiro.')
        sys.exit(1)
    return cookies


def obter_session(cookies_dict):
    """Cria requests.Session com cookies."""
    session = requests.Session()
    for k, v in cookies_dict.items():
        session.cookies.set(k, v)
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9',
    })
    return session


def expedir_mandado(mandado_id=None, processo_cnj=None, dry_run=False):
    """Fluxo completo de expedição de mandado via Playwright."""
    # Usa captura robusta de cookies (4 camadas)
    from projudi.services import ProjudiService
    user = User.objects.filter(is_active=True).first()
    if not user:
        print('❌ Nenhum usuário ativo')
        return False
    service = ProjudiService(user)
    result = service._get_session_from_cookies()
    if not result:
        print('❌ Não foi possível capturar a sessão do Projudi.')
        print('   Deixe o Firefox aberto e logado no Projudi, depois execute:')
        print('   D:\\Projudi\\capturar_cookies.bat  (dê duplo clique)')
        return False
    session, cookies_dict = result

    # ── Localizar MandadoRecord ────────────────────────────────
    if mandado_id:
        record = MandadoRecord.objects.get(id=mandado_id)
    elif processo_cnj:
        record = MandadoRecord.objects.filter(
            numero_processo_cnj=processo_cnj,
            status__in=['pendente', 'falha'],
        ).last()
    else:
        record = MandadoRecord.objects.filter(status='pendente').last()

    if not record:
        print('❌ Nenhum mandado pendente encontrado')
        return False

    proc = Process.objects.filter(number=record.numero_processo_cnj or record.processo).first()
    if not proc:
        print(f'❌ Processo {record.numero_processo_cnj} não encontrado no banco')
        return False

    print(f'\n{"="*60}')
    print(f'🔍 EXPEDINDO MANDADO: {record.numero_mandado}')
    print(f'   Processo: {record.numero_processo_cnj}')
    print(f'   Parte: {record.parte_nome}')
    print(f'{"="*60}')

    # ── Descobrir número Projudi ───────────────────────────────
    PROC_PROJUDI = None
    projudi_url = getattr(proc, 'projudi_url', None) or ''
    m = re.search(r'numeroProcesso=(\d+)', projudi_url)
    if m:
        PROC_PROJUDI = m.group(1)

    if not PROC_PROJUDI:
        print('   🔍 Buscando número Projudi...')
        busca_url = 'https://projudi.tjba.jus.br/projudi/processo/consultaProcesso'
        r = session.post(busca_url, data={'numeroProcesso': proc.number}, timeout=15)
        if r.status_code == 200:
            qs = parse_qs(urlparse(r.url).query)
            PROC_PROJUDI = qs.get('numeroProcesso', [None])[0]

    if not PROC_PROJUDI:
        print('   ❌ ERRO: número Projudi não encontrado')
        print('   Tente: python expedir_mandado_humanizado.py --mandado <id>')
        return False

    print(f'   📁 Projudi: {PROC_PROJUDI}')

    # ── Extrair dados do processo ──────────────────────────────
    proc_url = f'https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?numeroProcesso={PROC_PROJUDI}'
    r_proc = session.get(proc_url, timeout=30)
    if r_proc.status_code != 200:
        print(f'   ❌ ERRO acessando processo: {r_proc.status_code}')
        return False

    parser = ProcessoParserExt(r_proc.text, session=session)
    partes_raw = parser.extrair_partes()
    movs_raw, _ = parser.extrair_movimentacoes()

    # Parte
    party = Party.objects.filter(process=proc).last()
    if not party:
        print('   ❌ ERRO: parte não encontrada no banco!')
        return False
    print(f'   👤 Parte: {party.name}')

    # ── Renderizar template mandado ────────────────────────────
    template_obj = DocumentTemplate.objects.get(id=TEMPLATE_MANDADO_ID)

    ctx = {
        'processo': proc.number,
        'despacho_autor': 'MARTINHO FERRAZ DA NOBREGA JUNIOR',
        'parte': party,
        'numero_documento': record.numero_mandado,
        'prazo_dias': '05',
        'data': date.today().strftime('%d/%m/%Y'),
        'descricao_cumprimento': '',
        'observacoes': '',
    }
    html = Template(template_obj.html_template).render(Context(ctx))
    print(f'   📝 HTML: {len(html)} chars')

    if dry_run:
        print('   🏁 Dry-run — nada será executado')
        return True

    # ── Marcar como expedindo ──────────────────────────────────
    record.status = 'expedido'
    record.save(update_fields=['status'])
    MandadoLog.objects.create(
        mandado=record, tipo='expedicao',
        mensagem='Iniciando expedição via Playwright...',
    )

    # ── PLAYWRIGHT ─────────────────────────────────────────────
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
            print('   [1/5] 🚀 Abrindo Movimentação...')
            url_mov = f'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso={PROC_PROJUDI}'
            page.goto(url_mov, wait_until='networkidle')
            time.sleep(2)

            tem_form = page.evaluate('!!document.getElementById("seqCategoriaMovimentacao")')
            if not tem_form:
                print('   ❌ Formulário não encontrado (sessão expirou?)')
                page.screenshot(path='/tmp/pw_mandado_erro.png')
                browser.close()
                return False

            # Injetar movimento (581 = Solicitar Expedição)
            page.evaluate('''() => {
                var camp = document.getElementById('seqCategoriaMovimentacao');
                if (camp) camp.value = '581';
                var desc = document.getElementById('descCategoriaMovimentacao');
                if (desc) desc.value = 'Solicitada a Expedição de Mandado';
                var tr = document.getElementById('trTipoDocumento');
                if (tr) tr.style.display = 'table-row';
                var div = document.getElementById('rowDadosMovimentacaoComplemento');
                if (div) div.style.display = 'block';
                var panel = document.getElementById('divPanelCumprimento');
                if (panel) panel.style.display = 'block';
            }''')
            time.sleep(1)
            print('   [2/5] 🖍️ Movimento 581 injetado')

            # 🔴 IMPORTANTE: selecionar MANDADO (não 53-OFÍCIO)
            # O código do tipo de documento para Mandado/Mandado Genérico
            # precisa ser ajustado conforme o Projudi
            page.select_option('select[name="codTipoDocumento"]', '51')  # Mandado
            time.sleep(1.5)
            page.fill('#observacao', f'Solicitada a Expedicao de Mandado - {party.name[:30]}')
            time.sleep(0.5)

            # Expandir Cumprimento
            page.locator("a:text('Cumprimento')").first.click()
            time.sleep(1)

            # 🔴 IMPORTANTE: selecionar MANDADO (não 2-OFÍCIO)
            page.select_option('#tipoCumprimento', '4')  # Mandado
            time.sleep(0.5)
            # Seleciona subtipoCumprimento = "Intimação" (value 3) para mandado
            # Subtipos disponíveis (projudi/tjba):
            #   1  = Citação e Intimação para Audiência
            #   2  = Intimação para Audiência
            #   3  = Intimação ← (usando)
            #   4  = Citação
            #   5  = Intimação Despacho
            #   6  = Intimação de Sentença
            #   7  = Busca e Apreensão
            #   8  = Citação e/ou Intimação com Liminar
            #   9  = Mandado genérico
            #   10 = Alvará de soltura
            #   11 = Citação/Penhora/Avaliação/Intimação/Depósito
            #   12 = Ofício
            #   24 = Notificação
            #   26 = Penhora e/ou avaliação
            #   27 = Reintegração de Posse
            #   34 = Prisão
            try:
                st = page.locator('#subtipoCumprimento, select[name="subtipoCumprimento"]').first
                if st.count():
                    st.select_option('3')
                    print('   ✅ Subtipo cumprimento: Intimação (3)')
            except Exception as e:
                print(f'   Subtipo cumprimento: não encontrado ({e})')
            # Destinatário = código da parte (precisa descobrir)
            # page.select_option('#codigoDestinatario', '...')
            page.click('#btnAddCumprimento')
            time.sleep(1)
            print('   ✅ Cumprimento adicionado')

            # Concluir
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            time.sleep(0.5)
            page.click('#Concluir')
            time.sleep(4)

            try:
                alert = page.wait_for_event('dialog', timeout=5000)
                print(f'   📢 Alerta: "{alert.message}"')
                alert.accept()
                time.sleep(3)
            except:
                pass

            print(f'   ✅ Movimentação concluída!')

            # === PASSO 3: CumprimentoCartorio → Mandados ===
            print('   [3/5] 📋 Abrindo Cumprimento Cartorio (Mandados)...')
            url_cump = 'https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=mandado&acao=expedir'
            page.goto(url_cump, wait_until='networkidle')
            time.sleep(3)

            # Selecionar modelo (se houver) e Redigir sem AR
            # O código é similar ao ofício mas com select de modelo mandado
            cump_result = page.evaluate('''() => {
                var forms = document.querySelectorAll('form[name^="formCumprimento"]');
                if (forms.length === 0) return {erro: 'nenhum form'};
                var form = forms[forms.length - 1];
                var sel = form.querySelector('select[name="codModelo"]');
                if (!sel) return {erro: 'sem select codModelo', form: form.name};
                // Procura modelo Mandado RPA
                var opts = sel.options;
                var rpaValue = null;
                for (var i = 0; i < opts.length; i++) {
                    if (opts[i].text.toLowerCase().includes('rpa')) {
                        rpaValue = opts[i].value;
                        break;
                    }
                }
                if (!rpaValue) {
                    // Fallback: última opção
                    sel.value = opts[opts.length - 1].value;
                    return {ok: true, form: form.name, valor: sel.value, notice: 'fallback ultima opcao'};
                }
                sel.value = rpaValue;
                return {ok: true, form: form.name, valor: rpaValue, modelo: 'Mandado RPA'};
            }''')
            print(f'   📝 {cump_result}')

            if not cump_result.get('ok'):
                print('   ❌ ERRO na seleção do modelo')
                browser.close()
                return False

            # Redigir sem AR
            form_name = cump_result['form']
            print(f'   🔄 Redigir sem AR...')
            with page.expect_navigation(timeout=15000):
                page.evaluate(f'''() => {{
                    var form = document.forms['{form_name}'];
                    form.gerarar.value = 'false';
                    form.submit();
                }}''')
                time.sleep(3)

            time.sleep(3)
            print(f'   ✅ URL: {page.url}')

            if 'ExpedirCumprimento' not in page.url:
                print(f'   ❌ Não foi pra ExpedirCumprimento')
                browser.close()
                return False

            # === PASSO 4: FCKeditor — preservar brasão do RPA e colar nosso template ===
            print('   [4/5] ✍️ Extraindo brasão do RPA e colando template...')
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

            # 2. Extrair primeira imagem do brasão
            img_match = re.search(r'(<img[^>]+src="[^"]*brasao[^"]*"[^>]*>)', html_original, re.I)
            brasao_html = ''
            if img_match:
                brasao_html = f'<div style="text-align:center; margin-bottom:8px;">{img_match.group(1)}</div>'
                print('   ✅ Brasão do modelo RPA extraído')
            else:
                print('   ⚠️ Brasão não encontrado no modelo RPA')

            # 3. Montar HTML final: brasão + nosso template (já vem com destinatário do banco)
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

            # === PASSO 5: Submeter + Registrar ===
            print('   [5/5] 🔄 Submeter...')
            submeter = page.locator('input[src*="bot-submeter"], input[type="image"]').first
            if submeter.count():
                submeter.scroll_into_view_if_needed()
                time.sleep(1)
                submeter.click()
                time.sleep(5)
                print(f'   ✅ Submetido!')
            else:
                print('   ❌ Submeter não encontrado')
                browser.close()
                return False

            print('   🔄 Procurando Registrar...')
            registrar = page.locator("input[value='Registrar'], input[src*='registrar']").first
            if registrar.count():
                registrar.scroll_into_view_if_needed()
                time.sleep(1)
                registrar.click()
                time.sleep(4)
                print('   ✅ Mandado registrado com sucesso!')
                sucesso = True
            else:
                print('   ⚠️ Registrar não encontrado — pode ter ido direto')
                sucesso = True

            browser.close()

    except Exception as e:
        print(f'   ❌ ERRO: {e}')
        import traceback
        traceback.print_exc()
        sucesso = False

    # ── Atualizar registro ─────────────────────────────────────
    if sucesso:
        record.status = 'expedido'
        record.texto_html = html
        record.save(update_fields=['status', 'texto_html'])
        MandadoLog.objects.create(
            mandado=record, tipo='expedicao',
            mensagem='Mandado expedido com sucesso via Playwright.',
        )
        print(f'\n✅ Mandado {record.numero_mandado} expedido!')
    else:
        record.status = 'falha'
        record.save(update_fields=['status'])
        MandadoLog.objects.create(
            mandado=record, tipo='erro',
            mensagem='Falha na expedição via Playwright.',
        )
        print(f'\n❌ Falha ao expedir mandado {record.numero_mandado}')

    return sucesso


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Expede mandado no Projudi')
    parser.add_argument('--mandado', type=int, help='ID do MandadoRecord')
    parser.add_argument('--processo', type=str, help='CNJ do processo')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    expedir_mandado(
        mandado_id=args.mandado,
        processo_cnj=args.processo,
        dry_run=args.dry_run,
    )
