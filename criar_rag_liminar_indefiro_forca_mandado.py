"""Cria 3 RAGs TOGGLE para o despacho 'INDEFIRO liminar COM FORÇA DE MANDADO':

    DECISÃO COM FORÇA DE MANDADO¹
    o pedido de tutela de urgência tem natureza satisfativa, § 3º, do art. 300
    do CPC (perigo da irreversibilidade da medida).
    Desse modo, INDEFIRO O PEDIDO LIMINAR.
    Intimações necessárias, FICA VALENDO A PRESENTE COMO MANDADO. Cumpra-se com urgência.

3 modelos (alternar `active` conforme a conveniência):
  #1 (A) INTIMAÇÃO ELETRÔNICA + fallback AR  (assinar_ar true) — intimar as partes;
             se parte sem DJEN e última comunicação é AR → expede AR assinado.
  #2 (B) SOLICITAÇÃO de expedição de mandado (só Mov581, sem confecção).
  #3 (C) EXPEDIÇÃO de mandado completo (modelo #9, confeciona com TEOR).

Todas: polo reu_especifico, fluxo analisar+fluxo_fallback. Matching generalizado
(remove 'Cumpra-se com urgência'/numeração de prazos fixos).

Uso: source .venv/bin/activate && python criar_rag_liminar_indefiro_forca_mandado.py
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

OBS_MATCH = (
    'o pedido de tutela de urgência tem natureza satisfativa, § 3º, do art. 300 '
    'do CPC (perigo da irreversibilidade da medida). Desse modo, INDEFIRO O '
    'PEDIDO LIMINAR. Intimações necessárias, FICA VALENDO A PRESENTE COMO '
    'MANDADO. Cumpra-se com urgência.'
)

# (sufixo_ato, seq)
MODELOS = [
    ('INTIMACAO-ELETRONICA-AR', [{
        'polo': 'reu_especifico',
        'tipo': 'intimacao_eletronica',
        'fluxo': 'analisar', 'fluxo_fallback': True,
        'codigo_mov': '581', 'descricao_mov': 'Intimação',
        'observacao': ('Intimem-se as partes para ciência da Decisão (INDEFERIDO '
                       'o pedido Liminar), valendo a presente como mandado de '
                       'intimação. Cumpra-se com urgência.'),
        'prazo_intimacao': '3', 'motivo_intimacao': '3',
        'fallback_ar': True, 'assinar_ar': True,
    }]),
    ('SOLICITAR-EXPEDICAO', [{
        'polo': 'reu_especifico',
        'tipo': 'solicitar_expedicao',
        'fluxo': 'analisar', 'fluxo_fallback': True,
        'codigo_mov': '581',
        'descricao_mov': 'Solicitada a Expedicao de Mandado',
        'observacao': ('Solicitada a expedicao de mandado — decisão com força de '
                       'mandado (INDEFERIDO o pedido liminar, art. 300 CPC). '
                       'Cumpra-se com urgencia.'),
    }]),
    ('EXPEDICAO-MANDADO', [{
        'polo': 'reu_especifico',
        'tipo': 'mandado', 'subtipo': '11',
        'template_id': 9, 'fluxo': 'analisar', 'fluxo_fallback': True,
        'observacao': ('Intimem-se as partes para ciência da Decisão (INDEFERIDO '
                       'o pedido Liminar - art. 300 CPC), valendo a presente '
                       'decisão como mandado. Cumpra-se com urgência.'),
        'parte_na_observacao': False,
    }]),
]


def criar(sufixo, seq, active):
    norm = normalize_process_number(PROCESSO_FICTICIO)
    proc, _ = Process.objects.get_or_create(
        number=PROCESSO_FICTICIO,
        defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
    if not proc.number_normalized:
        proc.number_normalized = norm
        proc.save(update_fields=['number_normalized'])
    ato = (f'DECISÃO COM FORÇA DE MANDADO - INDEFIRO O PEDIDO LIMINAR (art. 300 '
           f'CPC) - {sufixo}')
    existente = RAGExample.objects.filter(despacho_ato=ato)
    if existente.exists():
        print(f'   ↦ #{existente.first().id} já existe ({sufixo}) — pulando.')
        return existente.first()
    rag = RAGExample.objects.create(
        tenant_id=TENANT_ID, process=proc, oficio='',
        despacho_ato=ato, despacho_observacao=OBS_MATCH,
        despacho_data='', despacho_autor='', evento_despacho='',
        cumprimentos=[], documentos=[], sequencia_cumprimento=seq,
        active=active,
    )
    print(f'   ✅ #{rag.id} criado — {sufixo} (active={active})')
    return rag


def main():
    print('Criando 3 modelos toggle — INDEFIRO liminar com força de mandado\n')
    # ativa só o modelo A (intimação+AR) por padrão
    resultados = []
    for i, (sufixo, seq) in enumerate(MODELOS, 1):
        ativo = (sufixo == 'INTIMACAO-ELETRONICA-AR')
        r = criar(sufixo, seq, ativo)
        resultados.append((r.id, sufixo, ativo))
    print('\nToggle (active):')
    for rid, sufixo, ativo in resultados:
        print(f'  #{rid} {sufixo} -> {"ATIVA" if ativo else "inativa"}')


if __name__ == '__main__':
    main()
