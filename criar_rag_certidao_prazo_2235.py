"""Cria RAGExample (intimação eletrônica + observação de prazo) p/ o processo
0002235-26.2026.8.05.0191 (41020263379522) e liga um CumprimentoRecord.

Observação de prazo (certidão_prazo) vai na OBSERVAÇÃO da Mov581; NÃO expede
o documento de certidão (expede_certidao_prazo=false).

Uso: python criar_rag_certidao_prazo_2235.py
"""
import os, sys, json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import django; django.setup()

from processes.models import Process, RAGExample, Movement
from projudi.models import CumprimentoRecord
from accounts.models import User

PROC_CNJ = '0002235-26.2026.8.05.0191'
PROC_INTERNO = '41020263379522'
REUS = 'BANCO BRADESCO S.A. e SERASA S A'

# ── Texto real do despacho do evento 13 (que gerou o prazo de 10 dias) ──
proc = Process.objects.filter(number=PROC_CNJ).first() \
    or Process.objects.filter(number_normalized__icontains='2235262026').first()
if not proc:
    raise SystemExit('Processo não encontrado no banco (rode scripts/pegar_atos_processo.py).')
mov13 = Movement.objects.filter(process=proc, event_number='13').first()
despacho_obs = (mov13.observation or '') if mov13 else ''
# tira o prefixo [DOC:
if '[DOC:' in despacho_obs:
    despacho_obs = despacho_obs.split('[DOC:', 1)[1].split(']', 1)[1].strip()
print('Despacho evento 13:\n', despacho_obs[:260], '\n')

SEQUENCIA = [
    {
        'tipo': 'movimentacao',          # intimação eletrônica (flujo eletronico)
        'observacao_prazo': True,        # observação da certidão de prazo → Mov581
        'expede_certidao_prazo': False,  # NÃO expede o documento de certidão
        'polo_prazo': 'reu',             # todos os réus
    }
]

rag, created = RAGExample.objects.update_or_create(
    process=proc,
    tenant=proc.tenant,
    despacho_ato='Intimação',
    defaults={
        'oficio': '',
        'despacho_observacao': despacho_obs or 'Intime-se a parte demandada no prazo de 10 dias.',
        'despacho_data': str(mov13.act_date) if mov13 else '',
        'despacho_autor': '',
        'evento_despacho': '13',
        'cumprimentos': [],
        'documentos': [],
        'sequencia_cumprimento': SEQUENCIA,
        'active': True,
    },
)
print(f'RAGExample #{rag.id} {"(criado)" if created else "(atualizado)"}')
print('  seq:', json.dumps(rag.sequencia_cumprimento, ensure_ascii=False))

# ── CumprimentoRecord (intimação eletrônica, réus) ──
user = User.objects.filter(is_active=True).first()
rec, rcreated = CumprimentoRecord.objects.update_or_create(
    processo=PROC_INTERNO,
    numero_processo_cnj=PROC_CNJ,
    defaults={
        'fluxo': 'eletronico',
        'status': 'pendente',
        'parte_nome': REUS,
        'parte_papel': 'reu',
        'rag_example': rag,
        'snippet': despacho_obs[:2000] or 'Intime-se a parte demandada no prazo de 10 dias.',
        'url_processo': proc.projudi_url or '',
        'user': user,
    },
)
print(f'\nCumprimentoRecord #{rec.id} {"(criado)" if rcreated else "(atualizado)"}')
print('  fluxo=%s status=%s parte_nome=%r parte_papel=%r rag=%s' % (
    rec.fluxo, rec.status, rec.parte_nome, rec.parte_papel, rag.id))

# ── Preview da observação que vai para a Mov581 ──
from projudi.cumprimento_service import CumprimentoService
svc = CumprimentoService(user=user)
out = svc.montar_json_envio(rec)
print('\n== PREVIEW do que vai na movimentação ==')
print('prazo_calculado=%s certidao=%s observacao_prazo=%s' % (
    out['prazo_calculado'], out['certidao'], out['observacao_prazo']))
print('prazo:', json.dumps(out.get('prazo') or {}, ensure_ascii=False, default=str)[:260])
print('\nOBSERVAÇÃO (vai na Mov581):\n', out.get('observacao', ''))
print('\ntexto_certidao (vazio = NÃO expede certidão):', repr(out.get('texto_certidao', '')))
