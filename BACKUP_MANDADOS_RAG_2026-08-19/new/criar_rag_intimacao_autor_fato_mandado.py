"""Cria 2 RAGExamples para o despacho:

    "Diante do resultado da comunicação (evento 19), intime-se o autor do fato
     através de Oficial de Justiça, para comparecer à assentada."

Em processos criminais o "autor do fato" É o réu (polo passivo). A captura do
evento (ex: "19") é DINÂMICA via placeholder {{evento}}, que o executor
(_executar_sequencia_rapido) substitui extraindo o número do despacho real.

Duas RAGs (decisão de negócio — usar a adequada por vara/natureza):
  #1  Expedição de MANDADO completo (confecciona via Oficial de Justiça):
        tipo 'mandado', template_id=9 (Mandado de Intimação com TEOR).
  #2  Solicitação de EXPEDIÇÃO (só Mov581, sem confecção):
        tipo 'solicitar_expedicao', polo reu_especifico.

Polo: 'reu_especifico' → busca réu específico no polo passivo; se não achar,
cai para TODOS os réus (loop por destinatário).

Uso:
  source .venv/bin/activate
  python criar_rag_intimacao_autor_fato_mandado.py
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

# Texto genérico (sem número fixo) para o MATCHING robusto em qualquer evento.
DESPACHO_ATO = (
    'DESPACHO - DIANTE DO RESULTADO DA COMUNICAÇÃO, INTIME-SE O AUTOR DO FATO '
    'ATRAVÉS DE OFICIAL DE JUSTIÇA PARA COMPARECER À ASSENTADA'
)

# Observação de MATCHING com as palavras-chave estruturais (sem o número).
DESPACHO_OBSERVACAO = (
    "Diante do resultado da comunicação (evento), intime-se o autor do fato "
    "através de Oficial de Justiça, para comparecer à assentada."
)

# ── RAG #1: EXPEDIÇÃO de mandado completo (Oficial de Justiça) ──
SEQUENCIA_MANDADO = [
    {
        "tipo": "mandado",
        "template_id": 9,               # Modelo #9 — "Mandado de Intimação (com TEOR)"
        "polo": "reu_especifico",       # autor do fato = réu; fallback → todos os réus
        "subtipo": "11",                # Citação/Penhora/Avaliação (mandado)
        # {{evento}} = número real do despacho (ex "19"), substituído no executor.
        "observacao": (
            "Intime-se o autor do fato, atraves de Oficial de Justica, para "
            "comparecer a assentada, diante do resultado da comunicacao "
            "(evento {{evento}})."
        ),
        "parte_na_observacao": False,
    }
]

# ── RAG #2: SOLICITAÇÃO de expedição de mandado (só Mov581) ──
SEQUENCIA_SOLICITAR = [
    {
        "tipo": "solicitar_expedicao",
        "polo": "reu_especifico",       # autor do fato = réu; fallback → todos os réus
        "codigo_mov": "581",
        "descricao_mov": "Solicitada a Expedicao de Mandado",
        "observacao": (
            "Diante do resultado da comunicacao (evento {{evento}}), intime-se "
            "o autor do fato atraves de Oficial de Justica, para comparecer a "
            "assentada. Solicitada a expedicao de mandado para o autor do fato."
        ),
        "parte_na_observacao": False,
    }
]


def criar_rag(seq, sufixo_nome, rotulo_ato):
    norm = normalize_process_number(PROCESSO_FICTICIO)
    proc, _ = Process.objects.get_or_create(
        number=PROCESSO_FICTICIO,
        defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
    if not proc.number_normalized:
        proc.number_normalized = norm
        proc.save(update_fields=['number_normalized'])

    # Evita duplicar se já existir idêntico
    ato = f'{DESPACHO_ATO} - {rotulo_ato}' if rotulo_ato else DESPACHO_ATO
    existente = RAGExample.objects.filter(despacho_ato=ato)
    if existente.exists():
        r = existente.first()
        print(f'   ↦ RAG #{r.id} já existente — pulando.')
        return r

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
        active=True,
    )
    print(f'   ✅ RAGExample #{rag.id} criado — {sufixo_nome}')
    return rag


def main():
    print('Criando RAGs — Intimação do autor do fato (Oficial de Justiça, assentada)\n')
    print('─ [RAG #1] Expedição de mandado completo:')
    r1 = criar_rag(SEQUENCIA_MANDADO, 'Expedição de mandado (tipo=mandado, template 9)',
                   'EXPEDICAO-MANDADO')
    print('─ [RAG #2] Solicitação de expedição (só Mov581):')
    r2 = criar_rag(SEQUENCIA_SOLICITAR,
                   'Solicitação de expedição (tipo=solicitar_expedicao)',
                   'SOLICITAR-EXPEDICAO')
    print()
    for r in (r1, r2):
        print(f'RAG #{r.id}: {r.despacho_ato}')
        print(f'  obs: {r.despacho_observacao}')
        if isinstance(r.sequencia_cumprimento, list) and r.sequencia_cumprimento:
            print(f'  passo[0]: {json.dumps(r.sequencia_cumprimento[0], ensure_ascii=False)}')
        print()


if __name__ == '__main__':
    main()
