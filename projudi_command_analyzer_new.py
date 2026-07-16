import re
from pprint import pprint
import spacy
from projudi_regex_pattern import PADROES_COMANDOS, PADROES_CUSTAS
import sqlite3
import json
import hashlib

    
class CommandAnalyzer:
    PADROES_COMANDOS = PADROES_COMANDOS
    PADRAO_SENTENCA = []
    sentencas_permitidas = {'publique-se','registre-se','arquive-se','intime-se','intimem-se',}
    # self.texto = texto
    nlp = spacy.load("pt_core_news_sm")

    def __init__(self):
        self.dados = {}
    #     self.nlp = spacy.load("pt_core_news_sm")

        
    def validar_destinatarios(
            self, texto, destinatarios, 
            verbo_alvo='intim'):
        doc = self.nlp(texto)
        validos = set()
        for token in doc:
            if (token.pos_ in ('VERB', 'AUX')and verbo_alvo in token.lemma_.lower()):

                for child in token.children:
                    if child.dep_ in ("obj", "obl", "iobj", "nsubj"):
                        bloco = ' '.join(
                            t.text.lower()
                            for t in child.subtree)

                        for dest in destinatarios:
                            if dest.lower() in bloco:
                                validos.add(dest)

                # entidades nomeadas
                for ent in doc.ents:
                    if ent.label_ in ("PER", "ORG"):
                        for dest in destinatarios:
                            if dest.lower() in ent.text.lower():
                                validos.add(dest)
        return list(validos)
    

    def salvar_no_banco(self, atos, texto_completo,
                        item, url_mov_generica=None, tipo=None):

        conn = sqlite3.connect("juizados_especiais.db")
        cursor = conn.cursor()

        for ato in atos:

            hash_trecho = hashlib.md5(
                ato['trecho'].encode('utf-8')
            ).hexdigest()

            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO comandos (

                        tipo_documento,
                        classe_processual,
                        movimentacao_tipo,

                        ato,

                        trecho,
                        texto_completo,

                        hash_trecho,

                        destinatario_texto,
                        destinatario,
                        objetivo,
                        prazo,
                        meio,
                        condicoes,
                        texto_custas,

                        custas,
                        cumprivel,

                        polo_ativo_automatizavel,
                        polo_passivo_automatizavel,

                        cumprimento_realizado,
                        cumprimento_categoria,
                        cumprimento_ok,
                        processo,
                        url_mov_generica

                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (

                        tipo,

                        item.get('classe_processual'),
                        item.get('tipo'),

                        ato['ato'],

                        ato['trecho'],
                        texto_completo,

                        hash_trecho,

                        str(ato['destinatario']),

                        json.dumps(ato.get('destinatario', []), ensure_ascii=False),
                        json.dumps(ato.get('objetivo', []), ensure_ascii=False),
                        json.dumps(ato.get('prazo', []), ensure_ascii=False),
                        json.dumps(ato.get('meio', []), ensure_ascii=False),
                        json.dumps(ato.get('condicoes', []), ensure_ascii=False),
                        json.dumps(ato.get('texto_custas', []), ensure_ascii=False),

                        int(ato['custas']),
                        int(ato['cumprivel']),

                        int(ato['autor_permitido']),
                        int(ato['reu_permitido']),

                        None,
                        None,
                        None,
                        item.get('processo'),
                        url_mov_generica,

                    ))
            
            except Exception as e:
                print("ERRO SQLITE:")
                print(e)

                # print("TOTAL VALORES:")
                # print(len(valores))
                raise
            
        conn.commit()
        conn.close()
    # def classificar_tipo(self, texto):

    #     scores = {}

    #     for tipo, padrao in CLASSIFICADORES.items():
    #         scores[tipo] = len(padrao.findall(texto))
    #         self.dados['tipo_score'] = scores[tipo]

    #     # pega o maior score
    #     tipo_final = max(scores, key=scores.get)
    #     self.dados['tipo'] = tipo_final

    #     # se tudo for 0
    #     if scores[tipo_final] == 0:
    #         return "indefinido", scores

    # #     return tipo_final, scores, self.dados
    # def classificar_tipo(self, texto):

    #     scores = {}

    #     for tipo, padrao in CLASSIFICADORES.items():
    #         scores[tipo] = len(padrao.findall(texto))

    #     tipo_final = max(scores, key=scores.get)

    #     self.dados['tipo'] = tipo_final
    #     self.dados['tipo_score'] = scores[tipo_final]

    #     if scores[tipo_final] == 0:
    #         self.dados['tipo'] = 'indefinido'

    #     return self.dados['tipo'], scores, self.dados
    

            
    # for idx, texto in enumerate(lista, start=1):
    def processar_texto(self, texto, salvar=False, item=None,
                        url_mov_generica=None, tipo=None):
        texto = re.sub(r'\s+', ' ', texto).strip().lower()
        # tipo, scores, dados_documento = self.classificar_tipo(texto)
        # print(dados_documento['tipo'])

        print("\n" + "=" * 80)
        print("TEXTO) # {idx}")
        print("=" * 80)

        # dados['cumprivel']= True
        atos = list(PADROES_COMANDOS['ato'].finditer(texto))
      
        atos_extraidos = {m.group().lower().strip()for m in atos}
        
        despachos_permitidos = {'arquive-se','intime-se','intimem-se','conceda-se', 'concedam-se',}
        
        destinatarios_complexos = {
            'embargante','recorrente','apelante','agravante',
            'embargantes','recorrentes','apelantes','agravantes',
            'embargados','recorridos','apelados','agravados',
            'embargado','recorrido','apelado','agravado',
        }
        dados_documento = {}
       
        dados_documento['cumprivel'] = (atos_extraidos.issubset(self.sentencas_permitidas))
        
        if not dados_documento['cumprivel']:

            print('⛔ Não é possível cumprir')
            # print('Tipo:', dados_documento['tipo'])
            print('Atos:', atos_extraidos)
        else:
            print('✅ Cumprível')

        resultado = []

        for j, ato in enumerate(atos):

            inicio = ato.start()

            if j < len(atos) - 1:
                fim = atos[j + 1].start()
            else:
                fim = len(texto)

            trecho = texto[inicio:fim]
            destinatarios = [m.group().lower().strip()
                for m in PADROES_COMANDOS['destinatario'].finditer(trecho)
            ]
            # autores_permitidos = any(d in partes_autoras_permitidas for d in destinatarios)
            # reus_permitidos = any(d in partes_res_permitidas for d in destinatarios)
            autores_permitidos = True
            reus_permitidos = True

            dados = {
                'texto' : texto,
                'processo': item['processo'],
                'url_mov_generica': url_mov_generica,
                # 'tipo' : dados_documento['tipo'],
                'cumprivel' : dados_documento['cumprivel'],
                'ato': ato.group(),
                'trecho': trecho, 
                'condicoes' : [],
                'destinatario': [],
                'meio': [],
                'objetivo': [],
                'prazo': [],
                'autor_permitido': autores_permitidos,
                'reu_permitido': reus_permitidos,
            }
                
            for campo in ['condicoes', 'destinatario', 'meio', 'objetivo', 'prazo']:

                dados[campo] = [m.group()
                        for m in PADROES_COMANDOS[campo].finditer(trecho)
                    ]
            # bloqueia cumprimento
            if dados['condicoes']:

                dados['cumprivel'] = False

                print('\nNÃO É POSSÍVEL CUMPRIR O ATO')
                print('Condições encontradas:')
                pprint(dados['condicoes'])
            texto_custas = [m.group()for m in PADROES_CUSTAS['custas'].finditer(trecho)]
            texto_sem_custas_ou_isencao = [m.group()for m in PADROES_CUSTAS['custas'].finditer(trecho)]
            dados['custas'] = bool(texto_custas and not texto_sem_custas_ou_isencao)

            # if dados['autor_permitido'] or dados['reu_permitido']:
            #     dados['cumprivel'] = True

            if any(d in destinatarios_complexos for d in destinatarios):
                dados['cumprivel'] = False

            if dados['custas']:
                dados['texto_custas'] = texto_custas

                # VALIDA DESTINATÁRIOS
            if dados['destinatario']:
                destinatarios_validos = self.validar_destinatarios(
                    trecho, dados['destinatario'])
                dados['destinatario'] = destinatarios_validos

                if not dados['destinatario']:
                    dados['destinatario'] = 'partes'

            resultado.append(dados)

        pprint(resultado)
        
        if salvar and item:
            self.salvar_no_banco(
                atos=resultado, texto_completo=texto,
                item=item, url_mov_generica=url_mov_generica)

        return resultado