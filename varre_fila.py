"""Varre a fila como o sistema faz e mostra texto real + RAG escolhida."""
import django, os, sys, re
sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from accounts.models import User
from projudi.services import ProjudiService
from projudi_client import ProjudiClient
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from expedir_rapido import buscar_cumprimentos_similares
from processes.movimentacoes_service import _palavras_para_match
from processes.models import RAGExample

user = User.objects.filter(is_active=True).first()
svc = ProjudiService(user)
result = svc._get_session_from_cookies()
session, cookies = result
client = ProjudiClient(); client.session = session; client.cookies = cookies

pages = client.obter_paginas_finais_movimentacoes(quantidade=4)
movs = []
for p in pages:
    data = {'pagina': str(p), 'loginJuiz': ''}
    rp = session.post(client.URL_MOVIMENTACOES, data=data, timeout=15)
    if len(rp.text) <= 1000: continue
    sp = BeautifulSoup(rp.text, 'html.parser')
    try: movs.extend(client.extrair_links_movimentacoes(sp))
    except: pass
print(f'{len(movs)} movimentações na fila\n')

for mov in movs:
    proc = mov.get('processo','')
    doc_url = mov.get('link_documento','')
    if not doc_url.startswith('http'):
        doc_url = urljoin('https://projudi.tjba.jus.br/projudi/', doc_url)
    try:
        rd = session.get(doc_url, timeout=20)
        texto = BeautifulSoup(rd.text, 'html.parser').get_text(' ', strip=True)
        if len(texto) < 50: continue
        similares = buscar_cumprimentos_similares(texto, top_k=5)
        if not similares: continue
        pw = _palavras_para_match(texto)
        melhor = None
        for s in similares:
            pr = _palavras_para_match(s['despacho_ato']+' '+s.get('despacho_observacao',''))
            base = max(min(len(pw), len(pr)),1)
            pct = len(pw&pr)/base
            if pct >= 0.70:
                melhor = (s['id'], pct, s.get('excesso'))
                break
        if melhor:
            print(f'== {proc}')
            print(f'   REAL: {texto[:280]}')
            print(f'   RAG #{melhor[0]} (pct={melhor[1]:.2f}, excesso={melhor[2]}): {similares[[s["id"] for s in similares].index(melhor[0])]["despacho_ato"][:60]!r}')
            print()
    except Exception as e:
        pass