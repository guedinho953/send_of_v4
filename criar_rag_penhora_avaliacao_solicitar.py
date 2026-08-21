"""Cria RAGExample de SOLICITAÇÃO DE MANDADO para o DESPACHO DE PENHORA E
AVALIAÇÃO (resultado negativo de SISBAJUD/RENAJUD, art. 835 CPC):

  Comando imediato (único passo): SOLICITAR a expedição do mandado de penhora
  e avaliação (passo `solicitar_expedicao`, Mov581 "Solicitada a Expedição de
  Mandado de Penhora e Avaliação" — SEM confeccionar).

  As intimações do parágrafo seguinte ("...intimando o executado na pessoa de
  seu advogado... 15 dias p/ impugnação" e "...intime-se a parte promovente/
  exequente para indicar bens em 5 dias, sob pena de arquivamento") são CONDI-
  CIONAIS ao resultado da penhora — NÃO entram na sequência imediata (regra
  do Ivan: só o comando do 1º parágrafo que a secretaria cumpre AGORA).

Uso:
  source .venv/bin/activate
  python criar_rag_penhora_avaliacao_solicitar.py
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
    'DESPACHO - MANDADO DE PENHORA E AVALIAÇÃO - SISBAJUD/RENAJUD NEGATIVO '
    '(art. 835 CPC) - SOLICITAÇÃO DE EXPEDIÇÃO'
)

# Âncora de match = texto REAL do despacho (generalizado).
ANCHORA = (
    "Diante do resultado negativo da pesquisa SISBAJUD/RENAJUD, proceda-se à "
    "penhora e avaliação dos bens do(a)(s) devedor(a)(s) necessários para "
    "garantir a execução, conforme a ordem estabelecida no art. 835 do CPC e "
    "excluindo os que a lei declare absolutamente impenhoráveis. No caso de "
    "penhora dos bens elencados no art. 840, II, do CPC, ficarão em poder da "
    "parte exequente, nos termos do § 1º do art. 840 do CPC, em razão de "
    "inexistência de depositário judicial nesta Comarca, ressalvada "
    "impossibilidade, lavrando-se o respectivo auto e de tais atos intimando, "
    "na mesma oportunidade, o(a) executado(a), na pessoa de seu advogado(a) "
    "ou, não o tendo, pessoalmente, para, querendo, no prazo de 15 dias, "
    "apresentar(em) manifestação/impugnação acerca da penhora efetivada, "
    "devendo o laudo da avaliação integrar o auto de penhora e conter a "
    "descrição dos bens, com as suas características, e a indicação do estado "
    "em que se encontram e seus valores atualizados. Deve o oficial de justiça, "
    "caso não encontre bens penhoráveis, descrever na certidão os bens que "
    "guarnecem a residência ou estabelecimento do executado, nomeando logo "
    "após o executado como depositário provisório de tais bens até ulterior "
    "determinação deste Juízo (art. 836, § 2º, do CPC). Expeça-se mandado de "
    "penhora e avaliação. Caso necessário, expeça-se carta precatória. Caso "
    "não seja encontrado bens penhoráveis, intime-se a parte promovente/"
    "exequente para indicar no prazo de 5 dias, bens penhoráveis pertencentes "
    "ao(à)(s) promovido(a)(s)/executado(a)(s), sob pena de arquivamento."
)

SEQUENCIA = [{
    "tipo": "solicitar_expedicao",
    "polo": "reu_especifico",        # mandado de penhora mira o(s) executado(s)
    "fluxo": "movimentar",
    "codigo_mov": "581",
    "descricao_mov": "Solicitada a Expedição de Mandado de Penhora e Avaliação",
    "observacao": ("Solicitada a Expedicao de Mandado de Penhora e Avaliacao - "
                   "penhora e avaliacao dos bens dos executados (art. 835 CPC)"),
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
            despacho_data='', despacho_autor='',
            evento_despacho='', cumprimentos=[], documentos=[],
            sequencia_cumprimento=SEQUENCIA, active=True,
        )
        print(f'   ✅ RAGExample #{rag.id} criado (solicitar expedição penhora)')
    else:
        rag.despacho_observacao = ANCHORA
        rag.sequencia_cumprimento = SEQUENCIA
        rag.active = True
        rag.save(update_fields=['despacho_observacao', 'sequencia_cumprimento', 'active'])
        print(f'   ↦ RAG #{rag.id} já existente — atualizado.')

    print(f'RAG #{rag.id} (active={rag.active}): {rag.despacho_ato}')
    print(json.dumps(rag.sequencia_cumprimento, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
