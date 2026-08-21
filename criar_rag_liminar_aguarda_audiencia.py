"""Cria RAGExamples (PAR toggle) p/ DECISÃO DE INDEFERIMENTO DE PEDIDOS
LIMINARES EM TUTELA DE URGÊNCIA (art. 300 CPC) c/ comando final
"Aguarde-se a audiência de conciliação aprazada. Intimem-se." (Juizado —
2ª VSJ Paulo Afonso).

De onde veio o padrão (sessão 2026-08-21, processo 41020263853435):
  A decisão real NÃO contém o boilerplate "intimem-se as partes para ciência
  ... valendo como mandado / cumpra-se com urgência" que está nas RAGs de
  liminar antigas (#2483/#2530/#2574/#2583) — por isso NENHUMA delas batia
  ≥70% na âncora `despacho_observacao`. O comando dela é indireto: depois de
  INDEFERIR OS PEDIDOS LIMINARES (art. 300 CPC, sem demonstração de
  probabilidade do direito / perigo de dano) "Aguarde-se a audiência de
  conciliação aprazada. Intimem-se."
  → ÂNCORA deve espelhar o TEXTO REAL generalizado (não boilerplate).

AÇÃO (decisão do Ivan, PADRÃO TOGGLE):
  - Sequência = INTIMAÇÃO ELETRÔNICA das partes (polo "todos").
  - Prazo do painel = 5 dias (prazo_intimacao "5"), motivo 3.
  - Duas RAGs com o MESMO texto de matching (alternar `active` por conveniência):
    # A  EXPEDIR mandado:   fallback "mandado"  + fallback AR digital (Correios)
    # B  SOLICITAR mandado: fallback "solicitar_mandado" (só Mov581, sem confecção)
  - ATIVA por padrão: a de SOLICITAÇÃO (B).

Uso:
  source .venv/bin/activate
  python criar_rag_liminar_aguarda_audiencia.py
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

# Título curto (palavras-chave do tipo de decisão). BASE ≠ é a chave de
# get_or_create → cada variante leva um sufixo de TOGGLE próprio.
ATO_BASE = (
    'DECISÃO - INDEFIRO OS PEDIDOS LIMINARES - TUTELA DE URGÊNCIA '
    '(art. 300 CPC) - AGUARDE-SE AUDIÊNCIA - INTIMEM-SE AS PARTES'
)
ATO_EXPEDIR = ATO_BASE + ' - EXPEDIR-MANDADO (AR)'
ATO_SOLICITAR = ATO_BASE + ' - SOLICITAR-MANDADO'

# Texto de matching — espelha o TEXTO REAL da decisão (generalizado; nomes,
# valores e endereços removidos). É a ÂNCORA do match via `despacho_observacao`.
DESPACHO_OBSERVACAO = (
    "DECISÃO  Para o deferimento da tutela de urgência, mister que existam "
    "elementos que evidenciem a probabilidade do direito e o perigo de dano ou "
    "risco ao resultado útil do processo, nos termos do art. 300 do CPC. "
    "Relata a parte autora, em síntese, ser irmã de vítima de acidente de "
    "trânsito que lhe causou graves lesões e prolongada internação hospitalar, "
    "e que, em razão da necessidade de acompanhamento, deixou de exercer "
    "atividade remunerada, suportando prejuízos patrimoniais e alegado dano "
    "moral reflexo. Requer a parte autora, em sede de tutela provisória de "
    "urgência, o pagamento mensal provisório a título de antecipação dos "
    "lucros cessantes, e a inserção de restrição de transferência sobre o "
    "veículo envolvido no acidente. Ausentes os requisitos do art. 300 do CPC, "
    "necessários à concessão das tutelas pretendidas, INDEFIRO OS PEDIDOS "
    "LIMINARES formulados pela parte autora, sem prejuízo de nova apreciação "
    "caso surjam elementos que modifiquem o quadro ora analisado. Aguarde-se a "
    "audiência de conciliação aprazada. Intimem-se."
)


def passo_intimacao(fallback, com_ar=False, extra=None):
    passo = {
        "tipo": "intimacao_eletronica",
        "polo": "todos",                 # partes autora e rés (ciência da decisão)
        "fallback_polo": "todos",
        "fluxo": "analisar",
        "fluxo_fallback": True,
        "codigo_mov": "581",
        "descricao_mov": "Intimação",
        "motivo_intimacao": "3",
        "prazo_intimacao": "5",          # 05 dias
        "fallback": fallback,            # "mandado" (expede c/ template) | "solicitar_mandado" (só Mov581)
        "observacao": (
            "Intimem-se as partes para ciência da Decisão (LIMINAR NÃO "
            "CONCEDIDA / INDEFERIDOS OS PEDIDOS LIMINARES)."
        ),
    }
    if com_ar:
        passo["fallback_ar"] = True
        passo["assinar_ar"] = False
        passo["expedir_ar"] = True
    if extra:
        passo.update(extra)
    return passo


SEQUENCIA_EXPEDIR = [passo_intimacao("mandado", com_ar=True)]
SEQUENCIA_SOLICITAR = [passo_intimacao("solicitar_mandado", com_ar=False)]


def _proc_ficticio():
    norm = normalize_process_number(PROCESSO_FICTICIO)
    proc, _ = Process.objects.get_or_create(
        number=PROCESSO_FICTICIO,
        defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
    if not proc.number_normalized:
        proc.number_normalized = norm
        proc.save(update_fields=['number_normalized'])
    return proc


def criar_rag(ato, seq, rotulo, active):
    """get_or_create por `despacho_ato`. Se o único RAG com o ato BASE (sem
    sufixo) existir, repurposa-o para o ato canônico (reconciliação p/ que a
    irmã que ainda tem ato base não fique órfã na 1ª execução)."""
    proc = _proc_ficticio()
    rag = RAGExample.objects.filter(despacho_ato=ato).first()
    if rag is None:
        base_existente = RAGExample.objects.filter(despacho_ato=ATO_BASE).first()
        if base_existente is not None:
            rag = base_existente
            print(f'   ↦ reconciliando RAG #{rag.id}: ato base → "{ato}"')
            rag.despacho_ato = ato
    if rag is not None:
        print(f'   ↦ RAG #{rag.id} já existente — atualizando sequência/âncora.')
        rag.despacho_observacao = DESPACHO_OBSERVACAO
        rag.despacho_data = '2026-08-21'
        rag.despacho_autor = 'MARTINHO FERRAZ DA NOBREGA JUNIOR'
        rag.sequencia_cumprimento = seq
        rag.active = active
        rag.save(update_fields=['despacho_ato', 'despacho_observacao',
                                'despacho_data', 'despacho_autor',
                                'sequencia_cumprimento', 'active'])
        return rag
    rag = RAGExample.objects.create(
        tenant_id=TENANT_ID,
        process=proc,
        oficio='',
        despacho_ato=ato,
        despacho_observacao=DESPACHO_OBSERVACAO,
        despacho_data='2026-08-21',
        despacho_autor='MARTINHO FERRAZ DA NOBREGA JUNIOR',
        evento_despacho='',
        cumprimentos=[],
        documentos=[],
        sequencia_cumprimento=seq,
        active=active,
    )
    print(f'   ✅ RAGExample #{rag.id} criado — {rotulo}')
    return rag


def main():
    print('Criando RAGs — Liminar NÃO concedida (Tutela de Urgência art. 300)\n')
    print('─ [RAG A] EXPEDIR mandado (fallback=mandado + AR):')
    r1 = criar_rag(ATO_EXPEDIR, SEQUENCIA_EXPEDIR, 'EXPEDIR mandado', active=False)
    print('─ [RAG B] SOLICITAR mandado (só Mov581 — ATIVA por padrão):')
    r2 = criar_rag(ATO_SOLICITAR, SEQUENCIA_SOLICITAR, 'SOLICITAR mandado', active=True)
    print()
    for r in (r1, r2):
        print(f'RAG #{r.id} (active={r.active}): {r.despacho_ato}')
        for i, p in enumerate(r.sequencia_cumprimento):
            print(f'  passo[{i}]: {json.dumps(p, ensure_ascii=False)}')
        print()
    print('Toggle: alternar `active` de A↔B no admin (nunca os dois ligados).')


if __name__ == '__main__':
    main()
