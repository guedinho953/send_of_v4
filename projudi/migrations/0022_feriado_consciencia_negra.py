from django.db import migrations
from django.db.models import Q


NOME = 'Dia da Consciência Negra'
OBSERVACAO = 'Feriado nacional — sem expediente forense (20/11).'


def criar_feriado(apps, schema_editor):
    Tenant = apps.get_model('accounts', 'Tenant')
    Feriado = apps.get_model('projudi', 'Feriado')

    for tenant in Tenant.objects.all():
        # Já pode existir como feriado fixo (seed de feriados nacionais)
        # ou como data única cadastrada manualmente. Nesse caso não cria
        # duplicata no calendário.
        ja_existe = Feriado.objects.filter(tenant=tenant).filter(
            Q(tipo='fixo', mes=11, dia=20)
            | Q(data__month=11, data__day=20)
        ).exists()
        if ja_existe:
            continue
        Feriado.objects.create(
            tenant=tenant,
            nome=NOME,
            tipo='fixo',
            mes=11,
            dia=20,
            escopo='nacional',
            observacao=OBSERVACAO,
            is_active=True,
        )


def remover_feriado(apps, schema_editor):
    Feriado = apps.get_model('projudi', 'Feriado')
    Feriado.objects.filter(
        nome=NOME,
        tipo='fixo',
        mes=11,
        dia=20,
        observacao=OBSERVACAO,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('projudi', '0021_feriado_cnj_novembro_2026'),
    ]

    operations = [
        migrations.RunPython(criar_feriado, remover_feriado),
    ]
