"""Cria RAGExample para o despacho:

    "Ante o exposto, INDEFIRO o pedido de levantamento da suspensão, devendo
     o feito permanecer suspenso até ulterior deliberação do Superior Tribunal
     de Justiça sobre os Temas Repetitivos n.º 1.328 e n.º 1.414. Intimem-se."

Caso RMC (cartão de crédito consignado) suspenso. A intimação é dirigida à
PARTE ESPECÍFICA = RÉU / parte promovida (a que pediu o levantamento da
suspensão), via INTIMAÇÃO ELETRÔNICA com fallback:
  - AR digital ASSINADO (quando a última comunicação da parte foi AR / sem DJEN)
  - Mandado / solicitação de expedição (fallback de destinatário por polo réu)

Comportamento desejado (Ivan):
  - A intimação eletrônica roda primeiro.
  - Se a parte RECEBEU a eletrônica → não precisa AR nem mandado.
  - AR/mandado só materializa para a parte que NÃO recebeu a eletrônica
    (sem domicílio eletrônico / DJEN) — comportamento natural do fallback.

Polo: reu_especifico → busca o réu específico; se não achar, cai para TODOS
os réus (pool/fallback res).

Uso:
  source .venv/bin/activate
  python criar_rag_suspensao_indefiro_reu.py
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

# Texto curto (título da movimentação) usado como âncora de matching.
DESPACHO_ATO = (
    'DESPACHO - INDEFIRO O PEDIDO DE LEVANTAMENTO DA SUSPENSÃO, PERMANECENDO '
    'O FEITO SUSPENSO ATÉ ULTERIOR DELIBERAÇÃO DO SUPERIOR TRIBUNAL DE '
    'JUSTIÇA SOBRE OS TEMAS REPETITIVOS'
)

# Observação de MATCHING com as palavras-chave estruturais (nomes/CNJ removidos
# para generalizar — regra do projeto: nome de parte NUNCA vai no JSON).
DESPACHO_OBSERVACAO = (
    "Ante o exposto, INDEFIRO o pedido de levantamento da suspensão, devendo "
    "o feito permanecer suspenso até ulterior deliberação do Superior "
    "Tribunal de Justiça sobre os Temas Repetitivos n.º 1.328 e n.º 1.414. "
    "Intimem-se."
)

# ── Sequência de cumprimento: INTIMAÇÃO ELETRÔNICA do réu específico,
#    com fallback AR assinado + solicitação de mandado. AR/mandado SÓ para a
#    parte que não recebeu a eletrônica (sem DJEN).
SEQUENCIA = [
    {
        "tipo": "intimacao_eletronica",
        "fluxo": "analisar",
        "fluxo_fallback": True,
        "codigo_mov": "581",
        "descricao_mov": "Intimação",
        "observacao": (
            "Intime-se a parte promovida (réu) para ciência do indeferimento "
            "do pedido de levantamento da suspensão, permanecendo o feito "
            "suspenso até ulterior deliberação do STJ sobre os Temas "
            "Repetitivos n.º 1.328 e n.º 1.414."
        ),
        "polo": "reu_especifico",      # réu específico (pediu o levantamento)
        "fallback_polo": "res",        # se não achar, TODOS os réus
        "motivo_intimacao": "3",       # Intimação
        "prazo_intimacao": "5",        # prazo padrão
        "fallback_ar": True,           # AR digital (só se não recebeu eletrônica)
        "assinar_ar": True,            # assina o AR automaticamente
        "solicitar_mandado": True,     # solicita expedição via Mov 581
        "mandado_polo": "reu_especifico",
        "mandado_subtipo": "11",       # Citação/Penhora/Avaliação
    },
]


def main():
    norm = normalize_process_number(PROCESSO_FICTICIO)
    proc, _ = Process.objects.get_or_create(
        number=PROCESSO_FICTICIO,
        defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
    if not proc.number_normalized:
        proc.number_normalized = norm
        proc.save(update_fields=['number_normalized'])

    existente = RAGExample.objects.filter(despacho_ato=DESPACHO_ATO)
    if existente.exists():
        r = existente.first()
        print(f'   ↦ RAG #{r.id} já existente — pulando (não duplica).')
        _mostrar(r)
        return r

    rag = RAGExample.objects.create(
        tenant_id=TENANT_ID,
        process=proc,
        oficio='',
        despacho_ato=DESPACHO_ATO,
        despacho_observacao=DESPACHO_OBSERVACAO,
        despacho_data='',
        despacho_autor='',
        evento_despacho='',
        cumprimentos=[],
        documentos=[],
        sequencia_cumprimento=SEQUENCIA,
        active=True,
    )
    print(f'   ✅ RAGExample #{rag.id} criado — suspensão indeferida (réu).')
    _mostrar(rag)
    return rag


def _mostrar(rag):
    print()
    print(f'RAG #{rag.id}: {rag.despacho_ato}')
    print(f'  obs: {rag.despacho_observacao}')
    if isinstance(rag.sequencia_cumprimento, list) and rag.sequencia_cumprimento:
        print(f'  passo[0]: {json.dumps(rag.sequencia_cumprimento[0], ensure_ascii=False, indent=2)}')
    print()


if __name__ == '__main__':
    main()
