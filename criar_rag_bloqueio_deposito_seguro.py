"""Cria RAGExample de BLOQUEIO (NÃO CUMPRIR) para:
"decurso do prazo sinalizado para que a promovida/embargante efetue depósito
judicial, em substituição ao seguro-garantia judicial."

Funciona como as demais RAGs de bloqueio: fica ACTIVE com `frases_bloqueio`
preenchido e `sequencia_cumprimento` vazio. O `encontrar_bloqueio()` dispara
por SUBSTRING (normaliza só caixa/acento) ANTES do matching por similaridade,
impedindo qualquer cumprimento automático do despacho.

A frase-chave registrada é a cláusula distintiva de substituição:
  "deposito judicial em substituicao ao seguro garantia judicial"
(sem acento/caixa, como o normalizar_texto deixaria). Ela aparece tanto se o
despacho citar "promovida" quanto "embargante", então cobre a variação
"promovida/embargante" sem precisar do "/".

Uso:
  source .venv/bin/activate
  python criar_rag_bloqueio_deposito_seguro.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.models import Process, RAGExample
from base.utils import normalize_process_number

PROCESSO_FICTICIO = '9999999-99.2026.8.05.0192'
TENANT_ID = 1

# Frase exata que o usuário quer bloquear (documentação/contexto da RAG).
DESPACHO_ATO = (
    'BLOQUEIO - DECURSO DO PRAZO SINALIZADO PARA QUE A PROMOVIDA/EMBARGANTE '
    'EFETUE DEPOSITO JUDICIAL EM SUBSTITUICAO AO SEGURO-GARANTIA JUDICIAL '
    '(NAO CUMPRIR / NAO EXPEDIR AUTOMATICAMENTE)'
)

DESPACHO_OBSERVACAO = (
    "Decurso do prazo sinalizado para que a promovida/embargante efetue "
    "depósito judicial, em substituição ao seguro-garantia judicial."
)

# Frases bloqueadoras (AND - TODAS devem aparecer). Normalizadas = só caixa/acento.
# Estratégia: duas frases CURTAS e CONTÍGUAS que capturam a essência e são
# imunes às variações reais do despacho:
#   1) "deposito judicial"  -> presente em todos os casos-alvo; AUSENTE em
#      "depósito em penhora" / "depositado o seguro" (evita falso positivo).
#   2) "substituicao ao seguro" -> prefixo comum a "seguro-garantia" (hífen) e
#      "seguro garantia" (espaço), tanto com vírgula ("judicial, em substituição")
#      quanto sem. Não depende do polo (promovida/embargante).
# Com AND, ambas precisam coexistir -> bloqueia o alvo e não bloqueia a penhora.
FRASES_BLOQUEIO = [
    'deposito judicial',
    'substituicao ao seguro',
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
