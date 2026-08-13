"""Testa se o _melhor_match corrigido (rag_router.py) pega os 3 textos."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath('.')))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.models import RAGExample, DocumentTemplate
from processes.movimentacoes_service import buscar_cumprimentos_similares
from projudi.rag_router import _melhor_match

t1 = """DECISÃO VALENDO COMO MANDADO E OFÍCIO¹
A concessão da antecipacao dos efeitos da tutela pretendida (obrigacao de fazer ou de nao fazer) no ambito das acoes consumeristas, mediante liminar, pressupoe o atendimento dos requisitos constantes do art. 84, § 3o, do CDC, quais sejam: sendo relevante o fundamento da demanda e havendo justificado receio de ineficacia do provimento final. Com efeito, tratando-se alegados descontos que ocorrem ha varios anos, portanto reclamados apos grande lapso, evidenciando a ausencia de urgencia do caso, INDEFIRO O PEDIDO LIMINAR, sendo recomendado que se aguarde a formacao do contraditorio. Por outro lado, DEFIRO a inversao do onus da prova em favor da parte autora, somente com relacao a formacao do contrato, por conta da evidente hipossuficiencia tecnica do consumidor, nos termos do art. 6o, VIII, do CDC. Intimem-se."""

t2 = """DECISÃO VALENDO COMO MANDADO E OFÍCIO¹
A concessao da antecipacao dos efeitos da tutela pretendida (obrigacao de fazer ou nao fazer) no ambito das acoes consumeristas, mediante liminar, pressupoe o atendimento dos requisitos constantes do art. 84, § 3o, do CDC, quais sejam: sendo relevante o fundamento da demanda e havendo justificado receio de ineficacia do provimento final. Com efeito, tratando-se de alegados descontos que ocorrem ha varios meses, portanto reclamados apos grande lapso, demonstrando a ausencia de urgencia do caso, entendo como nao preenchido o segundo requisito do § 3o, do art. 84 do CDC e, em consequencia, INDEFIRO O PEDIDO LIMINAR, sendo recomendado que se aguarde a formacao do contraditorio. Por outro lado, DEFIRO a inversao do onus da prova em favor da parte autora, somente com relacao a formacao do contrato, por conta da evidente hipossuficiencia tecnica do consumidor, nos termos do art. 6o, VIII, do CDC. Intimem-se."""

t3 = """DECISÃO COM FORÇA DE MANDADO¹
Verifico que o pedido de tutela de urgencia tem natureza satisfativa, ou seja, que esgota praticamente o objeto do pedido principal (obrigacao de fazer) desta acao, ferindo os principios constitucionais do devido processo legal, do contraditorio e da ampla defesa (art. 5o da CF) caso deferida, bem como por conta disposto no § 3o, do art. 300 do CPC (perigo da irreversibilidade da medida). Nesse sentido: julgados. Desse modo, INDEFIRO O PEDIDO LIMINAR. Intimacoes necessarias, FICA VALENDO A PRESENTE COMO MANDADO. Cumpra-se com urgencia."""

rag = RAGExample.objects.get(id=2486)
templates = DocumentTemplate.objects.filter(active=True)

print('RAG #{0}'.format(rag.id))
print('ato: ' + rag.despacho_ato)
print('seq: ' + json.dumps(rag.sequencia_cumprimento, ensure_ascii=False))
print()

for nome, texto in [('T1 (CDC anos)', t1), ('T2 (CDC meses)', t2), ('T3 (forca mandado)', t3)]:
    sim = buscar_cumprimentos_similares(texto, top_k=10)
    rank = next((i+1 for i,s in enumerate(sim) if s['id']==2486), None)
    jac = next((s['jaccard'] for s in sim if s['id']==2486), None)

    melhor, template, rag_obj, ignorar = _melhor_match(texto, sim, templates)

    ato_match = melhor['despacho_ato'][:60] if melhor else '-'
    rid = str(melhor['id']) if melhor else 'NENHUM'
    seq = json.dumps(rag_obj.sequencia_cumprimento if rag_obj else [], ensure_ascii=False)[:80]

    print('[{0}/{1}] {2}: jaccard={3:.3f}'.format(rank or '-', len(sim), nome, jac or 0))
    print('    melhor: #{0} -> {1}'.format(rid, ato_match))
    print('    seq: ' + seq)
    print()
