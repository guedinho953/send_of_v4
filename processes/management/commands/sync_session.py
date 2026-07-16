"""
Sincroniza cookies do Firefox com o Django.
O usuario deve estar logado no Projudi no Firefox antes de rodar.

Uso:
  python manage.py sync_session
  python manage.py sync_session --user admin@admin.com
"""

from django.core.management.base import BaseCommand
from django.conf import settings
import os, sys


class Command(BaseCommand):
    help = 'Sincroniza cookies do Firefox com o Django'

    def add_arguments(self, parser):
        parser.add_argument('--user', type=str, help='Email do usuario (default: superuser)')

    def handle(self, *args, **options):
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
        import django
        django.setup()

        from django.contrib.auth import get_user_model
        from projudi.services import ProjudiService
        from projudi.models import ProjudiSession

        User = get_user_model()

        if options['user']:
            user = User.objects.filter(email=options['user']).first()
        else:
            user = User.objects.filter(is_superuser=True).first()

        if not user:
            self.stderr.write('Usuario nao encontrado')
            return

        self.stdout.write(f'Sincronizando sessao para {user.email}...')
        service = ProjudiService(user)

        try:
            bot = service.get_bot()
            bot.criar_sessao()

            if not bot.testar_login():
                self.stderr.write(
                    'Nao foi possivel capturar a sessao.\n'
                    'Certifique-se de estar logado no Projudi no Firefox.\n'
                    'No Windows, rode: python scripts/capture_cookies_windows.py'
                )
                return

            cookies = bot.exportar_cookies()
            session, created = ProjudiSession.objects.update_or_create(
                user=user,
                defaults={
                    'cookies': cookies,
                    'status': 'active',
                    'tenant': user.tenant,
                }
            )

            msg = 'Sessao sincronizada com sucesso!' if created else 'Sessao atualizada!'
            self.stdout.write(self.style.SUCCESS(f'{msg}'))
            self.stdout.write(f'  Cookies: {list(cookies.keys())}')
            self.stdout.write(f'  JSESSIONID: {"OK" if "JSESSIONID" in cookies else "AUSENTE"}')

            if 'JSESSIONID' not in cookies:
                self.stderr.write('AVISO: JSESSIONID nao encontrado. A sessao pode estar expirada.')

        except Exception as e:
            self.stderr.write(f'Erro ao sincronizar: {e}')
