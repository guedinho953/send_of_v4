from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('projudi', '0011_movimentacaorecord_codigo_movimentacao_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='movimentacaorecord',
            name='localizador',
            field=models.CharField(blank=True, max_length=20, verbose_name='Localizador',
                                   help_text='Código do localizador (ex: 1, 2, 3...)'),
        ),
        migrations.AddField(
            model_name='movimentacaorecord',
            name='tipo_localizador',
            field=models.CharField(blank=True, max_length=20, verbose_name='Tipo Localizador',
                                   help_text='Tipo de localizador (ex: 1=Cartório, 2=Físico...)'),
        ),
    ]
