"""Valida o matching da RAG #2561 com o texto REAL do despacho.

Reproduz a EXATA lógica do executor (CLI/dashboard/batch):
  - recall: processes.movimentacoes_service.buscar_cumprimentos_similares
  - decisão: _palavras_para_match + base min(len) + corte >= 0.70
  - vencedor: _melhor_match (primeiro de similares com sequencia_cumprimento)

Mostra os top-N candidatos (id, jaccard, tem seq?) e qual RAG de fato vence.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.movimentacoes_service import buscar_cumprimentos_similares, _palavras_para_match
from processes.models import RAGExample

TEXTO_REAL = """Ante o exposto, INDEFIRO o pedido de levantamento da suspensão, devendo o feito permanecer suspenso até ulterior deliberação do Superior Tribunal de Justiça sobre os Temas Repetitivos n.º 1.328 e n.º 1.414.

Intimem-se.

DESPACHO¹

Vistos.

A parte promovida requer o levantamento da suspensão do feito, sustentando a inaplicabilidade dos Temas n. 1.328 e n. 1.414 do Superior Tribunal de Justiça ao caso concreto. Aduz, em síntese, que a demanda comporta a aplicação da técnica do distinguishing, ao argumento de que o conjunto probatório demonstra a ciência da parte autora acerca da natureza da contratação de cartão de crédito com reserva de margem consignável (RMC), notadamente em razão da utilização do cartão para realização de compras.

Com efeito, conforme decisão anterior, trata-se de ação em que se discute a validade de contratação do serviço de cartão de crédito com reserva de margem consignável (RMC), cujo curso processual foi anteriormente sobrestado em razão da instauração do Incidente de Resolução de Demandas Repetitivas n.º 8054499-74.2023.8.05.0000, no âmbito do Tribunal de Justiça do Estado da Bahia e, embora referido IRDR tenha sido extinto por perda de objeto, permanece vigente a suspensão processual determinada pelo Superior Tribunal de Justiça (Temas n.º 1.328 e n.º 1.414).

Não obstante as alegações da promovida, verifico que os fundamentos invocados dizem respeito ao mérito da controvérsia, consistindo em elementos probatórios voltados à demonstração da regularidade da contratação e do cumprimento do dever de informação. Tais circunstâncias não afastam, neste momento processual, a identidade entre a matéria discutida nos autos e as questões submetidas à sistemática dos recursos repetitivos.

A controvérsia, portanto, envolve questões jurídicas de interesse coletivo e abstrato — notadamente a validade de contratos de cartão de crédito consignado com RMC, o dever de informação, eventual abusividade, as consequências da invalidação contratual e a configuração de dano moral — cuja uniformização é de relevante interesse para a segurança jurídica e a isonomia.

Nesse contexto, mostra-se prudente a manutenção da suspensão processual até o julgamento definitivo dos temas repetitivos pelo Superior Tribunal de Justiça, evitando o risco de decisões conflitantes e preservando a orientação vinculante que será fixada. Eventual distinção entre o caso concreto e a tese a ser firmada poderá ser analisada oportunamente, após o julgamento dos referidos temas, quando será possível aferir a efetiva aderência do precedente à hipótese dos autos.

Ante o exposto, INDEFIRO o pedido de levantamento da suspensão, devendo o feito permanecer suspenso até ulterior deliberação do Superior Tribunal de Justiça sobre os Temas Repetitivos n.º 1.328 e n.º 1.414.

Intimem-se."""


def melhor_match(similares, texto_palavras):
    """Espelha _melhor_match do rag_router/cumprimento_service/expedir_rapido:
    primeiro de similares com sequencia_cumprimento não-vazia, acima do corte.
    """
    for s in similares:
        seq = RAGExample.objects.get(id=s['id']).sequencia_cumprimento
        if not seq:
            continue
        palavras_rag = _palavras_para_match(s.get('despacho_ato', '') + ' ' + s.get('despacho_observacao', ''))
        base = min(len(texto_palavras), len(palavras_rag))
        jac = s.get('jaccard', 0.0)
        if base > 0 and jac >= 0.70:
            return s['id'], s.get('jaccard'), s.get('similaridade')
    return None, None, None


def main():
    texto_palavras = _palavras_para_match(TEXTO_REAL)
    similares = buscar_cumprimentos_similares(TEXTO_REAL, top_k=20)

    print(f'Palavras do texto (pós stopwords): {len(texto_palavras)}\n')
    print('─ Top candidatos (recall + jaccard) ─')
    for i, s in enumerate(similares[:10], 1):
        seq = RAGExample.objects.get(id=s['id']).sequencia_cumprimento
        tem = 'SEQ' if seq else 'bloqueio/None'
        print(f'  {i}. #{s["id"]} jaccard={s.get("jaccard", 0):.2f} sim={s.get("similaridade")} '
              f'[{tem}] {s["despacho_ato"][:70]}')

    vencedor_id, jac, sim = melhor_match(similares, texto_palavras)
    print()
    if vencedor_id:
        print(f'🏆 VENCEDOR (>=70%): RAG #{vencedor_id} | jaccard={jac:.2f} | similaridade={sim}')
        if vencedor_id == 2561:
            print('   ✅ É a RAG #2561 criada — o corte e o desempate escolhem a certa.')
        else:
            print(f'   ⚠️ ATENÇÃO: uma RAG ANTIGA venceu (#{vencedor_id}). Se não devia, a #2561 não supera o match.')
    else:
        print('⚠️ NENHUMA RAG passou no corte de 70% — a #2561 ainda NÃO dispara.')

    # detalhe da #2561
    try:
        r = RAGExample.objects.get(id=2561)
        pr = _palavras_para_match(r.despacho_ato + ' ' + r.despacho_observacao)
        inter = texto_palavras & pr
        jac_2561 = len(inter) / min(len(texto_palavras), len(pr))
        print(f'\n#2561 isolada: palavras RAG={len(pr)}, interseção={len(inter)}, jaccard= {jac_2561:.2f} (corte 0.70)')
    except RAGExample.DoesNotExist:
        print('\n#2561 não encontrada no banco.')


if __name__ == '__main__':
    main()
