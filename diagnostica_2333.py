"""Busca um processo CNJ no Projudi e testa o matching RAG contra o texto real."""
import django, os, sys, re
sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
django.setup()

from accounts.models import User
from projudi.services import ProjudiService

CNJ = '0002333-11.2026.8.05.0191'
# monta o número interno Projudi (ANO + sequencial)
seq = CNJ.split('-')[0]  # 0002333
ano = CNJ.split('.')[1]  # 2026
interno = f'4102026{seq}'  # 4102026 0002333
print('número interno tentado:', interno)

user = User.objects.filter(is_active=True).first()
svc = ProjudiService(user)
result = svc._get_session_from_cookies()
if not result:
    print('SEM SESSAO'); sys.exit(1)
session, cookies = result
print('Sessão OK')

url = f'https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?numeroProcesso={interno}'
r = session.get(url, timeout=30)
print(f'status={r.status_code} len={len(r.text)}')
print('URL final:', r.url[:120] if r.url else '-')

from projudiProcessNavigator import ProcessoParser
parser = ProcessoParser(r.text)
try:
    movs, _ = parser.extrair_movimentacoes()
    print(f'{len(movs)} movimentações')
    print('--- 6 primeiras ---')
    for m in movs[:6]:
        print(f'  [{m.get("data_texto","")}] {str(m.get("ato",""))[:110]}')
except Exception as e:
    import traceback; traceback.print_exc()