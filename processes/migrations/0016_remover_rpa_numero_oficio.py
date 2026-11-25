import re

from django.db import migrations


def remover_rpa_numero(apps, schema_editor):
    """Troca o sufixo SEC/RPA por SEC nos modelos de ofício já cadastrados."""
    DocumentTemplate = apps.get_model('processes', 'DocumentTemplate')
    for template in DocumentTemplate.objects.filter(pk__in=[5, 7]):
        html = template.html_template or ''
        novo = re.sub(r'\bSEC\s*/\s*RPA\b', 'SEC', html, flags=re.I)
        if novo != html:
            template.html_template = novo
            template.save(update_fields=['html_template'])


class Migration(migrations.Migration):

    dependencies = [
        ('processes', '0015_ragexample_exigir_todas_frases_and_more'),
    ]

    operations = [
        migrations.RunPython(remover_rpa_numero, migrations.RunPython.noop),
    ]
