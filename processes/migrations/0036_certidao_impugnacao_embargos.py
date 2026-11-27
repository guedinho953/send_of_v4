from django.db import migrations


NOME = 'Certidão de Impugnação/Embargos à Execução'

HTML = """
<div style="font-family:'Times New Roman',serif; font-size:12pt; max-width:750px; margin:0 auto;">
  <div style="text-align:center; margin-bottom:6px;">
    <img src="https://projudi.tjba.jus.br/projudi/imagens/brasaoPetroBranco.jpg" style="width:80px; margin-bottom:4px;">
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

  <div style="font-size:12pt; font-weight:bold; text-align:center; margin:22px 0 30px;">
    CERTIDÃO DE IMPUGNAÇÃO/EMBARGOS À EXECUÇÃO
  </div>

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:0 0 24px;">
    <table style="width:100%; border-collapse:collapse;">
      <tr><td style="width:140px;"><strong>PROCESSO N.º</strong></td><td>-</td><td>{{ processo }}</td></tr>
    </table>
  </div>

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:0 0 18px; text-align:justify; text-indent:80px; line-height:1.45;">
    {{ observacao_prazo|linebreaksbr }}
  </div>

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:0 0 10px; text-align:justify; text-indent:80px;">
    O referido é verdade,<br>Dou fé.
  </div>

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:30px 0 6px; text-align:center;">
    <div style="margin-bottom:16px;">Paulo Afonso-BA, {{ data }}.</div>
    <strong>{{ servidor }}</strong><br>
    {{ servidor_cargo }}<br>
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

ATO = (
    'CERTIFIQUE-SE TEMPESTIVIDADE DOS EMBARGOS E SEGURANÇA DO JUÍZO '
    '- ART. 525 CPC - FONAJE 117 - INTIME-SE EMBARGADO - 15 DIAS'
)

OBSERVACAO = """Em vista da impugnação apresentada, certifique-se o cartório acerca da tempestividade dos embargos (art. 525, caput, do CPC) e a integral segurança do Juízo, devendo ser observado o valor executado e o valor depositado/penhorado (Enunciado n. 117 do FONAJE).

Se for o caso, intime-se o(a) embargado(a) na pessoa de seu advogado(a) ou, não o tendo, pessoalmente, para, querendo, no prazo de 15 (quinze) dias, apresentar manifestação acerca dos embargos à execução."""

SEQUENCIA = [
    {
        'tipo': 'movimentacao',
        'codigo_mov': '581',
        'descricao_mov': 'Certidão de Tempestividade e Segurança do Juízo',
        'observacao': (
            'Certifique-se a tempestividade dos embargos (art. 525, '
            'caput, do CPC) e a integral segurança do Juízo, observados '
            'o valor executado e o valor depositado/penhorado '
            '(Enunciado n. 117 do FONAJE). Se tempestivos, intime-se '
            'o(a) embargado(a) para manifestação em 15 dias.'
        ),
    },
]


def criar_modelo_e_rag(apps, schema_editor):
    Tenant = apps.get_model('accounts', 'Tenant')
    Process = apps.get_model('processes', 'Process')
    DocumentTemplate = apps.get_model('processes', 'DocumentTemplate')
    RAGExample = apps.get_model('processes', 'RAGExample')

    template, _ = DocumentTemplate.objects.update_or_create(
        name=NOME,
        defaults={
            'template_type': 'certidao',
            'description': (
                'Certidão de tempestividade da impugnação/embargos à '
                'execução e segurança do juízo (Enunciado 117 do FONAJE).'
            ),
            'html_template': HTML,
            'active': True,
        },
    )

    tenant = Tenant.objects.order_by('id').first()
    if not tenant:
        return
    processo, _ = Process.objects.update_or_create(
        number='9999999-99.2026.8.05.0191',
        defaults={
            'number_normalized': '99999999920268050191',
            'tenant': tenant,
            'status': 'analyzing',
        },
    )
    rag, _ = RAGExample.objects.update_or_create(
        process=processo,
        despacho_ato=ATO,
        defaults={
            'tenant': tenant,
            'despacho_observacao': OBSERVACAO,
            'despacho_data': '',
            'despacho_autor': '',
            'tipo_certidao': 'impugnacao_embargos_execucao',
            'tipo_conclusao': '18',
            'juiz_conclusao': '41201',
            'sequencia_cumprimento': SEQUENCIA,
            'active': True,
        },
    )
    rag.suggested_templates.add(template)


def remover_modelo_e_rag(apps, schema_editor):
    DocumentTemplate = apps.get_model('processes', 'DocumentTemplate')
    RAGExample = apps.get_model('processes', 'RAGExample')
    RAGExample.objects.filter(despacho_ato=ATO).delete()
    DocumentTemplate.objects.filter(name=NOME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('processes', '0035_certidao_decurso_debito_remanescente'),
    ]

    operations = [
        migrations.RunPython(criar_modelo_e_rag, remover_modelo_e_rag),
    ]
