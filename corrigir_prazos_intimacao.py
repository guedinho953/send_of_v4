"""Corrige prazo_intimacao das RAGs de intimação: o valor no JSON é o CÓDIGO
do painel, não dias. Códigos: 2=5d, 3=10d (default), 4=15d, 7=30d, 29=6m.
Ex: sentença (10 dias) → '3'. Se estiver '10' (dias) → corrige p/ '3'."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
import django; django.setup()
from processes.models import RAGExample

# códigos válidos do painel (docs/05-CONFIGURAR-RAGS.md)
VALIDOS = {'2', '3', '4', '7', '29'}

mudou = []
for r in RAGExample.objects.filter(active=True):
    seq = r.sequencia_cumprimento or []
    if not isinstance(seq, list):
        continue
    alterado = False
    for s in seq:
        if not isinstance(s, dict) or s.get('tipo') != 'intimacao_eletronica':
            continue
        pr = s.get('prazo_intimacao')
        if pr is None:
            continue  # default '3' já ok
        pr_str = str(pr)
        if pr_str not in VALIDOS:
            # era dia (ex '10')? vira código de 10 dias = '3'
            novo = '3'
            print(f'#{r.id} | prazo {pr_str!r} -> {novo!r} | {r.despacho_ato[:50]!r}')
            s['prazo_intimacao'] = novo
            alterado = True
    if alterado:
        r.save()
        mudou.append(r.id)

print(f'\nCorrigidas: {mudou or "nenhuma"}')
# mostra estado final
for r in RAGExample.objects.filter(active=True).order_by('id'):
    seq = r.sequencia_cumprimento or []
    for s in seq if isinstance(seq, list) else []:
        if isinstance(s, dict) and s.get('tipo') == 'intimacao_eletronica':
            print(f"  #{r.id} | prazo={s.get('prazo_intimacao','3')!r} | motivo={s.get('motivo_intimacao','3')!r}")
