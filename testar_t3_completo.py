"""Testa se RAG #2486 pega T3 com o texto completo."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath('.')))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.models import RAGExample
from processes.movimentacoes_service import buscar_cumprimentos_similares

t3 = """DECISÃO COM FORÇA DE MANDADO¹



Verifico que o pedido de tutela de urgência tem natureza satisfativa, ou seja, que esgota praticamente o objeto do pedido principal (obrigação de fazer) desta ação, ferindo os princípios constitucionais do devido processo legal, do contraditório e da ampla defesa (art. 5º da CF) caso deferida, bem como por conta disposto no  § 3º, do art. 300 do CPC (perigo da irreversibilidade da medida).



Nesse sentido:



"AGRAVO DE INSTRUMENTO. POSSE. BENS IMÓVEIS. AÇÃO DEMARCATÓRIA. ANTECIPAÇÃO DA TUTELA INDEFERIDA. POSSE VELHA. AUSÊNCIA DOS PRESSUPOSTOS PARA DEFERIMENTO DA MEDIDA. ART. 300 E 311 DO NCPC. MANUTENÇÃO DA DECISÃO. Posse velha. Quando o esbulho tiver ocorrido há mais de ano e dia a ação de forma velha poderá ser ajuizada pelo rito comum e o pedido de tutela antecipada analisada sob o enfoque da tutela de urgência e/ou evidência. Tutela provisória. Urgência ou de evidência. Requisitos não preenchidos. Art. 300 e 311 do NCPC. Indeferimento mantido. Medida satisfativa. O deferimento do pleito liminar poderia gerar um esvaziamento do mérito da ação, por caracterizar a antecipação do julgamento da lide, ou seja, seria um adiantamento total do que se está pleiteando na demanda, em descumprimento aos princípios do devido processo legal, do contraditório e da ampla defesa, insculpidos no art. 5º, incisos LIV e LV da Constituição Federal. Decisão mantida. NEGARAM PROVIMENTO AO AGRAVO DE INSTRUMENTO." (Agravo de Instrumento Nº 70074111345, Décima Sétima Câmara Cível, Tribunal de Justiça do RS, Relator: Giovanni Conti, Julgado em 26/10/2017)



DIREITO PROCESSUAL CIVIL. AGRAVO DE INSTRUMENTO. AÇÃO DE OBRIGAÇÃO DE FAZER. ANTECIPAÇÃO DE TUTELA. INDEFERIMENTO. LIMINAR DE NATUREZA SATISFATIVA. 1. A antecipação dos efeitos da tutela não pode ser deferida porquanto esgota o objeto da ação originária, restando, assim, inviabilizado o deferimento de liminar inaudita altera pars. 2. No caso em exame, o pedido liminar tem natureza satisfativa, porquanto a agravante pugnou pela entrega imediata do maquinário adquirido junto à empresa agravada, pretensão esta que corresponde exatamente àquela deduzida como provimento final,o que esvaziaria a própria ação originária. 3. Agravo de Instrumento conhecido e não provido.(AGI 20130020256027, 3ª TURMA CÍVEL, TJDFT, Relatora Des. Nídia Corrêa Lima).




Desse modo, INDEFIRO O PEDIDO LIMINAR.



Intimações necessárias, FICA VALENDO A PRESENTE COMO MANDADO. Cumpra-se com urgência."""

rag = RAGExample.objects.get(id=2486)

print(f'RAG #{rag.id}: {rag.despacho_ato}')
print()

sim = buscar_cumprimentos_similares(t3, top_k=10)
rank = next((i+1 for i,s in enumerate(sim) if s['id']==2486), None)
jac = next((s['jaccard'] for s in sim if s['id']==2486), None)

palavras_texto = set(t3.lower().split())
palavras_ato = set(rag.despacho_ato.lower().split())
total = max(len(palavras_ato), 1)
cobertura = len(palavras_texto & palavras_ato) / total
missing = palavras_ato - palavras_texto

print(f'Recall: #{rank} de {len(sim)}  jaccard={jac:.3f}')
print(f'_melhor_match cobertura={cobertura:.0%} (precisa 70%)')
print(f'Faltam no texto: {sorted(missing) or "-"}')

if cobertura >= 0.70:
    print(f'\n  OK! RAG #{rag.id} pegaria o T3.')
else:
    print(f'\n  FALHOU! Nao pega o T3.')
