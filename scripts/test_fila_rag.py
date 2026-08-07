#!/usr/bin/env python3
"""Teste READ-ONLY da fila real: varre movimentações recentes do Projudi,
baixa o texto dos documentos e roda o matching RAG. Imprime o que CASARIA
(≥70%) e qual RAG/sequência seria escolhida — sem expedir NADA.

Uso:
  source .venv/bin/activate
  cd /home/ivan/PythonProjects/send_of_v4
  python scripts/test_fila_match.py [--paginas N]
"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()
from django.apps import apps

User = apps.get_model('accounts.User')
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from projudi_client import ProjudiClient
from projudi.services import ProjudiService
from processes.models import RAGExample
from processes.movimentacoes_service import buscar_cumprimentos_similares, _palavras_para_match

LINK_BASE = 'https://projudi.tjba.jus.br/projudi/'

def main():
    paginas = 3
    if '--paginas' in sys.argv:
        i = sys.argv.index('--paginas')
        try:
            paginas = int(sys.argv[i + 1])
        except Exception:
            pass

    user = User.objects.filter(is_active=True).first()
    if not user:
        print('❌ Nenhum usuário ativo'); return
    service = ProjudiService(user)
    result = service._get_session_from_cookies()
    if not result:
        print('❌ Sessão não disponível'); return
    session, cookies_dict = result
    print(f'✅ Sessão: {user.email}\n')

    client = ProjudiClient()
    client.session = session
    client.cookies = cookies_dict

    pages = client.obter_paginas_finais_movimentacoes(quantidade=paginas)
    print(f'{len(pages)} página(s) para varrer — MODO TESTE (nada expedido)\n')

    movs = []
    for p in pages:
        data = {'pagina': str(p), 'loginJuiz': ''}
        rp = session.post(client.URL_MOVIMENTACOES, data=data, timeout=15)
        if len(rp.text) <= 1000:
            continue
        sp = BeautifulSoup(rp.text, 'html.parser')
        movs.extend(client.extrair_links_movimentacoes(sp))

    print(f'{len(movs)} movimentação(ões) encontrada(s)\n')

    matchou = 0
    sem_match = 0
    for mov in movs:
        proc_num = mov.get('processo', '')
        doc_url = mov.get('link_documento', '')
        if not proc_num or not doc_url:
            continue
        if not doc_url.startswith('http'):
            doc_url = urljoin(LINK_BASE, doc_url)
        try:
            r_doc = session.get(doc_url, timeout=30)
            if r_doc.status_code != 200:
                continue
            texto = BeautifulSoup(r_doc.text, 'html.parser').get_text(' ', strip=True)
            if len(texto) < 50:
                continue

            similares = buscar_cumprimentos_similares(texto, top_k=30)
            palavras_texto = _palavras_para_match(texto)
            melhor = None
            rag = None
            for s in similares:
                palavras_rag_s = _palavras_para_match(
                    s['despacho_ato'] + ' ' + s.get('despacho_observacao', ''))
                base_s = min(len(palavras_texto), len(palavras_rag_s))
                if base_s > 0 and len(palavras_texto & palavras_rag_s) / base_s < 0.70:
                    continue
                rag_cand = RAGExample.objects.get(id=s['id'])
                if rag_cand.sequencia_cumprimento:
                    melhor = s
                    rag = rag_cand
                    break
            if not melhor:
                sem_match += 1
                continue
            matchou += 1
            jac = (len(palavras_texto & _palavras_para_match(
                melhor['despacho_ato'] + ' ' + melhor.get('despacho_observacao', '')))
                / max(min(len(palavras_texto), len(_palavras_para_match(
                    melhor['despacho_ato'] + ' ' + melhor.get('despacho_observacao', '')))), 1))
            seq_tipos = [p.get('tipo') for p in (rag.sequencia_cumprimento or [])]
            print('=' * 70)
            print(f'CNJ: {proc_num}')
            print(f'  match → RAG #{melhor["id"]}: {(melhor["despacho_ato"] or "")[:70]}')
            print(f'  jaccard: {jac:.2f}')
            print(f'  sequência: {seq_tipos}')
            print(f'  [trecho do texto]: {texto[:150].strip()}')
        except Exception as e:
            print(f'  ⚠️ erro: {e}')

    print('\n' + '=' * 70)
    print(f'RESUMO: {matchou} match(es) ≥70% (NÃO expedidos) | {sem_match} movs sem match/abaixo do corte')
    if matchou:
        print('⚠️ Em execução real, estes expediriam. Revise antes de rodar expedir_rapido.py')

if __name__ == '__main__':
    main()