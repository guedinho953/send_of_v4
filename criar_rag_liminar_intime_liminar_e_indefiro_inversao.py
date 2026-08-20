"""Cria 2 trios TOGGLE (intimação e+AR / +solicitar / +expedir mandado):

  FAMÍLIA A — "INTIME-SE A PARTE DEMANDADA SOBRE O PEDIDO LIMINAR (10 dias)"
    DESPACHO¹  Por medida de cautela, intime-se a parte demandada para se
    manifestar sobre o pedido liminar no prazo de 10 dias. Após, com ou sem
    resposta, venham conclusos os autos para análise do pedido liminar.
    (cobre #3 e #4; a inversão do ônus é variante e não muda o comando de intimação)

  FAMÍLIA B — "DECISÃO - INDEFIRO O PEDIDO LIMINAR + INVERSÃO DO ÔNUS"
    Art. 84 §3º CDC ... INDEFIRO o pedido Liminar ... DEFIRO a inversão do ônus
    da prova em favor da parte autora (art. 6º, VIII, CDC). Intimem-se.

Para cada família, 3 modelos (alterna `active`):
  A. intimacao_eletronica + fallback_ar + assinar_ar (sem mandado)
  B. + fallback:"solicitar_mandado"
  C. + fallback:"mandado" + fallback_template_id:9 (expede)

Uso: source .venv/bin/activate && python criar_rag_liminar_intime_liminar_e_indefiro_inversao.py
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

def montar_sequencia(obs, destino):
    base = {
        'polo': 'reu_especifico', 'tipo': 'intimacao_eletronica',
        'fluxo': 'analisar', 'fluxo_fallback': True,
        'codigo_mov': '581', 'descricao_mov': 'Intimação',
        'observacao': obs, 'motivo_intimacao': '3',  # prazo dinâmico da decisão
        'fallback_ar': True, 'assinar_ar': True,
    }
    if destino == 'solicitar':
        base.update({'fallback': 'solicitar_mandado', 'solicitar_mandado': True,
                     'mandado_polo': 'reu_especifico', 'mandado_subtipo': '11'})
    elif destino == 'expedir':
        base.update({'fallback': 'mandado', 'fallback_template_id': 9,
                     'mandado_polo': 'reu_especifico', 'mandado_subtipo': '11'})
    return [base]

# (prefixo_ato, obs_match, obs_acao)
FAMILIAS = [
    ('INTIME-SE SOBRE O PEDIDO LIMINAR (10 DIAS)', (
        'Por medida de cautela, intime-se a parte demandada para se manifestar '
        'sobre o pedido liminar no prazo de 10 dias. Após, com ou sem resposta, '
        'venham conclusos os autos para análise do pedido liminar.'),
     ('Intimem-se as partes sobre o pedido liminar (parte demandada para '
      'manifestação no prazo de 10 dias). Após, com ou sem resposta, conclusos '
      'os autos para análise do pedido liminar.')),
    ('DECISÃO - INDEFIRO O PEDIDO LIMINAR + INVERSÃO DO ÔNUS', (
        'Passo à análise do pedido liminar. INDEFIRO o pedido Liminar. Por outro '
        'lado, DEFIRO a inversão do ônus da prova em favor da parte autora, por '
        'conta da evidente hipossuficiência técnica do consumidor, nos termos do '
        'art. 6º, VIII, do CDC. Intimem-se.'),
     ('Intimem-se as partes para ciência da Decisão (INDEFERIDO o pedido '
      'Liminar - art. 84 §3º CDC), com inversão do ônus da prova deferida à '
      'parte autora (art. 6º, VIII, CDC).')),
]

DESTINOS = [
    ('SOMENTE-INTIMACAO', 'base'),
    ('SOLICITAR-MANDADO', 'solicitar'),
    ('EXPEDICAO-MANDADO', 'expedir'),
]


def criar(prefixo, obs_match, obs_acao, sufixo, destino, ativo):
    norm = normalize_process_number(PROCESSO_FICTICIO)
    proc, _ = Process.objects.get_or_create(
        number=PROCESSO_FICTICIO,
        defaults={'number_normalized': norm, 'tenant_id': TENANT_ID})
    if not proc.number_normalized:
        proc.number_normalized = norm
        proc.save(update_fields=['number_normalized'])
    ato = f'{prefixo} - {sufixo}'
    e = RAGExample.objects.filter(despacho_ato=ato)
    if e.exists():
        print(f'   ↦ #{e.first().id} já existe ({sufixo}) — pulando.')
        return e.first()
    seq = montar_sequencia(obs_acao, destino)
    rag = RAGExample.objects.create(
        tenant_id=TENANT_ID, process=proc, oficio='',
        despacho_ato=ato, despacho_observacao=obs_match,
        despacho_data='', despacho_autor='', evento_despacho='',
        cumprimentos=[], documentos=[], sequencia_cumprimento=seq,
        active=ativo,
    )
    print(f'   ✅ #{rag.id} criado — {sufixo} (active={ativo})')
    return rag


def main():
    print('Criando 2 trios toggle (intimação e+AR / solicitar / expedir)\n')
    for prefixo, obs_match, obs_acao in FAMILIAS:
        print(f'── {prefixo}')
        for sufixo, destino in DESTINOS:
            criar(prefixo, obs_match, obs_acao, sufixo, destino,
                  ativo=(sufixo == 'SOMENTE-INTIMACAO'))
        print()


if __name__ == '__main__':
    main()
