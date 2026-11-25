from django.core.management.base import BaseCommand, CommandError

from projudi.oficio_planilha_service import (
    OficioPlanilhaError,
    OficioPlanilhaService,
)


class Command(BaseCommand):
    help = 'Testa a leitura da planilha Google de ofícios (último e próximo número).'

    def handle(self, *args, **options):
        service = OficioPlanilhaService()

        if not service.configurado:
            raise CommandError(
                'Planilha Google não configurada. Defina '
                'GOOGLE_SERVICE_ACCOUNT_FILE no .env e compartilhe o '
                'documento com a conta de serviço.'
            )

        try:
            ultimo = service._ultimo_numero()
            proximo = service.proximo_numero()
        except OficioPlanilhaError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f'Último número: {ultimo[0]}/{ultimo[1]} | '
                f'Próximo: {proximo}'
            )
        )
