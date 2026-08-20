"""Seed dos feriados/suspensões locais que o Ivan passou (2025-12 → 2026-10).

Cria SuspensaoPrazo (paralisações) + Feriado (unico, datas específicas) no
tenant do usuário. Idempotente (update_or_create por chave única).

Datas (do Ivan):
  recesso 19/12/2025 a 06/01/2026
  suspensão de prazo processual 07/01 a 20/01/2026
  carnaval 12 a 18/02/2026
  02-03/04 sexta-feira santa | 20-21/04 tiradentes | 01/05 trabalhador
  04-05/06 corpus christi | 22-23-24/06 são joão | 29-30/06 copa do mundo
  02-03/07 independência da Bahia | 27-28/07 aniversário de Paulo Afonso
  10-11/08 dia do magistrado | 12/10 aparecida | 30/10 dia do servidor

Uso: source .venv/bin/activate && python popular_feriados_local_2026.py [--tenant-id N]
"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from accounts.models import User
from projudi.models import Feriado, SuspensaoPrazo
from datetime import date

def tenant_padrao():
    return getattr(User.objects.first().tenant, 'id', None)

# suspensões: (data_inicio, data_fim, tipo, descricao)
SUSPENSOES = [
    (date(2025,12,19), date(2026,1,6),  'recesso_local',      'Recesso forense 19/12/2025 a 06/01/2026'),
    (date(2026,1,7),   date(2026,1,20), 'ponto_facultativo',  'Suspensao de prazo processual 07-20/01/2026'),
    (date(2026,2,12),  date(2026,2,18), 'ponto_facultativo',  'Carnaval 12-18/02/2026'),
    (date(2026,6,29),  date(2026,6,30), 'ponto_facultativo',  'Copa do Mundo 29-30/06/2026'),
]

# feriados unico (data, escopo, nome)
UNICOS = [
    (date(2026,4,2),   'estadual',  'Sexta-Feira Santa (ponto)'),
    (date(2026,4,3),   'nacional',  'Sexta-Feira Santa'),
    (date(2026,4,20),  'estadual',  'Tiradentes (ponto)'),
    (date(2026,4,21),  'nacional',  'Tiradentes'),
    (date(2026,5,1),   'nacional',  'Dia do Trabalho'),
    (date(2026,6,4),   'nacional',  'Corpus Christi'),
    (date(2026,6,5),   'estadual',  'Corpus Christi (ponto)'),
    (date(2026,6,22),  'comarca',   'Sao Joao'),
    (date(2026,6,23),  'comarca',   'Sao Joao'),
    (date(2026,6,24),  'comarca',   'Sao Joao'),
    (date(2026,7,2),   'estadual',  'Independencia da Bahia'),
    (date(2026,7,3),   'estadual',  'Independencia da Bahia (ponto)'),
    (date(2026,7,27),  'comarca',   'Aniversario de Paulo Afonso'),
    (date(2026,7,28),  'comarca',   'Aniversario de Paulo Afonso (ponto)'),
    (date(2026,8,10),  'estadual',  'Dia do Magistrado'),
    (date(2026,8,11),  'estadual',  'Dia do Magistrado (ponto)'),
    (date(2026,10,12), 'nacional',  'Nossa Senhora Aparecida'),
    (date(2026,10,30), 'estadual',  'Dia do Servidor'),
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tenant-id', type=int, default=tenant_padrao())
    args = parser.parse_args()
    tid = args.tenant_id
    print(f'Cadastrando feriados/suspensões no tenant #{tid}\n')

    n_criado = n_exist = 0
    for ini, fim, tipo, desc in SUSPENSOES:
        _, created = SuspensaoPrazo.objects.get_or_create(
            tenant_id=tid, data_inicio=ini, data_fim=fim, tipo=tipo,
            defaults={'nome': desc, 'observacao': desc, 'escopo': 'nacional',
                      'is_active': True})
        print(f'  susp {ini} a {fim} [{tipo}] {"criada" if created else "ja existe"}')
        n_criado += created; n_exist += (not created)

    for data, escopo, nome in UNICOS:
        _, created = Feriado.objects.get_or_create(
            tenant_id=tid, data=data, escopo=escopo,
            defaults={'tipo': 'unico', 'nome': nome,
                      'observacao': nome, 'is_active': True})
        print(f'  feriado {data} [{escopo}] {nome} {"criado" if created else "ja existe"}')
        n_criado += created; n_exist += (not created)

    print(f'\nCriados: {n_criado} | Ja existiam: {n_exist}')


if __name__ == '__main__':
    main()
