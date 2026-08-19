"""Cria RAGExample p/ a SENTENÇA DE EXECUÇÃO que:

  1. Declara EXTINTA a fase de execução de sentença (arts. 925 e 924, II,
     do CPC) pelo pagamento integral.
  2. Determina a TRANSFERÊNCIA DO CRÉDITO em favor da parte exequente
     (promovente) e da advogada, com valores separados.
  3. Condiciona o levantamento à certificação de procuração com poderes
     especiais p/ levantamento de valores depositados.
  4. Sem honorários (art. 55 Lei 9.099/95); custas pela executada c/ prazo
     de 15 dias (SCR / Ato Conjunto TJBA 14/2019).

AÇÃO da RAG (decisão do Ivan, 2026-08-19):
  - Sequência = INTIMAÇÃO ELETRÔNICA (Mov581 + intimação).
  - fallback = SOLICITAR EXPEDIÇÃO (quando a parte não tem domicílio
    eletrônico, solicita expedição — não confecciona mandado).
  - Polo: 'todos' na intimação; fallback_polo polo ativo (promovente/exequente).

Texto de matching genérico (sem R$ fixo), robusto a variações de valor.

Uso:
  source .venv/bin/activate
  python criar_rag_sentenca_execucao_transferencia.py
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
    'SENTENÇA DE EXECUÇÃO - EXTINTA A FASE DE EXECUÇÃO DE SENTENÇA '
    '(ARTS. 925 E 924, II, CPC) - TRANSFERÊNCIA DO CRÉDITO EM FAVOR DA '
    'PARTE EXEQUENTE - SEM HONORÁRIOS - CUSTAS PELA EXECUTADA'
)

# Matching global: a sentença pode variar valor/nome, mas repete as palavras
# estruturais chave.
DESPACHO_OBSERVACAO = (
    "SENTENÇA. o parte executada satisfez integralmente sua obrigação, "
    "conforme o comprovante de depósito bancário acostado aos autos, sem "
    "impugnação e com concordância da parte exequente. DECLARO extinta a "
    "fase de execução de sentença, nos termos dos arts. 925 e 924, II, do "
    "CPC. Após o trânsito em julgado, proceda-se a transferência do crédito "
    "em favor da parte exequente, sendo R$ valor em favor da parte "
    "promovente e R$ valor em favor da advogada da parte autora, devendo ser "
    "confeccionado em nome do Advogado(a), se for o caso, somente depois de "
    "certificar a existência nos autos de procuração com poderes especiais "
    "para levantamento de valores depositados em nome do exequente, "
    "arquivando-se em seguida. Sem honorários advocatícios, conforme art. 55 "
    "da Lei n.º 9.099/95. Custas da execução pela parte executada, com prazo "
    "de 15 dias para pagamento, sob pena de inscrição na dívida ativa, "
    "através do sistema SCR. P. R. I."
)

SEQUENCIA = [
    {
        "tipo": "intimacao_eletronica",
        "polo": "todos",                 # intimação eletrônica abrange todas as partes
        "fallback_polo": "autores",      # fallback foca no polo ativo (promovente/exequente)
        "fluxo": "analisar",
        "fluxo_fallback": True,
        "codigo_mov": "581",
        "descricao_mov": "Intimação",
        "fallback": "solicitar_expedicao",  # sem confecção de mandado
        "fallback_ar": True,                # último meio: AR digital
        "observacao": (
            "Intimem-se as partes da Sentença que declarou extinta a fase de "
            "execução de sentença (arts. 925 e 924, II, CPC), determinando a "
            "transferência do crédito em favor da parte exequente (promovente "
            "e advogada da parte autora), mediante certificação de procuração "
            "com poderes especiais para levantamento de valores depositados, "
            "arquivando-se em seguida. Sem honorários; custas pela parte "
            "executada no prazo de 15 dias, sob pena de inscrição na dívida "
            "ativa via sistema SCR."
        ),
    }
]


def main():
    ato = DESPACHO_ATO
    existente = RAGExample.objects.filter(despacho_ato=ato).first()
    if existente:
        print(f'   ↦ RAG #{existente.id} já existente — atualizando sequência.')
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
