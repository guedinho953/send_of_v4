from datetime import date

from django.db import migrations


NOME_ANTIGO = 'Dia do Servidor Público'
NOME_NOVO = 'Dia do Servidor Público'
OBS_ANTIGA = (
    'Dia do Servidor Público — sem expediente forense / ponto facultativo.'
)
OBS_NOVA = (
    'Sem expediente forense — Dia do Servidor Público transferido '
    'para 30/10/2026.'
)


def transferir(apps, schema_editor):
    Tenant = apps.get_model('accounts', 'Tenant')
    Feriado = apps.get_model('projudi', 'Feriado')

    for tenant in Tenant.objects.all():
        # Remove o feriado fixo de 28/10 criado anteriormente.
        Feriado.objects.filter(
            tenant=tenant,
            nome=NOME_ANTIGO,
            tipo='fixo',
            mes=10,
            dia=28,
        ).delete()

        # O dia do servidor público de 2026 foi transferido para 30/10.
        Feriado.objects.update_or_create(
            tenant=tenant,
            tipo='unico',
            data=date(2026, 10, 30),
            defaults={
                'nome': NOME_NOVO,
                'escopo': 'nacional',
                'observacao': OBS_NOVA,
                'is_active': True,
            },
        )


def reverter(apps, schema_editor):
    Tenant = apps.get_model('accounts', 'Tenant')
    Feriado = apps.get_model('projudi', 'Feriado')
    Feriado.objects.filter(
        tipo='unico',
        data=date(2026, 10, 30),
        observacao=OBS_NOVA,
    ).delete()
    for tenant in Tenant.objects.all():
        Feriado.objects.update_or_create(
            tenant=tenant,
            nome=NOME_ANTIGO,
            tipo='fixo',
            mes=10,
            dia=28,
            defaults={
                'escopo': 'nacional',
                'observacao': OBS_ANTIGA,
                'is_active': True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('projudi', '0023_feriado_dia_servidor_publico'),
    ]

    operations = [
        migrations.RunPython(transferir, reverter),
    ]
