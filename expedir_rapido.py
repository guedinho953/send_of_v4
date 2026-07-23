"""Rastrear movimentações e expedir documentos automaticamente.
Varre movimentações do Projudi, compara com RAGExamples e expede
o documento adequado (mandado ou ofício) conforme o template vinculado.

Uso:
  python expedir_rapido.py                     # rastrear (padrão)
  python expedir_rapido.py --oficios-only      # só ofícios
  python expedir_rapido.py --mandados-only     # só mandados
  python expedir_rapido.py --processo CNJ      # expedir processo específico
"""
import os, sys, re, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import date
from django.template import Template, Context
from django.db.models import Max

from accounts.models import User
from processes.models import Process, DocumentTemplate, Party, RAGExample, GeneratedDocument
from processes.movimentacoes_service import buscar_cumprimentos_similares
from projudi.services import ProjudiService
from projudi_client import ProjudiClient
from processo_parser_ext import ProcessoParserExt


def session_projudi():
    """Obtém sessão Projudi via captura robusta de cookies."""
    user = User.objects.filter(is_active=True).first()
    if not user:
        print('❌ Nenhum usuário ativo')
        sys.exit(1)
    service = ProjudiService(user)
    result = service._get_session_from_cookies()
    if not result:
        print('❌ Não foi possível capturar a sessão do Projudi.')
        print('   Deixe o Firefox aberto e logado no Projudi.')
        sys.exit(1)
    return user, result[0], result[1]


def rastrear_e_expedir(tipo=None):
    """
    Varre movimentações, match RAG e expede.
    tipo=None (todos), 'mandado', 'oficio'
    """
    user, session, cookies_dict = session_projudi()

    print('\n========== RASTREAR E EXPEDIR ==========')
    if tipo:
        print(f'Filtrando: {tipo}')
    else:
        print('Tipo: todos (mandados + ofícios)')

    client = ProjudiClient()
    client.session = session
    client.cookies = cookies_dict

    pages = client.obter_paginas_finais_movimentacoes(quantidade=3)
    print(f'{len(pages)} página(s) para varrer')

    movs = []
    for p in pages:
        data = {'pagina': str(p), 'loginJuiz': ''}
        rp = session.post(client.URL_MOVIMENTACOES, data=data, timeout=15)
        if len(rp.text) > 1000:
            sp = BeautifulSoup(rp.text, 'html.parser')
            movs.extend(client.extrair_links_movimentacoes(sp))

    print(f'{len(movs)} movimentação(ões) encontrada(s)')

    if tipo == 'mandado':
        templates_validos = DocumentTemplate.objects.filter(template_type='mandado', active=True)
    elif tipo == 'oficio':
        templates_validos = DocumentTemplate.objects.filter(template_type='oficio', active=True)
    else:
        templates_validos = DocumentTemplate.objects.filter(template_type__in=['mandado', 'oficio'], active=True)

    expedidos = 0
    erros = 0

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

            similares = buscar_cumprimentos_similares(texto, top_k=5)
            if not similares:
                continue

            melhor = None
            template = None
            rag = None
            palavras_texto = set(texto.lower().split())

            for s in similares:
                # Usa despacho_ato + observacao para comparação (mais preciso)
                texto_rag = s['despacho_ato'] + ' ' + s.get('despacho_observacao', '')
                palavras_rag_s = set(texto_rag.lower().split())
                total_s = max(len(palavras_rag_s), 1)
                if len(palavras_texto & palavras_rag_s) / total_s < 0.70:
                    continue
                try:
                    rag_cand = RAGExample.objects.get(id=s['id'])
                    if rag_cand.sequencia_cumprimento:
                        # Verifica tipo na sequência
                        seq_tipos = {p.get('tipo') for p in rag_cand.sequencia_cumprimento}
                        if tipo and tipo not in seq_tipos:
                            continue
                        # Valida que template_id existe e é do tipo certo (quando aplicável)
                        if tipo in ('mandado', 'oficio'):
                            ids_validos = set(templates_validos.values_list('id', flat=True))
                            tem_template_valido = any(
                                p.get('template_id') in ids_validos
                                for p in rag_cand.sequencia_cumprimento
                                if p.get('tipo') == tipo
                            )
                            if not tem_template_valido:
                                continue
                        melhor = s
                        template = None
                        rag = rag_cand
                        break
                    t = rag_cand.suggested_templates.filter(id__in=templates_validos).first()
                    if t:
                        melhor = s
                        template = t
                        rag = rag_cand
                        break
                except RAGExample.DoesNotExist:
                    continue

            if not melhor:
                continue

            if rag and rag.sequencia_cumprimento:
                print(f'\n  {proc_num}: match com sequência ({len(rag.sequencia_cumprimento)} passo(s))')
                _executar_sequencia_rapido(
                    rag.sequencia_cumprimento, mov, proc_num, texto,
                    session, cookies_dict, user, rag)
                expedidos += 1
                continue

            pct = len(palavras_texto & set(melhor['despacho_ato'].lower().split())) / max(len(set(melhor['despacho_ato'].lower().split())), 1)
            print(f'\n  {proc_num}: match {melhor["similaridade"]} pal ({pct:.0%}) → {template.name}')

            proc = Process.objects.filter(number=proc_num).first()
            if not proc:
                print('   — criando processo...', end='')
                proc = _criar_processo(session, mov, proc_num, user)
                if not proc:
                    print(' falhou')
                    continue
                print(' ✅')

            # Para mandados: destinatário é o RÉU/EXECUTADO
            if template and template.template_type == 'mandado':
                partes = list(Party.objects.filter(
                    process=proc,
                    role__in=['reu', 'executado', 'PROMOVIDO', 'EXECUTADO']
                ))
                if not partes:
                    partes = [Party.objects.filter(process=proc).first()]
            else:
                partes = [Party.objects.filter(process=proc).first()]

            for part in partes:
                if not part:
                    print('   — sem partes')
                    continue
                print(f'   ✅ {template.name} — {part.name}')

                html_doc = _gerar_html(proc, part, rag, template)
                if not html_doc:
                    continue

                if template.template_type == 'mandado':
                    sucesso = _expedir_mandado(proc, session, cookies_dict, html_doc, part)
                else:
                    sucesso = _expedir_oficio(proc, session, cookies_dict, html_doc, part, template)

                if sucesso:
                    expedidos += 1
                    print(f'   ✅ {template.name} expedido para {part.name}')
            else:
                erros += 1

        except Exception as e:
            print(f'   ❌ Erro: {e}')
            import traceback; traceback.print_exc()
            erros += 1

    print(f'\n{"="*50}')
    print(f'Expedidos: {expedidos} | Erros: {erros}')
    print(f'{"="*50}')


def _executar_sequencia_rapido(sequencia, mov, proc_num, texto,
                                session, cookies_dict, user, rag=None):
    """Executa cada passo da sequencia_cumprimento."""
    from projudi.movimentacao_service import MovimentacaoService
    from processes.models import Process, Party, DocumentTemplate
    from projudi.rag_router import _mapear_categoria_por_obs
    from types import SimpleNamespace

    print(f'   📋 Sequência de {len(sequencia)} passo(s):')

    for i, passo in enumerate(sequencia, 1):
        tipo = passo.get('tipo', '')
        obs = passo.get('observacao', '')
        template_id = passo.get('template_id')
        subtipo = passo.get('subtipo')

        print(f'      [{i}/{len(sequencia)}] {tipo}...', end=' ')

        try:
            if tipo == 'movimentacao':
                service = MovimentacaoService(user)
                record = service.importar(
                    processo_numero=proc_num,
                    act_verb='movimentacao',
                    observacao=obs or texto[:500],
                    categoria=_mapear_categoria_por_obs(obs or texto),
                    processo_cnj=proc_num,
                    url_processo=mov.get('link_processo', ''),
                    codigo_movimentacao=str(passo.get('codigo_mov', '581')),
                    descricao_movimentacao=passo.get(
                        'descricao_mov', 'Cumprimento de Decisão'),
                )
                print(f'Movimentação #{record.id}')

            elif tipo in ('mandado', 'oficio'):
                if not template_id:
                    print('sem template_id, pulando')
                    continue
                try:
                    tmpl = DocumentTemplate.objects.get(id=template_id, active=True)
                except DocumentTemplate.DoesNotExist:
                    print(f'template #{template_id} não encontrado')
                    continue

                proc = Process.objects.filter(number=proc_num).first()
                if not proc:
                    proc = _criar_processo(session, mov, proc_num, user)
                if not proc:
                    print('processo não encontrado')
                    continue

                # Filtra partes RÉU/EXECUTADO — para mandados, o destinatário é sempre o réu
                if tipo == 'mandado':
                    partes = Party.objects.filter(
                        process=proc,
                        role__in=['reu', 'executado', 'PROMOVIDO', 'EXECUTADO']
                    )
                    if not partes:
                        partes = Party.objects.filter(process=proc)[:1]
                else:
                    partes = Party.objects.filter(process=proc)[:1]

                for part in partes:
                    rag_ctx = rag or SimpleNamespace(
                        despacho_ato='', despacho_observacao='',
                        despacho_data='', despacho_autor='MARTINHO FERRAZ DA NOBREGA JUNIOR')
                    html_doc = _gerar_html(proc, part, rag_ctx, tmpl)
                    if not html_doc:
                        continue

                    if tipo == 'mandado' or tmpl.template_type == 'mandado':
                        subtipo_val = subtipo or '11'
                        part._subtipo_mandado = str(subtipo_val)
                        sucesso = _expedir_mandado(
                            proc, session, cookies_dict, html_doc, part, subtipo=subtipo_val)
                    else:
                        sucesso = _expedir_oficio(proc, session, cookies_dict, html_doc, part, tmpl)

                    if sucesso:
                        print(f'{tmpl.name} — {part.name}')
                    else:
                        print(f'{tmpl.name} falhou — {part.name}')

            else:
                print(f'tipo desconhecido: {tipo}')

        except Exception as e:
            print(f'erro: {e}')
            import traceback; traceback.print_exc()


def _criar_processo(session, mov, proc_num, user):
    """Cria Process + Party acessando DadosProcesso do Projudi."""
    from projudiProcessNavigator import ProcessoParser
    from projudi.models import Vara, Court
    from base.utils import normalize_process_number

    link_proc = mov.get('link_processo', '')
    if not link_proc:
        return None

    try:
        r = session.get(link_proc, timeout=30)
        if r.status_code != 200 or 'expirou' in r.text.lower():
            return None

        parser = ProcessoParser(r.text)
        partes_raw = parser.extrair_partes(parser.soup)

        court, _ = Court.objects.get_or_create(
            code='TJBA', defaults={'name': 'TJBA', 'state': 'BA', 'tenant': user.tenant})
        vara, _ = Vara.objects.get_or_create(
            code='2VSJ-PA',
            defaults={'name': '2ª VSJ de Paulo Afonso', 'comarca': 'Paulo Afonso',
                      'court': court, 'tenant': user.tenant})

        proc = Process.objects.create(
            number=proc_num, number_normalized=normalize_process_number(proc_num),
            status='analyzing', vara=vara, court=court,
            projudi_url=link_proc, tenant=user.tenant)

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
            if p.get('cep'):
                endereco += f' - CEP: {p.get("cep")}'

            Party.objects.get_or_create(
                process=proc, name=nome, tenant=user.tenant,
                defaults={
                    'name_normalized': nome.lower().strip(), 'role': role,
                    'cpf_cnpj': p.get('cpf/cnpj', ''), 'email': p.get('email', '') or '',
                    'phone': p.get('tel', '') or '', 'address': endereco,
                })

        return proc
    except Exception:
        return None


def _gerar_html(proc, part, rag, template):
    """Gera o HTML do documento com os dados corretos."""
    ctx = {
        'processo': proc.number,
        'despacho_ato': rag.despacho_ato,
        'despacho_observacao': rag.despacho_observacao,
        'despacho_data': rag.despacho_data,
        'despacho_autor': rag.despacho_autor or 'MARTINHO FERRAZ DA NOBREGA JUNIOR',
        'parte': {
            'nome': part.name, 'endereco': part.address or '',
            'email': part.email or '', 'telefone': part.phone or '',
            'cpf_cnpj': part.cpf_cnpj or '', 'rg': part.rg or '',
            'nome_pai': part.nome_pai or '', 'nome_mae': part.nome_mae or '',
        },
        'partes': [{
            'nome': part.name, 'endereco': part.address or '',
            'email': part.email or '', 'telefone': part.phone or '',
            'cpf_cnpj': part.cpf_cnpj or '', 'rg': part.rg or '',
        }],
        'prazo_dias': '05', 'data': date.today().strftime('%d/%m/%Y'),
    }

    if template.template_type == 'mandado':
        num_doc = f'MAN-{proc.id:03d}/{date.today().year}'
    else:
        last = GeneratedDocument.objects.filter(process=proc).aggregate(Max('sequential_number'))
        seq = (last['sequential_number__max'] or 0) + 1
        num_doc = f'{seq:03d}/{date.today().year}'
    ctx['numero_documento'] = num_doc

    if template.template_type == 'oficio':
        ente = Party.objects.filter(process=proc, role='reu').first()
        if ente:
            ctx['ente_devedor'] = ente.name
            ctx['ente_endereco'] = ente.address or ''
            ctx['ente_email'] = ente.email or ''
            ctx['ente_telefone'] = ente.phone or ''
        else:
            ctx['ente_devedor'] = ''
            ctx['ente_endereco'] = ''
            ctx['ente_email'] = ''

        valor_match = re.search(r'R\$?\s*([\d.,]+)', rag.despacho_observacao or rag.despacho_ato)
        ctx['valor'] = valor_match.group(1) if valor_match else ''

        # Se CPF/CNPJ do credor estiver vazio, tenta extrair do despacho
        if not ctx['parte']['cpf_cnpj']:
            cpf_match = re.search(r'CPF\s*:?\s*([\d.-]+)|CNPJ\s*:?\s*([\d./-]+)', rag.despacho_observacao or rag.despacho_ato)
            if cpf_match:
                ctx['parte']['cpf_cnpj'] = cpf_match.group(1) or cpf_match.group(2) or ''

        # Se email do ente estiver vazio, deixa vazio
        if not ctx.get('ente_email'):
            ctx['ente_email'] = ''

    try:
        html = Template(template.html_template).render(Context(ctx))
        return html
    except Exception as e:
        print(f'   ❌ Erro renderizando template: {e}')
        return None


def _expedir_mandado(proc, session, cookies_dict, html_mandado, part, subtipo='11'):
    """Expede mandado via Playwright."""
    from playwright.sync_api import sync_playwright

    PROC_PROJUDI = None
    projudi_url = getattr(proc, 'projudi_url', None) or ''
    m = re.search(r'numeroProcesso=(\d+)', projudi_url)
    if m:
        PROC_PROJUDI = m.group(1)
    if not PROC_PROJUDI:
        print('   ❌ Número Projudi não encontrado')
        return False

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

            url_mov = f'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso={PROC_PROJUDI}'
            page.goto(url_mov, wait_until='networkidle')
            time.sleep(2)

            page.evaluate('''() => {
                var camp = document.getElementById('seqCategoriaMovimentacao');
                if (camp) camp.value = '581';
                var desc = document.getElementById('descCategoriaMovimentacao');
                if (desc) desc.value = 'Solicitada a Expedição de Mandado';
                var tr = document.getElementById('trTipoDocumento');
                if (tr) tr.style.display = 'table-row';
            }''')
            time.sleep(1)
            page.select_option('select[name="codTipoDocumento"]', '51')
            time.sleep(1)
            page.fill('#observacao', f'Solicitada Expedicao de Mandado - {nome_parte[:30]}')
            time.sleep(0.5)
            page.locator("a:text('Cumprimento')").first.click()
            time.sleep(1)
            page.select_option('#tipoCumprimento', '4')
            time.sleep(0.5)

            # subtipoCumprimento — só existe DEPOIS de tipoCumprimento=4
            subtipo_valor = subtipo or getattr(part, '_subtipo_mandado', None) or '11'
            try:
                st = page.locator('#subtipoCumprimento').first
                if st.count():
                    st.select_option(str(subtipo_valor))
                    time.sleep(0.3)
                    print(f'   ✅ Subtipo mandado: {subtipo_valor}')
            except Exception:
                print(f'   ⚠️ Subtipo não selecionado')

            nome_dest = part.name if part else ''
            if nome_dest:
                try:
                    opt = page.locator(f'#codigoDestinatario option:text("{nome_dest}")').first
                    if opt.count():
                        val = opt.get_attribute('value')
                        page.select_option('#codigoDestinatario', val)
                        print(f'   ✅ Destinatário: {nome_dest} ({val})')
                    else:
                        first_opt = page.locator('#codigoDestinatario option').first
                        if first_opt.count():
                            val = first_opt.get_attribute('value')
                            page.select_option('#codigoDestinatario', val)
                            print(f'   ✅ Destinatário: primeiro ({val})')
                except Exception as e:
                    print(f'   ⚠️ Destinatário fallback: {e}')
                page.click('#btnAddCumprimento')
                time.sleep(1.5)
                print(f'   ✅ Cumprimento adicionado')
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            time.sleep(0.5)
            page.click('#Concluir')
            time.sleep(4)
            try:
                alert = page.wait_for_event('dialog', timeout=5000)
                print(f'   📢 {alert.message}')
                alert.accept()
                time.sleep(2)
            except:
                pass
            try:
                page.wait_for_load_state('networkidle', timeout=10000)
            except:
                pass

            print(f'   ✅ Movimentação concluída. URL: {page.url}')

            # Captura codCumprimento da URL
            cod_cump = ''
            m = re.search(r'codCumprimento=(\d+)', page.url)
            if m:
                cod_cump = m.group(1)
            if not cod_cump:
                cod_cump = page.evaluate(r'''() => {
                    var body = document.body.innerHTML;
                    var m = body.match(/codCumprimento["']?\s*[:=]\s*["']?(\d+)/i);
                    return m ? m[1] : '';
                }''')
            print(f'   codCumprimento: {cod_cump or "não encontrado"}')

            # Usa link de movimentação genérica (DadosProcesso)
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

            # ── FCKEDITOR ──
            print('   ✍️ Extraindo brasão e colando template...')
            time.sleep(3)

            html_original = page.evaluate('''() => {
                try { return FCKeditorAPI.GetInstance('FCKeditor1').GetHTML(); }
                catch(e) {
                    try { return window.parent.FCKeditorAPI.GetInstance('FCKeditor1').GetHTML(); }
                    catch(e2) { return ''; }
                }
            }''')

            img_match = re.search(r'(<img[^>]+src="[^"]*brasao[^"]*"[^>]*>)', html_original, re.I)
            brasao_html = ''
            if img_match:
                brasao_html = f'<div style="text-align:center; margin-bottom:8px;">{img_match.group(1)}</div>'
                print('   ✅ Brasão extraído')
            else:
                print('   ⚠️ Brasão não encontrado no RPA')

            html_final = brasao_html + html_mandado
            res = page.evaluate('''(html) => {
                try {
                    var ed = FCKeditorAPI.GetInstance('FCKeditor1');
                    ed.SetHTML(''); ed.SetHTML(html);
                    return 'OK SetHTML';
                } catch(e) {
                    try {
                        var ed2 = window.parent.FCKeditorAPI.GetInstance('FCKeditor1');
                        ed2.SetHTML(''); ed2.SetHTML(html);
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

            # ── SUBMETER ──
            print('   🔄 Submeter...')
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
                print('   ✅ Submeter clicado')
            else:
                print('   ⚠️ Submeter não encontrado')

            # ── REGISTRAR ──
            print('   🔄 Registrando...')
            registrar = page.locator("input[value='Registrar'], button:has-text('Registrar')").first
            if registrar.count():
                registrar.scroll_into_view_if_needed()
                time.sleep(1)
                registrar.click()
                time.sleep(4)
                print('   ✅ Registrar clicado')
            else:
                print('   ⚠️ Registrar não encontrado')

            # ── VERIFICAR ──
            html_check = page.content()
            if any(k in html_check.lower() for k in
                   ['registrado', 'sucesso', 'confirmado',
                    'mandados para expedir', 'cumprimentocartorio']):
                print('   ✅ Mandado registrado com sucesso!')
            else:
                print('   ⚠️ Registrar pode não ter confirmado')
            browser.close()
            sucesso = True
    except Exception as e:
        print(f'   ❌ Playwright mandado: {e}')
        import traceback; traceback.print_exc()
    return sucesso


def _expedir_oficio(proc, session, cookies_dict, html_oficio, part, template):
    """Expede ofício via Playwright seguindo fluxo igual ao CIAP."""
    from playwright.sync_api import sync_playwright

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
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(r.url).query)
            PROC_PROJUDI = qs.get('numeroProcesso', [None])[0]
        if not PROC_PROJUDI:
            print('   ❌ Número Projudi não encontrado')
            return False

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

            # === 1. Mov 581 ===
            url_mov = f'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso={PROC_PROJUDI}'
            page.goto(url_mov, wait_until='networkidle')
            time.sleep(2)

            page.evaluate('''() => {
                var camp = document.getElementById('seqCategoriaMovimentacao');
                if (camp) camp.value = '581';
                var desc = document.getElementById('descCategoriaMovimentacao');
                if (desc) desc.value = 'Solicitada a Expedição de Ofício';
                var tr = document.getElementById('trTipoDocumento');
                if (tr) tr.style.display = 'table-row';
                var div = document.getElementById('rowDadosMovimentacaoComplemento');
                if (div) div.style.display = 'block';
                var panel = document.getElementById('divPanelCumprimento');
                if (panel) panel.style.display = 'block';
            }''')
            time.sleep(1.5)

            page.select_option('select[name="codTipoDocumento"]', '53')
            time.sleep(1)
                        # Observação com tipo de ofício e credor
            eh_ciap = 'ciap' in template.name.lower()
            if eh_ciap:
                page.fill('#observacao', f'Solicitada Expedicao de Oficio CIAP - {nome_parte[:30]}')
            else:
                credor = Party.objects.filter(process=proc, role='autor').first()
                nome_credor = credor.name if credor else nome_parte
                page.fill('#observacao', f'Solicitada Expedicao de Oficio (RPV) - Credor: {nome_credor[:50]}')
            time.sleep(0.5)

            page.locator("a:text('Cumprimento')").first.click()
            time.sleep(1)
            page.select_option('#tipoCumprimento', '2')  # OFICIO
            time.sleep(0.5)

            # Destinatário conforme o template
            eh_ciap = 'ciap' in template.name.lower()
            if eh_ciap:
                page.select_option('#codigoDestinatario', '13809981')
                page.click('#btnAddCumprimento')
                time.sleep(1)
            else:
                # Seleciona destinatário pelo texto no dropdown (igual CIAP, mas por nome)
                ente = Party.objects.filter(process=proc, role='reu').first()
                nome_dest = ente.name if ente else 'Empresa Baiana de Aguas e Saneamento'
                try:
                    page.select_option('#codigoDestinatario', label=nome_dest)
                except:
                    # Fallback: tenta pelo texto parcial
                    page.evaluate("(nome) => {" +
                        "var sel = document.getElementById('codigoDestinatario');" +
                        "if (!sel) return;" +
                        "for (var i = 0; i < sel.options.length; i++) {" +
                            "var txt = sel.options[i].text.toLowerCase();" +
                            "if (txt.includes('embasa') || txt.includes('agua') || txt.includes('saneamento')) {" +
                                "sel.value = sel.options[i].value; break;" +
                            "}" +
                        "}" +
                    "}", nome_dest)
                page.click('#btnAddCumprimento')
                time.sleep(2)

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

            # === 2. CumprimentoCartorio → Redigir sem AR ===
            url_cump = 'https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=oficio&acao=expedir'
            page.goto(url_cump, wait_until='networkidle')
            time.sleep(3)

            cump_result = page.evaluate('''() => {
                var forms = document.querySelectorAll('form[name^="formCumprimento"]');
                if (forms.length === 0) return {erro: 'nenhum form encontrado'};
                var form = forms[forms.length - 1];
                var sel = form.querySelector('select[name="codModelo"]');
                if (!sel) return {erro: 'select codModelo nao encontrado', form: form.name};
                var rpaValue = null;
                for (var i = 0; i < sel.options.length; i++) {
                    if (sel.options[i].text.toLowerCase().includes('rpa')) {
                        rpaValue = sel.options[i].value; break;
                    }
                }
                if (!rpaValue) return {erro: 'modelo RPA nao encontrado'};
                sel.value = rpaValue;
                return {ok: true, form: form.name, codModelo: rpaValue};
            }''')
            print(f'   📝 {cump_result}')
            if not cump_result.get('ok'):
                print(f'   ❌ ERRO: {cump_result}')
                browser.close()
                return False

            form_name = cump_result['form']
            with page.expect_navigation(timeout=15000):
                page.evaluate(f'''() => {{
                    var form = document.forms['{form_name}'];
                    form.gerarar.value = 'false';
                    form.submit();
                }}''')
                time.sleep(3)

            time.sleep(3)
            if 'ExpedirCumprimento' not in page.url:
                print(f'   ❌ ERRO: nao foi pra ExpedirCumprimento. URL: {page.url}')
                browser.close()
                return False

            # === 3. FCKeditor ===
            time.sleep(3)
            html_original = page.evaluate('''() => {
                try { return FCKeditorAPI.GetInstance('FCKeditor1').GetHTML(); }
                catch(e) {
                    try { return window.parent.FCKeditorAPI.GetInstance('FCKeditor1').GetHTML(); }
                    catch(e2) { return ''; }
                }
            }''')

            img_match = re.search(r'(<img[^>]+src="[^"]*brasao[^"]*"[^>]*>)', html_original, re.I)
            brasao_html = ''
            if img_match:
                brasao_html = f'<div style="text-align:center; margin-bottom:8px;">{img_match.group(1)}</div>'
                print('   ✅ Brasão extraído')
            else:
                print('   ⚠️ Brasão não encontrado')

            html_final = brasao_html + html_oficio
            result = page.evaluate('''(html) => {
                try { var ed = FCKeditorAPI.GetInstance('FCKeditor1'); ed.SetHTML(''); ed.SetHTML(html); return 'OK'; }
                catch(e) {
                    try { var ed2 = window.parent.FCKeditorAPI.GetInstance('FCKeditor1'); ed2.SetHTML(''); ed2.SetHTML(html); return 'OK parent'; }
                    catch(e2) { return 'ERRO: ' + e2.message; }
                }
            }''', html_final)
            print(f'   📝 FCKeditor: {result}')
            time.sleep(2)

            # === 4. Submeter ===
            submeter = page.locator('input[src*="bot-submeter"], input[type="image"]').first
            if submeter.count():
                submeter.scroll_into_view_if_needed()
                time.sleep(1)
                submeter.click()
                time.sleep(5)
            else:
                print('   ❌ Submeter nao encontrado')
                browser.close()
                return False

            # === 5. Registrar ===
            registrar = page.locator("input[value='Registrar'], input[src*='registrar']").first
            if registrar.count():
                registrar.scroll_into_view_if_needed()
                time.sleep(1)
                registrar.click()
                time.sleep(3)
                print('   ✅ Registrar clicado!')
            else:
                print('   ⚠️ Registrar nao encontrado')

            # Verificar sucesso
            html_check = page.content()
            if any(k in html_check.lower() for k in ['registrado', 'sucesso', 'confirmado', 'ofícios para expedir', 'cumprimentocartorio']):
                sucesso = True
                print('   ✅ CONFIRMADO: Ofício expedido!')
            else:
                print(f'   ⚠️ Nao confirmado automaticamente')
            browser.close()
    except Exception as e:
        print(f'   ❌ ERRO Playwright: {e}')
        import traceback; traceback.print_exc()
    return sucesso


# ══════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Rastrear e expedir documentos')
    parser.add_argument('--processo', type=str, help='CNJ do processo específico')
    parser.add_argument('--mandados-only', action='store_true', help='Só mandados')
    parser.add_argument('--oficios-only', action='store_true', help='Só ofícios')
    args = parser.parse_args()

    if args.mandados_only:
        rastrear_e_expedir(tipo='mandado')
    elif args.oficios_only:
        rastrear_e_expedir(tipo='oficio')
    else:
        rastrear_e_expedir(tipo=None)
