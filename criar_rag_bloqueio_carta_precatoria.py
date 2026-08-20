"""Cria RAG BLOQUEADORA (NÃO CUMPRIR) para o despacho COM FORÇA DE MANDADO E
OFÍCIO do Juízo deprecado (devolução de carta precatória):

    "DESPACHO COM FORÇA DE MANDADO E OFÍCIO¹
     Oficie-se ao Juízo deprecado, solicitando no prazo de 30 dias, a devolução
     da carta precatória expedida devidamente cumprida ou, se for o caso,
     informação sobre o estado em que se encontra.
     Em caso de insucesso às diligências acima determinadas, conclusos.
     Intime-se a parte promovente para diligenciar junto ao juízo deprecado.
     Em atenção aos princípios basilares da economia e celeridade processual,
     atribuo ao presente força de mandado de intimação e ofício."

BLOQUEIO: envolve ofício ao juízo deprecado + condicional ("Em caso de insucesso
... conclusos") — NÃO automatizar. `sequencia_cumprimento = []` = BLOQUEIO TOTAL.

Matching generalizado (remove o prazo fixo "30 dias" — ruído; mantém palavras-chave).

Uso: source .venv/bin/activate && python criar_rag_bloqueio_carta_precatoria.py
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
    'DESPACHO COM FORÇA DE MANDADO E OFÍCIO - OFÍCIO AO JUÍZO DEPRECADO - '
    'DEVOLUÇÃO DE CARTA PRECATÓRIA - NÃO CUMPRIR'
)
OBS_MATCH = (
    'Oficie-se ao Juízo deprecado, solicitando a devolução da carta precatória '
    'expedida devidamente cumprida ou, se for o caso, informação sobre o estado '
    'em que se encontra. Em caso de insucesso às diligências acima determinadas, '
    'conclusos. Intime-se a parte promovente para diligenciar junto ao juízo '
    'deprecado. Em atenção aos princípios basilares da economia e celeridade '
    'processual, atribuo ao presente força de mandado de intimação e ofício.'
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
    print(f'   ✅ #{rag.id} criado — BLOQUEIO (carta precatória / juízo deprecado)')


if __name__ == '__main__':
    main()
