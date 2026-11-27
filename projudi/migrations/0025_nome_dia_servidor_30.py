from datetime import date

from django.db import migrations


NOME = 'Sem expediente forense — Dia do Servidor Público'
OBS = (
    'Sem expediente forense em razão do Dia do Servidor Público '
    '(30/10/2026).'
)


def padronizar(apps, schema_editor):
    Feriado = apps.get_model('projudi', 'Feriado')
    Feriado.objects.filter(
        tipo='unico',
        data=date(2026, 10, 30),
    ).update(nome=NOME, observacao=OBS, is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ('projudi', '0024_transfere_dia_servidor_30_outubro'),
    ]

    operations = [
        migrations.RunPython(padronizar, migrations.RunPython.noop),
    ]
