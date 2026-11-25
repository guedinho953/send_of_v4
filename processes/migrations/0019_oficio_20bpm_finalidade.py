from django.db import migrations


NOME = 'Ofício 20º BPM — Apresentação de Policiais'

ANTIGO = (
    'O objetivo é participar da Audiência de Instrução e Julgamento '
    'designada para o dia <strong>{{ data_audiencia }}</strong>, '
    'referente ao processo de nº {{ processo }}.'
)

NOVO = (
    '<br><br><strong>FINALIDADE:</strong> {{ finalidade }} da Audiência '
    'de Instrução e Julgamento designada para o dia '
    '<strong>{{ data_audiencia }}</strong>, referente ao processo de nº '
    '{{ processo }}.'
)


def atualizar_template(apps, schema_editor):
    DocumentTemplate = apps.get_model('processes', 'DocumentTemplate')
    template = DocumentTemplate.objects.filter(name=NOME).first()
    if not template:
        return

    html = template.html_template or ''
    if ANTIGO in html:
        template.html_template = html.replace(ANTIGO, NOVO, 1)
        template.save(update_fields=['html_template'])


class Migration(migrations.Migration):

    dependencies = [
        ('processes', '0018_oficio_20bpm_email_copia'),
    ]

    operations = [
        migrations.RunPython(atualizar_template, migrations.RunPython.noop),
    ]
