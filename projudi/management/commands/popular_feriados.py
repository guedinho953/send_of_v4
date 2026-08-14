"""Command: semeia feriados nacionais e recesso forense no banco.

Uso:
    # Semeia p/ todos os tenants, anos 2025-2027
    python manage.py popular_feriados --anos 2025 2026 2027

    # Semeia só para um tenant específico
    python manage.py popular_feriados --tenant-id 1 --anos 2026

    # Ano atual + próximo (padrão, se --anos omitido)
    python manage.py popular_feriados

O que semeia (idempotente — update_or_create, não duplica):
    - Feriados nacionais FIXOS (tipo='fixo').
    - Feriados nacionais MÓVEIS (Carnaval, Sexta-Feira Santa, Corpus
      Christi) calculados via Páscoa (tipo='movel').
    - Recesso forense (SuspensaoPrazo tipo='recesso_local').

Feriados estaduais/municipais e suspensões pontuais (greve, baixa,
ponto facultativo local) NÃO são semeados — cadastro manual no admin.
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = 'Semeia feriados nacionais (fixos+móveis) e recesso forense no banco.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--anos', nargs='+', type=int, default=None,
            help='Anos a semear (ex: --anos 2025 2026 2027). '
                 'Default: ano atual + próximo.',
        )
        parser.add_argument(
            '--tenant-id', type=int, default=None,
            help='Semeia só para este tenant (id). Default: todos os tenants.',
        )
        parser.add_argument(
            '--sem-recesso', action='store_true',
            help='Não semeia o recesso forense.',
        )

    def handle(self, *args, **opts):
        from accounts.models import Tenant
        from projudi.feriados_nacionais import popular_feriados_nacionais

        anos = opts['anos']
        if not anos:
            from datetime import date
            hoje = date.today()
            # Default: ano anterior + ano atual (o que falta de manual dá
            # pra ajustar no admin; o novo ano costuma já ter sido virado).
            anos = [hoje.year - 1, hoje.year]
        self.stdout.write(f'Anos alvo: {anos}')

        if opts['tenant_id']:
            tenants = Tenant.objects.filter(id=opts['tenant_id'])
            if not tenants.exists():
                raise CommandError(f'Tenant id={opts["tenant_id"]} não existe.')
        else:
            tenants = Tenant.objects.all()

        if not tenants.exists():
            raise CommandError('Nenhum tenant encontrado.')

        total = {'fixos': 0, 'moveis': 0, 'recesso': 0}
        for t in tenants:
            stats = popular_feriados_nacionais(
                t, anos=anos, incluir_recesso=not opts['sem_recesso'],
            )
            for k in total:
                total[k] += stats[k]
            self.stdout.write(
                f'  ✓ {t.name} (id={t.id}): {stats["fixos"]} fixos, '
                f'{stats["moveis"]} móveis, {stats["recesso"]} recesso'
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'\nConcluído. Total: {total["fixos"]} feriados fixos, '
                f'{total["moveis"]} móveis, {total["recesso"]} recessos.'
            )
        )
