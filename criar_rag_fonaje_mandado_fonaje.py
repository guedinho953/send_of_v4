"""Cria RAGExample de SÓ EXPEDIÇÃO DE MANDADO p/ despacho FONAJE 142:

    "Conforme enunciado 142 do FONAJE, intimem-se o(a)(s) executado(a)(s)
     ... na pessoa de seu advogado(a) ... no prazo de 15 dias, apresentar
     manifestação/impugnação/embargos acerca do bloqueio/indisponibilidade
     efetivado(a) (SISBAJUD)."

Decisão: SÓ EXPEDIR o mandado (tipo 'mandado' + modelo #9 com TEOR), sem
passo de intimação eletrônica separado. Polo reu_especifico (parte passiva);
loop por destinatário expede 1 mandado por executado (single-select).

Uso:
  source .venv/bin/activate
  python criar_rag_fonaje_mandado_fonaje.py
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

DESPACHO_ATO = (
    'EXPEDIÇÃO DE MANDADO - FONAJE 142 - INTIME-SE O(A)(S) EXECUTADO(A)(S) '
    'NA PESSOA DE SEU ADVOGADO - EMBARGOS/MANIFESTAÇÃO ACERCA DO BLOQUEIO '
    '(SISBAJUD) - PRAZO 15 DIAS'
)

DESPACHO_OBSERVACAO = (
    "Conforme enunciado 142 do FONAJE, intimem-se o(a)(s) executado(a)(s) na "
    "pessoa de seu(sua) advogado(a) ou, não o tendo, pessoalmente, para, "
    "querendo, no prazo de 15 (quinze) dias, apresentar(em) "
    "manifestação/impugnação/embargos à execução acerca do(a) "
    "bloqueio/indisponibilidade efetivado(a), por meio eletrônico, renovando-se "
    "a ordem de bloqueio via SISBAJUD caso não haja depósito espontâneo."
)

SEQUENCIA = [
    {
        "tipo": "mandado",                 # SÓ expede o mandado (sem intimação eletrônica)
        "template_id": 9,                  # Modelo #9 — Mandado de Intimação com TEOR
        "polo": "reu_especifico",          # executado específico; fallback → todos os réus
        "subtipo": "11",                   # Citação/Penhora/Avaliação
        "observacao": (
            "Conforme enunciado 142 do FONAJE, intimem-se o(a)(s) executado(a)(s) "
            "na pessoa de seu advogado(a) ou, não o tendo, pessoalmente, para, "
            "querendo, no prazo de 15 (quinze) dias, apresentar(em) "
            "manifestação/impugnação/embargos à execução acerca do bloqueio "
            "efetivado (SISBAJUD). Expedição de mandado."
        ),
        "parte_na_observacao": False,
    }
]


def main():
    ato = DESPACHO_ATO
    existente = RAGExample.objects.filter(despacho_ato=ato).first()
    if existente:
        print(f'   ↦ RAG #{existente.id} já existente — atualizando.')
        existente.despacho_observacao = DESPACHO_OBSERVACAO
        existente.sequencia_cumprimento = SEQUENCIA
        existente.active = True
        existente.save(update_fields=['despacho_observacao',
                                      'sequencia_cumprimento', 'active'])
        return existente

    norm = normalize_process_number(PROCESSO_FICTICIO)
    proc, _ = Process.objects.get_or_create(
        number=PROCESSO_FICTICIO,
        defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
    if not proc.number_normalized:
        proc.number_normalized = norm
        proc.save(update_fields=['number_normalized'])

    rag = RAGExample.objects.create(
        tenant_id=TENANT_ID,
        process=proc,
        oficio='',
        despacho_ato=ato,
        despacho_observacao=DESPACHO_OBSERVACAO,
        despacho_data='',
        despacho_autor='',
        evento_despacho='',
        cumprimentos=[],
        documentos=[],
        sequencia_cumprimento=SEQUENCIA,
        active=True,
    )
    print(f'   ✅ RAGExample #{rag.id} criado')
    return rag


if __name__ == '__main__':
    r = main()
    print('RAG', r.id, ':', r.despacho_ato)
    print('  seq[0]:', json.dumps(r.sequencia_cumprimento[0], ensure_ascii=False))
