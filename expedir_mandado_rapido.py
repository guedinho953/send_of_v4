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

            page.select_option('select[name="codTipoDocumento"]', '54')
            time.sleep(1)
            print(f'   Tipo doc: Mandado (54)')
            page.fill('#observacao', f'Solicitada Expedicao de Mandado - {nome_parte[:30]}')
            time.sleep(0.5)

            page.locator("a:text('Cumprimento')").first.click()
            time.sleep(1)
            page.select_option('#tipoCumprimento', '3')
            time.sleep(0.5)
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
                # Tenta pegar de links na página
                cod_cump = page.evaluate('''() => {
                    var body = document.body.innerHTML;
                    var m = body.match(/codCumprimento["']?\\s*[:=]\\s*["']?(\\d+)/i);
                    return m ? m[1] : '';
                }''')
            print(f'   codCumprimento: {cod_cump or "não encontrado"}')

            # Usa o link de movimentação genérica (do DadosProcesso)
            # que mostra todos os cumprimentos pendentes do processo
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
                                if (sel.options[j].text.toLowerCase().includes('mandado')) {
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
                    # Fallback: vai direto pro ExpedirCumprimento
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

            # ── 3. FCKEDITOR ──────────────────────────────────
            print('   [3/5] ✍️ Colando HTML...')
            time.sleep(3)
            res = page.evaluate('''(html) => {
                try { var ed = FCKeditorAPI.GetInstance('FCKeditor1'); ed.SetHTML(html); return 'OK'; }
                catch(e) {
                    try { var ed2 = window.parent.FCKeditorAPI.GetInstance('FCKeditor1'); ed2.SetHTML(html); return 'OK parent'; }
                    catch(e2) { return 'ERRO: ' + e2.message; }
                }
            }''', html_mandado)
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
                print('   ✅ Mandado registrado!')
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

    cookies_dict = carregar_cookies()
    session = session_com_cookies(cookies_dict)

    filtro = args.processo
    projudi_informado = args.projudi
    dry_run = args.dry_run

    user = User.objects.filter(is_active=True).first()
    if not user:
        print('❌ Nenhum usuário ativo')
        sys.exit(1)

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

                melhor = similares[0]

                # Filtro: % das palavras do RAGExample presentes no despacho
                palavras_texto = set(texto.lower().split())
                palavras_rag = set(melhor['despacho_ato'].lower().split())
                total_rag = max(len(palavras_rag), 1)
                intersecao = len(palavras_texto & palavras_rag)
                pct = intersecao / total_rag
                if pct < 0.70:
                    continue

                print(f'\n  {proc_num}: match {melhor["similaridade"]} pal ({pct:.0%})', end='')

                proc = Process.objects.filter(number=proc_num).first()
                if not proc:
                    print(' — criando...', end='')
                    proc = _criar_processo_da_mov(session, mov, proc_num)
                    if not proc:
                        print(' falhou')
                        continue
                    print(' OK', end='')

                rag = RAGExample.objects.filter(
                    process=proc, suggested_templates__in=templates_mandado,
                ).first()
                if not rag:
                    rag_similar = RAGExample.objects.filter(
                        despacho_ato__icontains=melhor['despacho_ato'][:50],
                        suggested_templates__in=templates_mandado,
                    ).first()
                    if not rag_similar:
                        print(' — sem RAG')
                        continue
                    rag = rag_similar

                template = rag.suggested_templates.filter(
                    template_type='mandado').first()
                if not template:
                    print(' — sem template')
                    continue

                part = Party.objects.filter(
                    process=proc, role__in=['reu', 'executado']).first()
                if not part:
                    part = Party.objects.filter(process=proc).first()
                if not part or not part.name:
                    print(' — sem parte')
                    continue

                print(f' ✅ {template.name} — {part.name}')

                ctx = rag.get_template_context(parte_id=part.id)
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
