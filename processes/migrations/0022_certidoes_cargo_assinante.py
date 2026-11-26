from django.db import migrations


NOMES = (
    'Certidão de Prazo',
    'Certidão de Recurso Inominado',
)


def atualizar_cargo(apps, schema_editor):
    DocumentTemplate = apps.get_model('processes', 'DocumentTemplate')
    for nome in NOMES:
        template = DocumentTemplate.objects.filter(name=nome).first()
        if not template:
            continue
        html = template.html_template or ''
        if 'Servidor Secretaria 2' not in html:
            continue
        template.html_template = html.replace(
            'Servidor Secretaria 2', '{{ servidor_cargo }}'
        )
        template.save(update_fields=['html_template'])


class Migration(migrations.Migration):

    dependencies = [
        ('processes', '0021_certidao_recurso_inominado'),
    ]

    operations = [
        migrations.RunPython(atualizar_cargo, migrations.RunPython.noop),
    ]
