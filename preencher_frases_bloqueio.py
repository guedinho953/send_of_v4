"""Preenche frases_bloqueio nas RAGs de NÃO FAZER/NÃO CUMPRIR.
Desativa a duplicata 2536 e reativa as demais com frases determinísticas.
Uso: source .venv/bin/activate && export DJANGO_SETTINGS_MODULE=core.settings
     python3 preencher_frases_bloqueio.py
"""
import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
django.setup()
from processes.models import RAGExample

# Frases bloqueadoras determinísticas por RAG (extraídas das observações reais).
# Frases são normalizadas (minúsculas, sem acento) pelo normalizar_texto.
RAG_FRASES = {
    2444: ['certifique-se sobre a tempestividade', 'integral seguranca do juizo'],
    2450: ['certifique-se a secretaria sobre a tempestividade', 'integral seguranca do juizo'],
    2526: ['certifique-se sobre a procuração'],
    2527: ['atualize-se o endereco', 'remarque-se a audiencia'],
    2532: ['acordo firmado entre as partes nao chegou a ser homologado',
           'diligencias pendentes'],
    2535: ['concessao da tutela provisoria de urgencia', 'segredo de justica',
           'bloqueio de conta'],
    2537: ['desarquive-se sem custas', 'assistencia judiciaria gratuita'],
    2539: ['convole o deposito judicial em penhora', 'efeito suspensivo aos embargos'],
    2543: ['oficie-se ao juizo deprecado', 'devolucao da carta precatoria'],
    2544: ['carta precatoria acostada', 'certifique-se a secretaria se'],
}

# 2536 é cópia da 2535 — desativar (eliminar duplicata).
DUPLICATA = [2536]

# exigir_todas = True para casos que precisam de TODOS os sinais (liminar 2535)
EXIGIR_TODAS = {2535: True}

for rid, frases in RAG_FRASES.items():
    r = RAGExample.objects.get(id=rid)
    r.frases_bloqueio = frases
    r.exigir_todas_frases = EXIGIR_TODAS.get(rid, False)
    r.active = True
    r.save(update_fields=['frases_bloqueio', 'exigir_todas_frases', 'active'])
    mod = ' (AND - todas)' if EXIGIR_TODAS.get(rid) else ' (OR - qualquer)'
    print(f'  RAG {rid}: {len(frases)} frases{mod} | active=True')

for rid in DUPLICATA:
    r = RAGExample.objects.get(id=rid)
    r.active = False
    r.save(update_fields=['active'])
    print(f'  RAG {rid}: DUPLICATA desativada (active=False)')

print('\nConcluído.')
