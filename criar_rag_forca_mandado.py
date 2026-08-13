"""Cria RAGExample #2487 para:
DECISÃO COM FORÇA DE MANDADO - INDEFIRO O PEDIDO LIMINAR - INTIMAÇÕES NECESSÁRIAS - CUMPRA-SE

Padrão: decisão que indefere liminar com natureza satisfativa (CPC, posse, etc.),
valendo como mandado.

Uso:
  source .venv/bin/activate
  python criar_rag_forca_mandado.py
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

DESPACHO_ATO = (
    'DECISÃO COM FORÇA DE MANDADO - INDEFIRO O PEDIDO LIMINAR '
    '- TUTELA DE URGÊNCIA NATUREZA SATISFATIVA - ART. 300 CPC '
    '- INTIMAÇÕES NECESSÁRIAS - CUMPRA-SE COM URGÊNCIA'
)

DESPACHO_OBSERVACAO = """DECISÃO COM FORÇA DE MANDADO¹



Verifico que o pedido de tutela de urgência tem natureza satisfativa, ou seja, que esgota praticamente o objeto do pedido principal (obrigação de fazer) desta ação, ferindo os princípios constitucionais do devido processo legal, do contraditório e da ampla defesa (art. 5º da CF) caso deferida, bem como por conta disposto no § 3º, do art. 300 do CPC (perigo da irreversibilidade da medida).



Nesse sentido:



"AGRAVO DE INSTRUMENTO. POSSE. BENS IMÓVEIS. AÇÃO DEMARCATÓRIA. ANTECIPAÇÃO DA TUTELA INDEFERIDA. POSSE VELHA. AUSÊNCIA DOS PRESSUPOSTOS PARA DEFERIMENTO DA MEDIDA. ART. 300 E 311 DO NCPC. MANUTENÇÃO DA DECISÃO. Posse velha. Quando o esbulho tiver ocorrido há mais de ano e dia a ação de forma velha poderá ser ajuizada pelo rito comum e o pedido de tutela antecipada analisada sob o enfoque da tutela de urgência e/ou evidência. Tutela provisória. Urgência ou de evidência. Requisitos não preenchidos. Art. 300 e 311 do NCPC. Indeferimento mantido. Medida satisfativa. O deferimento do pleito liminar poderia gerar um esvaziamento do mérito da ação, por caracterizar a antecipação do julgamento da lide, ou seja, seria um adiantamento total do que se está pleiteando na demanda, em descumprimento aos princípios do devido processo legal, do contraditório e da ampla defesa, insculpidos no art. 5º, incisos LIV e LV da Constituição Federal. Decisão mantida. NEGARAM PROVIMENTO AO AGRAVO DE INSTRUMENTO." (Agravo de Instrumento Nº 70074111345, Décima Sétima Câmara Cível, Tribunal de Justiça do RS, Relator: Giovanni Conti, Julgado em 26/10/2017)



DIREITO PROCESSUAL CIVIL. AGRAVO DE INSTRUMENTO. AÇÃO DE OBRIGAÇÃO DE FAZER. ANTECIPAÇÃO DE TUTELA. INDEFERIMENTO. LIMINAR DE NATUREZA SATISFATIVA. 1. A antecipação dos efeitos da tutela não pode ser deferida porquanto esgota o objeto da ação originária, restando, assim, inviabilizado o deferimento de liminar inaudita altera pars. 2. No caso em exame, o pedido liminar tem natureza satisfativa, porquanto a agravante pugnou pela entrega imediata do maquinário adquirido junto à empresa agravada, pretensão esta que corresponde exatamente àquela deduzida como provimento final, o que esvaziaria a própria ação originária. 3. Agravo de Instrumento conhecido e não provido. (AGI 20130020256027, 3ª TURMA CÍVEL, TJDFT, Relatora Des. Nídia Corrêa Lima).




Desse modo, INDEFIRO O PEDIDO LIMINAR.



Intimações necessárias, FICA VALENDO A PRESENTE COMO MANDADO. Cumpra-se com urgência."""

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
            "(INDEFERIDO o pedido liminar - nao concedida), "
            "valendo a presente decisao como mandado."
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
print(f'Processo: {PROCESSO_FICTICIO} -> #{proc.id} {status}')

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
print(f'   Obs: {len(rag.despacho_observacao)} chars')
print(f'   Seq: {json.dumps(rag.sequencia_cumprimento, ensure_ascii=False)}')
print(f'\nPronto para uso no matching RAG.')
