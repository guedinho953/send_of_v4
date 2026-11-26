from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projudi', '0018_movimentacaorecord_data_movimentacao'),
    ]

    operations = [
        migrations.AddField(
            model_name='cumprimentorecord',
            name='evento_decisao',
            field=models.CharField(
                blank=True,
                help_text='Número do evento da decisão usado na certidão',
                max_length=20,
                verbose_name='Evento da Decisão',
            ),
        ),
    ]
