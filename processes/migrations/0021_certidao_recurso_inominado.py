from django.db import migrations


NOME = 'Certidão de Recurso Inominado'

HTML = """
<div style="font-family:'Times New Roman',serif; font-size:12pt; max-width:750px; margin:0 auto;">
  <div style="text-align:center; margin-bottom:6px;">
    <div style="font-size:11pt; font-weight:bold; text-transform:uppercase;">Poder Judiciário do Estado da Bahia</div>
    <div style="font-size:11pt; font-weight:bold;">Tribunal de Justiça do Estado da Bahia</div>
    <div style="font-size:10pt; font-weight:bold;">2ª Vara do Sistema dos Juizados Especiais</div>
    <div style="font-size:10pt; font-weight:bold;">Paulo Afonso</div>
  </div>

  <hr style="border:0.5px solid #000; margin:4px 0;">

  <div style="font-size:9pt; text-align:center; margin:2px 0; line-height:1.2;">
    Rua das Caraibeiras, 420, Quadra 04 - 1º Andar, General Dutra - PAULO AFONSO<br>
    <strong>pafonso-2vsj@tjba.jus.br</strong> | Funcionamento: 13:00 às 19:00 | Tel.: (75)3281-8372
  </div>

  <hr style="border:0.5px solid #000; margin:4px 0;">

  <div style="font-size:12pt; font-weight:bold; text-align:center; margin:22px 0 24px;">
    CERTIDÃO DE RECURSO INOMINADO
  </div>

  <table style="width:100%; border-collapse:collapse; font-size:10pt; font-family:'Courier New',monospace; margin-bottom:22px;">
    <tr><td style="width:130px;"><strong>PROCESSO N.º</strong></td><td>-</td><td>{{ processo }}</td></tr>
    <tr><td><strong>RECORRENTE</strong></td><td>-</td><td>{{ recorrente }}</td></tr>
  </table>

  <div style="font-size:10pt; font-family:'Courier New',monospace; text-align:justify; text-indent:80px; line-height:1.5;">
    {{ texto_certidao }}
  </div>

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin-top:18px; text-align:justify; text-indent:80px;">
    O referido é verdade,<br>Dou fé.
  </div>

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:30px 0 6px; text-align:center;">
    <div style="margin-bottom:16px;">Paulo Afonso-BA, {{ data }}.</div>
    <strong>{{ servidor }}</strong><br>
    Servidor Secretaria 2<br>
    Documento Assinado Eletronicamente<sup>1</sup>
  </div>

  <div style="font-size:7pt; font-family:'Courier New',monospace; margin:10px 0 0; text-align:justify; line-height:1.2;">
    <sup>1</sup> Documento assinado eletronicamente conforme arts. 1º e 2º da Lei nº. 11.419/06, que dispõe sobre a informatização do processo digital. O documento pode ser acessado no endereço eletrônico https://projudi.tjba.jus.br/projudi/ sob o número acima epigrafado.
  </div>

  <div style="font-size:7pt; font-family:'Courier New',monospace; text-align:right; margin-top:16px; margin-bottom:24px;">
    {{ processo }}
  </div>
</div>
"""


def criar_template(apps, schema_editor):
    DocumentTemplate = apps.get_model('processes', 'DocumentTemplate')
    DocumentTemplate.objects.update_or_create(
        name=NOME,
        defaults={
            'template_type': 'certidao',
            'description': (
                'Certidão de recurso inominado — tempestividade, preparo '
                'ou gratuidade, com evento da intimação do recorrente.'
            ),
            'html_template': HTML,
            'active': True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('processes', '0020_certidao_prazo_recorrente'),
    ]

    operations = [
        migrations.RunPython(criar_template, migrations.RunPython.noop),
    ]
