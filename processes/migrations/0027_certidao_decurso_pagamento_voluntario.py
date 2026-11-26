from django.db import migrations


NOME = 'Certidão de Decurso de Prazo para Pagamento Voluntário'

HTML = """
<div style="font-family:'Times New Roman',serif; font-size:12pt; max-width:750px; margin:0 auto;">
  <div style="text-align:center; margin-bottom:6px;">
    <img src="https://projudi.tjba.jus.br/projudi/imagens/brasaoPetroBranco.jpg"
         alt="Brasão TJBA" style="width:80px; margin-bottom:4px;">
    <div style="font-size:13pt; font-weight:bold; text-transform:uppercase;">
      Poder Judiciário do Estado da Bahia
    </div>
    <div style="font-size:13pt; font-weight:bold;">
      Tribunal de Justiça do Estado da Bahia
    </div>
    <div style="font-size:11pt; font-weight:bold;">
      2ª Vara do Sistema dos Juizados Especiais
    </div>
    <div style="font-size:11pt; font-weight:bold;">Paulo Afonso</div>
  </div>

  <hr style="border:0.5px solid #000; margin:4px 0;">

  <div style="font-size:10pt; text-align:center; line-height:1.2;">
    Rua das Caraibeiras, 420, Quadra 04 - 1º Andar, General Dutra - PAULO AFONSO<br>
    <strong>pafonso-2vsj@tjba.jus.br</strong> | Funcionamento: 13:00 às 19:00 |
    Tel.: (75)3281-8372
  </div>

  <hr style="border:0.5px solid #000; margin:4px 0;">

  <div style="font-size:15pt; font-weight:bold; text-align:center; margin:22px 0 24px;">
    CERTIDÃO DE DECURSO DE PRAZO PARA PAGAMENTO VOLUNTÁRIO
  </div>

  <table style="width:100%; border-collapse:collapse; font-size:11pt; font-family:'Courier New',monospace; margin-bottom:20px;">
    <tr><td style="width:160px;"><strong>PROCESSO N.º</strong></td><td>-</td><td>{{ processo }}</td></tr>
    <tr><td><strong>EXECUTADO(A)</strong></td><td>-</td><td>{{ executado }}</td></tr>
    <tr><td><strong>DESPACHO</strong></td><td>-</td><td>evento {{ evento_despacho }}</td></tr>
    <tr><td><strong>INTIMAÇÃO</strong></td><td>-</td><td>{{ data_intimacao }}</td></tr>
    <tr><td><strong>ÚLTIMO DIA</strong></td><td>-</td><td>{{ ultimo_dia }}</td></tr>
    <tr><td><strong>DECURSO</strong></td><td>-</td><td>{{ data_decurso }}</td></tr>
  </table>

  <div style="font-size:12pt; font-family:'Courier New',monospace; text-align:justify; text-indent:80px; line-height:1.5;">
    Certifico, para os devidos fins, que, nos autos do processo em epígrafe,
    o(a) executado(a) {{ executado }}, intimado(a) da decisão de evento
    {{ evento_despacho }}, que determinou o pagamento voluntário no prazo de
    15 (quinze) dias, não efetuou o pagamento no prazo, tendo o prazo
    decorrido em {{ data_decurso }}, conforme intimação realizada em
    {{ data_intimacao }}.
  </div>

  <div style="font-size:12pt; font-family:'Courier New',monospace; margin-top:18px; text-align:justify; text-indent:80px;">
    O referido é verdade. Dou fé.
  </div>

  <div style="font-size:12pt; font-family:'Courier New',monospace; margin:30px 0 6px; text-align:center;">
    <div style="margin-bottom:16px;">Paulo Afonso-BA, {{ data }}.</div>
    <strong>{{ servidor }}</strong><br>
    {{ servidor_cargo }}<br>
    Documento Assinado Eletronicamente<sup>1</sup>
  </div>

  <div style="font-size:8pt; font-family:'Courier New',monospace; margin:10px 0 0; text-align:justify; line-height:1.2;">
    <sup>1</sup> Documento assinado eletronicamente conforme arts. 1º e 2º da
    Lei nº. 11.419/06, que dispõe sobre a informatização do processo digital.
    O documento pode ser acessado no endereço eletrônico
    https://projudi.tjba.jus.br/projudi/ sob o número acima epigrafado.
  </div>

  <div style="font-size:8pt; font-family:'Courier New',monospace; text-align:right; margin-top:16px; margin-bottom:24px;">
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
                'Certidão de decurso do prazo de 15 dias para pagamento '
                'voluntário, contado da intimação do despacho de '
                'cumprimento de sentença/execução.'
            ),
            'html_template': HTML,
            'active': True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('processes', '0026_certidao_inexistencia_evento_decisao'),
    ]

    operations = [
        migrations.RunPython(criar_template, migrations.RunPython.noop),
    ]
