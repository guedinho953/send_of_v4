import re
import time
from django.core.management.base import BaseCommand
from django.conf import settings
from bs4 import BeautifulSoup
import fitz


class Command(BaseCommand):
    help = 'Baixa documentos dos RAGExample, extrai texto e salva em despacho_observacao'

    def add_arguments(self, parser):
        parser.add_argument('--processo', type=str, help='Apenas um processo')
        parser.add_argument('--limite', type=int, default=0, help='Maximo de records (0=todos)')
        parser.add_argument('--pausa', type=float, default=0.3, help='Pausa entre downloads (segundos)')

    def handle(self, *args, **options):
        limite = options['limite']
        processo_filter = options['processo']
        pausa = options['pausa']

        user = self._get_user()
        if not user:
            self.stderr.write(self.style.ERROR('Nenhum usuario ativo'))
            return

        from projudi.services import ProjudiService
        from processes.models import RAGExample

        service = ProjudiService(user=user)
        session = service._get_session_from_cookie_jar()
        if not session:
            self.stderr.write(self.style.ERROR('Nenhuma sessao Projudi'))
            return

        warm = session.get(
            'https://projudi.tjba.jus.br/projudi/cadastros/AnalisarMovimentacao'
        )
        if 'sess\u00e3o expirou' in warm.text.lower() or len(warm.text) < 1000:
            self.stderr.write(self.style.ERROR('Sessao Projudi expirada'))
            return
        self.stdout.write(self.style.SUCCESS('[OK] Sessao Projudi ativa'))

        qs = RAGExample.objects.filter(despacho_observacao='').exclude(
            documentos__exact=[]
        ).exclude(documentos__isnull=True)
        if processo_filter:
            qs = qs.filter(process__number=processo_filter)
        if limite:
            qs = qs[:limite]
        total = qs.count()
        if total == 0:
            self.stdout.write('Nenhum RAGExample pendente de download')
            return

        self.stdout.write(f'Processando {total} RAGExample(s)...')

        ok = 0
        fail = 0
        skipped = 0

        for ex in qs:
            if ex.despacho_observacao.strip():
                skipped += 1
                continue

            textos = []
            for doc in ex.documentos:
                url = doc.get('url', '')
                if not url:
                    continue
                url_fixed = url.replace('downloadarquivo', 'DownloadArquivo')
                try:
                    resp = session.get(url_fixed, timeout=15)
                    if resp.status_code != 200:
                        continue
                    if b'%PDF' in resp.content[:10]:
                        doc_pdf = fitz.open(stream=resp.content, filetype='pdf')
                        txt = '\n'.join([page.get_text() for page in doc_pdf])
                        doc_pdf.close()
                    else:
                        soup = BeautifulSoup(resp.content, 'html.parser')
                        txt = soup.get_text(' ', strip=True)
                    if txt.strip():
                        textos.append(txt)
                except Exception as e:
                    self.stdout.write(self.style.WARNING(
                        f'  [ERRO] evento #{ex.evento_despacho}: {e}'
                    ))

            if textos:
                texto_completo = '\n\n---\n\n'.join(textos)
                if len(texto_completo) > 20:
                    RAGExample.objects.filter(pk=ex.pk).update(
                        despacho_observacao=texto_completo[:5000]
                    )
                    ok += 1
                    preview = texto_completo[:80].replace('\n', ' ')
                    self.stdout.write(
                        f'  [OK] #{ex.evento_despacho} {preview}...'
                    )
                else:
                    fail += 1
            else:
                fail += 1

            time.sleep(pausa)

        self.stdout.write(self.style.SUCCESS(
            f'\nOK: {ok}, Falhas: {fail}, Pulados: {skipped}'
        ))

    def _get_user(self):
        from accounts.models import User
        return User.objects.filter(is_active=True).first()
