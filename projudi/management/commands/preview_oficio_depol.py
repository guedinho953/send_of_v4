"""Gera um PREVIEW (sem expedir) do ofício DEPOL de cumprimento de diligências.

Uso:
    python manage.py preview_oficio_depol --processo 0002803-76.2025.8.05.0191
    python manage.py preview_oficio_depol --processo ... --sem-copia
    python manage.py preview_oficio_depol --processo ... --com-copia

O HTML é salvo em var/preview_depol_<processo>.html.
"""

import os
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

os.environ.setdefault('PLAYWRIGHT_HEADLESS', '1')

import expedir_oficios_por_tipo as E


class Command(BaseCommand):
    help = 'Gera preview do ofício DEPOL de diligências (não expede)'

    def add_arguments(self, parser):
        parser.add_argument('--processo', required=True, help='Número CNJ')
        parser.add_argument('--url', help='URL DadosProcesso (opcional)')
        parser.add_argument('--user', help='E-mail do usuário da sessão')
        parser.add_argument('--saida', help='Arquivo HTML de saída')
        parser.add_argument('--com-copia', action='store_true',
                            help='Força o modelo com cópia integral do MP')
        parser.add_argument('--sem-copia', action='store_true',
                            help='Força o modelo só com a lista de diligências')

    def handle(self, *args, **options):
        if options['com_copia'] and options['sem_copia']:
            raise CommandError('Use apenas --com-copia ou --sem-copia.')

        User = get_user_model()
        if options['user']:
            user = User.objects.filter(email=options['user']).first()
            if not user:
                raise CommandError(f'Usuário não encontrado: {options["user"]}')
        else:
            user = User.objects.filter(is_active=True).order_by('id').first()
        if not user:
            raise CommandError('Nenhum usuário ativo.')

        cookies = E._carregar_cookies(user)
        http_session = E._criar_sessao_http(cookies)
        processo = options['processo'].strip()

        item = None
        if options['url']:
            item = {'procHref': options['url'], 'rowText': processo}
        else:
            from processes.models import Process

            proc_db = Process.objects.filter(number=processo).first()
            if proc_db and proc_db.projudi_url:
                item = {'procHref': proc_db.projudi_url, 'rowText': processo}
            else:
                item = self._buscar_item_pendente(processo, cookies)

        if not item:
            raise CommandError(
                'Não encontrei o processo na lista de ofícios pendentes. '
                'Informe --url com a URL DadosProcesso do Projudi.')

        override = None
        if options['com_copia']:
            override = True
        elif options['sem_copia']:
            override = False

        self.stdout.write(f'Processo: {processo}')
        self.stdout.write(f'URL......: {item.get("procHref")}')
        self.stdout.write('Lendo despacho do juiz e parecer do MP...')

        html, template, proc, _dados, resumo = E._gerar_conteudo_depol(
            item, user, http_session, com_copia_override=override)

        if not html:
            raise CommandError(
                'Não foi possível montar o ofício. Veja as mensagens acima.')

        pasta = Path(settings.BASE_DIR) / 'var'
        pasta.mkdir(parents=True, exist_ok=True)
        saida = Path(options['saida']) if options['saida'] else (
            pasta / f'preview_depol_{processo.replace("/", "_")}.html')
        saida.parent.mkdir(parents=True, exist_ok=True)

        pagina = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>Preview ofício DEPOL — {processo}</title>
<style>body{{background:#eee;padding:20px;}}
.folha{{background:#fff;padding:40px;max-width:850px;margin:0 auto;
box-shadow:0 2px 12px rgba(0,0,0,.2);}}
.aviso{{max-width:850px;margin:0 auto 12px;padding:8px 12px;background:#fef3c7;
border:1px solid #f59e0b;font-family:Arial,sans-serif;font-size:13px;}}
</style></head><body>
<div class="aviso"><strong>PREVIEW — NÃO EXPEDIDO.</strong>
Processo {processo}. {resumo}</div>
<div class="folha">{html}</div>
</body></html>"""
        saida.write_text(pagina, encoding='utf-8')

        self.stdout.write(self.style.SUCCESS(f'Template: {template.name}'))
        self.stdout.write(self.style.SUCCESS(f'Resumo..: {resumo}'))
        self.stdout.write(self.style.SUCCESS(f'Preview.: {saida}'))
        self.stdout.write('Abra o arquivo no Firefox para revisar.')

    def _buscar_item_pendente(self, processo, cookies):
        from playwright.sync_api import sync_playwright
        from projudi.playwright_firefox import launch_firefox

        with sync_playwright() as pw:
            browser = launch_firefox(pw)
            contexto = browser.new_context(
                viewport={'width': 1500, 'height': 950}, locale='pt-BR')
            contexto.add_cookies([
                {'name': str(k), 'value': str(v),
                 'domain': 'projudi.tjba.jus.br', 'path': '/'}
                for k, v in cookies.items()
            ])
            page = contexto.new_page()
            page.goto(E.URL_CUMPRIMENTO, wait_until='networkidle',
                      timeout=60000)
            itens = page.evaluate(E.JS_SCAN)
            browser.close()

        for item in itens:
            texto = ' '.join([
                item.get('rowText') or '',
                item.get('procText') or '',
            ])
            if processo in texto:
                return item
        return None
