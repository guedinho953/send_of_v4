"""Valida o PASSO 3 (tipo documental via select codTipoDocumento por label)
em MODO TESTE (nao_concluir), via FLUXO B (MovimentarProcesso, link genérico).

Abre, faz a busca, seleciona 'Intimação' no select e imprime o valor
confirmado. NÃO clica em Concluir — sem efeito legal.

Uso:
  source .venv/bin/activate
  python test_validar_v3.py 41020262339469
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from django.apps import apps
User = apps.get_model('accounts.User')
from projudi.services import ProjudiService
from projudi.movimentacao_service import MovimentacaoService

INTERNO = sys.argv[1] if len(sys.argv) > 1 else '41020262339469'

user = User.objects.filter(is_active=True).first()
sess = ProjudiService(user)._get_session_from_cookies()
if not sess:
    print('❌ Sessão indisponível.')
    sys.exit(1)
_, cookies_dict = sess

# FLUXO B (sem codAnalise) + MODO TESTE
svc = MovimentacaoService(user)
print(f'🚀 FLUXO B MODO TESTE — proc interno {INTERNO}')
print('   Confira: PASSO 3 deve logar "Tipo doc: ... (confirmado=...)";\n'
      '   depois PARA antes do Concluir (nao_concluir).\n')
ok = svc.executar_com_intimacao(
    processo_numero='0001507-82.2026.8.05.0191',
    observacao='Intime-se o executado (TESTE tipo doc - não concluído)',
    codigo_mov='581',
    descricao_mov='Intimação',
    cookies_dict=cookies_dict,
    proc_projudi=INTERNO,
    cod_analise=None,            # FLUXO B
    prazo_intimacao='4',
    motivo_intimacao='3',
    nao_concluir=True,           # MODO TESTE
    polo_intimacao='res',
    expedir_ar=False,           # não chega na etapa AR no modo teste
    assinar_ar=False,
)
print(f'\n{"="*60}\nResultado: {"OK (sem Concluir)" if ok else "FALHOU"}\n{"="*60}')