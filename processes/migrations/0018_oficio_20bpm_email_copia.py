from django.db import migrations


NOME = 'Ofício 20º BPM — Apresentação de Policiais'


def atualizar_template(apps, schema_editor):
    DocumentTemplate = apps.get_model('processes', 'DocumentTemplate')
    template = DocumentTemplate.objects.filter(name=NOME).first()
    if not template:
        return

    html = template.html_template or ''
    antigo = 'E-mail: <strong>{{ destinatario_email }}</strong>'
    novo = (
        'E-mail: <strong>{{ destinatario_email }}</strong>'
        '{% if email_copia %}<br>C/c: <strong>{{ email_copia }}</strong>{% endif %}'
    )
    if antigo in html and 'email_copia' not in html:
        template.html_template = html.replace(antigo, novo, 1)
        template.save(update_fields=['html_template'])


class Migration(migrations.Migration):

    dependencies = [
        ('processes', '0017_oficio_20bpm_template'),
    ]

    operations = [
        migrations.RunPython(atualizar_template, migrations.RunPython.noop),
    ]
