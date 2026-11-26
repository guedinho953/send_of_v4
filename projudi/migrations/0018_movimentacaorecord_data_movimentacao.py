from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projudi', '0017_origem_rag_movimentacao'),
    ]

    operations = [
        migrations.AddField(
            model_name='movimentacaorecord',
            name='data_movimentacao',
            field=models.DateField(
                blank=True,
                db_index=True,
                help_text=(
                    'Data mostrada na listagem de movimentações do Projudi'
                ),
                null=True,
                verbose_name='Data da Movimentação',
            ),
        ),
    ]
