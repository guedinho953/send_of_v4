"""Testa qual despacho_ato genérico pega as 3 variações de decisão."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath('.')))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.models import RAGExample, DocumentTemplate
from processes.movimentacoes_service import buscar_cumprimentos_similares

t1 = """DECISÃO VALENDO COMO MANDADO E OFÍCIO¹



A concessão da antecipação dos efeitos da tutela pretendida (obrigação de fazer ou de não fazer) no âmbito das ações consumeristas, mediante liminar, pressupõe o atendimento dos requisitos constantes do art. 84, § 3º, do CDC, quais sejam: sendo relevante o fundamento da demanda e havendo justificado receio de ineficácia do provimento final.



Com efeito, tratando-se alegados descontos que ocorrem há vários anos, portanto reclamados após grande lapso, evidenciando a ausência de urgência do caso, bem como que não colaciona extrato da conta do período de início dos descontos para demonstrar que não recebeu quantia por conta do vergastado contrato, entendo como não preenchidos os requisitos e, em consequência, INDEFIRO O PEDIDO LIMINAR, sendo recomendado que se aguarde a formação do contraditório.




Por outro lado, DEFIRO a inversão do ônus da prova em favor da parte autora, somente com relação à formação do contrato, por conta da evidente hipossuficiência técnica do consumidor, nos termos do art. 6º, VIII, do CDC. Intimem-se."""

t2 = """DECISÃO VALENDO COMO MANDADO E OFÍCIO¹



A concessão da antecipação dos efeitos da tutela pretendida (obrigação de fazer ou não fazer) no âmbito das ações consumeristas, mediante liminar, pressupõe o atendimento dos requisitos constantes do art. 84, § 3º, do CDC, quais sejam: sendo relevante o fundamento da demanda e havendo justificado receio de ineficácia do provimento final.



Com efeito, tratando-se de alegados descontos que ocorrem há vários meses, portanto reclamados após grande lapso, demonstrando a ausência de urgência do caso, entendo como não preenchido o segundo requisito do § 3º, do art. 84 do CDC e, em consequência, INDEFIRO O PEDIDO LIMINAR, sendo recomendado que se aguarde a formação do contraditório.



Por outro lado, DEFIRO a inversão do ônus da prova em favor da parte autora, somente com relação à formação do contrato, por conta da evidente hipossuficiência técnica do consumidor, nos termos do art. 6º, VIII, do CDC. Intimem-se."""

t3 = """DECISÃO COM FORÇA DE MANDADO¹



Verifico que o pedido de tutela de urgência tem natureza satisfativa, ou seja, que esgota praticamente o objeto do pedido principal (obrigação de fazer) desta ação, ferindo os princípios constitucionais do devido processo legal, do contraditório e da ampla defesa (art. 5º da CF) caso deferida, bem como por conta disposto no  § 3º, do art. 300 do CPC (perigo da irreversibilidade da medida).



Nesse sentido:



"AGRAVO DE INSTRUMENTO. POSSE. BENS IMÓVEIS. AÇÃO DEMARCATÓRIA. ANTECIPAÇÃO DA TUTELA INDEFERIDA. POSSE VELHA. AUSÊNCIA DOS PRESSUPOSTOS PARA DEFERIMENTO DA MEDIDA. ART. 300 E 311 DO NCPC. MANUTENÇÃO DA DECISÃO. Posse velha. Quando o esbulho tiver ocorrido há mais de ano e dia a ação de forma velha poderá ser ajuizada pelo rito comum e o pedido de tutela antecipada analisada sob o enfoque da tutela de urgência e/ou evidência. Tutela provisória. Urgência ou de evidência. Requisitos não preenchidos. Art. 300 e 311 do NCPC. Indeferimento mantido. Medida satisfativa. O deferimento do pleito liminar poderia gerar um esvaziamento do mérito da ação, por caracterizar a antecipação do julgamento da lide, ou seja, seria um adiantamento total do que se está pleiteando na demanda, em descumprimento aos princípios do devido processo legal, do contraditório e da ampla defesa, insculpidos no art. 5º, incisos LIV e LV da Constituição Federal. Decisão mantida. NEGARAM PROVIMENTO AO AGRAVO DE INSTRUMENTO." (Agravo de Instrumento Nº 70074111345, Décima Sétima Câmara Cível, Tribunal de Justiça do RS, Relator: Giovanni Conti, Julgado em 26/10/2017)



DIREITO PROCESSUAL CIVIL. AGRAVO DE INSTRUMENTO. AÇÃO DE OBRIGAÇÃO DE FAZER. ANTECIPAÇÃO DE TUTELA. INDEFERIMENTO. LIMINAR DE NATUREZA SATISFATIVA. 1. A antecipação dos efeitos da tutela não pode ser deferida porquanto esgota o objeto da ação originária, restando, assim, inviabilizado o deferimento de liminar inaudita altera pars. 2. No caso em exame, o pedido liminar tem natureza satisfativa, porquanto a agravante pugnou pela entrega imediata do maquinário adquirido junto à empresa agravada, pretensão esta que corresponde exatamente àquela deduzida como provimento final,o que esvaziaria a própria ação originária. 3. Agravo de Instrumento conhecido e não provido.(AGI 20130020256027, 3ª TURMA CÍVEL, TJDFT, Relatora Des. Nídia Corrêa Lima).




Desse modo, INDEFIRO O PEDIDO LIMINAR.



Intimações necessárias, FICA VALENDO A PRESENTE COMO MANDADO. Cumpra-se com urgência."""

candidatos = [
    "DECISÃO - INDEFIRO O PEDIDO LIMINAR - VALENDO COMO MANDADO - INTIMEM-SE",
    "DECISÃO - INDEFIRO O PEDIDO LIMINAR - VALENDO COMO MANDADO",
    "DECISÃO - INDEFIRO O PEDIDO LIMINAR - INTIMEM-SE AS PARTES - VALENDO COMO MANDADO",
]

for ato in candidatos:
    print(f'\n{"="*60}')
    print(f'TESTANDO: {ato}')
    print(f'{"="*60}')
    palavras_ato = set(ato.lower().split())
    
    for nome, texto in [('T1 (CDC anos)', t1), ('T2 (CDC meses)', t2), ('T3 (forca mandado)', t3)]:
        palavras_texto = set(texto.lower().split())
        total = max(len(palavras_ato), 1)
        cobertura = len(palavras_texto & palavras_ato) / total
        missing = palavras_ato - palavras_texto
        status = 'OK' if cobertura >= 0.70 else 'FALHOU'
        print(f'  [{status}] {nome}: cobertura={cobertura:.0%}  faltam: {sorted(missing) or "-"}')
