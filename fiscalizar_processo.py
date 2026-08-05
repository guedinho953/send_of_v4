"""Fiscaliza os registros de execução de um processo (banco local).

Uso:
  source .venv/bin/activate
  python fiscalizar_processo.py 0001708-74

Busca em CumprimentoRecord, CumprimentoLog, MovimentacaoRecord e
MovimentacaoLog. Cobre os fluxos de intimação/mandado/ofício/vistas_mp.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from projudi.models import (
    CumprimentoRecord, CumprimentoLog,
    MovimentacaoRecord, MovimentacaoLog,
    OficioRecord, MandadoRecord,
)

PROC = sys.argv[1] if len(sys.argv) > 1 else input('Número do processo (parcial): ').strip()
PROC2 = PROC
print(f'\n{"="*70}\n  FISCALIZAÇÃO DE {PROC}\n{"="*70}')

def sec(titulo):
    print(f'\n--- {titulo} ---')

sec('CUMPRIMENTOS (intimação/AR)')
rs = CumprimentoRecord.objects.filter(processo__icontains=PROC).order_by('-created_at')
if not rs: print('  (nenhum)')
for r in rs:
    print(f'  #{r.id} | {r.created_at:%d/%m %H:%M} | fluxo={r.fluxo} | status={r.status} | parte={r.parte_nome or "-"}')
    if r.fluxo_justificativa:
        print(f'       just: {r.fluxo_justificativa[:90]}')
    if r.snippet:
        print(f'       ato: {r.snippet[:80]}')

sec('LOGS DOS CUMPRIMENTOS')
ql = CumprimentoLog.objects.filter(cumprimento__processo__icontains=PROC).order_by('-created_at')[:20]
if not ql: print('  (nenhum)')
for l in ql:
    print(f'  {l.created_at:%d/%m %H:%M} [{l.tipo}] {(l.mensagem or "")[:110]}')

sec('MOVIMENTAÇÕES (581/solicitar/vistas/certidão)')
qm = MovimentacaoRecord.objects.filter(processo__icontains=PROC).order_by('-created_at')
if not qm: print('  (nenhum)')
for r in qm:
    print(f'  #{r.id} | {r.created_at:%d/%m %H:%M} | status={r.status} | {r.act_verb}')
    if r.observacao:
        print(f'       obs: {r.observacao[:90]}')

sec('LOGS DAS MOVIMENTAÇÕES')
qml = MovimentacaoLog.objects.filter(movimentacao__processo__icontains=PROC).order_by('-created_at')[:20]
if not qml: print('  (nenhum)')
for l in qml:
    print(f'  {l.created_at:%d/%m %H:%M} [{l.tipo}] {(l.mensagem or "")[:110]}')

sec('OFÍCIOS')
qo = OficioRecord.objects.filter(processo__icontains=PROC).order_by('-created_at')
if not qo: print('  (nenhum)')
for r in qo:
    print(f'  {r.created_at:%d/%m %H:%M} | nº {r.numero_oficio} | status={r.status} | retorno={r.status_retorno}')

sec('MANDADOS')
qm2 = MandadoRecord.objects.filter(processo__icontains=PROC).order_by('-created_at')
if not qm2: print('  (nenhum)')
for r in qm2:
    print(f'  {r.created_at:%d/%m %H:%M} | nº {r.numero_mandado} | {r.parte_nome or "-"} | status={r.status}')

print(f'\n{"═"*70}')