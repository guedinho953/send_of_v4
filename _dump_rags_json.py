"""Dump das RAGs ativas com sequencia_cumprimento para curadoria de referência JSON."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.models import RAGExample

rags = list(RAGExample.objects.filter(active=True))
com_seq = [r for r in rags if r.sequencia_cumprimento]

print(f'Total ativas: {len(rags)} |  Com sequencia_cumprimento: {len(com_seq)}')
print()

for r in sorted(com_seq, key=lambda x: x.id):
    print('=' * 90)
    print(f'RAG #{r.id}')
    print(f'  ato: {r.despacho_ato}')
    print(f'  obs: {r.despacho_observacao[:160]}')
    print(f'  seq JSON ({len(r.sequencia_cumprimento)} passo(s)):')
    print(json.dumps(r.sequencia_cumprimento, ensure_ascii=False, indent=2))
    print()
