from django.core.management.base import BaseCommand, CommandError

from projudi.oficio_planilha_service import obter_servico_planilha


class Command(BaseCommand):
    help = 'Testa a leitura da planilha Google de ofícios (último e próximo número).'

    def handle(self, *args, **options):
        try:
            service = obter_servico_planilha()
        except Exception as exc:
            raise CommandError(f'Erro ao iniciar a planilha: {exc}') from exc

        if not service:
            raise CommandError(
                'Planilha Google não configurada. Use '
                'GOOGLE_OFICIOS_WEBHOOK_URL (Apps Script) ou '
                'GOOGLE_SERVICE_ACCOUNT_FILE (conta de serviço).'
            )

        try:
            ultimo = service._ultimo_numero()
            proximo = service.proximo_numero()
        except AttributeError:
            # Webhook não expõe _ultimo_numero; usa apenas o próximo.
            try:
                proximo = service.proximo_numero()
            except Exception as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                self.style.SUCCESS(f'Próximo número: {proximo}')
            )
            return
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f'Último número: {ultimo[0]}/{ultimo[1]} | '
                f'Próximo: {proximo}'
            )
        )
