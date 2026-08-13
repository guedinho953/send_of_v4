"""Cria RAGExample para a decisão modelo:
DECISÃO VALENDO COMO MANDADO E OFÍCIO
- INDEFIRO O PEDIDO LIMINAR (ausência de urgência - descontos há vários anos)
- DEFIRO a inversão do ônus da prova (CDC)
- Intimem-se

Uso:
  source .venv/bin/activate
  python criar_rag_decisao_mandado_oficio.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.models import Process, RAGExample
from base.utils import normalize_process_number

# ─── Config ───
PROCESSO_FICTICIO = '9999999-99.2026.8.05.0191'
TENANT_ID = 1

DESPACHO_ATO = (
    'DECISÃO - INDEFIRO O PEDIDO LIMINAR - AUSÊNCIA DE URGÊNCIA '
    '- DESCONTOS OCORREM HÁ VÁRIOS ANOS - FALTA DE EXTRATO BANCÁRIO '
    '- INVERSÃO DO ÔNUS DA PROVA - INTIMEM-SE AS PARTES '
    '(VALENDO COMO MANDADO E OFÍCIO)'
)

DESPACHO_OBSERVACAO = """DECISÃO VALENDO COMO MANDADO E OFÍCIO¹



A concessão da antecipação dos efeitos da tutela pretendida (obrigação de fazer ou de não fazer) no âmbito das ações consumeristas, mediante liminar, pressupõe o atendimento dos requisitos constantes do art. 84, § 3º, do CDC, quais sejam: sendo relevante o fundamento da demanda e havendo justificado receio de ineficácia do provimento final.



Com efeito, tratando-se alegados descontos que ocorrem há vários anos, portanto reclamados após grande lapso, evidenciando a ausência de urgência do caso, bem como que não colaciona extrato da conta do período de início dos descontos para demonstrar que não recebeu quantia por conta do vergastado contrato, entendo como não preenchidos os requisitos e, em consequência, INDEFIRO O PEDIDO LIMINAR, sendo recomendado que se aguarde a formação do contraditório.




Por outro lado, DEFIRO a inversão do ônus da prova em favor da parte autora, somente com relação à formação do contrato, por conta da evidente hipossuficiência técnica do consumidor, nos termos do art. 6º, VIII, do CDC. Intimem-se."""

SEQUENCIA_CUMPRIMENTO = [
    {
        "tipo": "intimacao_eletronica",
        "polo": "todos",
        "fluxo": "analisar",
        "fluxo_fallback": True,
        "assinar_ar": False,
        "codigo_mov": "581",
        "descricao_mov": "Intimação",
        "observacao": (
            "Intimem-se as partes para ciência da Decisão "
            "(INDEFERIDO o pedido liminar - não concedida), "
            "valendo a presente decisão como mandado e ofício de intimação."
        ),
        "motivo_intimacao": "3",
        "prazo_intimacao": "2",
        "fallback": "solicitar_expecidao",
        "fallback_ar": True,
    }
]

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
print(f'Processo: {PROCESSO_FICTICIO} → #{proc.id} {status}')

# ─── Cria RAGExample ───
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
    sequencia_cumprimento=SEQUENCIA_CUMPRIMENTO,
    active=True,
)

print(f'\n✅ RAGExample #{rag.id} criado!')
print(f'   Ato: {rag.despacho_ato}')
print(f'   Obs: {rag.despacho_observacao[:80]}...')
print(f'   Seq: {json.dumps(rag.sequencia_cumprimento, ensure_ascii=False)}')
print(f'\nPronto para uso no matching RAG.')
