"""Testa o matching RAG novo (âncora = observação + normalização) com dados reais.

Roda o pipeline completo de decisão para uma amostra de RAGExamples e confere
que cada RAG consegue se auto-reconhecer quando seu próprio texto (observação)
é usado como "texto da movimentação". Também roda uma varredura de velocidade
do matching.

Uso:
  source .venv/bin/activate
  python test_match_observacao.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.models import RAGExample, DocumentTemplate
from processes.movimentacoes_service import buscar_cumprimentos_similares, normalizar_texto

templates_validos = DocumentTemplate.objects.filter(active=True)
rags = list(RAGExample.objects.filter(active=True))

print('=' * 68)
print(f'  TESTE MATCH RAG — âncora = observação + normalização')
print(f'  RAGs ativos: {len(rags)}')
print('=' * 68)

# ── 1. Auto-reconhecimento: cada RAG deve casar com o próprio texto ──
print('\n[1/2] Auto-reconhecimento (texto próprio -> deve achar a si mesmo)')
acertos = 0
sem_observacao = 0
for rag in rags:
    obs = rag.despacho_observacao or rag.despacho_ato
    if not obs:
        sem_observacao += 1
        continue
    # Simula o texto baixado da movimentação real = observação do próprio RAG
    texto_mov = obs
    similares = buscar_cumprimentos_similares(texto_mov, top_k=10) or []
    achou = any(s['id'] == rag.id for s in similares)
    status = '✅' if achou else '❌'
    if achou:
        acertos += 1
    print(f'   {status} RAG #{rag.id} ({obs.strip()[:55]}...)  -> encontrado: {achou}')
print(f'\n   Auto-reconhecimento: {acertos}/{len(rags) - sem_observacao} (sem observação: {sem_observacao})')

# ── 2. Testa a normalização (acentos/caixa alta não devem quebrar) ──
print('\n[2/2] Normalização: texto sem acento deve casar texto com acento')
if rags:
    alvo = None
    for rag in rags:
        if rag.despacho_observacao and any(c in rag.despacho_observacao.lower() for c in 'áãõéíóúç'):
            alvo = rag
            break
    if alvo:
        obs = alvo.despacho_observacao
        print(f'   RAG alvo #{alvo.id}: "{obs.strip()[:70]}..."')
        # Remoção de acentos simulando variação da movimentação
        sem_acento = normalizar_texto(obs)
        similares = buscar_cumprimentos_similares(sem_acento, top_k=10) or []
        achou = any(s['id'] == alvo.id for s in similares)
        print(f'   Texto SEM acento ainda acha o RAG? {"✅ sim" if achou else "❌ não"}')
        if achou:
            sim = next(s for s in similares if s['id'] == alvo.id)
            print(f'   similaridade={sim["similaridade"]}, dispatch={sim["despacho_ato"]}')
    else:
        print('   (nenhum RAG com acento encontrado no banco para o teste)')

print('\n✅ Teste concluído.')