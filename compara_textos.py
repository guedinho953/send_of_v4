"""Compara o texto real dos processos executados hoje com o snippet usado (RAG)."""
import django, os, sys, re
sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from datetime import datetime, timedelta
from projudi.models import CumprimentoRecord
from accounts.models import User
from projudi.services import ProjudiService

# últimos cumprimentos com snippet que parecem ser das RAGs novas
recs = CumprimentoRecord.objects.filter(
    created_at__gte=datetime.now()-timedelta(hours=3)).order_by('-created_at')

user = User.objects.filter(is_active=True).first()
svc = ProjudiService(user)
session, cookies = svc._get_session_from_cookies()
print('Sessão OK\n')

from bs4 import BeautifulSoup
for c in recs[:12]:
    interno = c.processo
    url = f'https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?numeroProcesso={interno}'
    try:
        r = session.get(url, timeout=20)
        if len(r.text) < 2000:
            print(f'== {interno}: página vazia'); continue
        sp = BeautifulSoup(r.text, 'html.parser')
        # acha o texto do último despacho/movimentação relevante
        # pega o título e tenta o conteúdo do despacho mais recente
        txt = sp.get_text(' ', strip=True)
        # procura por 'DESPACHO' no texto
        m = re.search(r'DESPACHO.{0,600}', txt, re.I)
        real = m.group(0)[:450] if m else txt[:300]
        print(f'== #{c.id} {interno} [{c.created_at:%H:%M}] status={c.status}')
        print(f'   REAL : {real[:250]}')
        print(f'   USADO: {str(c.snippet)[:250]}')
        print()
    except Exception as e:
        print(f'== {interno}: erro {e}')