"""Executa as ações de certidão agendadas para depois da intimação."""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from projudi.acoes_agendadas import executar_pendentes


class Command(BaseCommand):
    help = 'Executa ações agendadas de certidões vencidas.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--data', help='Data limite YYYY-MM-DD (default: hoje)')
        parser.add_argument(
            '--user', help='E-mail do usuário (opcional)')
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Apenas lista as ações vencidas, sem executar.')

    def handle(self, *args, **options):
        data = None
        if options.get('data'):
            try:
                data = datetime.strptime(
                    options['data'], '%Y-%m-%d').date()
            except ValueError:
                raise CommandError('Data inválida. Use YYYY-MM-DD.')

        user = None
        if options.get('user'):
            from django.contrib.auth import get_user_model
            user = get_user_model().objects.filter(
                email=options['user']).first()
            if not user:
                raise CommandError('Usuário não encontrado.')

        from datetime import date as _date
        from projudi.models import AcaoCertidaoAgendada

        qs = AcaoCertidaoAgendada.objects.filter(
            status='pendente',
            data_agendada__lte=data or _date.today(),
        )
        if user:
            qs = qs.filter(user=user)
        if options.get('dry_run'):
            for acao in qs:
                self.stdout.write(
                    f'#{acao.id} {acao.data_agendada} '
                    f'{acao.get_tipo_display()} — {acao.registro.processo}')
            self.stdout.write(f'{qs.count()} ação(ões) vencida(s).')
            return

        resultado = executar_pendentes(user=user, data=data)
        self.stdout.write(self.style.SUCCESS(
            f'Ações executadas: {resultado["executadas"]}; '
            f'falhas: {resultado["falhas"]}.'))
