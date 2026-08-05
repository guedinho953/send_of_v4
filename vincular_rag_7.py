"""Vincula um RAGExample (cópia do RAG ideal por texto) a cada um dos 7.

Cria Process (se faltar) e um RAGExample (cópia do #2463, o match por texto
de "cumprimento de sentença prazo 15d") vinculado por FK. Depois é possível
rodar expedir_processo_especifico que acha o RAG por FK.

Não executa nada no Projudi — só o vínculo no banco.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.models import Process, RAGExample
from base.utils import normalize_process_number

LOTE = [
    '0001507-82.2026.8.05.0191',
    '0001503-45.2026.8.05.0191',
    '0000623-53.2026.8.05.0191',
    '0000677-19.2026.8.05.0191',
    '0003467-10.2025.8.05.0191',
    '0000624-38.2026.8.05.0191',
    '0003552-93.2025.8.05.0191',
]

ORIGEM_ID = 2463  # DESPACHO DE CUMPRIMENTO DE SENTENÇA (prazo 15d)
origem = RAGExample.objects.get(id=ORIGEM_ID)

print('Modelo RAG a replicar: #%s | %s' % (origem.id, origem.despacho_ato[:60]))
print('=' * 70)

for cnj in LOTE:
    norm = normalize_process_number(cnj)
    proc, created = Process.objects.get_or_create(
        number=cnj,
        defaults={'number_normalized': norm, 'tenant_id': origem.tenant_id or 1})
    # garante normalizado
    if not proc.number_normalized:
        proc.number_normalized = norm
        proc.save(update_fields=['number_normalized'])
    # já existe RAG vinculado a este processo?
    ja = RAGExample.objects.filter(process=proc).exists()
    if ja:
        print(f'{cnj}: Process #{proc.id} (existia) | RAG já vinculado — PULA (não duplica)')
        continue
    rag = RAGExample.objects.create(
        process=proc,
        tenant=origem.tenant_id,
        oficio=origem.oficio,
        despacho_ato=origem.despacho_ato,
        despacho_observacao=origem.despacho_observacao,
        despacho_data=origem.despacho_data,
        despacho_autor=origem.despacho_autor,
        evento_despacho=origem.evento_despacho,
        cumprimentos=origem.cumprimentos,
        documentos=origem.documentos,
        sequencia_cumprimento=origem.sequencia_cumprimento,
        active=True,
    )
    print(f'{cnj} → process#{proc.id} {"(criado)" if created else "(existia)"} | RAG#{rag.id} criado (reamostra do #%s)' % ORIGEM_ID)

print('=' * 70)
print('Vínculo OK. Agora pode rodar: python re_rodar_processos.py (ou expedir_processo_especifico por CN')