"""Cria um usuário administrador local, se ainda não existir nenhum.

Uso:
    python manage.py criar_usuario_local
    python manage.py criar_usuario_local --email admin@local --password admin123

Feito para o primeiro start em uma máquina nova (Windows ou Linux).
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Cria um superusuário local (padrão: admin@local / admin123)'

    def add_arguments(self, parser):
        parser.add_argument('--email', default='admin@local')
        parser.add_argument('--password', default='admin123')
        parser.add_argument('--nome', default='Administrador')
        parser.add_argument('--force', action='store_true',
                            help='Sobrescreve a senha se o usuário já existir')

    def handle(self, *args, **options):
        User = get_user_model()
        email = options['email'].strip().lower()
        senha = options['password']

        usuario = User.objects.filter(email=email).first()
        if usuario:
            if options['force']:
                usuario.set_password(senha)
                usuario.is_staff = True
                usuario.is_superuser = True
                usuario.save()
                self.stdout.write(self.style.SUCCESS(
                    f'Senha de {email} redefinida.'))
            else:
                self.stdout.write(
                    f'Usuário {email} já existe; nada foi alterado.')
            return

        User.objects.create_superuser(
            email=email,
            password=senha,
            first_name=options['nome'],
        )
        self.stdout.write(self.style.SUCCESS(
            f'Usuário criado: {email} / {senha}'))
        self.stdout.write('Troque a senha em /admin/ se necessário.')
