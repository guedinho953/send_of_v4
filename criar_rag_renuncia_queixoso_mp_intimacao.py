"""Cria RAGExample p/ SENTENÇA DE RENÚNCIA DO QUEIXOSO / PERDÃO ACEITO —
EXTINÇÃO DA PUNIBILIDADE (art. 107, V, CP).

Comando da sentença: "Intimem-se apenas a vítima e o Ministério Público,
conforme enunciado 105 do Fonaje."  ("Transitado em julgado, arquive-se" é
futuro/condicional → NÃO entra na sequência imediata.)

Sequência (1 passo `intimacao_completa` — um único Concluir):
  - Intimação ELETRÔNICA da VÍTIMA (polo autor_especifico), fallback
    SOLICITAÇÃO de mandado (não confecção);
  - VISTAS ao MP (envia_mp, núcleo 31, tipo 6=ciência, promotor SOSTENYS).
NÃO intimar o autor do fato (suplicado) eletronicamente.

Uso:
  source .venv/bin/activate
  python criar_rag_renuncia_queixoso_mp_intimacao.py
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

ATO = (
    'SENTENÇA - RENÚNCIA DO QUEIXOSO/PERDÃO ACEITO - EXTINÇÃO DA PUNIBILIDADE '
    '(ART. 107, V, CP) - INTIMEM-SE APENAS VÍTIMA E MP'
)

# Âncora = texto real generalizado da sentença.
ANCHORA = (
    "Diante do exposto, com fundamento no art. 107, V, do CP e a requerimento "
    "do Ministério Público, DECLARO extinta a punibilidade do(a)(s) "
    "suposto(a)(s) autor(a)(es) do fato em relação aos fatos apurados no "
    "presente termo circunstanciado, visto a ocorrência de "
    "renúncia/retratação tácita ao direito de queixa/representação. "
    "Transitado em julgado, arquive-se. Publique-se. Registre-se. "
    "Intimem-se apenas a vítima e o Ministério Público, conforme enunciado "
    "105 do Fonaje. P.R.I."
)

# Passo ÚNICO — intimação eletrônica da VÍTIMA + vistas ao MP (1 Concluir),
# espelho do padrão da #2438/#2599 (TP criminal), SEM ofício CIAP.
SEQUENCIA = [{
    "tipo": "intimacao_completa",
    "polo": "autor_especifico",            # VÍTIMA (parte autora)
    "fallback_polo": "autor_especifico",
    "fluxo": "movimentar",
    "fluxo_fallback": False,               # PADRÃO Ivan (não cai no genérico)
    "natureza": "criminal",
    "codigo_mov": "581",
    "descricao_mov": "Intimação",
    "motivo_intimacao": "3",
    "prazo_intimacao": "3",                # 10 dias
    "tipo_intimacao": "geral",
    "fallback": "solicitar_mandado",       # mandado → SOLICITAÇÃO (não expede)
    "fallback_ar": True,
    "assinar_ar": False,
    "expedir_ar": True,
    "observacao": (
        "Intimem-se as partes e o Ministério Público para ciência da "
        "Renúncia do queixoso ou perdão aceito"
    ),
    # Vistas ao MP (numa única mov)
    "envia_mp": True,
    "cod_nucleo_mp": "31",
    "tipo_parecer_mp": "6",                # 6 = Ciência
    "prazo_mp": "5",                       # 30 dias
    "promotor_mp": "SOSTENYS MARINHO BARRETO",
}]


def main():
    norm = normalize_process_number(PROCESSO_FICTICIO)
    proc, _ = Process.objects.get_or_create(
        number=PROCESSO_FICTICIO,
        defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
    if not proc.number_normalized:
        proc.number_normalized = norm
        proc.save(update_fields=['number_normalized'])

    rag = RAGExample.objects.filter(despacho_ato=ATO).first()
    if rag is None:
        rag = RAGExample.objects.create(
            tenant_id=TENANT_ID, process=proc, oficio='',
            despacho_ato=ATO, despacho_observacao=ANCHORA,
            despacho_data='', despacho_autor='', evento_despacho='',
            cumprimentos=[], documentos=[], sequencia_cumprimento=SEQUENCIA,
            active=True,
        )
        print(f'   ✅ RAGExample #{rag.id} criado (renúncia do queixoso/perdão → vítima + MP)')
    else:
        rag.despacho_observacao = ANCHORA
        rag.sequencia_cumprimento = SEQUENCIA
        rag.active = True
        rag.save(update_fields=['despacho_observacao', 'sequencia_cumprimento', 'active'])
        print(f'   ↦ RAG #{rag.id} já existente — atualizado.')

    print(f'RAG #{rag.id} (active={rag.active}): {rag.despacho_ato}')
    print('SEQ:', json.dumps(rag.sequencia_cumprimento, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
