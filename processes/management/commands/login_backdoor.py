"""
Comando para gerar uma sessao autenticada de backdoor (dev only).
Uso: python manage.py login_backdoor
Imprime a URL com sessionid para copiar/colar no navegador.
"""
from django.core.management.base import BaseCommand
from django.contrib.sessions.backends.db import SessionStore
from accounts.models import User


class Command(BaseCommand):
    help = 'Gera uma sessao autenticada para acessar o site sem login manual'

    def handle(self, *args, **options):
        user = User.objects.filter(is_active=True).first()
        if not user:
            self.stdout.write(self.style.ERROR('Nenhum usuario ativo encontrado'))
            return

        # Criar sessao
        session = SessionStore()
        session['_auth_user_id'] = str(user.id)
        session['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
        session.create()

        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS(' SESSAO BACKDOOR GERADA '))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(f'\nUsuario: {user.email}')
        self.stdout.write(f'Session key: {session.session_key}\n')
        self.stdout.write('URLS PRONTAS (copie e cole no navegador):\n')

        urls = [
            ('Dashboard', '/dashboard/'),
            ('Lista de Processos', '/processes/'),
            ('Movimentacoes do Processo 1', '/processes/1/movimentacoes/'),
            ('Admin', '/admin/'),
        ]

        base = 'http://127.0.0.1:8000'
        for name, path in urls:
            full = f"{base}{path}"
            self.stdout.write(f'\n  {name}:')
            self.stdout.write(f'  {full}')

        self.stdout.write('\n' + '=' * 70)
        self.stdout.write(self.style.WARNING('AVISO: Isso eh apenas para desenvolvimento local!'))
        self.stdout.write('=' * 70)

        # Imprimir JS para colar no console do navegador
        self.stdout.write('\nSe as URLs nao funcionarem direto, abra o navegador,')
        self.stdout.write('va em DevTools (F12) > Console, e cole:')
        self.stdout.write(f"\n  document.cookie = 'sessionid={session.session_key}; path=/';")
        self.stdout.write("  location.reload();\n")
