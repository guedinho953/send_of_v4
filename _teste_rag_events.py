from processes.models import RAGExample
from processes.movimentacoes_service import _palavras_para_match

r = RAGExample.objects.get(id=2533)
palavras_rag = _palavras_para_match((r.despacho_ato or '') + ' ' + (r.despacho_observacao or ''))
print('Tokens da RAG 2533 generica:', len(palavras_rag))
print(' ', sorted(palavras_rag))
print()

t1 = 'Intime-se a parte autora, atraves de sua defesa, para juntar a peticao mencionada no evento 94'
print('=== Teste 1 (original com evento 94) ===')
p1 = _palavras_para_match(t1)
inter1 = p1 & palavras_rag
print('Intersecao:', len(inter1), 'tokens:', sorted(inter1))
print()

t2 = 'Defiro o pedido de juntada de documentos. Intime-se a autora para manifestar-se sobre os documentos do evento 120, no prazo de 5 dias, sob pena de indeferimento'
print('=== Teste 2 (variacao) ===')
p2 = _palavras_para_match(t2)
inter2 = p2 & palavras_rag
print('Intersecao:', len(inter2), 'tokens:', sorted(inter2))
