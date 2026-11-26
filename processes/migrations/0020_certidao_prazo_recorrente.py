from django.db import migrations


NOME = 'Certidão de Prazo'

LINHA_ANTIGA = (
    '<tr><td><strong>PROMOVIDO(A)(S)</strong></td>'
    '<td>-</td><td>{{ parte }}</td></tr>'
)
LINHA_NOVA = (
    LINHA_ANTIGA
    + '\n'
    + '<tr><td><strong>RECORRENTE</strong></td>'
      '<td>-</td><td>{{ recorrente }}</td></tr>'
)

CORPO_ANTIGO = (
    'Certifico que, referente ao processo em epígrafe, '
    '{{ observacao_prazo }}'
)
CORPO_NOVO = (
    'Certifico que, referente ao processo em epígrafe, '
    '{% if recorrente %}tendo como recorrente '
    '<strong>{{ recorrente }}</strong>, {% endif %}'
    '{{ observacao_prazo }}'
)


def atualizar_template(apps, schema_editor):
    DocumentTemplate = apps.get_model('processes', 'DocumentTemplate')
    template = DocumentTemplate.objects.filter(name=NOME, active=True).first()
    if not template:
        return

    html = template.html_template or ''
    alterado = False

    if 'RECORRENTE' not in html and LINHA_ANTIGA in html:
        html = html.replace(LINHA_ANTIGA, LINHA_NOVA, 1)
        alterado = True

    if CORPO_ANTIGO in html:
        html = html.replace(CORPO_ANTIGO, CORPO_NOVO, 1)
        alterado = True

    if alterado:
        template.html_template = html
        template.save(update_fields=['html_template'])


class Migration(migrations.Migration):

    dependencies = [
        ('processes', '0019_oficio_20bpm_finalidade'),
    ]

    operations = [
        migrations.RunPython(atualizar_template, migrations.RunPython.noop),
    ]
