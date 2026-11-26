"""Cria RAGExample de inexistência de custas da execução.

Processo de referência: 0003822-20.2025.8.05.0191.
O RAG usa como âncora o despacho de extinção da fase de execução e
associa o template "Certidão de Inexistência de Custas da Execução".

Uso:
    source .venv/bin/activate
    python criar_rag_inexistencia_custas_0003822.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'

import django  # noqa: E402

django.setup()

from base.utils import normalize_process_number  # noqa: E402
from processes.models import DocumentTemplate, Process, RAGExample  # noqa: E402

PROCESSO = '0003822-20.2025.8.05.0191'
PROCESSO_URL = (
    'https://projudi.tjba.jus.br/projudi/listagens/'
    'DadosProcesso?numeroProcesso=41020254766562'
)
TENANT_ID = 1
TEMPLATE_NOME = 'Certidão de Inexistência de Custas da Execução'

ATO = 'EXTINÇÃO DA EXECUÇÃO — CUSTAS DA EXECUÇÃO (INEXISTÊNCIA)'

ANCHORA = """Relatório dispensado (art. 38 da Lei n.º 9.099/95). DECIDO:

Observo que a parte executada satisfez integralmente sua obrigação, conforme demonstra o comprovante de depósito bancário e a concordância da parte exequente ao solicitar o levantamento dando total quitação ou sem nada impugnar.

Diante do exposto, DECLARO a extinção da fase de execução de sentença, nos termos dos arts. 925 e 924, II, do CPC, visto a satisfação das obrigações pelo(a) devedor(a).

Expeça-se alvará em nome da parte exequente, já que a parte executada, ao realizar o depósito bancário do débito, expressou inegavelmente o desejo do cumprimento espontâneo do(a) sentença/acórdão, tratando-se, portanto, de liberação de quantia incontroversa, devendo o alvará ser expedido em nome do(a) Advogado(a), se for o caso, somente depois de certificar a existência nos autos de procuração com poderes especiais para levantamento de valores depositados em nome do(a) exequente.

Sem honorários advocatícios, conforme art. 55 da Lei n.º 9.099/95.

Custas da execução, se existirem, pela parte executada, nos termos do art. 55, parágrafo único, III, da Lei 9.099/95. Proceda-se no cálculo e na cobrança das custas, com prazo de 15 dias para pagamento, sob pena de inscrição na dívida ativa, através do sistema SCR, nos moldes do art. 4º do Ato Conjunto TJBA 14/2019. Após, arquive-se. P. R. I."""

SEQUENCIA = [{
    'tipo': 'movimentacao',
    'expede_certidao_prazo': True,
    'observacao_prazo': False,
    'decurso_prazo': False,
    'descricao_mov': TEMPLATE_NOME,
    'observacao': 'Certifique-se a inexistência de custas da execução.',
}]


def main():
    template = DocumentTemplate.objects.filter(
        name=TEMPLATE_NOME, active=True
    ).first()
    if not template:
        raise SystemExit(
            f'Template não encontrado: {TEMPLATE_NOME}. '
            'Rode as migrations antes.'
        )

    proc, created = Process.objects.get_or_create(
        number=PROCESSO,
        defaults={
            'number_normalized': normalize_process_number(PROCESSO),
            'tenant_id': TENANT_ID,
            'status': 'analyzing',
            'projudi_url': PROCESSO_URL,
        },
    )
    atualizar = []
    if not proc.number_normalized:
        proc.number_normalized = normalize_process_number(PROCESSO)
        atualizar.append('number_normalized')
    if not proc.projudi_url:
        proc.projudi_url = PROCESSO_URL
        atualizar.append('projudi_url')
    if atualizar:
        proc.save(update_fields=atualizar)

    rag = RAGExample.objects.filter(despacho_ato=ATO).first()
    if rag is None:
        rag = RAGExample.objects.create(
            tenant_id=TENANT_ID,
            process=proc,
            oficio='',
            despacho_ato=ATO,
            despacho_observacao=ANCHORA,
            despacho_data='',
            despacho_autor='',
            evento_despacho='',
            cumprimentos=[],
            documentos=[],
            sequencia_cumprimento=SEQUENCIA,
            active=True,
        )
        print(f'✅ RAGExample #{rag.id} criado.')
    else:
        rag.process = proc
        rag.despacho_observacao = ANCHORA
        rag.sequencia_cumprimento = SEQUENCIA
        rag.active = True
        rag.save(update_fields=[
            'process', 'despacho_observacao', 'sequencia_cumprimento',
            'active',
        ])
        print(f'↦ RAGExample #{rag.id} atualizado.')

    rag.suggested_templates.set([template])
    print(f'RAG #{rag.id}: {rag.despacho_ato}')
    print(f'Processo: {proc.number}')
    print(f'Template: {template.name} (id={template.id})')


if __name__ == '__main__':
    main()
