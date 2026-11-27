import re

from django.db import migrations


PADRAO = re.compile(r'font-size:\s*(\d+(?:\.\d+)?)pt')


def _ajustar(html, delta):
    def _sub(match):
        valor = max(1, float(match.group(1)) + delta)
        return f'font-size:{valor:g}pt'
    return PADRAO.sub(_sub, html or '')


def aumentar_fontes(apps, schema_editor):
    DocumentTemplate = apps.get_model('processes', 'DocumentTemplate')
    for template in DocumentTemplate.objects.filter(template_type='certidao'):
        novo = _ajustar(template.html_template, 2)
        if novo != (template.html_template or ''):
            template.html_template = novo
            template.save(update_fields=['html_template'])


def diminuir_fontes(apps, schema_editor):
    DocumentTemplate = apps.get_model('processes', 'DocumentTemplate')
    for template in DocumentTemplate.objects.filter(template_type='certidao'):
        novo = _ajustar(template.html_template, -2)
        if novo != (template.html_template or ''):
            template.html_template = novo
            template.save(update_fields=['html_template'])


class Migration(migrations.Migration):

    dependencies = [
        ('processes', '0037_rag_embargos_efeito_suspensivo'),
    ]

    operations = [
        migrations.RunPython(aumentar_fontes, diminuir_fontes),
    ]
