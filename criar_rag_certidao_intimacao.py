"""Cria RAG #2569 'CERTIDÃO COM INTIMAÇÃO' — partner de toggle da #2568.

Padrão do Ivan (2026-08-20): a certidão de prazo é confeccionada NA HORA de
movimentar; dentro do MESMO fluxo pode-se preencher a intimação eletrônica
(+ MP, localizador etc.) — UM movimentar, não dois.

Esta RAG modela isso como UM passo `intimacao_completa` com os flags de prazo/
certidão JUNTOS com os de intimação. Inativa por padrão (active=False) para NÃO
sombrear a #2568 (certidão com movimentação) — alterna-se `active` conforme o
caso, como no par mandado ↔ solicitar_expedicao.

OBSERVAÇÃO (wire pendente): o executor de `intimacao_completa`
(executar_com_intimacao) HOJE ainda NÃO injeta a certidão de prazo no FCKeditor
(ela só existe no caminho cumprimento_service). Até essa wire ser feita, este
passo executa a intimação mas NÃO confecciona a certidão. Manter #2568 (2 passos,
executável) até a wire.

Uso: source .venv/bin/activate && python criar_rag_certidao_intimacao.py
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

ATO = 'INTIMAR PARTE - PRAZO 10 DIAS - CERTIDÃO COM INTIMAÇÃO'
OBS_MATCH = 'Intime a parte. Prazo de 10 dias.'

# UM passo: certidão de prazo + intimação eletrônica (mesmo movimentar).
SEQUENCIA = [
    {
        "tipo": "intimacao_completa",
        "fluxo": "analisar",
        "fluxo_fallback": True,
        "codigo_mov": "581",
        "descricao_mov": "Intimação",
        "observacao": "Intime a parte. Prazo de 10 dias.",
        "motivo_intimacao": "3",
        "prazo_intimacao": "3",
        "polo": "todos",
        # certidão de prazo — flags lidas pelo fluxo da certidão
        "observacao_prazo": True,
        "expede_certidao_prazo": True,
        "flag_certidao": True,
        "polo_prazo": "ambos",
        "tipo_localizador": "",
        "localizador": "",
    },
]


def main():
    norm = normalize_process_number(PROCESSO_FICTICIO)
    proc, _ = Process.objects.get_or_create(
        number=PROCESSO_FICTICIO,
        defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
    if not proc.number_normalized:
        proc.number_normalized = norm
        proc.save(update_fields=['number_normalized'])

    existente = RAGExample.objects.filter(despacho_ato=ATO)
    if existente.exists():
        r = existente.first()
        print(f'   ↦ #{r.id} já existe ({ATO}) — pulando.')
        return r

    rag = RAGExample.objects.create(
        tenant_id=TENANT_ID, process=proc, oficio='',
        despacho_ato=ATO, despacho_observacao=OBS_MATCH,
        despacho_data='', despacho_autor='', evento_despacho='',
        cumprimentos=[], documentos=[],
        sequencia_cumprimento=SEQUENCIA,
        active=False,  # toggle: ative quando quiser certidão+intimação
    )
    print(f'   ✅ #{rag.id} criado — CERTIDÃO COM INTIMAÇÃO (active=False)')
    print(json.dumps(SEQUENCIA, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
