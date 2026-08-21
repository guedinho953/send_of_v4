"""Cria RAGExamples (PAR toggle) p/ o despacho de INTIMAR PARTE EXEQUENTE
ESPECÍFICA acerca de despacho (citação/intimação da devedora/executada):

  "Intime-se a parte exequente [NOME] acerca do despacho de evento [N], pois
   foi intimada a devedora/executada."

AÇÃO (intimação eletrônica da parte EXEQUENTE — polo ativo/autor):
  - A parte a intimar é a EXEQUENTE (credor) = polo ATIVO.
  - painel Autoras (polo: autores); destinatário do mandado = autor_especifico.
  - Evento capturado DINAMICAMENTE via placeholder {{evento}} (o executor
    extrai o número real do despacho).
  - Fallback AR digital (Correios) + fallback de mandado.

Duas RAGs com o MESMO texto de matching (alternar `active`):
  # A  EXPEDIR mandado:  fallback "mandado"  + fallback_template_id 9
  # B  SOLICITAR mandado: fallback "solicitar_mandado" (só Mov581)

ATENÇÃO polo (2026-08): 'autor_especifico' NÃO é válido no PAINEL de
intimação (só Autoras/Rés). Aqui usamos polo: "autores" (painel Autoras) +
fallback_polo: "autor_especifico" (destinatário do mandado).

Uso:
  source .venv/bin/activate
  python criar_rag_intimar_exequente_especifico.py
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
    'DESPACHO - INTIME-SE A PARTE EXEQUENTE ACERCA DO DESPACHO (POIS FOI '
    'INTIMADA A DEVEDORA/EXECUTADA) - INTIMAÇÃO ELETRÔNICA - FALLBACK AR E '
    'MANDADO'
)

# Texto de matching genérico (nome e número do evento variam — usar {{evento}}).
DESPACHO_OBSERVACAO = (
    "Intime-se a parte exequente acerca do despacho de evento, pois foi "
    "intimada a devedora/executada."
)


def passo_intimacao(fallback, extra=None):
    passo = {
        "tipo": "intimacao_eletronica",
        "polo": "autores",               # parte exequente = polo ATIVO (autor)
        "fallback_polo": "autor_especifico",  # destinatário do mandado = exequente específico
        "fluxo": "analisar",
        "fluxo_fallback": True,
        "codigo_mov": "581",
        "descricao_mov": "Intimação",
        "motivo_intimacao": "3",
        "prazo_intimacao": "2",          # 5 dias (despacho p/ ciência)
        "fallback_ar": True,             # parte sem domicílio eletrônico → Correios c/ AR
        "assinar_ar": False,             # padrão seguro: AR pendente de assinatura manual
        "fallback": fallback,            # "mandado" (expede) | "solicitar_mandado" (só Mov581)
        # {{evento}} = número real do despacho (ex 136), substituído pelo executor.
        "observacao": (
            "Intime-se a parte exequente acerca do despacho de evento "
            "{{evento}}, pois foi intimada a devedora/executada."
        ),
        "parte_na_observacao": False,
    }
    if extra:
        passo.update(extra)
    return passo


SEQUENCIA_EXPEDIR = [
    passo_intimacao("mandado",
                    {"fallback_template_id": 9, "fallback_subtipo": "11",
                     "fallback_prazo": "15"}),
]
SEQUENCIA_SOLICITAR = [passo_intimacao("solicitar_mandado", None)]


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
    print('Criando RAGs — Intimar parte exequente específica (evento dinâmico)\n')
    print('─ [RAG A] EXPEDIR mandado (fallback=mandado, template 9):')
    r1 = criar_rag(SEQUENCIA_EXPEDIR, 'EXPEDIR mandado', 'EXPEDIR-MANDADO', active=True)
    print('─ [RAG B] SOLICITAR mandado (só Mov581):')
    r2 = criar_rag(SEQUENCIA_SOLICITAR, 'SOLICITAR mandado', 'SOLICITAR-MANDADO', active=False)
    print()
    for r in (r1, r2):
        print(f'RAG #{r.id} (active={r.active}): {r.despacho_ato}')
        for i, p in enumerate(r.sequencia_cumprimento):
            print(f'  passo[{i}]: {json.dumps(p, ensure_ascii=False)}')
        print()


if __name__ == '__main__':
    main()
