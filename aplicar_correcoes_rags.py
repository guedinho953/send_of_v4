"""Aplica correções da auditoria de RAGs (2026-08-20).

NÃO toca nos pares complementares mandado<->solicitar_expedicao (o Ivan alterna
por botão). Apenas:
  1. EXCLUI cópias IDENTICAS  (#2465-2470, #2499, #2446)
  2. CORRIGE bugs:
       - #2547 polo 'exequente_especifico' (fora do vocabulário) -> 'exequentes'
       - #2483/#2487 fallback 'solicitar_expecidao' (typo) -> 'solicitar_expedicao'
       - #2443 nao_concluir true -> false (modo teste desligado)
       - fluxo_fallback:true nas RAGs com fluxo:'analisar' sem fallback
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()
from processes.models import RAGExample

# 1) Exclusões de cópias idênticas (mantendo: 2463, 2464, 2498, 2525, 2447)
EXCLUIR = [2465, 2466, 2467, 2468, 2469, 2470,   # 6 cópias idênticas a 2464
           2499,                                   # cópia exata de 2498
           2446]                                   # duplicado de 2447 (edita 2447)

def set_passo_flag(rag, campo, valor):
    seq = rag.sequencia_cumprimento
    if isinstance(seq, list):
        for p in seq:
            if isinstance(p, dict):
                p[campo] = valor
    else:
        seq[campo] = valor
    rag.save(update_fields=['sequencia_cumprimento'])
    return seq

def set_pol(rag, novo):
    seq = set_passo_flag(rag, 'polo', novo)
    for p in seq:
        if isinstance(p, dict) and 'fallback_polo' in p:
            p['fallback_polo'] = novo
    rag.save(update_fields=['sequencia_cumprimento'])

print('== 1) EXCLUSÕES ==')
for rid in EXCLUIR:
    try:
        r = RAGExample.objects.get(id=rid)
    except RAGExample.DoesNotExist:
        print(f'  #{rid} já não existe — pulando.'); continue
    print(f'  🗑  #{rid} {r.despacho_ato[:60]}')
    r.delete()

print('\n== 2) CORREÇÕES PONTUAIS ==')
# #2547 polo exequente_especifico -> exequentes
r = RAGExample.objects.get(id=2547)
set_pol(r, 'exequentes')
print(f'  ✅ #2547 polo/fallback_polo -> exequentes')

# typos fallback
for rid, palavras in [(2483, 'solicitar_expedicao'), (2487, 'solicitar_expedicao')]:
    r = RAGExample.objects.get(id=rid)
    set_passo_flag(r, 'fallback', palavras)
    print(f'  ✅ #{rid} fallback -> {palavras}')

# #2443 nao_concluir -> false
r = RAGExample.objects.get(id=2443)
set_passo_flag(r, 'nao_concluir', False)
print(f'  ✅ #2443 nao_concluir -> false')

print('\n== 3) fluxo_fallback:true (fluxo analisar) ==')
FLUXO_ANALISAR_SEM_FALLBACK = [2447, 2448, 2451, 2453, 2456, 2459, 2461, 2474,
                               2483, 2484, 2485, 2487, 2542, 2545, 2546, 2547, 2549]
for rid in FLUXO_ANALISAR_SEM_FALLBACK:
    try:
        r = RAGExample.objects.get(id=rid)
    except RAGExample.DoesNotExist:
        continue
    seq = r.sequencia_cumprimento
    if not isinstance(seq, list):
        continue
    mudou = False
    for p in seq:
        if isinstance(p, dict) and p.get('fluxo') == 'analisar' and not p.get('fluxo_fallback'):
            p['fluxo_fallback'] = True; mudou = True
    if mudou:
        r.save(update_fields=['sequencia_cumprimento'])
        print(f'  ✅ #{rid} fluxo_fallback=true')
    else:
        print(f'  ·  #{rid} (sem passo analisar)')

print('\nConcluído.')
