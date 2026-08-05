"""Valida o _melhor_match (decisão final, threshold 70% + template).

Simula o que o CumprimentoService.buscar_cumprimentos_pendentes faz após o
recall: recebe o texto real da movimentação, pega os similares e roda o
_melhor_match pra decidir. Verifica que a decisão não quebra nem com elevação
de palavras (observação longa = denominador maior).

Uso:
  source .venv/bin/activate
  python test_melhor_match.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.models import RAGExample, DocumentTemplate
from processes.movimentacoes_service import buscar_cumprimentos_similares
from projudi.cumprimento_service import CumprimentoService

templates = DocumentTemplate.objects.filter(active=True)
# Escolhe RAG com observação E template sugerido válido (caso real de expedição)
candidatos = [
    r for r in RAGExample.objects.filter(active=True, despacho_observacao__isnull=False)\
        .exclude(despacho_observacao='')
    if r.suggested_templates.filter(id__in=templates.values_list('id', flat=True)).exists()
]
rag = candidatos[0] if candidatos else None

print('=' * 68)
print('  VALIDAÇÃO _melhor_match (Threshold 70% + template)')
print('=' * 68)
if not rag:
    print('  Nenhum RAG com observação encontrado.')
    sys.exit(1)

texto_mov = rag.despacho_observacao
print(f'\nRAG alvo #{rag.id}: {rag.despacho_ato[:60]}')
print(f'Observação (len={len(texto_mov)}): {texto_mov.strip()[:90]}...')
print(f'Templates sugeridos: {list(rag.suggested_templates.values_list("id", flat=True))}')

service = CumprimentoService.__new__(CumprimentoService)  # sem init (não precisa sessão)
similares = buscar_cumprimentos_similares(texto_mov, top_k=10) or []
print(f'\nSimilares no recall: {len(similares)}')
for s in similares[:5]:
    print(f'   #{s["id"]} sim={s["similaridade"]} | {s["despacho_ato"][:50]}')

melhor, template, rag_certo = service._melhor_match(texto_mov, similares, templates)
print('\nResultado da DECISÃO (_melhor_match):')
if melhor:
    print(f'   ✅ Match: RAG #{melhor["id"]} -> template #{template.id} ({template.name})')
    print(f'      expectativa: RAG #{rag.id}. Casou {melhor["id"] == rag.id}')
else:
    print('   ❌ Nenhum match — verificar threshold/observação/template')

# ── Teste de robustez: só parte da observação (texto de movimentação parcial) ──
print('\n--- Robustez: movimentação com trecho da observação (80%) ---')
trecho = ' '.join(texto_mov.split()[-30:])
trecho_sim = buscar_cumprimentos_similares(trecho, top_k=10) or []
m2, t2, r2 = service._melhor_match(trecho, trecho_sim, templates)
if m2:
    print(f'   ✅ Trecho casa RAG #{m2["id"]} -> tpl #{t2.id}')
else:
    print('   ⚠️  Trecho curto não fechou os 70% (esperado se trecho for pequeno)')

print('\nConcluído.')