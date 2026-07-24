"""Teste comparativo das 3 opções de fluxo para RAGExample #2446.

Uso:
  source .venv/bin/activate
  python test_fluxo_opcoes.py
"""

import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.models import RAGExample, Process, Party
from projudi.command_analyzer import CommandAnalyzer
from projudi.fluxo_decisor import FluxoDecisor
from projudi.parte_classifier import ParteClassifier

# ─── Carrega dados reais ───
rag = RAGExample.objects.get(id=2446)
proc = Process.objects.filter(number=rag.process.number).first()
partes = Party.objects.filter(process=proc) if proc else []

print('=' * 68)
print('  DADOS DE ENTRADA')
print('=' * 68)
print(f'\nRAGExample #2446')
print(f'  Despacho ato:    {rag.despacho_ato}')
print(f'  Seq cumprimento: {json.dumps(rag.sequencia_cumprimento, indent=4)}')
print(f'  Suggested tmpl:  {[t.name for t in rag.suggested_templates.all()]}')

print(f'\nProcesso: {proc.number if proc else "N/A"}')
print(f'Partes:')
for p in partes:
    print(f'  [{p.role:>12}] {p.name}')
    print(f'          end: {p.address or "-"}')
    print(f'          email: {p.email or "-"}')

# ─── Prepara dados para os fluxos ───
partes_raw = []
for p in partes:
    partes_raw.append({
        'id': p.id, 'name': p.name,
        'name_normalized': (p.name or '').lower().strip(),
        'role': p.role or '', 'email': p.email or '',
        'phone': p.phone or '', 'address': p.address or '',
        'has_lawyer': False, 'receives_email_intimation': bool(p.email),
        'has_domicilio_cnj': False, 'is_revel': False,
    })

clf = ParteClassifier(partes_raw)
classif = clf.classificar()

# ─── CommandAnalyzer ───
ca = CommandAnalyzer()
ca_result = ca.analisar(rag.despacho_ato)
cmd = ca_result['comandos'][0] if ca_result.get('comandos') else {}
ato_data = {
    'tipo_ato': cmd.get('tipo_cumprimento', 'intimacao'),
    'act_verb': cmd.get('ato', 'intimem-se'),
    'destinatario_texto': ' '.join(cmd.get('destinatario', [])),
}

print(f'\n{"="*68}')
print('  COMMANDANALYZER')
print('=' * 68)
print(f'  Tipo doc:  {ca_result["tipo"]}')
print(f'  Cumprivel: {ca_result["cumprivel"]}')
print(f'  Comandos:')
for i, c in enumerate(ca_result.get('comandos', [])):
    print(f'    [{i+1}] ato={c.get("ato")} tipo_cumprimento={c.get("tipo_cumprimento")}')
    print(f'        destinatario={c.get("destinatario")}')

# ════════════════════════════════════════════════════════════════
# OPÇÃO A — Remove sequência, usa CommandAnalyzer + FluxoDecisor
# ════════════════════════════════════════════════════════════════
print(f'\n{"="*68}')
print('  OPÇÃO A — REMOVER SEQUÊNCIA + FLUXO DINÂMICO')
print('  (CommandAnalyzer → FluxoDecisor → expede individual)')
print('=' * 68)

print(f'\n  Passo 1: CommandAnalyzer')
print(f'    Tipo cumprimento: {cmd.get("tipo_cumprimento")}')
print(f'    Destinatário: {cmd.get("destinatario")}')
print(f'    Ato: {cmd.get("ato")}')

print(f'\n  Passo 2: FluxoDecisor decide canal p/ cada parte')
decisor = FluxoDecisor(partes_raw, classif.get('partes', []), ato_data)
decisao_a = decisor.decidir()

partes_a = decisao_a.get('partes', [])
for p in partes_a:
    print(f'\n    ► {p["nome"]}')
    print(f'      Fluxo: {p["fluxo"]}')
    print(f'      Justificativa: {p["justificativa"]}')
    if p.get('canais_possiveis'):
        print(f'      Canais: {[c["canal"] for c in p["canais_possiveis"][:3]]}')

print(f'\n  Resumo fluxos:')
for fluxo, nomes in decisao_a.get('resumo', {}).get('fluxos', {}).items():
    print(f'    {fluxo}: {nomes}')

print(f'\n  >>> AÇÃO REAL: para cada parte, gerar template e expedir no canal definido')
print(f'      Ex: VICTOR → email (template de intimação)')
print(f'      Ex: ESTADO → edital (publicação no DJE)')

# ════════════════════════════════════════════════════════════════
# OPÇÃO B — Mantém sequência, mas CommandAnalyzer enriquece
# ════════════════════════════════════════════════════════════════
print(f'\n{"="*68}')
print('  OPÇÃO B — SEQUÊNCIA + COMMANDANALYZER ENRIQUECE')
print('  (sequência existe, mas CommandAnalyzer identifica')
print('   destinatários e FluxoDecisor decide canal)')
print('=' * 68)

print(f'\n  Passo 1: CommandAnalyzer extrai destinatários do texto')
print(f'    Destinatário raw: {cmd.get("destinatario")}')
print(f'    → "partes" significa: ESTADO DA BAHIA + VICTOR FELIPE')

print(f'\n  Passo 2: Para cada parte, FluxoDecisor decide canal')
for p in partes_a:
    print(f'    ► {p["nome"]} → {p["fluxo"]}')

print(f'\n  Passo 3: Step da sequência é executado de forma ADAPTADA')
print(f'    Step original: "intimacao_eletronica" (Mov581 + click Intimar)')
print(f'    Comportamento adaptado por parte:')
for p in partes_a:
    canal = p['fluxo']
    nome = p['nome'][:30]
    if canal == 'eletronico' or canal == 'advogado':
        print(f'      {nome}: mantém intimacao_eletronica (click Intimar no DJEN)')
    elif canal == 'email':
        print(f'      {nome}: expede por email (template de intimação + envio)')
    elif canal == 'edital':
        print(f'      {nome}: publica edital no DJE')
    elif canal == 'ar':
        print(f'      {nome}: expede AR (correios)')
    elif canal == 'mandado':
        print(f'      {nome}: expede mandado (oficial de justiça)')

# ════════════════════════════════════════════════════════════════
# OPÇÃO C — Step composto: analisa → decide → executa
# ════════════════════════════════════════════════════════════════
print(f'\n{"="*68}')
print('  OPÇÃO C — STEP COMPOSTO (analyzer + decisor + dispatcher)')
print('  (cada ato é analisado, canal decidido, e executado)')
print('=' * 68)

print(f'\n  Passo 1: Texto completo → CommandAnalyzer')
print(f'    Extrai TODOS os comandos do despacho')

print(f'\n  Passo 2: Cada comando → FluxoDecisor → canal')
for i, c in enumerate(ca_result.get('comandos', [])):
    print(f'\n    Comando [{i+1}]: "{c.get("ato")}" → {c.get("tipo_cumprimento")}')
    print(f'    Destinatário: {c.get("destinatario")}')
    for p in partes_a:
        print(f'      ► {p["nome"]} → {p["fluxo"]}')

print(f'\n  Passo 3: Dispatcher executa o step adequado p/ cada parte+canal')
print(f'    Mapeamento canal → step executor:')
print(f'      eletronico   → intimacao_eletronica (Mov581 + click Intimar)')
print(f'      advogado     → intimacao_eletronica (DJEN p/ adv)')
print(f'      email        → expedir_email(template, parte)')
print(f'      ar           → expedir_ar(template, parte)')
print(f'      mandado      → expedir_mandado(template, parte)')
print(f'      edital       → expedir_edital(parte)')
print(f'      oficio       → expedir_oficio(template, parte)')

# ════════════════════════════════════════════════════════════════
# COMPARAÇÃO FINAL
# ════════════════════════════════════════════════════════════════
print(f'\n{"="*68}')
print('  🆚 COMPARAÇÃO RESUMO')
print('=' * 68)
print(f'''
  ATUAL (sequência fixa):
    ├── ESTADO DA BAHIA  → intimacao_eletronica (click Intimar no DJEN)
    └── VICTOR FELIPE    → intimacao_eletronica (click Intimar no DJEN)
    Obs: todos viram o mesmo DJEN, simples e rápido

  OPÇÃO A (dinâmico):
    ├── ESTADO DA BAHIA  → edital (publicação, sem email/endereço)
    └── VICTOR FELIPE    → email (victor.souza@email.com)
    Obs: mais correto juridicamente, mas mais complexo

  OPÇÃO B (híbrido):
    ├── ESTADO DA BAHIA  → step mantido: intimacao_eletronica (DJEN)
    └── VICTOR FELIPE    → email (com template de intimação)
    Obs: melhor middle-ground, usa sequência + decisão dinâmica

  OPÇÃO C (full composto):
    ├── Step 1: analisar texto → identificar comando "intimem-se"
    ├── Step 2: decidir canal p/ cada parte
    └── Step 3: executar step adequado p/ cada canal
    Obs: mais extensível, mas maior mudança na arquitetura
''')
