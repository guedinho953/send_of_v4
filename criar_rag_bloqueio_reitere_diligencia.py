"""Cria RAGExample BLOQUEADORA (NÃO CUMPRIR) para despachos de reiteração:

    "DESPACHO¹
     Diante do informado no evento 226, reitere-se a diligência de evento 218."

Despachos desse tipo NÃO trazem comando novo de juntada/expedição — apenas
reiteram uma diligência anterior (cada processo tem evento diferente). Por isso
a RAG tem `sequencia_cumprimento` VAZIA = BLOQUEIO TOTAL (NÃO CUMPRIR):
  - `if rag and not rag.sequencia_cumprimento and melhor: BLOQUEADO; continue`
  - impede que RAGs abaixo no ranking (ex: catch-all de 'evento') expedam algo.
  - O registro cadastra o BLOQUEIO ANTES das RAGs que cumpririam.

Matching GENERALIZADO (remove os números de evento fixos 226/218):
  - despacho_ato: 'DESPACHO - REITERE-SE A DILIGÊNCIA'
  - despacho_observacao: "Diante do informado no evento, reitere-se a
    diligência de evento."  → casa com QUALQUER número de evento.

Uso:
  source .venv/bin/activate
  python criar_rag_bloqueio_reitere_diligencia.py
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

# ── FAMÍLIA de RAGs bloqueadoras "REITERE-SE <objeto>" ─────────────────────
# O recall do buscar_cumprimentos_similares exige >=2 tokens em comum, então
# a âncora ÚNICA "reitere"(1 token) é DESCARTADA. Solução mínima viável: 2
# tokens = "reitere-se" + o OBJETO da reiteração → jaccard 1.00 na sua variação
# e recall >=2. Nada de referência a evento (n° 226/218 / "no evento") — isso
# é ruído que onera busca/processamento. Uma RAG por objeto (não se sombreiam,
# porque cada uma tem token de objeto diferente).
OBJETOS_REITERACAO = [
    # (despacho_ato, texto de matching)
    ('REITERE-SE DILIGÊNCIA', 'Reitere-se a diligência.'),
    ('REITERE-SE OFÍCIO', 'Reitere-se o ofício.'),
    ('REITERE-SE INTIMAÇÃO', 'Reitere-se a intimação.'),
    ('REITERE-SE COMUNICAÇÃO', 'Reitere-se a comunicação.'),
]

# sequencia_cumprimento VAZIA = BLOQUEIO TOTAL (NÃO CUMPRIR)
SEQUENCIA_BLOQUEIO = []


def criar_bloqueio(ato, obs):
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
        # atualiza observação de matching (idempotente a texto novo)
        if r.despacho_observacao != obs:
            r.despacho_observacao = obs
            r.save(update_fields=['despacho_observacao'])
        print(f'   ↦ RAG bloqueadora #{r.id} já existente ({ato}) — atualizada.')
        _mostrar(r)
        return r

    rag = RAGExample.objects.create(
        tenant_id=TENANT_ID,
        process=proc,
        oficio='',
        despacho_ato=ato,
        despacho_observacao=obs,
        despacho_data='',
        despacho_autor='',
        evento_despacho='',
        cumprimentos=[],
        documentos=[],
        sequencia_cumprimento=SEQUENCIA_BLOQUEIO,  # [] → BLOQUEIO
        active=True,
    )
    print(f'   ✅ RAGExample bloqueadora #{rag.id} criado — NÃO CUMPRIR ({ato}).')
    _mostrar(rag)
    return rag


def _mostrar(rag):
    print()
    print(f'RAG #{rag.id}: {rag.despacho_ato}')
    print(f'  obs (matching): {rag.despacho_observacao}')
    print(f'  sequencia_cumprimento: {rag.sequencia_cumprimento!r}  → BLOQUEIO TOTAL')
    print()


if __name__ == '__main__':
    print('Criando família de RAGs bloqueadoras — REITERE-SE <objeto>\n')
    for ato, obs in OBJETOS_REITERACAO:
        criar_bloqueio(ato, obs)
