"""Cria RAGExample p/ SENTENÇA DE EMBARGOS DE DECLARAÇÃO REJEITADOS
(art. 1.022, CPC).

Comando: "P. R. intimando-se apenas a parte autora, por seu Advogado, e os
réus que foram citados."  ("Certificado o trânsito... executado... arquive-se"
é futuro/condicional → NÃO entra na sequência imediata.)

Sequência (1 passo `intimacao_eletronica`):
  - Intimação ELETRÔNICA das PARTES (polo todos: autora + réus);
  - Fallback AR (fallback_ar) e fallback SOLICITAÇÃO de mandado
    (fallback: solicitar_mandado).
Sem MP/ofício.

Uso:
  source .venv/bin/activate
  python criar_rag_embargos_declaracao_rejeitados.py
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
    'SENTENÇA - EMBARGOS DE DECLARAÇÃO REJEITADOS (ART. 1.022 CPC) - '
    'INTIMEM-SE APENAS PARTE AUTORA E RÉUS CITADOS'
)

# Âncora = texto real generalizado da sentença.
ANCHORA = (
    "Diante do exposto, ausentes os vícios do art. 1.022 do CPC, REJEITO os "
    "embargos declaratórios. Sem custas e honorários advocatícios, como "
    "determina o art. 55 da Lei n.º 9.099/95. Certificado o trânsito em "
    "julgado da sentença e, caso não seja requerida a execução no prazo de 5 "
    "dias, arquive-se, sem prejuízo de seu desarquivamento a pedido. "
    "P. R. intimando-se apenas a parte autora, por seu Advogado, e os réus "
    "que foram citados."
)

# Passo ÚNICO — intimação eletrônica das partes (autora + réus) com fallbacks
# AR + solicitação de mandado.
SEQUENCIA = [{
    "tipo": "intimacao_eletronica",
    "polo": "todos",                       # autora (advogado) + réus citados
    "fallback_polo": "todos",
    "fluxo": "movimentar",
    "fluxo_fallback": False,               # PADRÃO Ivan (não cai no genérico)
    "natureza": "civel",
    "codigo_mov": "581",
    "descricao_mov": "Intimação",
    "motivo_intimacao": "3",
    "prazo_intimacao": "3",                # 10 dias
    "tipo_intimacao": "geral",
    "fallback": "solicitar_mandado",       # sem DJEN → SOLICITA mandado
    "fallback_ar": True,                   # sem DJEN → expede AR (Correios)
    "assinar_ar": False,
    "expedir_ar": True,
    "observacao": (
        "Intimando-se apenas a parte autora, por seu advogado, e os réus que "
        "foram citados, da decisão que REJEITOU os embargos de declaração."
    ),
}]


def main():
    norm = normalize_process_number(PROCESSO_FICTICIO)
    proc, _ = Process.objects.get_or_create(
        number=PROCESSO_FICTICIO,
        defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
    if not proc.number_normalized:
        proc.number_normalized = norm
        proc.save(update_fields=['number_normalized'])

    rag = RAGExample.objects.filter(despacho_ato=ATO).first()
    if rag is None:
        rag = RAGExample.objects.create(
            tenant_id=TENANT_ID, process=proc, oficio='',
            despacho_ato=ATO, despacho_observacao=ANCHORA,
            despacho_data='', despacho_autor='', evento_despacho='',
            cumprimentos=[], documentos=[], sequencia_cumprimento=SEQUENCIA,
            active=True,
        )
        print(f'   ✅ RAGExample #{rag.id} criado (embargos rejeitados → intimação autora+réus)')
    else:
        rag.despacho_observacao = ANCHORA
        rag.sequencia_cumprimento = SEQUENCIA
        rag.active = True
        rag.save(update_fields=['despacho_observacao', 'sequencia_cumprimento', 'active'])
        print(f'   ↦ RAG #{rag.id} já existente — atualizado.')

    print(f'RAG #{rag.id} (active={rag.active}): {rag.despacho_ato}')
    print('SEQ:', json.dumps(rag.sequencia_cumprimento, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
