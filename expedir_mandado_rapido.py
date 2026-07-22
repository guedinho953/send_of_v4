"""
Expedição humanizada de Mandado no Projudi — fluxo completo.
Similar ao expedir_humanizado.py dos ofícios, mas para mandados.

Faz TUDO em um único comando:
  1. Varre movimentações (AnalisarMovimentacao)
  2. Baixa documento do despacho
  3. Match com RAG (70%+ similaridade)
  4. Se tem template mandado vinculado → abre Playwright
  5. Mov 581 → CumprimentoCartorio tipo=mandado → FCKeditor → Registrar

Uso:
  python expedir_mandado_rapido.py
  python expedir_mandado_rapido.py --processo 0000799-32.2026.8.05.0191 --projudi 41020261253760
  python expedir_mandado_rapido.py --dry-run
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
from datetime import date, datetime
from projudi_bot import ProjudiBot
from processo_parser_ext import ProcessoParserExt

from accounts.models import User
from processes.models import Process, DocumentTemplate, Party, RAGExample
from processes.movimentacoes_service import buscar_cumprimentos_similares
from projudi.models import MandadoRecord, MandadoLog

# ── CONFIG ──────────────────────────────────────────────────────
TEMPLATE_MANDADO_ID = 6
COOKIES_PATH = '/mnt/d/Projudi/cookies.json'


def carregar_cookies():
    c = ProjudiBot.carregar_cookies_do_arquivo()
    if not c or 'JSESSIONID' not in c:
        print('❌ Cookies sem JSESSIONID. Capture primeiro.')
        sys.exit(1)
    return c


def session_com_cookies(cookies_dict):
    s = requests.Session()
    for k, v in cookies_dict.items():
        s.cookies.set(k, v)
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9',
    })
    return s


def _criar_processo_da_mov(session, mov, proc_num):
    """Cria Process + Party acessando DadosProcesso do Projudi."""
    from projudiProcessNavigator import ProcessoParser
    from projudi.models import Vara, Court
    from base.utils import normalize_process_number

    url = mov.get('link_processo', '')
    if not url:
        print('   Sem link_processo')
        return None

    try:
        r = session.get(url, timeout=30)
        if r.status_code != 200 or 'expirou' in r.text.lower():
            return None

        parser = ProcessoParser(r.text)
        partes_raw = parser.extrair_partes(parser.soup)

        u = User.objects.filter(is_active=True).first()
        if not u:
            return None

        court, _ = Court.objects.get_or_create(
            code='TJBA',
            defaults={'name': 'TJBA', 'state': 'BA', 'tenant': u.tenant})
        vara, _ = Vara.objects.get_or_create(
            code='2VSJ-PA',
            defaults={'name': '2ª VSJ de Paulo Afonso', 'comarca': 'Paulo Afonso',
                      'court': court, 'tenant': u.tenant})

        proc = Process.objects.create(
            number=proc_num,
            number_normalized=normalize_process_number(proc_num),
            status='analyzing',
            vara=vara, court=court,
            projudi_url=url,
            tenant=u.tenant,
        )

        for p in partes_raw:
            nome = p.get('nome', '').strip()
            if not nome:
                continue
            role = 'autor' if p.get('tipo', '').upper() in ('EXEQUENTE', 'PROMOVENTE') else 'reu'
            end_parts = []
            for k in ('logradouro', 'bairro', 'cidade', 'uf'):
                v = p.get(k, '')
                if v:
                    end_parts.append(str(v).strip())
            endereco = ', '.join(end_parts) if end_parts else ''
            cep_val = p.get('cep', '')
            if cep_val:
                endereco += f' - CEP: {cep_val}'

            Party.objects.get_or_create(
                process=proc, name=nome, tenant=u.tenant,
                defaults={
                    'name_normalized': nome.lower().strip(),
                    'role': role,
                    'cpf_cnpj': p.get('cpf/cnpj', ''),
                    'email': p.get('email', '') or '',
                    'phone': p.get('tel', '') or '',
                    'address': endereco,
                })

        print(f'   ✅ Processo {proc.number} criado com {len(partes_raw)} parte(s)')
        return proc

    except Exception as e:
        print(f'   Erro criar processo: {e}')
        return None


def expedir_mandado_playwright(proc, session, cookies_dict, html_mandado, part=None):
    """Abre Playwright e faz mov 581 + CumprimentoCartorio + FCKeditor + Registrar."""
    PROC_PROJUDI = None
    projudi_url = getattr(proc, 'projudi_url', None) or ''
    m = re.search(r'numeroProcesso=(\d+)', projudi_url)
    if m:
        PROC_PROJUDI = m.group(1)

    if not PROC_PROJUDI:
        print('   🔍 Buscando número Projudi...')
        r = session.post(
            'https://projudi.tjba.jus.br/projudi/processo/consultaProcesso',
            data={'numeroProcesso': proc.number}, timeout=15)
        if r.status_code == 200:
            qs = parse_qs(urlparse(r.url).query)
            PROC_PROJUDI = qs.get('numeroProcesso', [None])[0]

    if not PROC_PROJUDI:
        print('   ❌ Número Projudi não encontrado')
        return False

    print(f'   📁 Projudi: {PROC_PROJUDI}')

    if part is None:
        part = Party.objects.filter(process=proc).last()
    nome_parte = part.name if part else 'parte'

    # Se a parte não tem endereço, tenta buscar dados atualizados do Projudi
    if part and (not part.address or not part.phone):
        print('   🔍 Buscando dados atualizados da parte no Projudi...')
        try:
            proc_url = (proc.projudi_url or
                f'https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?numeroProcesso={PROC_PROJUDI}')
            r = session.get(proc_url, timeout=30)
            if r.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r.text, 'html.parser')
                # Procura a linha (tr) da parte pelo nome
                nome_busca = part.name.lower().strip()
                for tr in soup.find_all('tr', id=lambda x: x and x.startswith('tr')):
                    tds = tr.find_all('td')
                    if len(tds) < 2:
                        continue
                    nome_td = tds[1].get_text(' ', strip=True).lower().strip()
                    if nome_busca in nome_td or nome_td in nome_busca:
                        id_linha = tr.get('id', '').replace('tr', '')
                        span_end = soup.find('span', id=f'spanEnd{id_linha}')
                        if span_end:
                            texto = span_end.get_text(' ', strip=True)
                            # Extrai endereço (tudo entre "Endereço" e o próximo campo)
                            end_match = re.search(r'Endereço\s*(.*?)(?:\s+\d{10,11}|$)', texto, re.I | re.DOTALL)
                            tel_match = re.search(r'(\d{10,11})', texto)
                            email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', texto)
                            endereco = end_match.group(1).strip() if end_match else ''
                            if endereco:
                                # Limpa caracteres especiais e espaços extras
                                endereco = endereco.replace('\xa0', ' ').replace('\r\n', ', ').replace('\r', ', ').replace('\n', ', ')
                                endereco = re.sub(r'\s+', ' ', endereco).strip().rstrip(',').strip()
                            telefone = tel_match.group(1) if tel_match else ''
                            email = email_match.group(0) if email_match else ''
                            if endereco or telefone or email:
                                part.address = endereco or part.address
                                part.phone = telefone or part.phone
                                part.email = email or part.email
                                part.save(update_fields=['address', 'phone', 'email'])
                                print(f'   ✅ Dados atualizados: endereço={bool(endereco)}, tel={bool(telefone)}, email={bool(email)}')
                            break
                else:
                    print('   ⚠️ Parte não encontrada nos dados do Projudi')
        except Exception as e:
            print(f'   ⚠️ Erro ao buscar dados: {e}')

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

            # ── 1. MOVIMENTAR PROCESSO (581) ──────────────────
            print('   [1/5] 🚀 Mov 581...')
            url_mov = f'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso={PROC_PROJUDI}'
            page.goto(url_mov, wait_until='load')
            time.sleep(3)

            if not page.evaluate('!!document.getElementById("seqCategoriaMovimentacao")'):
                print('   ❌ Formulário não encontrado')
                browser.close()
                return False

            page.evaluate('''() => {
                var c = document.getElementById('seqCategoriaMovimentacao');
                if (c) c.value = '581';
                var d = document.getElementById('descCategoriaMovimentacao');
                if (d) d.value = 'Solicitada a Expedição de Mandado';
                var tr = document.getElementById('trTipoDocumento');
                if (tr) tr.style.display = 'table-row';
                var div = document.getElementById('rowDadosMovimentacaoComplemento');
                if (div) div.style.display = 'block';
                var p = document.getElementById('divPanelCumprimento');
                if (p) p.style.display = 'block';
            }''')
            time.sleep(1)
            print('   ✅ Mov 581 injetado')

            page.select_option('select[name="codTipoDocumento"]', '51')
            time.sleep(1.5)
            print(f'   Tipo doc: Mandado (51)')
            page.fill('#observacao', f'Solicitada Expedicao de Mandado - {nome_parte[:30]}')
            time.sleep(0.5)

            page.locator("a:text('Cumprimento')").first.click()
            time.sleep(1)
            page.select_option('#tipoCumprimento', '4')
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
            # Seleciona destinatário: a parte ré (autor do fato)
            nome_dest = part.name if part else ''
            if nome_dest:
                try:
                    # Tenta pelo texto da opção
                    opt = page.locator(f'#codigoDestinatario option:text("{nome_dest}")').first
                    if opt.count():
                        val = opt.get_attribute('value')
                        page.select_option('#codigoDestinatario', val)
                        print(f'   Destinatário: {nome_dest} ({val})')
                    else:
                        # Fallback: pega a primeira opção disponível
                        first_opt = page.locator('#codigoDestinatario option').first
                        if first_opt.count():
                            val = first_opt.get_attribute('value')
                            page.select_option('#codigoDestinatario', val)
                            print(f'   Destinatário: first option ({val})')
                except Exception as e:
                    print(f'   Destinatário fallback: {e}')
            page.click('#btnAddCumprimento')
            time.sleep(1)
            print('   ✅ Cumprimento adicionado')

            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            time.sleep(0.5)
            page.click('#Concluir')
            time.sleep(2)
            # Aceita alerta primeiro (ele bloqueia a navegação)
            try:
                alert = page.wait_for_event('dialog', timeout=5000)
                print(f'   📢 {alert.message}')
                alert.accept()
                time.sleep(2)
            except:
                pass
            # Agora espera a navegação
            try:
                page.wait_for_load_state('networkidle', timeout=10000)
            except:
                pass

            print(f'   ✅ Movimentação concluída. URL: {page.url}')
            print(f'   ✅ Movimentação concluída. URL: {page.url}')

            # Captura codCumprimento da URL atual
            cod_cump = ''
            m = re.search(r'codCumprimento=(\d+)', page.url)
            if m:
                cod_cump = m.group(1)

            if not cod_cump:
                cod_cump = page.evaluate('''() => {
                    var body = document.body.innerHTML;
                    var m = body.match(/codCumprimento["']?\\s*[:=]\\s*["']?(\\d+)/i);
                    return m ? m[1] : '';
                }''')
            print(f'   codCumprimento: {cod_cump or "não encontrado"}')

            # Usa o link de movimentação genérica (do DadosProcesso)
            link_mov = proc.projudi_url or f'https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?numeroProcesso={PROC_PROJUDI}'
            r_mov = session.get(link_mov, timeout=15)
            if r_mov.status_code == 200:
                from projudiProcessNavigator import ProcessoParser
                parser = ProcessoParser(r_mov.text)
                links = parser.extrair_links(parser.soup, parser.base_url)
                url_movimentar = links.get('movimentar', '')
                if url_movimentar:
                    page.goto(url_movimentar, wait_until='load')
                    time.sleep(3)
                    print(f'   🔗 Link movimentação genérica')
            else:
                page.goto(
                    'https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=mandado&acao=expedir',
                    wait_until='load')
                time.sleep(3)

            # Procura "Redigir sem AR" ou forms com select codModelo
            link = page.locator('a:has-text("Redigir sem AR")').last
            if link.count():
                with page.expect_navigation(timeout=20000):
                    link.click()
                time.sleep(3)
                print(f'   ✅ URL: {page.url}')
            else:
                r = page.evaluate('''() => {
                    var forms = document.querySelectorAll('form');
                    for (var i = forms.length - 1; i >= 0; i--) {
                        var sel = forms[i].querySelector('select[name="codModelo"]');
                        if (sel) {
                            for (var j = 0; j < sel.options.length; j++) {
                                if (sel.options[j].text.toLowerCase().includes('rpa')) {
                                    sel.value = sel.options[j].value; break;
                                }
                            }
                            if (sel.value == '-1') sel.value = sel.options[sel.options.length-1].value;
                            return {ok: true, form: forms[i].name || forms[i].id};
                        }
                    }
                    return {erro: 'nenhum form com codModelo'};
                }''')
                print(f'   {r}')
                if not r.get('ok'):
                    if cod_cump:
                        url_exp = f'https://projudi.tjba.jus.br/projudi/acoes/ExpedirCumprimentoCartorio?codCumprimento={cod_cump}&gerarar=false'
                        page.goto(url_exp, wait_until='load')
                        time.sleep(3)
                        print(f'   ✅ URL: {page.url}')
                    else:
                        print('   ❌ Não encontrado')
                        browser.close()
                        return False

            if 'ExpedirCumprimento' not in page.url:
                print(f'   ❌ Não foi pra ExpedirCumprimento. URL: {page.url}')
                browser.close()
                return False

            # ── 3. FCKEDITOR — preservar brasão do RPA e colar nosso template ──
            print('   [3/5] ✍️ Extraindo brasão do RPA e colando template...')
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
            html_final = brasao_html + html_mandado

            # 4. Colar no editor
            res = page.evaluate('''(html) => {
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
            print(f'   📝 {res}')
            time.sleep(2)

            # ── 4. SUBMETER ───────────────────────────────────
            print('   [4/5] 🔄 Submeter...')
            # Debug: ver botões disponíveis
            botoes = page.evaluate('''() => {
                var btns = document.querySelectorAll('input[type="submit"], input[type="image"], input[type="button"], button');
                return Array.from(btns).map(function(b) {
                    return (b.id || '') + '=' + (b.value || b.textContent || '') + ' (' + (b.type || '') + ')';
                }).join(' | ');
            }''')
            print(f'   Botões: {botoes}')
            btn = page.locator('input[src*="bot-submeter"], input[type="image"]').first
            if btn.count():
                btn.scroll_into_view_if_needed()
                time.sleep(1)
                btn.click()
                time.sleep(5)
                print('   ✅ Submetido')
            else:
                # Tenta botão Registrar direto
                btn_r = page.locator("input[value='Registrar'], input[src*='registrar']").first
                if btn_r.count():
                    btn_r.scroll_into_view_if_needed()
                    time.sleep(1)
                    btn_r.click()
                    time.sleep(4)
                    print('   ✅ Registrado direto!')
                    sucesso = True
                    browser.close()
                    return sucesso
                else:
                    print('   ❌ Nenhum botão encontrado')
                    browser.close()
                    return False

            # ── 5. REGISTRAR ──────────────────────────────────
            print('   [5/5] 🔄 Registrar...')
            btn_r = page.locator("input[value='Registrar'], input[src*='registrar']").first
            if btn_r.count():
                btn_r.scroll_into_view_if_needed()
                time.sleep(1)
                btn_r.click()
                time.sleep(4)
                # Verificar se registrou
                html_final = page.content()
                if any(k in html_final.lower() for k in ['registrado', 'sucesso', 'confirmado', 'mandados para expedir', 'cumprimentocartorio']):
                    print('   ✅ Mandado registrado!')
                    sucesso = True
                else:
                    print('   ⚠️ Registrar clicado, mas não confirmado. Pode ter funcionado.')
                    sucesso = True
            else:
                print('   ⚠️ Registrar não encontrado (pode ter ido direto)')
                sucesso = True

            browser.close()
    except Exception as e:
        print(f'   ❌ {e}')
        import traceback; traceback.print_exc()

    return sucesso


# ══════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Expede mandado completo')
    parser.add_argument('--processo', type=str, help='CNJ do processo')
    parser.add_argument('--projudi', type=str, help='Número Projudi interno')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    user = User.objects.filter(is_active=True).first()
    if not user:
        print('❌ Nenhum usuário ativo')
        sys.exit(1)

    # Usa captura robusta de cookies (4 camadas: JSON → PowerShell → browser_cookie3 → banco)
    from projudi.services import ProjudiService
    service = ProjudiService(user)
    result = service._get_session_from_cookies()
    if not result:
        print('❌ Não foi possível capturar a sessão do Projudi.')
        print('   Deixe o Firefox aberto e logado no Projudi, depois execute:')
        print('   D:\\Projudi\\capturar_cookies.bat  (dê duplo clique)')
        sys.exit(1)
    session, cookies_dict = result

    filtro = args.processo
    projudi_informado = args.projudi
    dry_run = args.dry_run

    # ══════════ MODO DIRETO (--processo) ══════════
    if filtro:
        proc = Process.objects.filter(number=filtro).first()
        if not proc:
            print(f'❌ Processo {filtro} não encontrado')
            sys.exit(1)

        if projudi_informado and not proc.projudi_url:
            proc.projudi_url = f'https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?numeroProcesso={projudi_informado}'
            proc.save(update_fields=['projudi_url'])

        template = DocumentTemplate.objects.get(id=TEMPLATE_MANDADO_ID)
        part = Party.objects.filter(process=proc).last()
        if not part:
            print('❌ Sem partes')
            sys.exit(1)

        ctx = {
            'processo': proc.number,
            'despacho_autor': 'MARTINHO FERRAZ DA NOBREGA JUNIOR',
            'parte': {
                'nome': part.name, 'endereco': part.address,
                'email': part.email, 'telefone': part.phone,
                'cpf_cnpj': part.cpf_cnpj, 'rg': part.rg,
                'nome_pai': part.nome_pai, 'nome_mae': part.nome_mae,
                'advogado': part.lawyer_name,
            },
            'numero_documento': f'MAN-{proc.id:03d}/{date.today().year}',
            'prazo_dias': '05',
            'data': date.today().strftime('%d/%m/%Y'),
        }
        html = Template(template.html_template).render(Context(ctx))

        if dry_run:
            print(f'🏁 Dry-run — expediria mandado')
            sys.exit(0)

        expedir_mandado_playwright(proc, session, cookies_dict, html, part)

    # ══════════ MODO RASTREAR ══════════
    else:
        print('\n========== RASTREAR MANDADOS ==========')
        from projudi_client import ProjudiClient
        client = ProjudiClient()
        client.session = session
        client.cookies = cookies_dict

        # Varre múltiplas páginas de movimentações
        pages = client.obter_paginas_finais_movimentacoes(quantidade=3)
        print(f'{len(pages)} página(s) para varrer')

        movs = []
        for p in pages:
            data = {'pagina': str(p), 'loginJuiz': ''}
            rp = session.post(client.URL_MOVIMENTACOES, data=data, timeout=15)
            if len(rp.text) > 1000:
                sp = BeautifulSoup(rp.text, 'html.parser')
                movs_pag = client.extrair_links_movimentacoes(sp)
                movs.extend(movs_pag)

        print(f'{len(movs)} movimentação(ões) encontrada(s)')

        templates_mandado = DocumentTemplate.objects.filter(
            template_type='mandado', active=True)
        if not templates_mandado.exists():
            print('❌ Nenhum template mandado ativo')
            sys.exit(1)

        for mov in movs:
            proc_num = mov.get('processo', '')
            if not proc_num:
                continue

            doc_url = mov.get('link_documento', '')
            if not doc_url:
                continue

            if not doc_url.startswith('http'):
                doc_url = urljoin('https://projudi.tjba.jus.br/projudi/', doc_url)

            try:
                r_doc = session.get(doc_url, timeout=30)
                if r_doc.status_code != 200:
                    continue
                texto = BeautifulSoup(r_doc.text, 'html.parser').get_text(' ', strip=True)
                if len(texto) < 50:
                    continue

                similares = buscar_cumprimentos_similares(texto, top_k=3)
                if not similares:
                    continue

                melhor = None
                template = None
                # Procura entre os matches: prioriza quem TEM template vinculado
                palavras_texto = set(texto.lower().split())
                for s in similares:
                    palavras_rag_s = set(s['despacho_ato'].lower().split())
                    total_s = max(len(palavras_rag_s), 1)
                    inter_s = len(palavras_texto & palavras_rag_s)
                    pct_s = inter_s / total_s
                    if pct_s < 0.70:
                        continue
                    try:
                        rag_cand = RAGExample.objects.get(id=s['id'])
                        t = rag_cand.suggested_templates.filter(
                            template_type='mandado').first()
                        if t:
                            melhor = s
                            template = t
                            rag = rag_cand
                            break
                    except RAGExample.DoesNotExist:
                        continue

                if not melhor:
                    # Fallback: pega o primeiro que passar dos 70% E tiver template mandado
                    for s in similares:
                        palavras_rag_s = set(s['despacho_ato'].lower().split())
                        total_s = max(len(palavras_rag_s), 1)
                        inter_s = len(palavras_texto & palavras_rag_s)
                        if inter_s / total_s >= 0.70:
                            try:
                                rag_cand = RAGExample.objects.get(id=s['id'])
                                t = rag_cand.suggested_templates.filter(
                                    template_type='mandado').first()
                                if t:
                                    melhor = s
                                    rag = rag_cand
                                    template = t
                                    break
                            except RAGExample.DoesNotExist:
                                continue

                if not melhor:
                    continue

                print(f'\n  {proc_num}: match {melhor["similaridade"]} pal ({pct_s:.0%})', end='')

                proc = Process.objects.filter(number=proc_num).first()
                if not proc:
                    print(' — criando...', end='')
                    proc = _criar_processo_da_mov(session, mov, proc_num)
                    if not proc:
                        print(' falhou')
                        continue
                    print(' OK', end='')

                part = Party.objects.filter(
                    process=proc, role__in=['reu', 'executado']).first()
                if not part:
                    part = Party.objects.filter(process=proc).first()
                if not part or not part.name:
                    print(' — sem parte')
                    continue

                print(f' ✅ {template.name} — {part.name}')

                ctx = {
                    'processo': proc.number,
                    'despacho_ato': rag.despacho_ato,
                    'despacho_observacao': rag.despacho_observacao,
                    'despacho_data': rag.despacho_data,
                    'despacho_autor': rag.despacho_autor or 'MARTINHO FERRAZ DA NOBREGA JUNIOR',
                    'parte': {
                        'nome': part.name,
                        'endereco': part.address,
                        'email': part.email,
                        'telefone': part.phone,
                    },
                    'partes': [{
                        'nome': part.name,
                        'endereco': part.address,
                        'email': part.email,
                        'telefone': part.phone,
                    }],
                    'prazo_dias': '05',
                }
                num_man = f'MAN-{proc.id:03d}/{date.today().year}'
                ctx.update({
                    'numero_documento': num_man,
                    'prazo_dias': '05',
                    'data': date.today().strftime('%d/%m/%Y'),
                })
                html_m = Template(template.html_template).render(Context(ctx))

                if dry_run:
                    print(f'   🏁 Dry-run')
                    continue

                # Cria/atualiza MandadoRecord
                m_rec, _ = MandadoRecord.objects.get_or_create(
                    processo=proc.number.replace('.', '').replace('-', '')[:30],
                    numero_mandado=num_man,
                    defaults={
                        'numero_processo_cnj': proc.number,
                        'status': 'pendente',
                        'parte_nome': part.name,
                        'texto_html': html_m,
                        'user': user,
                    },
                )
                print(f'   📋 #{m_rec.id} — expedindo...', end='')

                ok = expedir_mandado_playwright(proc, session, cookies_dict, html_m, part)
                if ok:
                    m_rec.status = 'expedido'
                    m_rec.save(update_fields=['status'])
                    MandadoLog.objects.create(
                        mandado=m_rec, tipo='expedicao',
                        mensagem=f'Expedido. Match: {melhor["similaridade"]} pal ({pct:.0%}).',
                    )
                    print(' ✅')
                else:
                    m_rec.status = 'falha'
                    m_rec.save(update_fields=['status'])
                    print(' ❌')

            except Exception as e:
                print(f'   Erro: {e}')
