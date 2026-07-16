"""
Uso:
  python manage.py expedir_oficio_projudi
  python manage.py expedir_oficio_projudi --processo 0003099 --projudi-numero 41020261733480
  python manage.py expedir_oficio_projudi --documento 1
  python manage.py expedir_oficio_projudi --debug
"""

import os, re, time, random
from django.core.management.base import BaseCommand

LINK_BASE = 'https://projudi.tjba.jus.br/projudi/'


class Command(BaseCommand):
    help = 'Expede Ofícios no Projudi: cria mov 581 + substitui HTML'

    def add_arguments(self, parser):
        parser.add_argument('--processo', type=str)
        parser.add_argument('--documento', type=int)
        parser.add_argument('--debug', action='store_true')
        parser.add_argument('--mov-codigo', type=str, default='581')
        parser.add_argument('--projudi-numero', type=str)

    def _pausa(self, mi=0.8, ma=2.5):
        time.sleep(random.uniform(mi, ma))

    def _pausa_curta(self):
        time.sleep(random.uniform(0.3, 1.2))

    def handle(self, *args, **options):
        self.debug = options['debug']
        codigo = options['mov_codigo']

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
        import django; django.setup()

        from processes.models import GeneratedDocument
        from projudi.services import ProjudiService
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.filter(is_superuser=True).first()
        if not user:
            self.stderr.write('Nenhum superuser')
            return

        qs = GeneratedDocument.objects.filter(template__template_type='oficio')\
            .order_by('-created_at')
        if options['documento']:
            qs = qs.filter(id=options['documento'])
        elif options['processo']:
            qs = qs.filter(process__number__icontains=options['processo'])

        if not qs.exists():
            self.stdout.write('Nenhum documento pendente')
            return

        service = ProjudiService(user=user)
        session = service._get_session_from_cookie_jar()
        if not session:
            self.stderr.write('Sessao indisponivel. Sincronize.')
            return

        cookies = session.cookies.get_dict()
        if 'JSESSIONID' not in cookies:
            self.stderr.write('JSESSIONID ausente')
            return

        projudi_numero = options.get('projudi_numero')

        for doc in qs:
            pnum = projudi_numero or re.sub(r'\D', '', doc.process.number)[:20]
            if not pnum:
                continue

            self.stdout.write(f'\n=== Doc #{doc.id} | {doc.process.number} | {doc.recipient_name} ===')

            if self._check_expedido(pnum, session):
                self.stdout.write('  Ja expedido. Pulando.')
                doc.exported_to_projudi = True
                doc.save(update_fields=['exported_to_projudi'])
                continue

            if self.debug:
                self._debug_pages(pnum, session)
                continue

            try:
                self._expedir(doc=doc, pnum=pnum, cookies=cookies,
                              codigo=codigo, observacao=self._obs(doc))
                doc.exported_to_projudi = True
                doc.save(update_fields=['exported_to_projudi'])
                self.stdout.write(f'  Doc #{doc.id} OK!')
            except Exception as e:
                self.stderr.write(f'  Erro: {e}')
                import traceback; traceback.print_exc()

        self.stdout.write('\nFim')

    def _obs(self, doc):
        p = []
        if doc.rag_example:
            if doc.rag_example.despacho_ato:
                p.append(doc.rag_example.despacho_ato)
            if doc.rag_example.despacho_observacao:
                p.append(doc.rag_example.despacho_observacao[:300])
        if doc.recipient_name:
            p.append(doc.recipient_name)
        return ' | '.join(p) if p else f'Oficio #{doc.sequential_number:03d}/{doc.year}'

    def _check_expedido(self, pnum, session):
        url = f'{LINK_BASE}listagens/DadosProcesso?numeroProcesso={pnum}'
        r = session.get(url, timeout=15)
        return 'Solicitada a Expedicao' in r.text or 'Solicitada a Expedição' in r.text

    # =====================================================================
    # PLAYWRIGHT
    # =====================================================================

    def _expedir(self, doc, pnum, cookies, codigo, observacao):
        from playwright.sync_api import sync_playwright

        url = f'{LINK_BASE}movimentacao/MovimentarProcesso?numeroProcesso={pnum}'

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=False)
            ctx = browser.new_context(viewport={'width': 1280, 'height': 800},
                                      locale='pt-BR')
            for name, value in cookies.items():
                ctx.add_cookies([{
                    'name': name, 'value': value,
                    'domain': 'projudi.tjba.jus.br', 'path': '/'
                }])
            page = ctx.new_page()
            page.goto(url, wait_until='networkidle')
            self._pausa()

            if self.debug:
                page.screenshot(path=f'/tmp/pw_0_{pnum}.png')

            # 1. Codigo 581
            page.fill('#seqCategoriaMovimentacao', codigo)
            self._pausa()

            # 2. Buscar
            page.click('#btnBuscaMovimentacao')
            self._pausa(1, 3)

            if self.debug:
                page.screenshot(path=f'/tmp/pw_1_{pnum}.png')

            # 3. Aguardar DWR preencher descricao (mov 581)
            page.wait_for_function(
                "document.getElementById('descCategoriaMovimentacao').value !== ''",
                timeout=15000
            )
            self._pausa()
            desc = page.input_value('#descCategoriaMovimentacao')
            self.stdout.write(f'  Mov selecionada: 581 - {desc}')
            self._pausa()

            # 4. codTipoDocumento = 53 (Ofício)
            page.select_option('#codTipoDocumento', '53')
            self._pausa()

            # 5. Observacao (despacho do juiz)
            page.fill('#observacao', observacao)
            self._pausa()

            # 6. Clicar "Cumprimento(s) Cartório" para mostrar painel oculto
            page.locator("a:text('Cumprimento')").first.click()
            self._pausa()
            page.wait_for_selector('#tipoCumprimento', timeout=10000)

            # 7. Cumprimento Cartorario: tipo = OFICIO (2)
            page.select_option('#tipoCumprimento', '2')
            self._pausa()

            # 8. Selecionar destinatario
            dest_value = self._find_destinatario(page, doc)
            if dest_value == '-2':
                page.fill('#outroDestinatario', doc.recipient_name or '')
                self._pausa()
            else:
                page.select_option('#codigoDestinatario', dest_value)
                self._pausa()

            # 9. Adicionar cumprimento (>>)
            page.click('#btnAddCumprimento')
            self._pausa()

            # 10. Scroll + Concluir
            page.evaluate('window.scrollBy(0, 400)')
            self._pausa()
            page.click('#Concluir')
            self._pausa(2, 4)

            # 7. Alerta
            try:
                alert = page.wait_for_event('dialog', timeout=8000)
                self.stdout.write(f'  Alerta: {alert.message}')
                alert.accept()
                self._pausa()
            except Exception:
                pass

            self.stdout.write(f'  URL: {page.url}')
            ok = 'DadosProcesso' in page.url or 'Historico' in page.url
            self.stdout.write(f'  Mov 581 {"criada!" if ok else "verificar"}')

            # 8. Substituir HTML
            try:
                self._substituir_html(page, pnum, doc.html_content)
            except Exception as e:
                self.stdout.write(f'  HTML: {e}')

            browser.close()

    def _substituir_html(self, page, pnum, html):
        self.stdout.write('  Buscando oficio...')
        page.goto(
            f'{LINK_BASE}listagens/CumprimentoCartorio?tipo=oficio&acao=naoexpedir',
            wait_until='networkidle'
        )
        self._pausa(2, 4)

        link = page.locator(f"a:has-text('{pnum[:15]}')").first
        if not link.is_visible():
            self.stdout.write('  Nao achou no naoexpedir, tentando expedidos...')
            page.goto(
                f'{LINK_BASE}listagens/CumprimentoCartorio?tipo=oficio&acao=expedidos',
                wait_until='networkidle'
            )
            self._pausa(2, 4)
            link = page.locator(f"a:has-text('{pnum[:15]}')").first
            if not link.is_visible():
                self.stdout.write('  Oficio nao encontrado')
                return

        link.scroll_into_view_if_needed()
        self._pausa()
        link.click()
        self._pausa(2, 4)

        try:
            page.locator('#btnCodigoFonte').wait_for(timeout=10000)
            page.locator('#btnCodigoFonte').scroll_into_view_if_needed()
            self._pausa()
            page.locator('#btnCodigoFonte').click()
            self._pausa()

            page.locator('#codigoFonte').wait_for(timeout=10000)
            page.locator('#codigoFonte').fill(html)
            self._pausa()

            page.locator('#btnSalvarCodigoFonte').click()
            self._pausa(1, 3)
            self.stdout.write('  HTML substituido!')
        except Exception as e:
            self.stdout.write(f'  Erro HTML: {e}')

    def _find_destinatario(self, page, doc):
        """Busca o destinatario na lista; se nao achar, retorna '-2' (OUTRO)."""
        options = page.locator('#codigoDestinatario option').all()
        for opt in options:
            val = opt.get_attribute('value') or ''
            txt = opt.inner_text().strip().lower()
            if val != '-1' and val != '-2':
                if doc.recipient_name and doc.recipient_name.lower() in txt:
                    return val
        return '-2'

    # =====================================================================
    # DEBUG
    # =====================================================================

    def _debug_pages(self, pnum, session):
        d = f'/tmp/pd_{pnum}'
        os.makedirs(d, exist_ok=True)
        for name, url in [
            ('mov', f'{LINK_BASE}movimentacao/MovimentarProcesso?numeroProcesso={pnum}'),
            ('cum', f'{LINK_BASE}listagens/CumprimentoCartorio?tipo=oficio&acao=naoexpedir'),
        ]:
            r = session.get(url, timeout=15)
            with open(f'{d}/{name}.html', 'w') as f:
                f.write(r.text)
            self.stdout.write(f'  [DEBUG] {d}/{name}.html')
