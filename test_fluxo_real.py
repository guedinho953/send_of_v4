"""Testa o fluxo de intimação contra o processo real 0002000-59.2026.8.05.0191.

Uso:
  source .venv/bin/activate
  python test_fluxo_real.py
"""

import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from django.apps import apps
from processes.models import RAGExample, Process, Party
User = apps.get_model('accounts.User')

from projudi.command_analyzer import CommandAnalyzer
from projudi.fluxo_decisor import FluxoDecisor
from projudi.parte_classifier import ParteClassifier
from projudi.services import ProjudiService
from projudiProcessNavigator import ProcessoParser
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# ─── Config ───
PROCESSO_CNJ = '0002000-59.2026.8.05.0191'
PROC_PROJUDI = '41020262997209'
LINK_BASE = 'https://projudi.tjba.jus.br/projudi/'

print('=' * 68)
print(f'  TESTE FLUXO INTIMAÇÃO — {PROCESSO_CNJ}')
print('=' * 68)

# ─── 1. Sessão Projudi ───
print('\n[1/5] Conectando ao Projudi...')
user = User.objects.filter(is_active=True).first()
if not user:
    print('❌ Nenhum usuário ativo')
    sys.exit(1)

service = ProjudiService(user)
result = service._get_session_from_cookies()
if not result:
    print('❌ Sessão não disponível. Firefox precisa estar logado no Projudi.')
    sys.exit(1)

session, cookies_dict = result
print(f'   ✅ Sessão OK — {user.email}')

# ─── 2. Buscar DadosProcesso ───
print(f'\n[2/5] Buscando DadosProcesso...')
url_dados = f'{LINK_BASE}listagens/DadosProcesso?numeroProcesso={PROC_PROJUDI}'
r = session.get(url_dados, timeout=30)
if r.status_code != 200:
    print(f'❌ HTTP {r.status_code}')
    sys.exit(1)
if 'expirou' in r.text.lower()[:500]:
    print('❌ Sessão expirou')
    sys.exit(1)
print(f'   ✅ Página carregada ({len(r.text)} bytes)')

# ─── 3. Extrair partes reais ───
print(f'\n[3/5] Extraindo partes do processo...')
parser = ProcessoParser(r.text)
# extrair_partes precisa do soup
partes_raw_parser = parser.extrair_partes(parser.soup)

print(f'   {len(partes_raw_parser)} parte(s) encontrada(s):')
for p in partes_raw_parser:
    nome = p.get('nome', '?')
    papel = p.get('papel', '?')
    email = p.get('email', '-') or '-'
    tel = p.get('tel', '-') or '-'
    end = f"{p.get('logradouro', '')}, {p.get('cidade', '')}/{p.get('uf', '')}"
    print(f'     [{papel:>12}] {nome}')
    print(f'               email: {email}  tel: {tel}')
    print(f'               end: {end.strip(", /") or "-"}')

# Prepara pro FluxoDecisor
partes_raw = []
for p in partes_raw_parser:
    end = f"{p.get('logradouro', '')}, {p.get('cidade', '')}/{p.get('uf', '')}".strip(', /')
    partes_raw.append({
        'name': p.get('nome', ''),
        'name_normalized': (p.get('nome_normalizado', p.get('nome', ''))).lower().strip(),
        'role': p.get('papel', ''),
        'email': p.get('email', '') or '',
        'phone': p.get('tel', '') or '',
        'address': end,
        'has_lawyer': False,
        'receives_email_intimation': bool(p.get('email')),
        'has_domicilio_cnj': False,
        'is_revel': False,
    })

clf = ParteClassifier(partes_raw)
classif = clf.classificar()

# ─── 4. Buscar movimentação da liminar ───
print(f'\n[4/5] Buscando texto da movimentação Liminar...')

# Procura na lista geral de movimentações
from projudi_client import ProjudiClient
client = ProjudiClient()
client.session = session
client.cookies = cookies_dict

texto_liminar = ''
pages = client.obter_paginas_finais_movimentacoes(quantidade=3)
encontradas = 0
for p in pages:
    data = {'pagina': str(p), 'loginJuiz': ''}
    rp = session.post(client.URL_MOVIMENTACOES, data=data, timeout=15)
    if len(rp.text) <= 1000:
        continue
    sp = BeautifulSoup(rp.text, 'html.parser')
    movs = client.extrair_links_movimentacoes(sp)
    for m in movs:
        if PROCESSO_CNJ not in m.get('processo', ''):
            continue
        encontradas += 1
        doc_url = m.get('link_documento', '')
        if not doc_url:
            continue
        if not doc_url.startswith('http'):
            doc_url = urljoin(LINK_BASE, doc_url)
        try:
            rd = session.get(doc_url, timeout=30)
            if rd.status_code == 200:
                texto_liminar = BeautifulSoup(rd.text, 'html.parser').get_text(' ', strip=True)
                print(f'   📄 Mov: {m.get("tipo", "?")} — {doc_url[:80]}...')
                print(f'   📝 Texto: {texto_liminar[:150]}...')
        except Exception as e:
            print(f'   ⚠️ Erro ao baixar doc: {e}')

if not texto_liminar:
    print('   ⚠️ Não foi possível recuperar o texto, usando despacho_ato do RAGExample')

# ─── 5. Executar CommandAnalyzer + FluxoDecisor ───
print(f'\n[5/5] CommandAnalyzer + FluxoDecisor')

# Texto da liminar ou fallback pro despacho_ato do RAG
rag = RAGExample.objects.get(id=2446)
texto_analise = texto_liminar or rag.despacho_ato

ca = CommandAnalyzer()
ca_result = ca.analisar(texto_analise)
print(f'\n   CommandAnalyzer:')
print(f'     Tipo: {ca_result["tipo"]}')
print(f'     Cumprível: {ca_result["cumprivel"]}')
for i, cmd in enumerate(ca_result.get('comandos', [])):
    print(f'     Comando {i+1}:')
    print(f'       ato: {cmd.get("ato")}')
    print(f'       tipo_cumprimento: {cmd.get("tipo_cumprimento")}')
    print(f'       destinatario: {cmd.get("destinatario")}')

cmd = ca_result['comandos'][0] if ca_result.get('comandos') else {}
ato_data = {
    'tipo_ato': cmd.get('tipo_cumprimento', 'intimacao'),
    'act_verb': cmd.get('ato', 'intimem-se'),
    'destinatario_texto': ' '.join(cmd.get('destinatario', [])),
}

print(f'\n   FluxoDecisor:')
print(f'     ato_data: {ato_data}')
decisor = FluxoDecisor(partes_raw, classif.get('partes', []), ato_data)
decisao = decisor.decidir()

for p in decisao.get('partes', []):
    print(f'\n     ► {p["nome"]}')
    print(f'        Fluxo: {p["fluxo"]}')
    print(f'        Justificativa: {p["justificativa"]}')
    if p.get('canais_possiveis'):
        canais = [c['canal'] for c in p['canais_possiveis'][:3]]
        print(f'        Canais possíveis: {canais}')

print(f'\n   Resumo:')
for fluxo, nomes in decisao.get('resumo', {}).get('fluxos', {}).items():
    print(f'     {fluxo}: {nomes}')

# ─── Resumo Final ───
print(f'\n{"="*68}')
print('  RESUMO DO FLUXO')
print('=' * 68)
print(f'''
  RAGExample #2446 matchou com 93% de interseção
  Sequência vinculada: {rag.sequencia_cumprimento}
  
  OPÇÃO ATUAL (sequência fixa):
    → Executa Mov581 + click Intimar no DJEN
    → Todas as partes intimadas eletronicamente
  
  OPÇÃO B (híbrido — recomendada):
    → CommandAnalyzer identificou: "{cmd.get("ato")}" ({cmd.get("tipo_cumprimento")})
    → FluxoDecisor decide canal individual')
''')

# Mostra o fluxo atual vs. opção B
print(f'  │ Parte                          │ Atual (sequência) │ Opção B (dinâmico) │')
print(f'  │{"─"*32}│{"─"*20}│{"─"*20}│')
for p in decisao.get('partes', []):
    nome_p = p['nome'][:30].ljust(30)
    fluxo_b = p['fluxo'].ljust(18)
    print(f'  │ {nome_p}│ intimacao_eletronica │ {fluxo_b}│')

print(f'\n{"="*68}')
