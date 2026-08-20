"""Cria RAG #2571 'EXPEDIR MANDADO' — irmã de toggle da #2561 (suspensão do
indefiro/indeferimento, réu). Padrão do Ivan (2026-08-20): o mesmo fluxo em 2
variantes para usar conforme a conveniência:
  - #2561 (ativa): intimação eletrônica + fallback AR assinado + SOLICITAR mandado.
  - #2571 (inativa): intimação eletrônica + fallback AR assinado + EXPEDIR o
    mandado completo (fallback 'mandado' + modelo #9 com TEOR).

Ambas: polo reu_especifico, fluxo analisar + fluxo_fallback, assinar_ar true,
fallback_ar true, mandado_polo reu_especifico, subtipo 11, prazo 5 (15d? prazo 5).

Uso: source .venv/bin/activate && python criar_rag_suspensao_expedir_mandado.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()
from processes.models import Process, RAGExample
from base.utils import normalize_process_number

PROCESSO_FICTICIO = '9999999-99.2026.8.05.0191'
TENANT_ID = 1
# mesmo matching da #2561
ATO = (
    'DESPACHO - INDEFIRO O PEDIDO DE LEVANTAMENTO DA SUSPENSÃO - '
    'TEMAS REPETITIVOS - INTIMAÇÃO ELETRÔNICA + EXPEDIÇÃO DE MANDADO (réu)'
)
OBS_MATCH = (
    'Ante o exposto, INDEFIRO o pedido de levantamento da suspensão, devendo '
    'o feito permanecer suspenso até ulterior deliberação do Superior '
    'Tribunal de Justiça sobre os Temas Repetitivos. Intimem-se.'
)
SEQ = [{
    'polo': 'reu_especifico',
    'tipo': 'intimacao_eletronica',
    'fluxo': 'analisar',
    'fluxo_fallback': True,
    'codigo_mov': '581',
    'descricao_mov': 'Intimação',
    'observacao': (
        'Intime-se a parte promovida (réu) para ciência do indeferimento do '
        'pedido de levantamento da suspensão, permanecendo o feito suspenso '
        'até ulterior deliberação do STJ sobre os Temas Repetitivos n.º 1.328 '
        'e n.º 1.414. Expedição de mandado.'
    ),
    'prazo_intimacao': '5',
    'motivo_intimacao': '3',
    'fallback_ar': True,
    'assinar_ar': True,
    'fallback_polo': 'res',
    # EXPEDIR mandado completo (fallback 'mandado' + modelo #9 com TEOR)
    'fallback': 'mandado',
    'fallback_template_id': 9,
    'mandado_polo': 'reu_especifico',
    'mandado_subtipo': '11',
}]


def main():
    norm = normalize_process_number(PROCESSO_FICTICIO)
    proc, _ = Process.objects.get_or_create(
        number=PROCESSO_FICTICIO,
        defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
    existente = RAGExample.objects.filter(despacho_ato=ATO)
    if existente.exists():
        print(f'   ↦ #{existente.first().id} já existe — pulando.'); return
    rag = RAGExample.objects.create(
        tenant_id=TENANT_ID, process=proc, oficio='',
        despacho_ato=ATO, despacho_observacao=OBS_MATCH,
        despacho_data='', despacho_autor='', evento_despacho='',
        cumprimentos=[], documentos=[],
        sequencia_cumprimento=SEQ, active=False,
    )
    print(f'   ✅ #{rag.id} criado — EXPEDIR mandado (toggle da #2561)')
    print(json.dumps(SEQ, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
