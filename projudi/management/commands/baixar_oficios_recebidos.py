"""
Comando para baixar (MarcaRecebimento) oficios cujo email foi respondido.

Uso:
  python manage.py baixar_oficios_recebidos
  python manage.py baixar_oficios_recebidos --dias 60 --usuario 1

Agenda (cron):
  0 8 * * 1 cd /caminho && .venv/bin/python manage.py baixar_oficios_recebidos
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.conf import settings
from datetime import timedelta


class Command(BaseCommand):
    help = 'Da baixa em oficios com retorno recebido apos N dias'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dias', type=int, default=0,
            help='Dias de carencia apos o retorno (default: settings.OFICIO_BAIXA_DIAS_ESPERA ou 90)'
        )
        parser.add_argument(
            '--usuario', type=int, default=None,
            help='ID do usuario (default: primeiro usuario ativo)'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='So lista os elegiveis sem executar a baixa'
        )

    def handle(self, *args, **options):
        from projudi.models import OficioRecord, OficioLog
        from projudi.oficio_service import OficioService
        from accounts.models import User

        # Usuario
        usuario_id = options['usuario']
        if usuario_id:
            user = User.objects.filter(id=usuario_id, is_active=True).first()
            if not user:
                raise CommandError(f'Usuario #{usuario_id} nao encontrado ou inativo')
        else:
            user = User.objects.filter(is_active=True).first()
            if not user:
                raise CommandError('Nenhum usuario ativo encontrado')

        # Dias de carencia
        dias = options['dias'] or getattr(settings, 'OFICIO_BAIXA_DIAS_ESPERA', 90)
        dry_run = options['dry_run']

        self.stdout.write(f'Usuario: {user.email} ({user.id})')
        self.stdout.write(f'Dias de carencia: {dias}')
        self.stdout.write(f'Dry-run: {dry_run}')
        self.stdout.write('')

        # Busca elegiveis: so oficios juntados (resposta registrada no Projudi)
        # com retorno processado e link de baixa disponivel
        elegiveis = OficioRecord.objects.filter(
            user=user,
            status='juntado',
            status_retorno='processado',
        ).exclude(url_baixa='')

        if dias > 0:
            limite = timezone.now() - timedelta(days=dias)
            elegiveis = elegiveis.filter(data_retorno__lte=limite)

        total = elegiveis.count()
        if total == 0:
            self.stdout.write(self.style.WARNING(
                'Nenhum oficio elegivel para baixa.'))
            return

        self.stdout.write(f'{total} oficio(s) elegivel(is) para baixa:\n')

        for r in elegiveis:
            data_ret = r.data_retorno.strftime('%d/%m/%Y') if r.data_retorno else '-'
            self.stdout.write(
                f'  #{r.id} {r.numero_oficio} | '
                f'{r.processo} | '
                f'retorno: {data_ret} | '
                f'baixa: {r.url_baixa[:60]}...'
            )

        if dry_run:
            self.stdout.write(self.style.WARNING(
                '\nDry-run: nenhuma baixa executada.'))
            return

        # Executa
        self.stdout.write('')
        service = OficioService(user)
        baixados = 0
        erros = 0

        for record in elegiveis:
            self.stdout.write(f'  Baixando #{record.id} {record.numero_oficio}...', ending=' ')
            try:
                sucesso, msg = service.realizar_baixa(record)
                if sucesso:
                    self.stdout.write(self.style.SUCCESS(f'OK: {msg}'))
                    baixados += 1
                else:
                    self.stdout.write(self.style.ERROR(f'FALHOU: {msg}'))
                    erros += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'ERRO: {str(e)[:200]}'))
                erros += 1
                try:
                    OficioLog.objects.create(
                        oficio=record,
                        tipo='erro_baixa',
                        mensagem=f'Excecao no comando baixar_oficios_recebidos: {str(e)[:200]}',
                        detalhes={'comando': True}
                    )
                except Exception:
                    pass

        try:
            service.fechar()
        except Exception:
            pass

        self.stdout.write('')
        if baixados > 0:
            self.stdout.write(self.style.SUCCESS(
                f'Total: {baixados} baixados, {erros} erros'))
        else:
            self.stdout.write(self.style.WARNING(
                f'Total: {baixados} baixados, {erros} erros'))
