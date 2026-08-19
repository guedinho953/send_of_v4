"""Cria 2 RAGExamples BLOQUEADORES (NÃO CUMPRIR) para os processos que falharam
no lote "só movimentar" de 19/08:

  #1  0001538-05.2026.8.05.0191 — despacho: cancelamento de audiência +
        pede endereço atualizado da parte ré + aguardar prazo (nada a executar
        automaticamente). Bloqueia para não cair em fluxo de intimação/mandado.

  #2  0004374-19.2024.8.05.0191 — despacho que pede BUSCA NO RENAJUD POR NÚMERO
        DE CHASSI (verificação de registro do veículo). Bloqueia porque o fluxo
        automático NÃO faz busca por chassi (não existe emissor de chassi).

RAG bloqueadora = sequencia_cumprimento vazio/None + frases_bloqueio + active=True.
encontrar_bloqueio() roda ANTES do matching por similaridade; se o texto da
movimentação contém as frases, BLOQUEIA totalmente (não executa nada).

Técnica (validada nas RAGs 2553/2554): exigir_todas_frases=True + frases curtas
e robustas (sem vírgula/hífen que quebram o substring).

Uso:
  source .venv/bin/activate
  python criar_rag_bloqueio_1538_4374.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.models import Process, RAGExample
from base.utils import normalize_process_number

TENANT_ID = 1


def garantir_processo(cnj):
    norm = normalize_process_number(cnj)
    proc, _ = Process.objects.get_or_create(
        number=cnj, defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
    if not proc.number_normalized:
        proc.number_normalized = norm
        proc.save(update_fields=['number_normalized'])
    return proc


def criar_bloqueio(ato, obs, frases, rotulo, proc):
    existente = RAGExample.objects.filter(despacho_ato=ato, active=True).first()
    if existente:
        print(f'   ↦ RAG #{existente.id} já existente — confere frases/bloqueio.')
        return existente
    rag = RAGExample.objects.create(
        tenant_id=TENANT_ID,
        process=proc,
        oficio='',
        despacho_ato=ato,
        despacho_observacao=obs,
        despacho_data='',
        despacho_autor='',
        evento_despacho='',
        cumprimentos=[],
        documentos=[],
        sequencia_cumprimento=[],            # vazio = BLOQUEIO
        frases_bloqueio=frases,
        exigir_todas_frases=True,            # AND robusto
        active=True,
    )
    print(f'   ✅ RAGExample #{rag.id} criado — {rotulo}')
    return rag


def main():
    print('Criando RAGs BLOQUEADORAS (NÃO CUMPRIR)\n')

    # ── #1 1538: cancelamento de audiência + endereço atualizado + aguardar ──
    print('─ [RAG B1] 0001538-05.2026.8.05.0191 (cancelamento audiência / endereço):')
    proc1 = garantir_processo('0001538-05.2026.8.05.0191')
    criar_bloqueio(
        ato=('BLOQUEIO - CANCELAMENTO DE AUDIENCIA + APRESENTAR ENDERECO '
             'ATUALIZADO DA PARTE RE + AGUARDAR PRAZO'),
        obs=('Diante do resultado da comunicação, ratifico o cancelamento da '
             'audiência de instrução aprazada, pois a promovida não chegou a ser '
             'citada. Concedo prazo para a parte autora apresentar endereço '
             'atualizado da parte ré. Aguarde-se o transcurso do prazo.'),
        frases=['cancelamento da audiencia de instrucao', 'endereco atualizado da referida parte'],
        rotulo='Bloqueio cancelamento audiência/endereço',
        proc=proc1,
    )

    # ── #2 4374: busca no RENAJUD por número de chassi ──
    print('─ [RAG B2] 0004374-19.2024.8.05.0191 (busca RENAJUD por chassi):')
    proc2 = garantir_processo('0004374-19.2024.8.05.0191')
    criar_bloqueio(
        ato=('BLOQUEIO - BUSCA NO RENAJUD POR NUMERO DE CHASSI '
             '(VERIFICACAO DE REGISTRO DO VEICULO)'),
        obs=('Considerando a nova manifestação da parte exequente, proceda-se na '
             'busca junto ao Renajud para verificação de registro, por meio do '
             'número do chassi, juntando-se a resposta da consulta.'),
        # Frases curtas sem vírgula/hífen interno — robustas ao substring.
        frases=['numero do chassi', 'renajud'],
        rotulo='Bloqueio busca RENAJUD por chassi',
        proc=proc2,
    )

    print()
    for ato in ('BLOQUEIO - CANCELAMENTO DE AUDIENCIA', 'BLOQUEIO - BUSCA NO RENAJUD'):
        r = RAGExample.objects.filter(despacho_ato__startswith=ato, active=True).first()
        if r:
            print(f'RAG #{r.id}: {r.despacho_ato}')
            print(f'  frases={list(r.frases_bloqueio)} | exigir_todas={r.exigir_todas_frases} '
                  f'| seq_vazia={not r.sequencia_cumprimento}')
            print()


if __name__ == '__main__':
    main()
