"""Executa a sequência fixa (intimacao_eletronica) no processo real.

Uso:
  source .venv/bin/activate
  python test_executar_intimacao.py
"""

import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from django.apps import apps
User = apps.get_model('accounts.User')

from projudi.services import ProjudiService
from projudi.movimentacao_service import MovimentacaoService
from processes.models import RAGExample

# ─── Config ───
PROCESSO_CNJ = '0002000-59.2026.8.05.0191'
PROC_PROJUDI = '41020262997209'
RAG_ID = 2446

print('=' * 68)
print(f'  EXECUTAR INTIMAÇÃO ELETRÔNICA')
print(f'  Processo: {PROCESSO_CNJ}')
print(f'  RAGExample #{RAG_ID}')
print('=' * 68)

# ─── 1. Sessão ───
print('\n[1/4] Conectando ao Projudi...')
user = User.objects.filter(is_active=True).first()
service = ProjudiService(user)
result = service._get_session_from_cookies()
if not result:
    print('❌ Sessão não disponível. Firefox precisa estar logado no Projudi.')
    sys.exit(1)
session, cookies_dict = result
print(f'   ✅ Sessão OK — {user.email}')

# ─── 2. Carrega RAGExample ───
print(f'\n[2/4] Carregando RAGExample #{RAG_ID}...')
rag = RAGExample.objects.get(id=RAG_ID)
seq = rag.sequencia_cumprimento
obs = seq[0].get('observacao', '') if seq else ''
codigo_mov = str(seq[0].get('codigo_mov', '581')) if seq else '581'
descricao_mov = seq[0].get('descricao_mov', 'Intimação') if seq else 'Intimação'

print(f'   Sequência: {json.dumps(seq, indent=4)}')
print(f'   Observação: {obs}')
print(f'   Código Mov: {codigo_mov}')

# ─── 3. Confirmação ───
print(f'\n[3/4] Preparando execução...')
print()
print('   ⚠️  O Playwright vai ABRIR o Firefox e executar:')
print(f'      1. Abrir MovimentarProcesso ({PROCESSO_CNJ})')
print(f'      2. Injetar código {codigo_mov} + observação')
print(f'      3. Clicar Concluir')
print(f'      4. Ir para DadosProcesso')
print(f'      5. Clicar no link "Intimar"')
print(f'      6. Confirmar intimação')
print()
print('   🔴 O navegador vai abrir na sua frente.')
print('   Pressione ENTER para continuar ou CTRL+C para cancelar...')

try:
    input()
except KeyboardInterrupt:
    print('\n   Cancelado.')
    sys.exit(0)

# ─── 4. Executa ───
print(f'\n[4/4] Executando intimação eletrônica...')
print()

mov_service = MovimentacaoService(user)
ok = mov_service.executar_com_intimacao(
    processo_numero=PROCESSO_CNJ,
    observacao=obs or 'Intimem-se as partes para ciência da Liminar Não Concedida',
    codigo_mov=codigo_mov,
    descricao_mov=descricao_mov,
    cookies_dict=cookies_dict,
    proc_projudi=PROC_PROJUDI,
)

print()
if ok:
    print('   ✅ INTIMAÇÃO ELETRÔNICA CONCLUÍDA COM SUCESSO')
else:
    print('   ❌ INTIMAÇÃO ELETRÔNICA FALHOU')

print(f'\n{"="*68}')
