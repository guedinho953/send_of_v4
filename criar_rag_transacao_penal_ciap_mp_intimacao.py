"""Cria RAGExample p/ SENTENÇA DE HOMOLOGAÇÃO DE TRANSAÇÃO PENAL (art. 76,
Lei 9.099/95). Ação combinada EM UMA ÚNICA MOVIMENTAÇÃO (passo
`intimacao_completa`, espelho da RAG #2438):

  - Intimação ELETRÔNICA DAS PARTES (polo todos);
  - VISTA ao MINISTÉRIO PÚBLICO (envia_mp, núcleo 31, tipo parecer 6);
  - OFÍCIO CIAP (solicitar_oficio + oficio_template_id 5);
  - fallback AR + fallback mandado, natureza criminal.

Sentença-alvo:
  "Vistos etc. ... Em conformidade com o art. 76 da Lei nº 9.099/95, HOMOLOGO
  por SENTENÇA, a transação realizada, condicionando seus efeitos ao
  cumprimento integral. Adote a Secretaria as providências necessárias junto
  ao CIAP e a parte transacionada. Com o cumprimento, certifique-se e conceda
  vista ao Ministério Público. Em caso de descumprimento, certifique-se e
  venham conclusos. P.R.I."

Uso:
  source .venv/bin/activate
  python criar_rag_transacao_penal_ciap_mp_intimacao.py
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
    'SENTENÇA - HOMOLOGAÇÃO DE TRANSAÇÃO PENAL (ART. 76 LEI 9.099/95) - '
    'CUMPRIMENTO JUNTO AO CIAP - VISTA AO MINISTÉRIO PÚBLICO - INTIMEM-SE '
    'AS PARTES'
)

# Âncora = texto real da sentença (generalizado).
ANCHORA = (
    "Vistos etc. Dispensado o relatório nos termos do § 3º, do art. 81, da "
    "Lei nº 9.099/95. Em conformidade com o art. 76 da Lei nº 9.099/95, "
    "HOMOLOGO por SENTENÇA, a transação realizada, condicionando seus efeitos "
    "ao cumprimento integral. Adote a Secretaria as providências necessárias "
    "junto ao CIAP e a parte transacionada. Com o cumprimento, certifique-se "
    "e conceda vista ao Ministério Público. Em caso de descumprimento, "
    "certifique-se e venham conclusos. P.R.I."
)

# Passo 1 — intimação da VÍTIMA (parte AUTORA) para ciência + vista ao MP
# (1 Concluir). Conforme #2438 (TP funciona): NÂO intimar o AUTOR DO FATO
# (réu/polo passivo) eletronicamente — em criminal o autor do fato É o réu, e
# a intimação da sentença de TP é dirigida à VÍTIMA. Se houver mandado → usar
# SOLICITAÇÃO de mandado (Mov581), não confecção completa.
PASSO_INTIMACAO = {
    "tipo": "intimacao_completa",
    "polo": "autor_especifico",            # VÍTIMA (parte autora)
    "fallback_polo": "autor_especifico",
    "fluxo": "analisar",
    "fluxo_fallback": False,               # PADRÃO Ivan
    "natureza": "criminal",
    "codigo_mov": "581",
    "descricao_mov": "Intimação",
    "motivo_intimacao": "3",
    "prazo_intimacao": "3",                # 10 dias
    "tipo_intimacao": "geral",
    "fallback": "solicitar_mandado",       # mandado → SOLICITAÇÃO (não expede mandado)
    "fallback_ar": True,
    "assinar_ar": False,
    "expedir_ar": True,
    "observacao": (
        "Intime-se a vítima (parte autora) para ciência da Sentença de "
        "Homologação de Transação Penal (art. 76 Lei 9.099/95)."
    ),
    # Vistas ao MP (numa única mov)
    "envia_mp": True,
    "cod_nucleo_mp": "31",
    "tipo_parecer_mp": "6",                # 6 = Ciência
    "prazo_mp": "5",                       # 30 dias
    "promotor_mp": "SOSTENYS MARINHO BARRETO",
}

# Passo 2 — OFÍCIO CIAP CONFEECCIONADO. Autor do fato vem EXCLUSIVAMENTE da
# ata (o executor `oficio` + template CIAP toma os autores_do_fato da ata —
# NÃO usa role). Resultado: expede para TODOS os autores do fato.
PASSO_OFICIO_CIAP = {
    "tipo": "oficio",
    "observacao": "Oficio CIAP - providencias junto ao CIAP (transacao penal)",
    "template_id": 5,
}

SEQUENCIA = [PASSO_INTIMACAO, PASSO_OFICIO_CIAP]


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
        print(f'   ✅ RAGExample #{rag.id} criado (transação penal → CIAP + MP + partes)')
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
