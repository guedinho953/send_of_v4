"""Valida que a RAG bloqueadora #2562 (reitere-se diligência) BLOQUEIA o despacho.

Reproduz o loop do executor (mandado-expedicao-polo-fallback #14):
  percorre similares em ordem de ranking; no primeiro candidato com
  sequencia_cumprimento — VAZIO = BLOQUEIO → melhora/rag+break → BLOQUEADO.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.movimentacoes_service import buscar_cumprimentos_similares
from processes.models import RAGExample

TEXTO_REAL = """DESPACHO¹

Diante do informado no evento 226, reitere-se a diligência de evento 218."""


def main():
    similares = buscar_cumprimentos_similares(TEXTO_REAL, top_k=20)
    print('─ Top candidatos (real) ─')
    for i, s in enumerate(similares[:10], 1):
        seq = RAGExample.objects.get(id=s['id']).sequencia_cumprimento
        tag = 'SEQ' if seq else 'BLOQUEIO'
        print(f'  {i}. #{s["id"]} jaccard={s.get("jaccard",0):.2f} sim={s.get("similaridade")} '
              f'[{tag}] {s["despacho_ato"][:60]}')

    # loop do executor
    bloqueado = False
    vencedor = None
    for s in similares:
        seq = RAGExample.objects.get(id=s['id']).sequencia_cumprimento
        if not seq:
            vencedor = s['id']
            bloqueado = True
            break

    print()
    if bloqueado:
        print(f'🚫 BLOQUEADO pela RAG #{vencedor} (sequencia_cumprimento vazia = NÃO CUMPRIR).')
        print('   Nenhuma expedição/juntada será feita automaticamente — correto para "reitere-se".')
    else:
        print(f'⚠️ NENHUMA RAG de bloqueio venceu (vencedor tenta cumprir = #{vencedor}).')
        print('   Se o despacho de "reitere-se a diligência" NÃO deve expedir nada, a #2562 precisa superar no ranking.')


if __name__ == '__main__':
    main()
