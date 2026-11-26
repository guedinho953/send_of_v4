from django.db import migrations, models


def classificar_origem(apps, schema_editor):
    MovimentacaoRecord = apps.get_model('projudi', 'MovimentacaoRecord')
    # Registros que já nasceram de análise de petição/RAG.
    MovimentacaoRecord.objects.filter(
        rag_example__isnull=False
    ).update(origem='peticao')
    # Certidão de recurso inominado é gerada pela fila de petições.
    MovimentacaoRecord.objects.filter(
        descricao_movimentacao='Certidão de Recurso Inominado'
    ).update(origem='peticao')


class Migration(migrations.Migration):

    dependencies = [
        ('projudi', '0015_oficiorecord_baixado_em'),
    ]

    operations = [
        migrations.AddField(
            model_name='movimentacaorecord',
            name='origem',
            field=models.CharField(
                choices=[
                    ('peticao', 'Petição'),
                    ('movimentacao', 'Movimentação'),
                    ('outro', 'Outro'),
                ],
                db_index=True,
                default='movimentacao',
                help_text=(
                    'Separa certidões/procedimentos de petições e de '
                    'movimentações'
                ),
                max_length=20,
                verbose_name='Origem',
            ),
        ),
        migrations.RunPython(classificar_origem, migrations.RunPython.noop),
    ]
