"""Diagnóstico: por que o processo não deu match na RAG.

Uso:
  source .venv/bin/activate
  python diag_match_582.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'

from expedir_rapido import session_projudi
from projudi_client import ProjudiClient
from processes.models import RAGExample
from bs4 import BeautifulSoup

PROC = '0000582-86.2026.8.05.0191'

user, session, cookies_dict = session_projudi()

client = ProjudiClient()
client.session = session
client.cookies = cookies_dict

# 1. O processo está nas movimentações varridas (3 páginas)?
pages = client.obter_paginas_finais_movimentacoes(quantidade=3)
print(f'{len(pages)} página(s)')
mov = None
for p in pages:
    data = {'pagina': str(p), 'loginJuiz': ''}
    rp = session.post(client.URL_MOVIMENTACOES, data=data, timeout=15)
    if len(rp.text) <= 1000:
        continue
    sp = BeautifulSoup(rp.text, 'html.parser')
    for m in client.extrair_links_movimentacoes(sp):
        if PROC in m.get('processo', ''):
            mov = m
            print(f'✅ ACHOU na página {p}')
            print('   processo:', m.get('processo'))
            print('   link_documento:', (m.get('link_documento') or '')[:100])
            print('   link_processo:', (m.get('link_processo') or '')[:100])
            break
    if mov:
        break

if not mov:
    print(f'❌ {PROC} NÃO está nas 3 páginas varridas — fora do alcance do rastreio')
    sys.exit(0)

# 2. Baixa o documento do despacho e extrai texto
doc_url = mov.get('link_documento', '')
if not doc_url:
    print('❌ Sem link_documento (movimentação sem documento p/ baixar)')
    sys.exit(0)
if not doc_url.startswith('http'):
    from urllib.parse import urljoin
    doc_url = urljoin('https://projudi.tjba.jus.br/projudi/', doc_url)

r_doc = session.get(doc_url, timeout=30)
print(f'✅ Documento HTTP {r_doc.status_code}')
texto = BeautifulSoup(r_doc.text, 'html.parser').get_text(' ', strip=True)
print(f'📄 Texto ({len(texto)} chars):')
print('   ', texto[:400])
print()

# 3. Matching contra RAG #2457 (e top geral)
palavras_texto = set(texto.lower().split())
for rid in (2457,):
    r = RAGExample.objects.get(id=rid)
    palavras_ato = set(r.despacho_ato.lower().split())
    inter = palavras_texto & palavras_ato
    pct = len(inter) / max(len(palavras_ato), 1)
    print(f'RAG #{rid}: {pct:.0%} do despacho_ato presente no texto '
          f'({len(inter)}/{len(palavras_ato)} palavras)')
    if pct < 0.70:
        print('   → ABAIXO de 70% — não passa no filtro. Palavras faltando:')
        faltando = palavras_ato - palavras_texto
        print('     faltando:', sorted(faltando)[:20])

print()
print('--- buscar_cumprimentos_similares (top 5) ---')
from processes.movimentacoes_service import buscar_cumprimentos_similares
sim = buscar_cumprimentos_similares(texto, top_k=5)
for s in sim:
    print(f"  #{s.get('id')} sim={s.get('similaridade')} | {s.get('despacho_ato','')[:70]}")
