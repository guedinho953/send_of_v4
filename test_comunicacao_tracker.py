"""Teste do ComunicacaoTracker — emparelhamento de comunicações."""
import sys, os
sys.path.insert(0, '/home/ivan/PythonProjects/send_of_v4')
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
import django; django.setup()

from projudi.comunicacao_tracker import ComunicacaoTracker


# ── CENÁRIO: Processo com movimentações reais de intimação ──
movimentacoes = [
    # Evento 181: Despacho do juiz determinando intimação
    {
        'evento': '181',
        'ato': 'DESPACHO¹: Intime-se a parte autora para pagar o débito remanescente no prazo de 15 dias.',
        'ato_normalizado': 'despacho¹: intime-se a parte autora para pagar o débito remanescente no prazo de 15 dias.',
        'data_texto': '10/06/26',
        'data_obj': None,
        'autor': 'MARTINHO FERRAZ DA NOBREGA JUNIOR',
        'observacao': '',
        'destinatario': '',
        'category': 'despacho',
        'communication_status': '',
        'communication_means': '',
        'evento_referenciado': '',
    },
    # Evento 182: Certidão — expedição da intimação
    {
        'evento': '182',
        'ato': 'Certidão — Expedido(a) — Intimação — Advgs. DJEN — referente ao evento 181 (10/06/26)',
        'ato_normalizado': 'certidão — expedido(a) — intimação — advgs. djen — referente ao evento 181 (10/06/26)',
        'data_texto': '11/06/26',
        'data_obj': None,
        'autor': 'SECRETARIA JUDICIAL',
        'observacao': 'Intimação expedida para MUNICÍPIO DE PAULO AFONSO via DJEN.',
        'destinatario': {'nome': 'MUNICÍPIO DE PAULO AFONSO', 'papel': 'PROMOVIDO'},
        'category': 'intimacao',
        'communication_status': 'expedida',
        'communication_means': 'domicilio_cnj',
        'evento_referenciado': '181',
    },
    # Evento 183: Despacho citando executado
    {
        'evento': '183',
        'ato': 'Cite-se o executado para pagar em 24h ou nomear bens.',
        'ato_normalizado': 'cite-se o executado para pagar em 24h ou nomear bens.',
        'data_texto': '12/06/26',
        'data_obj': None,
        'autor': 'MARTINHO FERRAZ DA NOBREGA JUNIOR',
        'observacao': '',
        'destinatario': '',
        'category': 'despacho',
        'communication_status': '',
        'communication_means': '',
        'evento_referenciado': '',
    },
    # Evento 184: Certidão — mandado solicitado
    {
        'evento': '184',
        'ato': 'Solicitada a Expedição de Mandado — Citação — executado: JOSE CARLOS PEREIRA',
        'ato_normalizado': 'solicitada a expedição de mandado — citação — executado: jose carlos pereira',
        'data_texto': '13/06/26',
        'data_obj': None,
        'autor': 'SECRETARIA JUDICIAL',
        'observacao': 'Mandado de citação expedido para JOSE CARLOS PEREIRA.',
        'destinatario': {'nome': 'JOSE CARLOS PEREIRA', 'papel': 'PROMOVIDO'},
        'category': 'citacao',
        'communication_status': 'expedida',
        'communication_means': 'mandado',
        'evento_referenciado': '183',
    },
    # Evento 190: Leitura da intimação (evento 182)
    {
        'evento': '190',
        'ato': 'Certidão — Lido(a) — Intimação — Advgs. — referente ao evento 182 (11/06/26)',
        'ato_normalizado': 'certidão — lido(a) — intimação — advgs. — referente ao evento 182 (11/06/26)',
        'data_texto': '15/06/26',
        'data_obj': None,
        'autor': 'MUNICÍPIO DE PAULO AFONSO',
        'observacao': '',
        'destinatario': {'nome': 'MUNICÍPIO DE PAULO AFONSO', 'papel': 'PROMOVIDO'},
        'category': 'intimacao',
        'communication_status': 'lida',
        'communication_means': 'domicilio_cnj',
        'evento_referenciado': '182',
    },
]

print('=' * 70)
print('  COMUNICACAO TRACKER — EMPARELHAMENTO')
print('=' * 70)

tracker = ComunicacaoTracker(movimentacoes)

# --- PRE-CHECK: Já existe intimação para Município? ---
print('\n📋 PRE-CHECK 1: Já existe intimação para MUNICÍPIO DE PAULO AFONSO?')
r = tracker.ja_expedida('intimacao', 'MUNICÍPIO DE PAULO AFONSO')
print(f'   Existe: {r["existe"]}')
print(f'   Situação: {r["situacao"]}')
print(f'   Evento: {r["evento"]}')
print(f'   Mensagem: {r["mensagem"][:100]}')
assert r['existe'] == True
assert r['situacao'] == 'lida'  # já foi lida
print('   ✅')

# --- PRE-CHECK: Já existe citação para JOSE? ---
print('\n📋 PRE-CHECK 2: Já existe citação para JOSE CARLOS PEREIRA?')
r = tracker.ja_expedida('citacao', 'JOSE CARLOS PEREIRA')
print(f'   Existe: {r["existe"]}')
print(f'   Situação: {r["situacao"]}')
print(f'   Evento: {r["evento"]}')
print(f'   Mensagem: {r["mensagem"][:100]}')
assert r['existe'] == True
assert r['situacao'] == 'mandado_solicitado'
print('   ✅')

# --- PRE-CHECK: Intimação para alguém que não foi intimado ---
print('\n📋 PRE-CHECK 3: Já existe intimação para EMPRESA XYZ (não existe)?')
r = tracker.ja_expedida('intimacao', 'EMPRESA XYZ')
print(f'   Existe: {r["existe"]}')
print(f'   Mensagem: {r["mensagem"]}')
assert r['existe'] == False
print('   ✅')

# --- POST-CHECK: Rastrear resultado da citação ---
print('\n📋 POST-CHECK 4: Rastrear resultado da citação de JOSE CARLOS PEREIRA')
r = tracker.rastrear_resultado('proc123', 'cite-se', 'JOSE CARLOS PEREIRA', 'mandado')
print(f'   Encontrou: {r["encontrou"]}')
print(f'   Situação: {r["situacao"]}')
print(f'   Mensagem: {r["mensagem"]}')
assert r['encontrou'] == False  # ainda não foi lida/devolvida
assert r['situacao'] == 'pendente'
print('   ✅')

# --- RESUMO ---
print('\n📊 RESUMO DO PROCESSO:')
resumo = tracker.resumo()
print(f'   Total expedidas: {resumo["total_expedidas"]}')
print(f'   Total lidas/devolvidas: {resumo["total_lidas"]}')
print(f'   Com retorno: {resumo["com_retorno"]}')
print(f'   Sem retorno: {resumo["sem_retorno"]}')
assert resumo['total_expedidas'] == 2  # 1 expedida + 1 mandado_solicitado
assert resumo['com_retorno'] == 1  # uma já retornou (intimação)
assert resumo['sem_retorno'] == 1  # mandado de citação ainda pendente
print('   ✅')

# --- PARES DETALHADOS ---
print('\n🔗 PARES:')
for par in resumo['pares']:
    exp = par['expedicao']
    status = par['status']
    print(f'   📤 Evento {exp["evento"]}: {exp["tipo"]} → {exp["destinatario"][:40]}')
    if par['retorno']:
        ret = par['retorno']
        print(f'   📥 Retorno evento {ret["evento"]}: {ret["situacao"]}')
    else:
        print(f'   ⏳ Sem retorno ainda')
    print(f'   🏷️  Status: {status}')
    print()

print('=' * 70)
print('  ✅ TODOS OS TESTES PASSARAM')
print('=' * 70)
