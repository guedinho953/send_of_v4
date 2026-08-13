"""Confere no Projudi se os processos foram movimentados (581/intimação)."""
import django, os, sys
sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
django.setup()

from accounts.models import User
from projudi.services import ProjudiService

user = User.objects.filter(is_active=True).first()
svc = ProjudiService(user)
result = svc._get_session_from_cookies()
if not result:
    print('SEM SESSAO'); sys.exit(1)
session, cookies = result
print('Sessão OK')

# 1823-03 (erro de rede, mas dizem que já movimentado) e 1109-38 (não executou)
for interno in ['41020232325226', '41020261707872']:
    url = f'https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?numeroProcesso={interno}'
    r = session.get(url, timeout=30)
    print(f'\n=== interno {interno} status={r.status_code} ===')
    from projudiProcessNavigator import ProcessoParser
    parser = ProcessoParser(r.text)
    try:
        movs, _ = parser.extrair_movimentacoes()
        print(f'  {len(movs)} movimentações.')
        # Mostra as 3 primeiras e todas de intimação
        for i, m in enumerate(movs[:3]):
            ato = str(m.get('ato', '')).replace('\n', ' ').strip()[:120]
            print(f'  [{i}] {ato}')
        print('  --- intimações ---')
        for m in movs:
            ato = str(m.get('ato', '')).replace('\n', ' ').strip()
            if 'intima' in ato.lower():
                print(f'  • {ato[:130]}')
    except Exception as e:
        print(f'  erro: {e}')
    print()