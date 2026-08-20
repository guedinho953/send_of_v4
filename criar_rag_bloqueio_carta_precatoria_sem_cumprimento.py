"""Cria RAG BLOQUEADORA (NÃO CUMPRIR) — despacho de carta precatória sem cumprimento:

    "DESPACHO¹
     Verifico que a carta precatória acostada ao evento 119, encontra-se sem
     cumprimento.
     Certifique-se a secretaria se o despacho de evento 115 foi cumprido.
     Em caso positivo, intime-se a parte exequente para manifestação no prazo
     de 5 dias."

BLOQUEIO: tem CONDICIONAL ("Em caso positivo, intime-se...") cuja resposta exige
que a secretaria CERTIFIQUE primeiramente se o despacho anterior foi cumprido.
NÃO automatizar. `sequencia_cumprimento = []`.

Matching generalizado (remove os nºs de evento 119/115 — ruído; mantém as
palavras-chave estruturais).

Uso: source .venv/bin/activate && python criar_rag_bloqueio_carta_precatoria_sem_cumprimento.py
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

ATO = (
    'DESPACHO - CARTA PRECATÓRIA SEM CUMPRIMENTO - CERTIFICAR CUMPRIMENTO '
    'DE DESPACHO ANTERIOR - NÃO CUMPRIR'
)
OBS_MATCH = (
    'Verifico que a carta precatória acostada ao evento encontra-se sem '
    'cumprimento. Certifique-se a secretaria se o despacho de evento foi '
    'cumprido. Em caso positivo, intime-se a parte exequente para manifestação '
    'no prazo de 5 dias.'
)


def main():
    norm = normalize_process_number(PROCESSO_FICTICIO)
    proc, _ = Process.objects.get_or_create(
        number=PROCESSO_FICTICIO,
        defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
    if not proc.number_normalized:
        proc.number_normalized = norm
        proc.save(update_fields=['number_normalized'])
    existente = RAGExample.objects.filter(despacho_ato=ATO)
    if existente.exists():
        print(f'   ↦ #{existente.first().id} já existe — pulando.'); return
    rag = RAGExample.objects.create(
        tenant_id=TENANT_ID, process=proc, oficio='',
        despacho_ato=ATO, despacho_observacao=OBS_MATCH,
        despacho_data='', despacho_autor='', evento_despacho='',
        cumprimentos=[], documentos=[],
        sequencia_cumprimento=[], active=True,
    )
    print(f'   ✅ #{rag.id} criado — BLOQUEIO (carta precatória sem cumprimento)')


if __name__ == '__main__':
    main()
