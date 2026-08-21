"""Cria RAGExample de BLOQUEIO (NÃO CUMPRIR) p/ o despacho de CONSULTA SOBRE
MOVIMENTAÇÃO DE CARTA PRECATÓRIA:

  "DESPACHO COM FORÇA DE MANDADO E OFÍCIO. Em atenção aos princípios da
   celeridade e economia processual, proceda-se à consulta acerca da
   movimentação da carta precatória junto ao Juízo deprecado. Caso seja
   verificado o regular andamento, aguarde-se a devolução. Em caso negativo,
   oficie-se ao Juízo deprecado, solicitando no prazo de 30 dias, a devolução
   da carta precatória expedida devidamente cumprida ou se for o caso,
   informação sobre o estado em que se encontra. Em caso de insucesso às
   diligências acima determinadas, conclusos."

NÃO há nada executável automaticamente (é consulta/aguardo/ofício condicional
feito pelo cartório) → BLOQUEIO via `frases_bloqueio`.

Frases robustas (substring — ver skill rag-bloqueio-configuracao-fallback-ar):
  ["consulta acerca da movimentacao", "aguarde-se a devolucao"] com
  `exigir_todas_frases=True` (AND) — são distintas desta variante (consulta +
  aguardo de devolução), curtas e imunes a vírgula/Hífen.

Distingue das irmãs: #2572/#2543 (ofício direto ao Juízo deprecado, sem o
passo de consulta) e #2573 (certificar cumprimento). Esta é a variante
"consulta primeiro, aguarda devolução".

Uso:
  source .venv/bin/activate
  python criar_rag_bloqueio_precatoria_consulta.py
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
    'NÃO CUMPRIR - CONSULTA SOBRE MOVIMENTAÇÃO DE CARTA PRECATÓRIA JUNTO AO '
    'JUÍZO DEPRECADO - AGUARDAR DEVOLUÇÃO / OFICIAR SE NEGATIVO / CONCLUSOS'
)

DESPACHO_OBSERVACAO = (
    "DESPACHO COM FORÇA DE MANDADO E OFÍCIO. Em atenção aos princípios da "
    "celeridade e economia processual, proceda-se à consulta acerca da "
    "movimentação da carta precatória junto ao Juízo deprecado. Caso seja "
    "verificado o regular andamento, aguarde-se a devolução. Em caso negativo, "
    "oficie-se ao Juízo deprecado, solicitando no prazo de 30 dias, a devolução "
    "da carta precatória expedida devidamente cumprida ou se for o caso, "
    "informação sobre o estado em que se encontra. Em caso de insucesso às "
    "diligências acima determinadas, conclusos."
)

# Frenas de BLOQUEIO: AND (exigir_todas_frases=True), curtas e imunes a variação.
FRASES_BLOQUEIO = ["consulta acerca da movimentacao", "aguarde-se a devolucao"]


def main():
    ato = DESPACHO_ATO
    existente = RAGExample.objects.filter(despacho_ato=ato).first()
    if existente:
        print(f'   ↦ RAG #{existente.id} já existente — atualizando.')
        existente.despacho_observacao = DESPACHO_OBSERVACAO
        existente.frases_bloqueio = FRASES_BLOQUEIO
        existente.exigir_todas_frases = True
        existente.sequencia_cumprimento = []
        existente.active = True
        existente.save(update_fields=['despacho_observacao', 'frases_bloqueio',
                                      'exigir_todas_frases',
                                      'sequencia_cumprimento', 'active'])
        r = existente
    else:
        norm = normalize_process_number(PROCESSO_FICTICIO)
        proc, _ = Process.objects.get_or_create(
            number=PROCESSO_FICTICIO,
            defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
        if not proc.number_normalized:
            proc.number_normalized = norm
            proc.save(update_fields=['number_normalized'])
        r = RAGExample.objects.create(
            tenant_id=TENANT_ID, process=proc, oficio='',
            despacho_ato=ato, despacho_observacao=DESPACHO_OBSERVACAO,
            despacho_data='', despacho_autor='', evento_despacho='',
            cumprimentos=[], documentos=[],
            sequencia_cumprimento=[],
            frases_bloqueio=FRASES_BLOQUEIO, exigir_todas_frases=True,
            active=True,
        )
        print(f'   ✅ RAGExample #{r.id} criado')

    print(f'BLOQUEIO #{r.id} (active={r.active}) exigir_todas={r.exigir_todas_frases}')
    print(f'  frases: {r.frases_bloqueio}')
    print(f'  ATO: {r.despacho_ato}')
    return r


if __name__ == '__main__':
    main()
