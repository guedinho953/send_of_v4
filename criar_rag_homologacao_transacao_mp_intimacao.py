"""Cria RAGExamples (PAR toggle) p/ a SENTENÇA DE HOMOLOGAÇÃO DE TRANSAÇÃO
(Juizado Especial — art. 22 + 55 Lei 9.099/95; art. 487, III, "b" CPC):

  1. HOMOLOGA, por sentença, a transação judicial/extrajudicial firmada entre
     as partes, surtindo seus legais e jurídicos efeitos.
  2. Extingue o processo com resolução de mérito (art. 487, III, "b", CPC),
     cancelando eventual audiência aprazada.
  3. Sem custas e honorários advocatícios (art. 55 da Lei 9.099/95).
  4. Trânsito em julgado imediato (art. 41 caput, Lei 9.099/95).
  5. Intime-se a parte EXECUTADA para pagar o débito executado no prazo de
     15 DIAS, sob pena de multa de 10% e consequente penhora.

AÇÃO (decisão do Ivan, PADRÃO TOGGLE):
  - Sequência = INTIMAÇÃO ELETRÔNICA da parte executada (polo passivo).
  - Prazo do painel = 15 dias (prazo_intimacao "4").
  - Fallback AR digital (Correios) + fallback de mandado.

Duas RAGs com o MESMO texto de matching (alternar `active` por conveniência):
  # A  EXPEDIR mandado:   fallback "mandado"  + fallback_template_id 9 (confeciona)
  # B  SOLICITAR mandado: fallback "solicitar_mandado" (só Mov581, sem confecção)

Polo: 'res' (parte executada = polo passivo). NÃO usar autor/exequente — quem
paga o débito é a executada.

Uso:
  source .venv/bin/activate
  python criar_rag_homologacao_transacao_mp_intimacao.py
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
    'SENTENÇA - HOMOLOGAÇÃO DE TRANSAÇÃO (ART. 487, III, "b", CPC - ART. 22 '
    'LEI 9.099/95) - EXTINÇÃO COM RESOLUÇÃO DE MÉRITO - SEM CUSTAS E '
    'HONORÁRIOS - TRÂNSITO EM JULGADO IMEDIATO - INTIME-SE A PARTE EXECUTADA '
    'A PAGAR O DÉBITO EM 15 DIAS'
)

# Texto de matching genérico — espelha o despacho real (valores/nomes variam).
DESPACHO_OBSERVACAO = (
    "SENTENÇA. Relatório dispensado, conforme art. 38 da Lei n.º 9.099/95. A "
    "conciliação obtida entre as partes do processo será reduzida a escrito e "
    "homologada pelo Juiz togado, mediante sentença com eficácia de título "
    "executivo, nos termos do art. 22 da Lei n.º 9.099/95. A transação "
    "judicial/extrajudicial firmada entre as partes decorreu do exercício da "
    "autonomia privada livre de vício de consentimento, sendo lícito e possível "
    "o objeto do acordo. Diante do exposto, HOMOLOGO, por sentença, a transação "
    "firmada pelas partes, para que surta seus legais e jurídicos efeitos, ao "
    "passo em que extingo o processo com resolução de mérito, nos termos do "
    "art. 487, III, b, do CPC, ficando cancelada eventual audiência aprazada. "
    "Sem custas e honorários advocatícios, como determina o art. 55 da Lei "
    "n.º 9.099/95. Intimem-se. Com o lançamento desta sentença o trânsito em "
    "julgado ocorre de imediato, nos termos do art. 41, caput, da Lei "
    "n.º 9.099/95. P.R.I. Certifique-se o trânsito em julgado desta sentença "
    "e, após, intime-se a parte executada para pagar o débito executado no "
    "prazo de 15 dias, sob pena de multa de 10% e consequente penhora."
)


# Passo — INTIMAÇÃO ELETRÔNICA da parte executada (polo passivo) + fallbacks
def passo_intimacao(fallback, extra=None):
    passo = {
        "tipo": "intimacao_eletronica",
        "polo": "res",                   # parte executada = polo passivo (quem paga)
        "fallback_polo": "res",
        "fluxo": "analisar",
        "fluxo_fallback": True,
        "codigo_mov": "581",
        "descricao_mov": "Intimação",
        "motivo_intimacao": "3",
        "prazo_intimacao": "4",          # 15 dias
        "fallback_ar": True,             # parte sem domicílio eletrônico → Correios c/ AR digital
        "assinar_ar": False,             # padrão seguro: AR pendente de assinatura manual
        "fallback": fallback,            # "mandado" (expede) | "solicitar_mandado" (só Mov581)
        "observacao": (
            "Intime-se a parte executada da sentença que homologou a transação "
            "firmada entre as partes, extinguindo o processo com resolução de "
            "mérito (art. 487, III, b, CPC), sem custas e honorários (art. 55 "
            "Lei 9.099/95), para pagar o débito executado no prazo de 15 dias, "
            "sob pena de multa de 10% e consequente penhora."
        ),
    }
    if extra:
        passo.update(extra)
    return passo


SEQUENCIA_EXPEDIR = [
    passo_intimacao(
        "mandado",
        {"fallback_template_id": 9, "fallback_subtipo": "11",
         "fallback_prazo": "15"},
    ),
]

SEQUENCIA_SOLICITAR = [
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
    print('Criando RAGs — Homologação de Transação (Intimação eletrônica + fallbacks)\n')
    print('─ [RAG A] EXPEDIR mandado (fallback=mandado, template 9):')
    r1 = criar_rag(SEQUENCIA_EXPEDIR, 'EXPEDIR mandado', 'EXPEDIR-MANDADO', active=True)
    print('─ [RAG B] SOLICITAR mandado (só Mov581, sem confecção):')
    r2 = criar_rag(SEQUENCIA_SOLICITAR, 'SOLICITAR mandado', 'SOLICITAR-MANDADO', active=False)
    print()
    for r in (r1, r2):
        print(f'RAG #{r.id} (active={r.active}): {r.despacho_ato}')
        for i, p in enumerate(r.sequencia_cumprimento):
            print(f'  passo[{i}]: {json.dumps(p, ensure_ascii=False)}')
        print()


if __name__ == '__main__':
    main()
