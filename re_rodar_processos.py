"""Re-roda o fluxo nos processos que falharam, para validar as correções.

Cada processo usa expedir_processo_especifico (match RAG + sequencia_cumprimento).
Requer sessão Projudi ativa (Firefox logado). Corre com as correções desta
sessão: seleção robusta do tipo de doc, prazos (despacho=5d/sentença=10d),
polo no painel, assinar_ar default false.

Uso:
  source .venv/bin/activate
  python re_rodar_processos.py [nº a rodar]
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

# CNJ dos processos que falharam (05/08 sessão anterior)
PROCESSOS = [
    '0001507-82.2026.8.05.0191',   # interno 41020262339469
    '0001503-45.2026.8.05.0191',    # 41020262334106
    '0000623-53.2026.8.05.0191',   # 41020261016340
    '0000677-19.2026.8.05.0191',   # 41020261089461
    '0003467-10.2025.8.05.0191',   # 41020254320329
    '0000624-38.2026.8.05.0191',   # 41020261016795
    '0003552-93.2025.8.05.0191',   # 41020254419220
]

# Permite rodar só alguns (ex: python re_rodar_processos.py 3 = só os 3 primeiros)
if len(sys.argv) > 1:
    n = int(sys.argv[1])
    PROCESSOS = PROCESSOS[:n]

from expedir_rapido import expedir_processo_especifico

print('=' * 70)
print(f'  RE-RODANDO {len(PROCESSOS)} PROCESSOS (correções aplicadas)')
print('=' * 70)

resultados = {}
for i, cnj in enumerate(PROCESSOS, 1):
    print(f'\n\n[{i}/{len(PROCESSOS)}] ================= {cnj} =================')
    print('   ▶️ RODANDO (acompanhe o Firefox)...\n')
    try:
        expedir_processo_especifico(cnj)
        resultados[cnj] = 'rodou'
    except Exception as e:
        import traceback; traceback.print_exc()
        resultados[cnj] = f'erro: {e}'
    if i < len(PROCESSOS):
        print(f'\n   ⏳ aguardando 3s antes do próximo...')
        time.sleep(3)

print('\n' + '=' * 70)
print('  RESUMO (verifique cada um no fiscalizar_processo.py)')
print('=' * 70)
for cnj, res in resultados.items():
    print(f'  {cnj}: {res}')
print('\n✅ Concluído. Use: python fiscalizar_processo.py <CNJ> para conferir status.')