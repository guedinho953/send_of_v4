"""Cria RAGExamples (PAR toggle) p/ o DESPACHO de PEDIDO LIMINAR DE SUSPENSÃO
DE RESTABELECIMENTO DE CONTA WHATSAPP:

  "Para possibilitar a análise do Juízo, com segurança, de um pedido liminar
  de suspensão de restabelecimento de conta whatsapp, deve a parte autora
  trazer, no prazo de 5 dias, as imagens e registros da tentativa de
  solicitação de análise administrativa perante à ré, bem como a resposta da
  reclamação efetuada no Portal Consumidor de forma legível. Após, com ou sem
  resposta, venham conclusos na fila de urgência."

AÇÃO (decisão do Ivan):
  - Intimação ELETRÔNICA da(s) parte(s) AUTORA(s) (polo autores).
  - Prazo 5 dias (prazo_intimacao "2"), motivo 3 (ciência).
  - Fluxo `analisar` + `fluxo_fallback: false` (PADRÃO Ivan).
  - PAR complementar (alternar `active` por conveniência):
    # A  SOLICITAR mandado:  fallback "solicitar_mandado" + fallback AR digital
    # B  EXPEDIR mandado: fallback "mandado" (+ fallback AR digital)
  - ATIVA por padrão: a de SOLICITAÇÃO (A).
  - Observação (mesma nas duas): "Intime-se a(s) parte(s) autora(s) os
    documentos constantes no despacho nº do evento despacho atual."

Base estrutural: RAG #2533 (intimação eletrônica + fallback + evento dinâmico).

Uso:
  source .venv/bin/activate
  python criar_rag_liminar_whatsapp_intimacao.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.models import Process, RAGExample
from base.utils import normalize_process_number

PROCESSO_FICTICIO = '9999999-99.2026.8.05.0191'
TENANT_ID = 1

ATO_BASE = (
    'DESPACHO - PEDIDO LIMINAR SUSPENSÃO RESTABELECIMENTO CONTA WHATSAPP - '
    'PARTE AUTORA TRAZER DOCUMENTOS (ANÁLISE ADMINISTRATIVA / RECLAMAÇÃO '
    'PORTAL CONSUMIDOR) - PRAZO 5 DIAS - CONCLUSOS NA FILA DE URGÊNCIA'
)
ATO_SOLICITAR = ATO_BASE + ' - SOLICITAR-MANDADO'
ATO_EXPEDIR = ATO_BASE + ' - EXPEDIR-MANDADO'

# Âncora = texto real do despacho (generalizado).
ANCHORA = (
    "Para possibilitar a análise do Juízo, com segurança, de um pedido liminar "
    "de suspensão de restabelecimento de conta whatsapp, deve a parte autora "
    "trazer, no prazo de 5 dias, as imagens e registros da tentativa de "
    "solicitação de análise administrativa perante a ré, bem como a resposta "
    "da reclamação efetuada no Portal Consumidor de forma legível. Após, com "
    "ou sem resposta, venham conclusos na fila de urgência."
)

OBS = ("Intime-se a(s) parte(s) autora(s) os documentos constantes no despacho "
       "nº do evento despacho atual.")


def passo_intimacao(fallback, com_ar=False, subtipo=None):
    p = {
        "tipo": "intimacao_eletronica",
        "polo": "autores",                 # parte AUTORA (trazer documentos)
        "fallback_polo": "autores",
        "fluxo": "analisar",
        "fluxo_fallback": False,           # PADRÃO Ivan (só roda c/ codAnalise)
        "codigo_mov": "581",
        "descricao_mov": "Intimação",
        "motivo_intimacao": "3",
        "prazo_intimacao": "2",            # 05 dias
        "fallback": fallback,              # "solicitar_mandado" | "mandado"
        "observacao": OBS,
    }
    if com_ar:
        p["fallback_ar"] = True
        p["assinar_ar"] = False
        p["expedir_ar"] = True
    if subtipo:
        p["mandado_subtipo"] = subtipo
    return p


SEQUENCIA_SOLICITAR = [passo_intimacao("solicitar_mandado", com_ar=True)]
SEQUENCIA_EXPEDIR = [passo_intimacao("mandado", com_ar=True, subtipo="11")]


def _proc_ficticio():
    norm = normalize_process_number(PROCESSO_FICTICIO)
    proc, _ = Process.objects.get_or_create(
        number=PROCESSO_FICTICIO,
        defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
    if not proc.number_normalized:
        proc.number_normalized = norm
        proc.save(update_fields=['number_normalized'])
    return proc


def criar_rag(ato, seq, active):
    proc = _proc_ficticio()
    rag = RAGExample.objects.filter(despacho_ato=ato).first()
    if rag is None:
        base_existente = RAGExample.objects.filter(despacho_ato=ATO_BASE).first()
        if base_existente is not None:
            rag = base_existente
            rag.despacho_ato = ato
            print(f'   ↦ reconciliando ato base → "{ato}" (#{rag.id})')
    if rag is not None:
        rag.despacho_observacao = ANCHORA
        rag.sequencia_cumprimento = seq
        rag.active = active
        rag.save(update_fields=['despacho_ato', 'despacho_observacao',
                                'sequencia_cumprimento', 'active'])
        return rag
    rag = RAGExample.objects.create(
        tenant_id=TENANT_ID, process=proc, oficio='',
        despacho_ato=ato, despacho_observacao=ANCHORA,
        despacho_data='', despacho_autor='', evento_despacho='',
        cumprimentos=[], documentos=[], sequencia_cumprimento=seq,
        active=active,
    )
    print(f'   ✅ RAGExample #{rag.id} criado — {"SOLICITAR" if "SOLICITAR" in ato else "EXPEDIR"}')
    return rag


def main():
    print('Criando RAGs — Liminar Suspensão Conta WhatsApp (Intimação autora + fallbacks)\n')
    print('─ [RAG A] SOLICITAR mandado (fallback solicitar_mandado + AR) — ATIVA:')
    r1 = criar_rag(ATO_SOLICITAR, SEQUENCIA_SOLICITAR, active=True)
    print('─ [RAG B] EXPEDIR mandado (fallback mandado + AR) — INATIVA:')
    r2 = criar_rag(ATO_EXPEDIR, SEQUENCIA_EXPEDIR, active=False)
    print()
    for r in (r1, r2):
        print(f'RAG #{r.id} (active={r.active}): ...{r.despacho_ato[-18:]}')
        for i, p in enumerate(r.sequencia_cumprimento):
            print(f'  passo[{i}]: {json.dumps(p, ensure_ascii=False)}')
        print()
    print('Toggle: alternar `active` de A↔B no admin (nunca os dois ligados).')


if __name__ == '__main__':
    main()
