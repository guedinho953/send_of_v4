"""Cria 3 RAGs TOGGLE para 'CONCEDI A LIMINAR ... valendo como mandado E ofício':

    DECISÃO COM FORÇA DE MANDADO E OFÍCIO¹
    ... art. 84 §3º CDC ... CONCEDO a LIMINAR, determinando a parte ré que SE
    ABSTENHA de suspender o fornecimento de energia ... sob pena de multa ...
    DEFIRO a inversão do ônus da prova ... Intimações necessárias, FICA VALENDO
    A PRESENTE COMO MANDADO E OFÍCIO. Cumpra-se com urgência.

3 modelos (alterna active), TODOS base `intimacao_eletronica` + fallback_ar +
assinar_ar, mudando só o destino do mandado:
  A. só intimação eletrônica
  B. + solicitar mandado
  C. + expedir mandado (modelo 9)

Matching generalizado (remove R$/código cliente/endereço da unidade).

Uso: source .venv/bin/activate && python criar_rag_liminar_concedida_oficio.py
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

OBS_MATCH = (
    'Por se tratar de causa consumerista, observados os requisitos do § 3º do '
    'art. 84 do CDC, CONCEDO a LIMINAR, determinando a parte ré que se abstenha '
    'de suspender o fornecimento de energia no endereço da unidade consumidora, '
    'bem como que se abstenha de negativar o nome da parte autora em cadastros '
    'de inadimplentes, sob pena de multa. DEFIRO a inversão do ônus da prova em '
    'favor do demandante. Intimações necessárias, FICA VALENDO A PRESENTE COMO '
    'MANDADO E OFÍCIO. Cumpra-se com urgência.'
)
OBS_ACAO = (
    'Intimem-se as partes para ciência da Decisão (CONCEDIDA A MEDIDA LIMINAR), '
    'valendo a presente como mandado de intimação. Cumpra-se com urgência.'
)

MODELOS = [
    ('INTIMACAO-ELETRONICA-AR', [{
        'polo': 'reu_especifico', 'tipo': 'intimacao_eletronica',
        'fluxo': 'analisar', 'fluxo_fallback': True,
        'codigo_mov': '581', 'descricao_mov': 'Intimação',
        'observacao': OBS_ACAO,
        'motivo_intimacao': '3',  # prazo da intimação vem da DECISÃO quando liminar concedida
        'fallback_ar': True, 'assinar_ar': True,
    }]),
    ('SOLICITAR-MANDADO', [{
        'polo': 'reu_especifico', 'tipo': 'intimacao_eletronica',
        'fluxo': 'analisar', 'fluxo_fallback': True,
        'codigo_mov': '581', 'descricao_mov': 'Intimação',
        'observacao': OBS_ACAO,
        'motivo_intimacao': '3',  # prazo da intimação vem da DECISÃO quando liminar concedida
        'fallback_ar': True, 'assinar_ar': True,
        'fallback': 'solicitar_mandado', 'solicitar_mandado': True,
        'mandado_polo': 'reu_especifico', 'mandado_subtipo': '11',
    }]),
    ('EXPEDICAO-MANDADO', [{
        'polo': 'reu_especifico', 'tipo': 'intimacao_eletronica',
        'fluxo': 'analisar', 'fluxo_fallback': True,
        'codigo_mov': '581', 'descricao_mov': 'Intimação',
        'observacao': OBS_ACAO,
        'motivo_intimacao': '3',  # prazo da intimação vem da DECISÃO quando liminar concedida
        'fallback_ar': True, 'assinar_ar': True,
        'fallback': 'mandado', 'fallback_template_id': 9,
        'mandado_polo': 'reu_especifico', 'mandado_subtipo': '11',
    }]),
]


def criar(sufixo, seq, ativo):
    norm = normalize_process_number(PROCESSO_FICTICIO)
    proc, _ = Process.objects.get_or_create(
        number=PROCESSO_FICTICIO,
        defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
    if not proc.number_normalized:
        proc.number_normalized = norm
        proc.save(update_fields=['number_normalized'])
    ato = (f'DECISÃO COM FORÇA DE MANDADO E OFÍCIO - CONCEDIDA A MEDIDA LIMINAR '
           f'(ENERGIA) - {sufixo}')
    e = RAGExample.objects.filter(despacho_ato=ato)
    if e.exists():
        print(f'   ↦ #{e.first().id} já existe ({sufixo}) — pulando.')
        return e.first()
    rag = RAGExample.objects.create(
        tenant_id=TENANT_ID, process=proc, oficio='',
        despacho_ato=ato, despacho_observacao=OBS_MATCH,
        despacho_data='', despacho_autor='', evento_despacho='',
        cumprimentos=[], documentos=[], sequencia_cumprimento=seq,
        active=ativo,
    )
    print(f'   ✅ #{rag.id} criado — {sufixo} (active={ativo})')
    return rag


def main():
    print('Criando 3 modelos toggle — CONCEDIDA liminar (energia, mandado e ofício)\n')
    for sufixo, seq in MODELOS:
        criar(sufixo, seq, sufixo == 'INTIMACAO-ELETRONICA-AR')


if __name__ == '__main__':
    main()
