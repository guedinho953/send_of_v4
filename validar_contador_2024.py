"""Valida PrazoService.contar_prazo contra o algoritmo manual de
contagem de dias úteis (script do Ivan: avança dia a dia, conta só
úteis, exclui fins de semana/feriados)."""
import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
django.setup()

from datetime import date, timedelta
from projudi.prazo_service import (
    PrazoService, FERIADOS_NACIONAIS_FIXOS,
)

# ── Referência manual (mesma lógica do script do usuário) ──
data_inicio = date(2024, 10, 14)
prazo_concedido = 15

# dias úteis 2024 = dias que NÃO são fds nem feriado fixo nacional
feriados_2024 = set()
for mes, dia, *_ in FERIADOS_NACIONAIS_FIXOS:
    feriados_2024.add(date(2024, mes, dia))

def eh_util(d):
    return d.weekday() < 5 and d not in feriados_2024

dias_uteis_2024 = set()
d = date(2024, 1, 1)
while d.year == 2024:
    if eh_util(d):
        dias_uteis_2024.add(d)
    d += timedelta(days=1)

# script do usuário (replicado)
ultimo_dia = data_inicio
dias_contados = []
dias_excluidos = []
while prazo_concedido != len(dias_contados):
    ultimo_dia = ultimo_dia + timedelta(1)
    if ultimo_dia in dias_uteis_2024:
        dias_contados.append(ultimo_dia)
    else:
        dias_excluidos.append(ultimo_dia)

print('=== MANUAL ===')
print('contados:', len(dias_contados), '| último:', ultimo_dia,
      '| decurso:', ultimo_dia + timedelta(1))

# ── PrazoService (default: nacionais fixos, modo uteis) ──
svc = PrazoService()  # incluir_nacionais=True por padrão
res = svc.contar_prazo(data_inicio, prazo_concedido)

print('\n=== PRAZOSERVICE ===')
print('contados:', len(res.dias_contados), '| último:', res.ultimo_dia,
      '| decurso:', res.data_decurso)

# ── Comparação ──
# O script manual do usuário não lista o dia da intimação em excluidos
# (ele é o `ultimo_dia` inicial, fora do while). O PrazoService registra
# explicitamente para clareza. A CONTAGEM em si deve ser idêntica.
excluidos_svc = set(res.dias_excluidos) - {data_inicio}
ok = (
    set(res.dias_contados) == set(dias_contados)
    and excluidos_svc == set(dias_excluidos)
    and res.ultimo_dia == ultimo_dia
    and res.data_decurso == ultimo_dia + timedelta(1)
)
print('\nBATE?', ok)
if not ok:
    print('contados manual:', [d.isoformat() for d in dias_contados])
    print('contados svc    :', [d.isoformat() for d in res.dias_contados])
    diff_c = set(dias_contados) ^ set(res.dias_contados)
    diff_e = set(dias_excluidos) ^ set(res.dias_excluidos)
    if diff_c:
        print('diff contados:', sorted(x.isoformat() for x in diff_c))
    if diff_e:
        print('diff excluidos:', sorted(x.isoformat() for x in diff_e))
