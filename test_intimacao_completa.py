"""Testa o fluxo `intimacao_completa` (intimação + MP + ofício, 1 movimentação).

Requer sessão Projudi ativa (Firefox logado). Roda a sequência completa num
RAGExample de teste ou num processo pendente real de transação penal.

Uso:
  source .venv/bin/activate
  python test_intimacao_completa.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from django.apps import apps
from processes.models import RAGExample, Process, Party
User = apps.get_model('accounts.User')
from projudi.services import ProjudiService
from expedir_rapido import _executar_sequencia_rapido
from types import SimpleNamespace

# ─── JSON do fluxo: intimação + MP (SOSTENYS) + ofício CIAP ───
SEQUENCIA = [
    {
        "tipo": "intimacao_completa",
        "fluxo": "analisar",
        "fluxo_fallback": True,
        "descricao_mov": "Intimação",
        "observacao": "Intime-se a vítima (parte autora) para ciência",
        "motivo_intimacao": "3",
        "prazo_intimacao": "3",
        "expedir_ar": True,
        "assinar_ar": True,
        "tipo_intimacao": "geral",
        "natureza": "criminal",
        "fallback": "mandado",
        "fallback_polo": "autor_especifico",
        "envia_mp": True,
        "cod_nucleo_mp": "31",
        "tipo_parecer_mp": "6",
        "prazo_mp": "5",
        "promotor_mp": "SOSTENYS MARINHO BARRETO",
        "solicitar_oficio": True,
        "oficio_template_id": 5
    }
]

print('=' * 68)
print('  TESTE intimacao_completa (intimação + MP + ofício)')
print('=' * 68)

user = User.objects.filter(is_active=True).first()
if not user:
    print('❌ Sem usuário ativo'); sys.exit(1)

svc = ProjudiService(user)
r = svc._get_session_from_cookies()
if not r:
    print('❌ Sessão Projudi indisponível — abra/log no Firefox no Projudi.')
    sys.exit(1)
session, cookies_dict = r
print(f'   ✅ Sessão OK — {user.email}')

# Acha um processo criminal real pendente (RAG ativo, preferindo TP/criminal)
rag = RAGExample.objects.filter(active=True, id=2443).first() or \
    RAGExample.objects.filter(active=True).exclude(process__isnull=True)\
    .exclude(process__number__startswith='0000008').first()
if not rag or not rag.process:
    print('❌ Nenhum RAGExample com processo para testar.')
    sys.exit(1)
proc = rag.process
proc_num = proc.number
print(f'\n📦 Processo: {proc_num}')
print(f'   RAG #{rag.id}: {rag.despacho_ato[:60]}')

# Monta mov fake (exige link_processo → proc_projudi)
mov = {
    'processo': proc_num,
    'link_processo': getattr(proc, 'projudi_url', ''),
    'movimentar': '',
}
print(f'   link_processo: {mov["link_processo"]}')
print('\n▶️ Executando sequência (1 movimentação: intimação + MP + ofício)...')
print('   ⚠️ ACOMPANHE O NAVEGADOR FIREFOX — AR e assinatura rodam nele.\n')

try:
    _executar_sequencia_rapido(
        SEQUENCIA, mov, proc_num,
        rag.despacho_observacao or rag.despacho_ato,
        session, cookies_dict, user, rag)
    print('\n✅ Sequência executada.')
except Exception as e:
    import traceback; traceback.print_exc()
    print(f'\n❌ Falha: {e}')