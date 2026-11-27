from django.db import migrations


NOME_DECURSO = 'Certidão de Decurso de Prazo para Pagamento Voluntário'
NOME_BASE = 'Certidão de Prazo — Modelo Base'

EXECUTADO_ANTIGO = (
    '<strong>EXECUTADO(A)</strong> - {{ executado }}<br>'
)
EXECUTADO_NOVO = (
    '{% if executado %}<strong>EXECUTADO(A)</strong> - '
    '{{ executado }}<br>{% endif %}'
)

PARTE_ANTIGA = (
    '<strong>PARTE</strong> - {{ parte|default:"—" }}<br>'
)
PARTE_NOVA = (
    '{% if parte %}<strong>PARTE</strong> - {{ parte }}<br>{% endif %}'
)


def aplicar(apps, schema_editor):
    DocumentTemplate = apps.get_model('processes', 'DocumentTemplate')

    tpl = DocumentTemplate.objects.filter(name=NOME_DECURSO).first()
    if tpl:
        html = tpl.html_template or ''
        if EXECUTADO_ANTIGO in html and EXECUTADO_NOVO not in html:
            tpl.html_template = html.replace(
                EXECUTADO_ANTIGO, EXECUTADO_NOVO)
            tpl.save(update_fields=['html_template'])

    tpl = DocumentTemplate.objects.filter(name=NOME_BASE).first()
    if tpl:
        html = tpl.html_template or ''
        if PARTE_ANTIGA in html and PARTE_NOVA not in html:
            tpl.html_template = html.replace(PARTE_ANTIGA, PARTE_NOVA)
            tpl.save(update_fields=['html_template'])


def reverter(apps, schema_editor):
    DocumentTemplate = apps.get_model('processes', 'DocumentTemplate')

    tpl = DocumentTemplate.objects.filter(name=NOME_DECURSO).first()
    if tpl:
        html = tpl.html_template or ''
        if EXECUTADO_NOVO in html:
            tpl.html_template = html.replace(
                EXECUTADO_NOVO, EXECUTADO_ANTIGO)
            tpl.save(update_fields=['html_template'])

    tpl = DocumentTemplate.objects.filter(name=NOME_BASE).first()
    if tpl:
        html = tpl.html_template or ''
        if PARTE_NOVA in html:
            tpl.html_template = html.replace(PARTE_NOVA, PARTE_ANTIGA)
            tpl.save(update_fields=['html_template'])


class Migration(migrations.Migration):

    dependencies = [
        ('processes', '0028_certidao_prazo_modelo_base'),
    ]

    operations = [
        migrations.RunPython(aplicar, reverter),
    ]
