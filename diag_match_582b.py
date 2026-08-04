"""Lista TODAS as movimentações/documentos do processo e roda o RAG match
em cada documento baixado (para ver qual RAG deveria ter disparado)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'

from expedir_rapido import session_projudi
from projudi_client import ProjudiClient
from processes.movimentacoes_service import buscar_cumprimentos_similares
from processes.models import RAGExample
from bs4 import BeautifulSoup
from urllib.parse import urljoin

PROC = '0000582-86.2026.8.05.0191'
user, session, cookies_dict = session_projudi()
client = ProjudiClient(); client.session = session; client.cookies = cookies_dict

movs = []
for p in client.obter_paginas_finais_movimentacoes(quantidade=20):
    data = {'pagina': str(p), 'loginJuiz': ''}
    rp = session.post(client.URL_MOVIMENTACOES, data=data, timeout=15)
    if len(rp.text) <= 1000:
        continue
    sp = BeautifulSoup(rp.text, 'html.parser')
    for m in client.extrair_links_movimentacoes(sp):
        if PROC.replace('.', '').replace('-', '') in m.get('processo', '').replace('.', '').replace('-', ''):
            movs.append(m)
    print('page done', p)

import json
print(f'{len(movs)} movimentação(ões) do processo')
for i, m in enumerate(movs):
    proc_num = m.get('processo', '')
    doc = m.get('link_documento', '')
    print(f'\n--- [{i}] {proc_num} ---')
    print('   link_doc:', (doc or '')[:80])
    if not doc:
        print('   (sem documento)')
        continue
    if not doc.startswith('http'):
        doc = urljoin('https://projudi.tjba.jus.br/projudi/', doc)
    try:
        rd = session.get(doc, timeout=30)
        if rd.status_code != 200:
            print('   HTTP', rd.status_code); continue
        texto = BeautifulSoup(rd.text, 'html.parser').get_text(' ', strip=True)
        print(f'   texto ({len(texto)}): {texto[:160]!r}')
        sim = buscar_cumprimentos_similares(texto, top_k=3)
        for s in sim:
            rag = RAGExample.objects.filter(id=s.get('id')).first()
            ato = (rag.despacho_ato if rag else '') or ''
            pal_at = set(ato.lower().split())
            # recompute 70%
            pct = len(set(texto.lower().split()) & pal_at) / max(len(pal_at),1)
            seq = rag.sequencia_cumprimento if rag else None
            tipos = {ss.get('tipo') for ss in seq} if isinstance(seq, list) else set()
            print(f'     → #{s.get("id")} sim={s.get("similaridade")} pct_ato={pct:.0%} seq={tipos} | {ato[:50]}')
            print(f'          RAGExample #{s.get("id")} exists={bool(rag)}')
    except Exception as e:
        print('   ERRO:', e)