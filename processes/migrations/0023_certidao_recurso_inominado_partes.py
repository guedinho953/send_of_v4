from django.db import migrations


NOME = 'Certidão de Recurso Inominado (COJE)'
ANTIGO = (
    '<tr><td><strong>PARA</strong></td><td>-</td>'
    '<td>{{ parte }}</td></tr>'
)
NOVO = (
    '{% if parte %}<tr><td><strong>PARA</strong></td><td>-</td>'
    '<td>{{ parte }}</td></tr>{% endif %}'
)


def aplicar(apps, schema_editor):
    DocumentTemplate = apps.get_model('processes', 'DocumentTemplate')
    tpl = DocumentTemplate.objects.filter(name=NOME).first()
    if not tpl:
        return
    html = tpl.html_template or ''
    if ANTIGO in html and NOVO not in html:
        tpl.html_template = html.replace(ANTIGO, NOVO)
        tpl.save(update_fields=['html_template'])


def reverter(apps, schema_editor):
    DocumentTemplate = apps.get_model('processes', 'DocumentTemplate')
    tpl = DocumentTemplate.objects.filter(name=NOME).first()
    if not tpl:
        return
    html = tpl.html_template or ''
    if NOVO in html:
        tpl.html_template = html.replace(NOVO, ANTIGO)
        tpl.save(update_fields=['html_template'])


class Migration(migrations.Migration):

    dependencies = [
        ('processes', '0022_certidao_recurso_inominado'),
    ]

    operations = [
        migrations.RunPython(aplicar, reverter),
    ]
