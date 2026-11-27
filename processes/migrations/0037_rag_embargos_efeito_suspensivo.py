from django.db import migrations


ATO = (
    'CONVOLO DEPÓSITO EM PENHORA - EFEITO SUSPENSIVO EMBARGOS '
    '(ART. 525, §6º, CPC) - CERTIFIQUE-SE TEMPESTIVIDADE E SEGURANÇA '
    'DO JUÍZO - FONAJE 117 - INTIME-SE EMBARGADO - 15 DIAS'
)

OBSERVACAO = """Convolo o depósito judicial realizado no evento 80 em penhora.

Em vista da impugnação apresentada, a requerimento da parte executada, atribuo o efeito suspensivo aos embargos, na forma do art. 525, §6º, do CPC.

Certifique-se o cartório acerca da tempestividade dos embargos (art. 525, caput, do CPC) e a integral segurança do Juízo, devendo ser observado o valor executado e o valor depositado/penhorado (Enunciado n. 117 do FONAJE).

Se for o caso, intime-se o(a) embargado(a) na pessoa de seu advogado(a) ou, não o tendo, pessoalmente, para, querendo, no prazo de 15 (quinze) dias, apresentar manifestação acerca dos embargos à execução.

Decorrido o prazo, com ou sem manifestação, remetam-se os autos à contadoria para conferência das contas.

Com os cálculos, conceda-se vista às partes pelo prazo de 5 dias.

Após, voltem os autos conclusos para sentença (dos embargos à execução)."""

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


def criar_rag(apps, schema_editor):
    Tenant = apps.get_model('accounts', 'Tenant')
    Process = apps.get_model('processes', 'Process')
    DocumentTemplate = apps.get_model('processes', 'DocumentTemplate')
    RAGExample = apps.get_model('processes', 'RAGExample')

    tenant = Tenant.objects.order_by('id').first()
    if not tenant:
        return
    template = DocumentTemplate.objects.filter(
        name='Certidão de Impugnação/Embargos à Execução'
    ).first()
    if not template:
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


def remover_rag(apps, schema_editor):
    RAGExample = apps.get_model('processes', 'RAGExample')
    RAGExample.objects.filter(despacho_ato=ATO).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('processes', '0036_certidao_impugnacao_embargos'),
    ]

    operations = [
        migrations.RunPython(criar_rag, remover_rag),
    ]
