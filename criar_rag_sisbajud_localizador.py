"""Cria RAGExample p/ o DESPACHO de PENHORA VIA LOCALIZADOR SISBAJUD
(art. 854 CPC — busca de ativos financeiros do devedor):

  "Sigam os autos ao localizador SISBAJUD para penhora de bens do devedor,
   tantos quantos bastem para a garantia da execução, conforme requerido pela
   parte exequente junto ao evento processual n. 70.
   Na forma do parágrafo único do art. 854 do CPC, a ordem que determina a
   busca de ativos financeiros do devedor deverá ser realizada independente
   de intimação da parte requerida."

AÇÃO (uma movimentação só): alterar o LOCALIZADOR para SISBAJUD (código 22614)
— NÃO expede mandado, NÃO intima (o próprio despacho diz que dispensa
intimação). tipo: localizar.

Observação curta no padrão do fluxo: "Ao loc 1" (SISBAJUD = localizador 1).

Uso:
  source .venv/bin/activate
  python criar_rag_sisbajud_localizador.py
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
    'DESPACHO - SIGAM OS AUTOS AO LOCALIZADOR SISBAJUD PARA PENHORA DE BENS '
    'DO DEVEDOR, TANTOS QUANTOS BASTEM PARA A GARANTIA DA EXECUÇÃO - BUSCA DE '
    'ATIVOS FINANCEIROS (ART. 854 CPC) - INDEPENDENTE DE INTIMAÇÃO DA PARTE '
    'REQUERIDA'
)

# Texto de matching genérico (o número do evento varia — não fixar).
DESPACHO_OBSERVACAO = (
    "DESPACHO. Sigam os autos ao localizador SISBAJUD para penhora de bens do "
    "devedor, tantos quantos bastem para a garantia da execução, conforme "
    "requerido pela parte exequente junto ao evento processual. Saliente-se "
    "que, na forma do parágrafo único do art. 854 do CPC, a ordem que "
    "determina a busca de ativos financeiros do devedor deverá ser realizada "
    "independente de intimação da parte requerida."
)

# Localizador SISBAJUD: código 22614. Ação = só alterar o localizador (581).
SEQUENCIA = [
    {
        "tipo": "localizar",
        "fluxo": "analisar",
        "fluxo_fallback": True,
        "codigo_mov": "581",
        "descricao_mov": "CUMPRIMENTO",
        "tipo_documento": "CUMPRIMENTO",
        "tipo_localizador": "22614",   # SISBAJUD
        "localizador": "",
        "observacao": "Ao loc 1",      # padrão curto do fluxo (SISBAJUD = loc 1)
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
        print('RAG', existente.id, ':', existente.despacho_ato)
        print('  seq[0]:', json.dumps(existente.sequencia_cumprimento[0],
                                      ensure_ascii=False, indent=2))
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
    print('RAG', rag.id, ':', rag.despacho_ato)
    print('  seq[0]:', json.dumps(rag.sequencia_cumprimento[0],
                                  ensure_ascii=False, indent=2))
    return rag


if __name__ == '__main__':
    main()
