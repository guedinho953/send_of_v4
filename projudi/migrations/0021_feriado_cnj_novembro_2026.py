from datetime import date

from django.db import migrations


NOME_BASE = 'Sem expediente forense — determinação do CNJ'
DATAS = [date(2026, 11, 12), date(2026, 11, 13)]


def criar_feriados(apps, schema_editor):
    Tenant = apps.get_model('accounts', 'Tenant')
    Feriado = apps.get_model('projudi', 'Feriado')

    for tenant in Tenant.objects.all():
        for data in DATAS:
            Feriado.objects.update_or_create(
                tenant=tenant,
                nome=f'{NOME_BASE} ({data.strftime("%d/%m/%Y")})',
                tipo='unico',
                data=data,
                defaults={
                    'escopo': 'nacional',
                    'observacao': (
                        'Sem expediente forense por determinação do CNJ.'
                    ),
                    'is_active': True,
                },
            )


def remover_feriados(apps, schema_editor):
    Feriado = apps.get_model('projudi', 'Feriado')
    Feriado.objects.filter(
        nome__startswith=NOME_BASE,
        data__in=DATAS,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('projudi', '0020_certidaoregistro'),
    ]

    operations = [
        migrations.RunPython(criar_feriados, remover_feriados),
    ]
