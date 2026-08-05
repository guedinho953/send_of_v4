"""Valida o PASSO 3 (clique no link 'Intimação' do grid) em MODO TESTE.

Abre o Firefox, preenche a movimentação + painel de intimação usando o novo
código, mas NÃO clica em Concluir (nao_concluir=True). Serve para confirmar
que o alerta "escolha um tipo de documento" não aparece mais (o grid é
selecionado de verdade via a:has-text).

Uso:
  source .venv/bin/activate
  python test_validar_grid.py 0003369-25.2025.8.05

Se não passar CNJ, usa o primeiro pendente com codAnalise.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from django.apps import apps
User = apps.get_model('accounts.User')
from projudi.services import ProjudiService
from projudi_client import ProjudiClient
from bs4 import BeautifulSoup

CNJ = sys.argv[1] if len(sys.argv) > 1 else None

user = User.objects.filter(is_active=True).first()
sess = ProjudiService(user)._get_session_from_cookies()
if not sess:
    print('❌ Sessão Projudi indisponível.')
    sys.exit(1)
session, cookies_dict = sess
client = ProjudiClient(); client.session = session; client.cookies = cookies_dict

# ── 1. Achar codAnalise do processo ──
cod_analise = None
pages = client.obter_paginas_finais_movimentacoes(quantidade=3)
for p in pages:
    rp = session.post(client.URL_MOVIMENTACOES, data={'pagina': str(p), 'loginJuiz': ''}, timeout=15)
    if len(rp.text) <= 1000:
        continue
    sp = BeautifulSoup(rp.text, 'html.parser')
    for m in client.extrair_links_movimentacoes(sp):
        if CNJ and CNJ not in m.get('processo', ''):
            continue
        mov = m.get('movimentar', '')
        if 'codAnalise=' in mov:
            cod_analise = mov.split('codAnalise=')[1].split('&')[0]
            print(f'  📄 {m.get("processo", "?")} | {m.get("tipo", "?")}')
            print(f'  🔗 codAnalise={cod_analise}')
            break
    if cod_analise:
        break

if not cod_analise:
    print('❌ Nenhum pendente com codAnalise' + (f' para {CNJ}' if CNJ else '') + '.')
    sys.exit(1)

# ── 2. Executar em MODO TESTE (não conclui) ──
from projudi.movimentacao_service import MovimentacaoService
svc = MovimentacaoService(user)
print('\n🚀 Abrindo Firefox em MODO TESTE (nao_concluir)...')
print('   Confira: grid deve clicar no link "Intimação" e o alerta\n'
      '   "escolha um tipo de documento" NÃO deve aparecer.\n')
ok = svc.executar_com_intimacao(
    processo_numero=CNJ or '',
    observacao='Intimem-se as partes (TESTE de validação do grid - não concluído)',
    codigo_mov='581',
    descricao_mov='Intimação',
    cookies_dict=cookies_dict,
    cod_analise=cod_analise,
    prazo_intimacao='3',
    motivo_intimacao='3',
    nao_concluir=True,      # ← MODO TESTE, não clica Concluir
    polo_intimacao='todos',
)
print(f'\n{"="*60}\nResultado: {"OK (grid preenchido, sem Concluir)" if ok else "FALHOU"}\n{"="*60}')