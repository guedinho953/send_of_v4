"""Acha o número interno do 0001530-96.2024.8.05.0191 no Projudi fila e imprime histórico."""
import django, os, sys
sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()
from accounts.models import User
from projudi.services import ProjudiService
from projudi_client import ProjudiClient

TARGET = '1530-96.2024'
user = User.objects.filter(is_active=True).first()
svc = ProjudiService(user)
result = svc._get_session_from_cookies()
session, cookies = result
print('Sessão OK')

client = ProjudiClient(); client.session = session; client.cookies = cookies
from bs4 import BeautifulSoup
internos = []
pages = client.obter_paginas_finais_movimentacoes(quantidade=10)
for p in pages:
    data = {'pagina': str(p), 'loginJuiz': ''}
    rp = session.post(client.URL_MOVIMENTACOES, data=data, timeout=15)
    if len(rp.text) <= 1000: continue
    sp = BeautifulSoup(rp.text, 'html.parser')
    try: movs = client.extrair_links_movimentacoes(sp)
    except: continue
    for m in movs:
        proc = m.get('processo','')
        if '1530' in proc and '.2024' in proc:
            print('PROCESSO:', proc)
            print('  link_processo:', m.get('link_processo'))
            import re
            mm = re.search(r'numeroProcesso=(\d+)', m.get('link_processo',''))
            interno = mm.group(1) if mm else None
            print('  interno:', interno)
            if interno:
                url = f'https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?numeroProcesso={interno}'
                rd = session.get(url, timeout=20)
                from projudiProcessNavigator import ProcessoParser
                parser = ProcessoParser(rd.text)
                mvs, _ = parser.extrair_movimentacoes()
                print(f'  {len(mvs)} movimentações')
                # imprime comunicações (intimação/citação) com meio
                for mv in mvs:
                    ato = str(mv.get('ato','')).replace('\n',' ').strip()
                    if any(x in ato.lower() for x in ['intima','citaç','citação']):
                        print(f'    [{mv.get("data_texto","")}] {ato[:90]}')
            sys.exit(0)
print('não achou 1530-96.2024 na fila varrida')