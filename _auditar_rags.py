"""Auditoria (somente análise) das RAGs ativas, usando as pitfalls conhecidas do
executor (expedir_rapido / cumprimento_service / rag_router).

Checagens:
  A. fallback com TYPO "solicitar_expecidao" (correto: solicitar_expedicao)
  B. polo/fallback_polo/mandado_polo FORA do vocabulário do executor
     (atribuição: autores, autoras, promoventes, exequentes, autor_especifico,
      res, reus, executados, promovidos, reu_especifico, todos, ambos)
  C. fluxo:analisar SEM fluxo_fallback=true  → risco "cumprido sem ação"
  D. placeholder {{...}} num passo cujo tipo NÃO é (mandado|solicitar_expedicao)
     → fica LITERAL na obs da movimentação
  E. nao_concluir:true  → modo teste deixado ligado (não conclui de verdade!)
  F. duplicatas prováveis (mesmo despacho_ato em várias RAGs)
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()
from processes.models import RAGExample

VOCAB_POLO = {'autores','autoras','promoventes','exequentes','exequente',
              'autor_especifico','autora_especifico','res','reus','executados',
              'promovidos','reu_especifico','todos','ambos'}
TIPOS_SUBSTITUEM_EVENTO = {'mandado','solicitar_expedicao'}
PADRAO_TYPO = 'expecidao'
import re
PH = re.compile(r'\{\{\s*[\w]+\s*\}\}')

rags = list(RAGExample.objects.filter(active=True))
com_seq = [r for r in rags if r.sequencia_cumprimento]

def scan_passos(r):
    issues = []
    seq = r.sequencia_cumprimento
    if not isinstance(seq, list):
        seq = [seq]
    for p in seq:
        if not isinstance(p, dict):
            continue
        tp = p.get('tipo','')
        # A. typo fallback
        for k in ('fallback',):
            v = str(p.get(k,''))
            if PADRAO_TYPO in v:
                issues.append(f'  ⚠ [A-typo] fallback="{v}" → correto é "solicitar_expedicao"  (passo {tp})')
        # B. polo fora do vocabulario
        for k in ('polo','fallback_polo','mandado_polo'):
            v = str(p.get(k,'')).strip().lower()
            if v and v not in VOCAB_POLO:
                issues.append(f'  ⚠ [B-polo] {k}="{p.get(k)}" fora do vocabulário (passo {tp})')
        # C. fluxo analisar sem fluxo_fallback
        if p.get('fluxo')=='analisar' and not p.get('fluxo_fallback'):
            issues.append(f'  ⚠ [C-fluxo] fluxo="analisar" SEM fluxo_fallback=true (passo {tp})')
        # D. placeholder sem substituicao garantida
        if PH.search(p.get('observacao','') or p.get('texto_base','') or '') and tp not in TIPOS_SUBSTITUEM_EVENTO:
            issues.append(f'  ⚠ [D-placeholder] {{...}} em passo tipo "{tp}" (substituição não confirmada)')
        # E. nao_concluir ligado
        if p.get('nao_concluir'):
            issues.append(f'  ⚠ [E-nao_concluir] nao_concluir=true (modo teste?) no passo {tp}')
    return issues

print(f'Total ativas: {len(rags)} | com sequência: {len(com_seq)}\n')
tot = {'A':0,'B':0,'C':0,'D':0,'E':0,'F':0}

# F. duplicatas
from collections import Counter
count_atos = Counter(r.despacho_ato.strip() for r in com_seq)
dups = {k:v for k,v in count_atos.items() if v>1}

for r in sorted(com_seq, key=lambda x:x.id):
    issues = scan_passos(r)
    if not issues and r.despacho_ato.strip() not in dups:
        continue
    print('#'*78)
    print(f'RAG #{r.id}')
    print(f'  ato: {r.despacho_ato[:90]}')
    for it in issues:
        print(it)
        if it.strip().startswith('⚠ [A'): tot['A']+=1
        elif it.strip().startswith('⚠ [B'): tot['B']+=1
        elif it.strip().startswith('⚠ [C'): tot['C']+=1
        elif it.strip().startswith('⚠ [D'): tot['D']+=1
        elif it.strip().startswith('⚠ [E'): tot['E']+=1

print('\n'+'='*78)
if dups:
    print('Duplicatas prováveis (mesmo despacho_ato):')
    for ato,n in dups.items():
        ids = [str(r.id) for r in com_seq if r.despacho_ato.strip()==ato]
        print(f'  ×{n}: {ato[:70]}  → RAGs {", ".join(ids)}')
        tot['F']+=1
else:
    print('Sem duplicatas por despacho_ato.')

print('\n=== RESUMO POR CATEGORIA (nº de flags) ===')
print(f'  A. typo fallback "expecidao" ....: {tot["A"]}')
print(f'  B. polo fora do vocabulário ......: {tot["B"]}')
print(f'  C. analisar sem fluxo_fallback ...: {tot["C"]}')
print(f'  D. placeholder em tipo não-suport.: {tot["D"]}')
print(f'  E. nao_concluir ligado ...........: {tot["E"]}')
print(f'  F. grupos duplicados ..............: {tot["F"]}')
