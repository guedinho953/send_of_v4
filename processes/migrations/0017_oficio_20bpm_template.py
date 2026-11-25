from django.db import migrations


NOME = 'Ofício 20º BPM — Apresentação de Policiais'

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
    Rua das Caraibeiras, 420, Quadra 04 - 1º Andar, General Dultra - PAULO AFONSO<br>
    <strong>pafonso-2vsj@tjba.jus.br</strong> | Funcionamento: 13:00 às 19:00 | Tel.: (75)3281-8372
  </div>

  <hr style="border:0.5px solid #000; margin:4px 0;">

  <div style="text-align:right; font-size:10pt; font-family:'Courier New',monospace; margin:8px 0;">
    <strong>Ofício nº {{ numero_documento }} - SEC</strong>
  </div>

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:4px 0;">
    <strong>Ref. ao Proc. nº {{ processo }}</strong>
  </div>

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:16px 0; text-align:left; line-height:1.4;">
    À Senhora<br>
    <strong>{{ destinatario_nome }}</strong><br>
    {{ destinatario_cargo }}<br>
    {{ destinatario_endereco }}<br>
    E-mail: <strong>{{ destinatario_email }}</strong>
  </div>

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:16px 0; text-align:justify; text-indent:80px;">
    Senhor Comandante,
  </div>

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:12px 0; text-align:justify; text-indent:80px; line-height:1.4;">
    De ordem do Excelentíssimo Juiz de Direito da 2ª Vara do Sistema dos Juizados Especiais da Comarca de Paulo Afonso, <strong>Dr. {{ juiz }}</strong>, sirvo-me do presente expediente para requisitar a Vossa Senhoria que seja apresentado(a) o(s) Policial(is) Militar(es), <strong>{{ policiais }}</strong>, neste Juízo, localizado no endereço supracitado, ou podendo comparecer, se desejar, no formato Telepresencial através do link: {{ link_audiencia }} - ingresse na sala INSERINDO O NÚMERO DO PROCESSO e a DATA DA AUDIÊNCIA. O objetivo é participar da Audiência de Instrução e Julgamento designada para o dia <strong>{{ data_audiencia }}</strong>, referente ao processo de nº {{ processo }}.
  </div>

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:24px 0 6px; text-align:left;">
    Atenciosamente,
  </div>

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:24px 0 6px; text-align:center;">
    <strong>{{ assinante_nome }}</strong><br>
    <strong>{{ assinante_cargo }}</strong>
  </div>

  <div style="font-size:7pt; font-family:'Courier New',monospace; text-align:center; margin:2px 0;">
    Documento assinado eletronicamente
  </div>

  <div style="font-size:7pt; font-family:'Courier New',monospace; margin:10px 0 0; text-align:justify; line-height:1.2;">
    <sup>1</sup> Documento assinado eletronicamente conforme arts. 1º e 2º da Lei nº. 11.419/06, que dispõe sobre a informatização do processo digital. O documento pode ser acessado no endereço eletrônico https://projudi.tjba.jus.br/projudi sob o número acima epigrafado.
  </div>

  <div style="font-size:7pt; font-family:'Courier New',monospace; text-align:right; margin-top:2px;">
    {{ processo }}
  </div>

  <div style="border:1px solid #000; padding:8px; margin-top:18px; font-size:9pt; font-family:'Courier New',monospace; line-height:1.5;">
    <strong>DESTINATÁRIO:</strong><br>
    20 BPM<br>
    Rua da Providência, S/N<br>
    BAIRRO: PERPETUO SOCORRO<br>
    48.603-100 - PAULO AFONSO/BA
  </div>
</div>
"""


def criar_template(apps, schema_editor):
    DocumentTemplate = apps.get_model('processes', 'DocumentTemplate')
    DocumentTemplate.objects.update_or_create(
        name=NOME,
        defaults={
            'template_type': 'oficio',
            'description': (
                'Ofício ao 20º BPM para apresentação de policiais '
                'militares/testemunhas em audiência.'
            ),
            'html_template': HTML,
            'active': True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('processes', '0016_remover_rpa_numero_oficio'),
    ]

    operations = [
        migrations.RunPython(criar_template, migrations.RunPython.noop),
    ]
