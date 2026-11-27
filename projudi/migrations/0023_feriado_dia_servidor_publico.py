from django.db import migrations
from django.db.models import Q


NOME = 'Dia do Servidor Público'
OBSERVACAO = (
    'Dia do Servidor Público — sem expediente forense / ponto facultativo.'
)


def criar_feriado(apps, schema_editor):
    Tenant = apps.get_model('accounts', 'Tenant')
    Feriado = apps.get_model('projudi', 'Feriado')

    for tenant in Tenant.objects.all():
        ja_existe = Feriado.objects.filter(tenant=tenant).filter(
            Q(tipo='fixo', mes=10, dia=28)
            | Q(data__month=10, data__day=28)
        ).exists()
        if ja_existe:
            continue
        Feriado.objects.create(
            tenant=tenant,
            nome=NOME,
            tipo='fixo',
            mes=10,
            dia=28,
            escopo='nacional',
            observacao=OBSERVACAO,
            is_active=True,
        )


def remover_feriado(apps, schema_editor):
    Feriado = apps.get_model('projudi', 'Feriado')
    Feriado.objects.filter(
        nome=NOME,
        tipo='fixo',
        mes=10,
        dia=28,
        observacao=OBSERVACAO,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('projudi', '0022_feriado_consciencia_negra'),
    ]

    operations = [
        migrations.RunPython(criar_feriado, remover_feriado),
    ]
