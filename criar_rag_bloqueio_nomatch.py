"""Cria RAGs BLOQUEADORAS (placeholders NÃO CUMPRIR) para os despachos pendentes
que vieram da sincronização do Projudi SEM match de RAG (CumprimentoRecord
status='pendente' e rag_example=None).

Cada bloqueador é um placeholder genérico (seq=[]) — o Ivan vai ajeitar depois
(trocando por uma RAG real de cumprimento). A cobertura é por TEXTO DISTINTO:
  #144/147/151/153/154/155 : 'Intimo a parte em 15 dias, intimação eletrônica
                              realizada em <data>, (nos termos do art. 5º CPC).'
  #146                     : 'Expedir notificação à parte.'
  #166                     : 'Intime a parte. Prazo de 10 dias.'

Generalização: remove data/nº de artigo fixos (ruído de matching). Mantém o
essencial (≥2 tokens). seq=[] = BLOQUEIO TOTAL.

Uso: source .venv/bin/activate && python criar_rag_bloqueio_nomatch.py
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

# (despacho_ato, texto de matching/-observação) — dedup por despacho_ato
BLOCKS = [
    ('INTIMAÇÃO ELETRÔNICA REALIZADA - INTIMO A PARTE EM 15 DIAS',
     'Intimo a parte em 15 dias, sendo a intimação eletrônica realizada.'),
    ('EXPEDIR NOTIFICAÇÃO',
     'Expedir notificação à parte.'),
    ('INTIMAR PARTE - PRAZO 10 DIAS',
     'Intime a parte. Prazo de 10 dias.'),
]


def criar(ato, obs):
    norm = normalize_process_number(PROCESSO_FICTICIO)
    proc, _ = Process.objects.get_or_create(
        number=PROCESSO_FICTICIO,
        defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
    if not proc.number_normalized:
        proc.number_normalized = norm
        proc.save(update_fields=['number_normalized'])

    existente = RAGExample.objects.filter(despacho_ato=ato)
    if existente.exists():
        r = existente.first()
        print(f'   ↦ bloqueadora #{r.id} já existe ({ato}) — pulando.')
        return r
    rag = RAGExample.objects.create(
        tenant_id=TENANT_ID, process=proc, oficio='',
        despacho_ato=ato, despacho_observacao=obs,
        despacho_data='', despacho_autor='', evento_despacho='',
        cumprimentos=[], documentos=[],
        sequencia_cumprimento=[], active=True)
    print(f'   ✅ bloqueadora #{rag.id} ({ato}) — seq=[] (BLOQUEIO)')
    return rag


def main():
    print('Criando RAGs bloqueadoras para os pendentes sem match\n')
    por_id = {}
    for ato, obs in BLOCKS:
        r = criar(ato, obs)
        por_id[r.id] = (ato, obs)
    print()
    for rid, (ato, obs) in por_id.items():
        print(f'#{rid}: {ato}\n      obs={obs}')


if __name__ == '__main__':
    main()
