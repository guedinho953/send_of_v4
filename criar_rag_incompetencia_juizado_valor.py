"""Cria RAGExample para a sentença de INCOMPETÊNCIA do Juizado por VALOR:

    "Diante do exposto, de ofício, reconheço a incompetência do Juízo, em razão
     do seu valor ser superior ao teto dos Juizados Especiais, no que JULGO
     extinto o feito sem resolução do mérito, com espeque no art. 3º, I, c/c o
     art. 51, II, ambos da Lei nº 9.099/95. Sem custas e honorários advocatícios
     (art. 55). Transitada em julgado, arquive-se. P.R.I."

Ato de secretaria = P.R.I. → INTIMAR as partes da sentença de extinção para
ciência. Matching GENERALIZADO (remove o valor fixo R$ 101.553,25 e "corrigido
acima" — ruído; mantém as palavras-chave estruturais).

Uso: source .venv/bin/activate && python criar_rag_incompetencia_juizado_valor.py
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
    'SENTENÇA - INADMISSIBILIDADE DO PROCEDIMENTO SUMARÍSSIMO '
    '(INCOMPETÊNCIA DO JUIZADO POR VALOR EXCEDENTE AO TETO) - '
    'EXTINÇÃO SEM RESOLUÇÃO DE MÉRITO'
)

OBS_MATCH = (
    'Diante do exposto, de ofício, reconheço a incompetência do Juízo, em razão '
    'do seu valor ser superior ao teto dos Juizados Especiais, no que JULGO '
    'extinto o feito sem resolução do mérito, com espeque no art. 3º, I, c/c o '
    'art. 51, II, ambos da Lei nº 9.099/95. Sem custas e honorários '
    'advocatícios, nos termos do art. 55 da Lei nº 9.099/95. Transitada em '
    'julgado, arquive-se. P.R.I.'
)

# P.R.I. → intimar as partes da sentença (como as demais sentenças de extinção).
SEQUENCIA = [
    {
        "polo": "todos",
        "tipo": "intimacao_eletronica",
        "fluxo": "analisar",
        "fluxo_fallback": True,
        "fallback": "solicitar_expedicao",
        "fallback_ar": True,
        "codigo_mov": "581",
        "descricao_mov": "Intimação",
        "observacao": (
            "Intimem-se as partes da Sentença de extinção sem resolução do "
            "mérito (Incompetência do Juizado Especial por valor excedente ao "
            "teto - art. 51, II, c/c art. 3º, I, da Lei nº 9.099/95), para ciência."
        ),
        "prazo_intimacao": "3",
        "motivo_intimacao": "3",
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
        sequencia_cumprimento=SEQUENCIA, active=True,
    )
    print(f'   ✅ #{rag.id} criado — INCOMPETÊNCIA DO JUIZADO (valor > teto)')
    print(json.dumps(SEQUENCIA, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
