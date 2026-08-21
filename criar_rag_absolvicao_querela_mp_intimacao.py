"""Cria RAGExamples (PAR toggle) p/ a SENTENÇA DE ABSOLVIÇÃO em QUEIXA-CRIME
(ação penal privada — calúnia, art. 138 CPB):

  1. JULGO IMPROCEDENTES os pedidos do querelante (parte AUTORA).
  2. ABSOLVO a querelada (parte RÉ / autora do fato) das reprimendas do
     art. 138 do CPB, nos termos do art. 386, inciso VII, do CPP — por não
     existir prova suficiente para condenação.
  3. Após trânsito em julgado: arquivem-se os autos com baixa na distribuição.
  4. Ciência ao Ministério Público.
  5. Intimem-se as partes.

AÇÃO (decisão do Ivan, PADRÃO TOGGLE):
  - Sequência = 2 passos: (a) VISTAS AO MP (Mov 493, ciência) e
    (b) INTIMAÇÃO ELETRÔNICA (Mov 581 + painel Autoras/Rés).
  - Intimação com fallback AR digital (Correios) + fallback de mandado.
  - POLO "todos" (intimem-se as partes) no painel e no fallback_polo.

Duas RAGs com o MESMO texto de matching (alternar `active` por conveniência):
  # A  EXPEDIR mandado:   fallback "mandado"  + fallback_template_id 9 (confeciona)
  # B  SOLICITAR mandado: fallback "solicitar_mandado" (só Mov581, sem confecção)
NÃO devem ficar as duas ativas simultaneamente para o MESMO fluxo sem critério
deixa uma ativa e a outra inativa (alternar conforme a vara/conveniência).

Uso:
  source .venv/bin/activate
  python criar_rag_absolvicao_querela_mp_intimacao.py
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
    'SENTENÇA - QUEIXA-CRIME (ART. 138 CPB - CALÚNIA) - JULGO IMPROCEDENTES '
    'OS PEDIDOS DO QUERELANTE - ABSOLVO A QUERELADA (ART. 386, VII, CPP) '
    'POR INSUFICIÊNCIA DE PROVAS - CIÊNCIA AO MP - INTIMEM-SE AS PARTES '
    '- ARQUIVAMENTO APÓS TRÂNSITO EM JULGADO'
)

# Texto de matching genérico (sem nome de parte) — espelha melhor o despacho real.
DESPACHO_OBSERVACAO = (
    "Ante o exposto, JULGO IMPROCEDENTES os pedidos do querelante, ao passo em "
    "que ABSOLVO a querelada das reprimendas do art. 138 do CPB, nos termos do "
    "art. 386, inciso VII, do CPP, visto que não existe prova suficiente para "
    "sua condenação. Após o trânsito em julgado da presente sentença e "
    "cumpridas as formalidades legais, arquivem-se os autos com baixa do "
    "processo na distribuição. Ciência ao Ministério Público. Intimem-se as "
    "partes."
)

# Passo 1 — VISTAS AO MP (Mov 493, ciência)
PASSO_MP = {
    "tipo": "vistas_mp",
    "fluxo": "analisar",
    "fluxo_fallback": True,
    "codigo_mov": "493",
    "observacao": (
        "Ciência ao Ministério Público da sentença que julgou improcedentes os "
        "pedidos do querelante e absolveu a querelada (art. 386, VII, CPP) por "
        "insuficiência de provas."
    ),
    "cod_nucleo_mp": "31",
    "tipo_parecer_mp": "6",
    "prazo_mp": "5",
    "promotor_mp": "SOSTENYS MARINHO BARRETO",
}

# Passo 2 — INTIMAÇÃO ELETRÔNICA das partes + fallbacks (AR e mandado)
def passo_intimacao(fallback, extra=None):
    passo = {
        "tipo": "intimacao_eletronica",
        "polo": "todos",                 # "Intimem-se as partes" → todas
        "fallback_polo": "todos",
        "fluxo": "analisar",
        "fluxo_fallback": True,
        "codigo_mov": "581",
        "descricao_mov": "Intimação",
        "motivo_intimacao": "3",
        "prazo_intimacao": "3",          # 10 dias (sentença p/ ciência)
        "fallback_ar": True,             # parte sem domicílio eletrônico → Correios c/ AR digital
        "assinar_ar": False,             # padrão seguro: deixa AR pendente p/ assinatura manual
        "fallback": fallback,            # "mandado" (expede) | "solicitar_mandado" (só Mov581)
        "observacao": (
            "Intimem-se as partes da sentença que julgou improcedentes os "
            "pedidos do querelante e absolveu a querelada das reprimendas do "
            "art. 138 do CPB, nos termos do art. 386, VII, CPP, por "
            "insuficiência de provas, com baixa do processo na distribuição "
            "após o trânsito em julgado."
        ),
    }
    if extra:
        passo.update(extra)
    return passo

# nº do "EXPEDIR mandado": confecciona o mandado completo via modelo #9 (TEOR).
SEQUENCIA_EXPEDIR = [
    PASSO_MP,
    passo_intimacao(
        "mandado",
        {"fallback_template_id": 9, "fallback_subtipo": "11",
         "fallback_prazo": "15"},
    ),
]

# nº de "SOLICITAR mandado": só Mov581 pedindo a expedição, sem confecção.
SEQUENCIA_SOLICITAR = [
    PASSO_MP,
    passo_intimacao("solicitar_mandado", None),
]


def criar_rag(seq, sufixo_nome, rotulo_ato, active=True):
    norm = normalize_process_number(PROCESSO_FICTICIO)
    proc, _ = Process.objects.get_or_create(
        number=PROCESSO_FICTICIO,
        defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
    if not proc.number_normalized:
        proc.number_normalized = norm
        proc.save(update_fields=['number_normalized'])

    ato = f'{DESPACHO_ATO} - {rotulo_ato}' if rotulo_ato else DESPACHO_ATO
    existente = RAGExample.objects.filter(despacho_ato=ato).first()
    if existente:
        print(f'   ↦ RAG #{existente.id} já existente — atualizando sequência.')
        existente.despacho_observacao = DESPACHO_OBSERVACAO
        existente.sequencia_cumprimento = seq
        existente.active = active
        existente.save(update_fields=['despacho_observacao',
                                      'sequencia_cumprimento', 'active'])
        return existente

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
        sequencia_cumprimento=seq,
        active=active,
    )
    print(f'   ✅ RAGExample #{rag.id} criado — {sufixo_nome}')
    return rag


def main():
    print('Criando RAGs — Absolvição em Queixa-Crime (MP + Intimação eletrônica)\n')
    print('─ [RAG A] EXPEDIR mandado (fallback=mandado, template 9):')
    r1 = criar_rag(SEQUENCIA_EXPEDIR, 'EXPEDIR mandado', 'EXPEDIR-MANDADO', active=True)
    print('─ [RAG B] SOLICITAR mandado (só Mov581, sem confecção):')
    r2 = criar_rag(SEQUENCIA_SOLICITAR, 'SOLICITAR mandado', 'SOLICITAR-MANDADO', active=False)
    print()
    for r in (r1, r2):
        print(f'RAG #{r.id} (active={r.active}): {r.despacho_ato}')
        print(f'  obs: {r.despacho_observacao[:90]}...')
        for i, p in enumerate(r.sequencia_cumprimento):
            print(f'  passo[{i}]: {json.dumps(p, ensure_ascii=False)}')
        print()


if __name__ == '__main__':
    main()
