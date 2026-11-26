from django.db import migrations


def reclassificar_rag(apps, schema_editor):
    """RAG de despacho é análise de movimentação, não de petição."""
    MovimentacaoRecord = apps.get_model('projudi', 'MovimentacaoRecord')
    MovimentacaoRecord.objects.filter(
        rag_example__isnull=False
    ).update(origem='movimentacao')


class Migration(migrations.Migration):

    dependencies = [
        ('projudi', '0016_movimentacaorecord_origem'),
    ]

    operations = [
        migrations.RunPython(reclassificar_rag, migrations.RunPython.noop),
    ]
