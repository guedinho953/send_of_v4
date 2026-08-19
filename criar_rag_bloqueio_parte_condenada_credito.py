"""Cria RAGExample de BLOQUEIO (NÃO CUMPRIR) para despachos em que NÃO SE SABE
quem é a parte condenada, mas HÁ transferência de crédito (alvará / crédito a
favor da parte).

Exemplo real (despacho de alvará com custas finais pendentes + transferência
de crédito, onde o sistema não consegue mapear a "parte condenada"):

  "... Intime-se a parte condenada para pagá-las no prazo de 15 dias.
   Após a quitação das custas, certifique-se e expeça-se a transferência do
   crédito de R$ 832,41 em favor da parte executada."

Estratégia (AND - TODAS as frases devem aparecer):
  1) "parte condenada"      -> o despacho cita a parte condenada (o sistema não
     sabe quem é, por isso não pode cumprir automaticamente).
  2) "transferencia do credito" -> manda transferir o crédito (alvará). Presente
     em "expeça-se a transferência do crédito". Ausente em intimar/intimar
     comuns sem alvará.

Com AND: ambas coexistem -> bloqueia o alvo (não sabe a parte + tem transferência)
e NÃO bloqueia despachos que só citam "parte condenada" sem transferência, nem
alvarás onde a parte está claramente mapeada (sem "parte condenada" no texto).

Uso:
  source .venv/bin/activate
  python criar_rag_bloqueio_parte_condenada_credito.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.models import Process, RAGExample
from base.utils import normalize_process_number

PROCESSO_FICTICIO = '9999999-99.2026.8.05.0193'
TENANT_ID = 1

DESPACHO_ATO = (
    'BLOQUEIO - DESPACHO DE ALVARA/CREDITO ONDE NAO SE SABE A PARTE CONDENADA '
    '(INTIME-SE A PARTE CONDENADA + TRANSFERENCIA DO CREDITO) - NAO CUMPRIR / '
    'NAO EXPEDIR AUTOMATICAMENTE'
)

DESPACHO_OBSERVACAO = (
    "Reiterando o despacho anterior e, considerando que a parte promovida "
    "formulou requerimento de expedição de alvará [...] mas por outro lado, a "
    "existência de pendência no recolhimento das custas finais (evento 185), "
    "etapa condicionante para possibilitar a expedição do alvará conforme "
    "sentença proferida no evento 148, cujo crédito fixado à parte promovida e "
    "ainda pendente de liberação é de R$ 832,41, intime-se a parte condenada "
    "para pagá-las no prazo de 15 dias. Após a quitação das custas, "
    "certifique-se e expeça-se a transferência do crédito de R$ 832,41 em favor "
    "da parte executada. Intime-se a parte promovida deste despacho."
)

# Frases bloqueadoras (AND - TODAS devem aparecer). Normalizadas = só caixa/acento.
FRASES_BLOQUEIO = [
    'parte condenada',
    'transferencia do credito',
]

# ─── Evita duplicar a mesma RAG de bloqueio ───
existente = RAGExample.objects.filter(
    active=True,
    frases_bloqueio__contains=[FRASES_BLOQUEIO[0]],
).first()
if existente:
    print(f'⚠️  RAG de bloqueio já existe: #{existente.id} (frases={existente.frases_bloqueio})')
    print('    Nenhuma RAG nova criada.')
    sys.exit(0)

# ─── Cria/garante processo fictício ───
norm = normalize_process_number(PROCESSO_FICTICIO)
proc, created = Process.objects.get_or_create(
    number=PROCESSO_FICTICIO,
    defaults={
        'number_normalized': norm,
        'tenant_id': TENANT_ID,
    },
)
if not proc.number_normalized:
    proc.number_normalized = norm
    proc.save(update_fields=['number_normalized'])

status = '(criado)' if created else '(existente)'
print(f'Processo: {PROCESSO_FICTICIO} -> #{proc.id} {status}')

# ─── Cria RAGExample de BLOQUEIO (NÃO CUMPRIR) ───
rag = RAGExample.objects.create(
    tenant_id=TENANT_ID,
    process=proc,
    oficio='',
    despacho_ato=DESPACHO_ATO,
    despacho_observacao=DESPACHO_OBSERVACAO,
    despacho_data='',
    despacho_autor='',
    evento_despacho='',
    cumprimentos=[],
    documentos=[],
    frases_bloqueio=FRASES_BLOQUEIO,
    exigir_todas_frases=True,    # AND: TODAS as frases devem aparecer
    sequencia_cumprimento=[],    # NÃO CUMPRIR: nenhum ato a executar
    active=True,
)

print(f'\n✅ RAG de BLOQUEIO #{rag.id} criada!')
print(f'   Ato:      {rag.despacho_ato}')
print(f'   Frases:   {json.dumps(rag.frases_bloqueio, ensure_ascii=False)}')
print(f'   Modo:     AND (TODAS as frases devem aparecer)')
print(f'   Seq:      vazia (NÃO CUMPRIR)')
print(f'\nPronta para uso no encontrar_bloqueio().')
