"""Validação OFFLINE (sem Playwright/sessão) da maquinaria de certidão de prazo
reutilizada no batch. NÃO executa nada no Projudi real.
"""
import os, sys, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from types import SimpleNamespace
from accounts.models import User
from processes.models import RAGExample, DocumentTemplate
from projudi.cumprimento_service import CumprimentoService

OK = 0
FAIL = 0
def checa(nome, cond, extra=''):
    global OK, FAIL
    if cond:
        OK += 1
        print(f'  ✅ {nome}')
    else:
        FAIL += 1
        print(f'  ❌ {nome} {extra}')

# ── 1) RAG #2538 presente e com as flags certas ──────────────────────
try:
    rag = RAGExample.objects.get(id=2538)
    print(f'RAG #2538: "{rag.despacho_ato or rag.titulo or ""}"')
    seq = rag.sequencia_cumprimento or []
    print(f'  sequencia_cumprimento tem {len(seq)} passo(s)')
    passo_mov = next((p for p in seq if isinstance(p, dict) and p.get('tipo') == 'movimentacao'), None)
    if passo_mov:
        chave = ('expede_certidao_prazo', 'observacao_prazo', 'polo_prazo',
                 'decurso_prazo', 'exigir_intimacao_penhora')
        print(f'  passo movimentacao flags: { {k: passo_mov.get(k) for k in chave} }')
        checa('RAG #2538 tem expede_certidao_prazo=True',
              bool(passo_mov.get('expede_certidao_prazo')))
        checa('RAG #2538 polo_prazo presente', bool(passo_mov.get('polo_prazo')))
        checa('RAG #2538 exigir_intimacao_penhora presente',
              bool(passo_mov.get('exigir_intimacao_penhora')))
        # record stub para _config_prazo_do_rag (estático, lê via getattr)
        stub = SimpleNamespace(rag_example=rag, fluxo='movimentacao_simples',
                               snippet='Certifique-se o decurso do prazo para impugnação à penhora',
                               parte_papel='')
        cfg = CumprimentoService._config_prazo_do_rag(stub)
        print(f'  _config_prazo_do_rag => {cfg}')
        checa('config lê polo_prazo', cfg.get('polo_prazo') == passo_mov.get('polo_prazo'))
        checa('config lê expede_certidao_prazo=True', cfg.get('expede_certidao_prazo') is True)
    else:
        print('  ⚠️ RAG #2538 sem passo "movimentacao" na sequência')
except RAGExample.DoesNotExist:
    print('  ⚠️ RAG #2538 não encontrada no banco — pulando validação de config.')

# ── 2) Template fixo "Certidão de Prazo" existe ──────────────────────
try:
    tpl = DocumentTemplate.objects.get(name='Certidão de Prazo', active=True)
    print(f'Template "Certidão de Prazo": id={tpl.id}, type={tpl.template_type}')
    checa('Template Certidão de Prazo existe (id 11)', tpl.id == 11)
except DocumentTemplate.DoesNotExist:
    print('  ⚠️ Template "Certidão de Prazo" não encontrado — _html_certidao_prazo usará fallback HTML.')
    tpl = None

# ── 3) Geração do HTML da certidão OFFLINE (receita do reference) ────
user = User.objects.filter(is_active=True).first()
svc = CumprimentoService.__new__(CumprimentoService)
svc.user = user
rec = SimpleNamespace(
    rag_example=rag if 'rag' in dir() else None,
    fluxo='movimentacao_simples',
    snippet='Certifique-se o decurso do prazo para impugnação à penhora',
    numero_processo_cnj='0001234-40.2025.8.05.0191',
    processo='654321',
    parte_nome='LADO INDUSTRIA TEXTIL LTDA',
    parte_papel='ambos',
    observacao_prazo=('Decorrido o prazo em 18/08/2026, intimação lida '
                      '(intimação) em 08/08/2026, inicio do prazo 10/08/2026, '
                      'ultimo dia do prazo 15/08/2026.'),
    prazo_info={
        'data_inicio': '2026-08-08', 'ultimo_dia': '2026-08-15',
        'data_decurso': '2026-08-18', 'dias_contados': ['2026-08-10'],
        'prazo_dias': 5, 'modo': 'uteis', 'djen': False, 'vencido': True,
    },
)
html = svc._html_certidao_prazo(rec)
print(f'HTML da certidão ({len(html)} chars), 150 primeiros:')
print(html[:150].replace('\n', ' '))
checa('HTML certidão gerado (não vazio)', bool(html and html.strip()))
cruz = '"00/00/00"' not in html and 'especifico' not in html and '00/00/00' not in html
checa('HTML sem placeholders crus (00/00/00 / especifico)', cruz)
checa('HTML contém CERTIDÃO DE PRAZO', 'CERTID' in html.upper())

# papel resolvido (polo_prazo da RAG 'ambos')
papel = CumprimentoService._papel_resolvido(rec)
print(f'  _papel_resolvido => {papel!r}')
checa('papel resolvido = ambos (polo_prazo da RAG)', papel == 'ambos')

# ── 4) Helpers do batch (placeholders do passo 2 + rota) ─────────────
p = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, p)
from expedir_rapido import (
    _preencher_obs_prazo, _rota_prazo_pre_activate, _fmt_data_prazo)

# a) preencher obs do passo 2 (intimacao_eletronica) com dados reais
obs_r2 = ('Decorrido o prazo reu/autor/ambos especifico em 00/00/00. '
          'Intimação(DJEN OU adv ou email, ou ar) em 00/00/00, '
          'início do prazo 00/00/00 ultimo dia do prazo 00/00/00')
ctx = {
    'polo': 'ambos',
    'prazo_info': {
        'data_inicio': '2026-08-08', 'ultimo_dia': '2026-08-15',
        'data_decurso': '2026-08-18', 'dias_contados': ['2026-08-10'],
        'prazo_dias': 5, 'modo': 'uteis'},
}
obs_preenchido = _preencher_obs_prazo(obs_r2, ctx)
print(f'\nObs passo 2 (preenchida): {obs_preenchido}')
checa('obs passo 2 sem "00/00/00"', '00/00/00' not in obs_preenchido)
checa('obs passo 2 sem "especifico"', 'especifico' not in obs_preenchido)
checa('obs passo 2 tem data real 18/08/2026', '18/08/2026' in obs_preenchido)
checa('obs passo 2 identifica polo (autores e réus)',
      'autores' in obs_preenchido and 'réus' in obs_preenchido)

# b) _preencher_obs_prazo inócuo sem contexto de prazo
checa('_preencher_obs_prazo inócuo sem ctx_prazo',
      _preencher_obs_prazo('obs qualquer', {}) == 'obs qualquer')

# c) _rota_prazo_pre_activate
if 'rag' in dir():
    passo1 = {'tipo': 'movimentacao', 'expede_certidao_prazo': True,
              'polo_prazo': 'ambos'}
    passo_normal = {'tipo': 'movimentacao'}
    checa('rota ativa p/ passo c/ expede_certidao_prazo',
          _rota_prazo_pre_activate(passo1, rag) is True)
    checa('rota inativa sem flags (protege mov genérica)',
          _rota_prazo_pre_activate(passo_normal, rag) is False)
    checa('rota inativa sem RAG',
          _rota_prazo_pre_activate(passo1, None) is False)

# d) _fmt_data_prazo
from datetime import date
checa('_fmt_data_prazo(date)', _fmt_data_prazo(date(2026, 8, 18)) == '18/08/2026')
checa('_fmt_data_prazo(str ISO)', _fmt_data_prazo('2026-08-18') == '18/08/2026')

print(f'\nRESULTADO: {OK} OK, {FAIL} FAIL')
sys.exit(1 if FAIL else 0)
