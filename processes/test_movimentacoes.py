"""
Teste manual do MovimentacoesService.
Rode: python manage.py shell < processes/test_movimentacoes.py
Ou:   python manage.py shell
>>> exec(open('processes/test_movimentacoes.py').read())
"""

import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from datetime import date
from processes.movimentacoes_service import MovimentacoesService, extrair_comandos, classificar_movimentacao, situacao_comunicacao

# Teste 1: Extrair comandos de um despacho
texto_teste = """
DESPACHO¹

Diante do explanado pela parte autora (evento 193) e planilha de evento 184,
intimem-se as executadas para pagarem o débito remanescente de R$ 943,18
e/ou manifestar no prazo de 15 dias,
sob pena de prosseguimento do feito com consequente penhora.
"""

print("="*60)
print("TESTE 1: Extrair comandos de despacho")
print("="*60)

comandos = extrair_comandos(texto_teste, "despacho")
print(f"Comandos encontrados: {len(comandos)}")
for i, c in enumerate(comandos, 1):
    print(f"\n  Comando {i}:")
    print(f"    ato: {c['ato']}")
    print(f"    cumprivel: {c['cumprivel']}")
    print(f"    destinatario: {c['destinatario']}")
    print(f"    meio: {c['meio']}")
    print(f"    objetivo: {c['objetivo']}")
    print(f"    prazo: {c['prazo']}")
    print(f"    condicoes: {c['condicoes']}")

# Teste 2: Classificar movimentacoes
movimentacoes_teste = [
    "Intimação expedida p/ parte ré (advogado)",
    "Sentença - julgo procedente o pedido",
    "Mandado assinado e à disposição",
    "Aviso de Recebimento juntado (Referente ao evento 45)",
    "Decisão - indefiro a liminar",
    "Petição da parte autora",
]

print("\n" + "="*60)
print("TESTE 2: Classificar movimentacoes")
print("="*60)
for mov in movimentacoes_teste:
    tipo, scores = classificar_movimentacao(mov)
    print(f"  [{tipo:12s}] {mov[:50]}...")

# Teste 3: Situacao comunicacao
print("\n" + "="*60)
print("TESTE 3: Detectar situacao de comunicacao")
print("="*60)
situacoes_teste = [
    "Intimação expedida",
    "Intimação lida em 10/07/26",
    "Devolução sem leitura",
    "Mandado devolvido",
    "Juntada de AR",
]
for s in situacoes_teste:
    print(f"  [{situacao_comunicacao(s) or 'N/A':20s}] {s}")

# Teste 4: Service completo (com HTML falso)
print("\n" + "="*60)
print("TESTE 4: Pipeline completo com MovimentacoesService")
print("="*60)

from processes.models import Process

# Criar processo de teste usando tenant existente
from accounts.models import Tenant
tenant_teste = Tenant.objects.first()
if not tenant_teste:
    tenant_teste = Tenant.objects.create(cnpj='12345678000195', name='Teste Cartorio')

processo_teste, _ = Process.objects.update_or_create(
    number="0001306-27.2025.8.05.0191",
    defaults={
        'status': 'analyzing',
        'number_normalized': '00013062720258050191',
        'tenant': tenant_teste,
    }
)

# HTML simplificado do Projudi (apenas estrutura basica)
html_teste = """<!DOCTYPE html>
<html><body>
<table class="tabelaLista">
<tr class="linhaClara" id="tr1">
<td>1</td>
<td>Intimação expedida p/ João Silva (advogado)</td>
<td>10/07/26</td>
<td>Juiz</td>
</tr>
<tr class="linhaEscura" id="tr2">
<td>2</td>
<td>Intimação lida em 12/07/26 (Referente ao evento 1)</td>
<td>12/07/26</td>
<td>Sistema</td>
</tr>
<tr class="linhaClara" id="tr3">
<td>3</td>
<td>Despacho: intimem-se as partes para manifestar no prazo de 15 dias</td>
<td>15/07/26</td>
<td>Juiz</td>
</tr>
<tr class="linhaEscura" id="tr4">
<td>4</td>
<td>Sentença - julgo procedente o pedido, condeno a parte ré</td>
<td>20/07/26</td>
<td>Juiz</td>
</tr>
</table>
</body></html>"""

service = MovimentacoesService(user=None, html_dados_processo=html_teste,
                                process_number="0001306-27.2025.8.05.0191")

try:
    resultado = service.processar_movimentacoes(
        html=html_teste,
        numero_processo="0001306-27.2025.8.05.0191",
        processo_obj=processo_teste
    )
    print(f"\nResultado do pipeline:")
    print(f"  Processo: {resultado['processo']}")
    print(f"  Movimentacoes: {resultado['movimentacoes']}")
    print(f"  Comandos: {resultado['comandos']}")
    print(f"  Completaveis: {resultado['completaveis']}")
    print(f"  Comunicacoes rastreadas: {resultado['comunicacoes_rastreadas']}")
    print(f"  Automatizavel: {resultado['automatizavel']}")
    print(f"  Status: {resultado['status']}")

    # Mostrar o que foi salvo
    from processes.models import Movement, MovementCommand, CommunicationTracking, ProcessSummary
    print(f"\nDados salvos no banco:")
    print(f"  Movements: {Movement.objects.filter(process=processo_teste).count()}")
    print(f"  Commands: {MovementCommand.objects.filter(movement__process=processo_teste).count()}")
    print(f"  Communications: {CommunicationTracking.objects.filter(process=processo_teste).count()}")
    print(f"  Summary: {ProcessSummary.objects.filter(process=processo_teste).first()}")

    for m in Movement.objects.filter(process=processo_teste):
        print(f"\n  Movement {m.event_number}: {m.category} | {m.act_description[:50]}...")
        for c in m.commands.all():
            print(f"    -> Command: {c.act_verb} | cumprivel={c.is_completable}")

except Exception as e:
    print(f"\nErro: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("TESTE CONCLUIDO")
print("="*60)
