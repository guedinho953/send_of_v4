"""Varre a fila de movimentações do Projudi procurando o 2333-11 e testa matching RAG por texto."""
import django, os, sys
sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from accounts.models import User
from projudi.services import ProjudiService
from projudi_client import ProjudiClient

TARGET = '2333'
user = User.objects.filter(is_active=True).first()
svc = ProjudiService(user)
result = svc._get_session_from_cookies()
if not result:
    print('SEM SESSAO'); sys.exit(1)
session, cookies = result
print('Sessão OK')

client = ProjudiClient()
client.session = session
client.cookies = cookies

from bs4 import BeautifulSoup
pages = client.obter_paginas_finais_movimentacoes(quantidade=8)
print(f'{len(pages)} páginas')
for p in pages:
    data = {'pagina': str(p), 'loginJuiz': ''}
    rp = session.post(client.URL_MOVIMENTACOES, data=data, timeout=15)
    if len(rp.text) <= 1000:
        continue
    sp = BeautifulSoup(rp.text, 'html.parser')
    try:
        movs = client.extrair_links_movimentacoes(sp)
    except Exception as e:
        print('erro extrair:', e); continue
    for m in movs:
        proc = m.get('processo', '')
        if TARGET in proc:
            print(f'\n=== MATCH página {p}: processo={proc} ===')
            print('mov:', m)
            doc_url = m.get('link_documento', '')
            if not doc_url.startswith('http'):
                from urllib.parse import urljoin
                doc_url = urljoin('https://projudi.tjba.jus.br/projudi/', doc_url)
            rd = session.get(doc_url, timeout=20)
            txt = BeautifulSoup(rd.text, 'html.parser').get_text(' ', strip=True)
            print(f'--- TEXTO ({len(txt)} chars) ---')
            print(txt[:1200])
            print('--- FIM TEXTO ---')
            sys.exit(0)
print('\n2333-11 não encontrado nas páginas varridas.')