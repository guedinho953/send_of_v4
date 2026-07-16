import re
import projudi_command_analyzer
from projudi_command_analyzer import ProjudiCommandAnalyzer
from collections import defaultdict

import spacy
from bs4 import BeautifulSoup


class DocumentAnalyzer:

    def __init__(self):
        self.projudi_analyser = ProjudiCommandAnalyzer()
        self.nlp = spacy.load("pt_core_news_sm")

        # self.PADRAO_INTIMACAO = re.compile(
        #     r"\bintim(?:e|em)[-\s\b]", re.I)
        
        # self.PADRAO_CERTIDAO = re.compile(r'\bcertifiqu(?:e|em)[-\s]?se\b')
        # self.PADRAO_EXPECA_SE_CERTIDAO = re.compile(r'\bexpeç(?:ç)(?:a|am)(?:[-\s]?se)?\s+certid[aã]o\b',re.I)
        # self.EXTRAIR_PRAZO = re.search(r'(\d+)\s*(?:dias|dia|horas|hora|mes|meses))')

        # self.PADRAO_COMANDO = re.compile(
        #     r'''((?:arquivem-se| arquivem-se de imediado, arquive-se de imediato|
        #     intimem-se|intimando-se apenas|intimando-se|intime-se|expeça-se|oficie-se|#determin\w*|
        #     calcule-se|realize|comunique-se|junte-se|certifique-se|cumpra-se|indefiro o pedido liminar|
        #     proceda-se|voltem|se tempestivo e preparado|ficando cancelada eventual audiência|p\.r\.i)[^.;]*[.;]?)''',
        #     re.I,
        # )
        self.PADRAO_COMANDO = re.compile(
            r'''
            intimem?-se |
            cite-se |
            arquivem?-se |
            oficie-se |
            expeça-se |
            cumpra-se |
            certifique-se
            ''',
            re.I | re.X
            )
        
        self.PADRAO_MEIO = re.compile(
            r'''
            por\s+oficial\s+de\s+justiça |
            por\s+carta |
            por\s+ar |
            via\s+bacenjud |
            via\s+sisbajud |
            via\s+renajud |
            eletronicamente
            ''',
            re.I | re.X
        )
        self.PADRAO_CONDICAO = re.compile(
            r'''
            se\s+tempestivo(?:\s+e\s+preparado)? |
            # após\s+o\s+trânsito\s+em\s+julgado |
            cumpridas\s+as\s+formalidades\s+legais |
            caso\s+necessário |
            independentemente\s+de\s+nova\s+conclusão
            ''',
            re.I | re.X
        )
        self.PADRAO_QUANDO = re.compile(
            r'''
            com\s*urg[eê]ncia\.?,?|
            se\s+tempestivo(?:\s+e\s+preparado)? |
            após\s*o\s*trânsito\s*em\s*julgado |
            cumpridas?\s*as\s+formalidades\s*legais|
            aguarde-se|
            caso resida em outra Comarca|
            imediatamente |
            # após\s+o\s+trânsito\s+em\s+julgado |
            # no\s+prazo\s+de\s+\d+\s+dias?
            ''',
            re.I | re.X
        )
    
     # =========================
    # EXTRAÇÃO DE PRAZO
    # =========================
    def extrair_prazo(self, texto):
        texto_lower = texto.lower()
        match = re.search(r'(\d+)\s*(?:dias|dia|horas|hora|mes|meses)', texto_lower)
        return f'{match.group(1)} - {match.group(2)}'
    
    

    # =========================
    # LIMPEZA
    # =========================
    def extrair_texto_documento(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "head", "meta", "noscript"]):
            tag.decompose()

        texto = soup.get_text(separator="\n")
        
        texto = re.sub(r'(\w+)\n(\w+)', r'\1\2', texto)
        
        texto = re.sub(r'\n+', '\n', texto)
        texto = re.sub(r'[ \t]+', ' ', texto) # [ \t]+ sequência de espaço ou tabs
        

        texto = re.sub(r'(DESPACHO|SENTENÇA|DECISÃO|FORÇA DE MANDADO)', r'\n\1\n', texto, flags=re.IGNORECASE)

        inicio = re.search(r'(DESPACHO|SENTENÇA|DECISÃO|FORÇA DE MANDADO)', texto, flags=re.IGNORECASE)
        if inicio:
            texto = texto[inicio.start():]

        fim = re.search(r'Documento Assinado Eletronicamente', texto, re.IGNORECASE)
        if fim:
            texto = texto[:fim.start()]

        linhas = [l.strip() for l in texto.split("\n") if l.strip()]
        return "\n".join(linhas)

    def limpar_texto(self, texto):
        texto = texto.replace('\n', ' ')
        texto = texto.replace('\xa0', ' ')
        texto = re.sub(r'[¹\'"]', '', texto)
        texto = re.sub(r'\s+', ' ', texto)
        return texto.strip().lower()
    
   
    

    # =========================
    # EXTRAÇÃO
    # =========================
    def extrair_comandos_regex(self, texto):
        encontrados = self.PADRAO_COMANDO.findall(texto)

        vistos = set()
        comandos = []

        for c in encontrados:
            c = c.strip()
            if c not in vistos:
                comandos.append(c)
                vistos.add(c)

        return comandos

    def extrair_comandos_spacy(self, texto):
        doc = self.nlp(texto)
        comandos = []

        for sent in doc.sents:
            s = sent.text.lower()

            if any(p in s for p in [
                "intime", "cite", "oficie", "expeça",
                "arquive", "cumpra", "determine",
                "proceda", "junte", "certifique"
            ]):
                comandos.append(sent.text.strip())

        return comandos

    # =========================
    # PROCESSAMENTO
    # =========================
    def normalizar_comandos(self, lista):
        vistos = set()
        resultado = []

        for c in lista:
            c = c.strip().lower()
            c = re.sub(r'\s+', ' ', c)

            if c not in vistos:
                vistos.add(c)
                resultado.append(c)

        return resultado

    def remover_duplicados(self, lista):
        return list(dict.fromkeys(lista))

    def classificar_comando(self, cmd):
        cmd = cmd.lower()

        if "alvar" in cmd or "libere" in cmd:
            return "ALVARA"

        if "arquiv" in cmd:
            return "ARQUIVAMENTO"

        if "ofic" in cmd:
            return "OFICIO"

        if "junte" in cmd:
            return "JUNTADA"

        if "certifique" in cmd:
            return "CERTIFICAR"

        if "intim" in cmd or "p.r.i" in cmd:
            return "INTIMACAO"

        return "OUTROS"

    def organizar_comandos(self, comandos):
        agrupado = defaultdict(list)

        for cmd in comandos:
            tipo = self.classificar_comando(cmd)
            agrupado[tipo].append(cmd)

        return agrupado
    def analisar_comandos(self, comandos, texto_completo):

        executar_agora = []
        executar_depois = []
        nao_suportado = []

        # contexto global (ex: trânsito)
        transito = self.detectar_transito(texto_completo)
        if transito:
            executar_depois.append(transito)

        for c in comandos:
            tipo = self.classificar_tipo(c)
            quando = self.extrair_quando(c)
            executavel = self.CAPACIDADES.get(tipo, False)

            item = {
                "comando": c,
                "tipo": tipo,
                "quando": quando,
                "prazo": self.extrair_prazo(c),
                "condicao": self.extrair_condicao(c),
                "meios": self.extrair_meios(c),
                "executavel": executavel
            }

            item = self.enriquecer(item)

            if not executavel:
                nao_suportado.append(item)
            elif quando == "imediato":
                executar_agora.append(item)
            else:
                executar_depois.append(item)

        return {
            "executar_agora": executar_agora,
            "executar_depois": executar_depois,
            "nao_suportado": nao_suportado
        }

    # =========================
    # PIPELINE COMPLETO
    # =========================
    def analisar_movimentacao(self, html, item):
        texto = self.extrair_texto_documento(html)
        texto = self.limpar_texto(texto)
        

        comandos_regex = self.extrair_comandos_regex(texto)
        comandos_spacy = self.extrair_comandos_spacy(texto)

        comandos = comandos_regex + comandos_spacy
        comandos = self.normalizar_comandos(comandos)

        agrupado = self.organizar_comandos(comandos)

        resultado = {
            "processo": item.get("processo"),
            "tipo_movimentacao": item.get("tipo"),
            "link_processo": item.get("link_processo"),
            "link_documento": item.get("link_documento"),
            "movimentar": item.get("movimentar"),
            "dispensar": item.get("dispensar"),
            'texto' : texto,
            "comandos": {}
        }

        for tipo, lista in agrupado.items():
            resultado["comandos"][tipo] = self.remover_duplicados(lista)

        return resultado

class ProjudiCommandParser:
    ...
# import spacy
# import re
# from bs4 import BeautifulSoup
# from collections import defaultdict
# from urllib.parse import urljoin
# from projudi_client import ProjudiClient


# nlp = spacy.load("pt_core_news_sm")


# def extrair_texto_documento(html: str) -> str:
#     soup = BeautifulSoup(html, "html.parser")

#     # remove lixo estrutural
#     for tag in soup(["script", "style", "head", "meta", "noscript"]):
#         tag.decompose()

#     texto = soup.get_text(separator="\n")

#     # 🔹 junta palavras quebradas (eletrôni\nco → eletrônico)
#     texto = re.sub(r'(\w+)\n(\w+)', r'\1\2', texto)

#     # 🔹 remove múltiplas quebras de linha
#     texto = re.sub(r'\n+', '\n', texto)

#     # 🔹 remove espaços extras
#     texto = re.sub(r'[ \t]+', ' ', texto)

#     texto = re.sub(r'(DESPACHO|SENTENÇA|DECISÃO)', r'\n\1\n', texto, flags=re.IGNORECASE)

    

#     # 🔹 corta cabeçalho antes do conteúdo relevante
#     inicio = re.search(r'(DESPACHO|SENTENÇA|DECISÃO)',texto, flags=re.IGNORECASE)
#     if inicio:
        
#         texto = texto[inicio.start():]

#     # 🔹 corta rodapé
#     fim = re.search(r'Documento Assinado Eletronicamente', texto, re.IGNORECASE)
#     if fim:
#         texto = texto[:fim.start()]

#     # 🔹 limpa linhas vazias
#     linhas = [l.strip() for l in texto.split("\n") if l.strip()]

#     return "\n".join(linhas)

# def quebrar_sentencas(texto):
#     # limpa quebras ruins
#     texto = texto.replace('\n', ' ')
    
#     # quebra por pontuação jurídica comum
#     sentencas = re.split(r'(?<=[.;:])\s+', texto)
    
#     return [s.strip() for s in sentencas if len(s.strip()) > 10]


# def limpar_texto(texto):
#     texto = texto.replace('\n', ' ')
#     texto = re.sub(r'\s+', ' ', texto)
#     return texto.lower()

# #########################################################################

# PADRAO_COMANDO = re.compile(
#     r'((?:arquivem-se|intimem-se|intimando-se|expeça-se|oficie-se|determin\w*|calcule-se|comunique-se|abstenha-se|junte-se|certifique-se|cumpra-se|proceda-se|voltem|se tempestivo e preparado)[^.;]*[.;]?)',
#     re.IGNORECASE
# )
# def extrair_comandos(texto):
#     encontrados = PADRAO_COMANDO.findall(texto)

#     # remove duplicados mantendo ordem
#     vistos = set()
#     comandos = []

#     for c in encontrados:
#         c = c.strip()
#         if c not in vistos:
#             comandos.append(c)
#             vistos.add(c)

#     return comandos



# def filtrar_comandos_spacy(texto):
#     doc = nlp(texto)
#     comandos = []

#     for sent in doc.sents:
#         s = sent.text.lower()

#         if any(p in s for p in [
#             "intime", "cite", "oficie", "expeça",
#             "arquive", "cumpra", "determine",
#             "proceda", "junte", "certifique"
#         ]):
#             comandos.append(sent.text.strip())

#     return comandos

# def normalizar_comandos(lista):
#     vistos = set()
#     resultado = []

#     for c in lista:
#         c = c.strip().lower()
#         c = re.sub(r'\s+', ' ', c)

#         if c not in vistos:
#             vistos.add(c)
#             resultado.append(c)

#     return resultado

# def classificar_comando(cmd):
#     cmd = cmd.lower()

#     #  prioridade mais alta primeiro
#     if "alvar" in cmd or "libere" in cmd:
#         return "ALVARA"

#     if "arquiv" in cmd:
#         return "ARQUIVAMENTO"

#     if "ofic" in cmd or "solicite-se ao ceapa" in cmd:
#         return "OFICIO"

#     if "junte" in cmd:
#         return "JUNTADA"

#     if "certifique" in cmd:
#         return "CERTIFICAR"

#     if "intim" in cmd or "p.r.i" in cmd:
#         return "INTIMACAO"

#     return "OUTROS"


# def organizar_comandos(comandos):
#     agrupado = defaultdict(list)

#     for cmd in comandos:
#         tipo = classificar_comando(cmd)
#         agrupado[tipo].append(cmd)

#     return agrupado

# def remover_duplicados(lista):
#     return list(dict.fromkeys(lista))

# client = ProjudiClient()
# client.iniciar()

# soup_movimentacoes = client.get_sopa(client.URL_MOVIMENTACOES)
# # extrai os dados
# movs = client.extrair_links_movimentacoes(soup_movimentacoes)

# print("\nTOTAL:", len(movs))

# for item in movs:
#     print("\n===== MOVIMENTAÇÃO =====")
#     print("Processo:", item["processo"])
#     print("Tipo:", item["tipo"])
#     print("Link processo:", item["link_processo"])
#     url = urljoin(client.LINK_BASE, item["link_documento"])
#     documento = extrair_texto_documento(client.get_documento(url))
#     # print(documento)
#     texto = documento

#     texto = limpar_texto(documento)


#     comandos_regex = extrair_comandos(texto)
#     comandos_spacy = filtrar_comandos_spacy(texto)

#     # junta os dois
#     comandos = comandos_regex + comandos_spacy
#     comandos = normalizar_comandos(comandos)

#     agrupado = organizar_comandos(comandos)

#     for tipo, lista in agrupado.items():
#         print(f"\n=== {tipo} ===")
#         for i, cmd in enumerate(remover_duplicados(lista), 1):
#             print(f"{i}. {cmd}")
    
#     print("Movimentar:", item["movimentar"])
#     print("Dispensar:", item["dispensar"])

# import spacy
# import re
# from bs4 import BeautifulSoup
# from collections import defaultdict


# class DocumentAnalyzer:

#     def __init__(self):
#         self.nlp = spacy.load("pt_core_news_sm")

#         self.PADRAO_COMANDO = re.compile(
#             r'''((?:arquivem-se|intimem-se|intimando-se|expeça-se|oficie-se|determin\w*|
#             calcule-se|comunique-se|abstenha-se|junte-se|certifique-se|cumpra-se|
#             proceda-se|voltem|se tempestivo e preparado)[^.;]*[.;]?)''',
#             re.IGNORECASE
#         )

#     # =========================
#     # LIMPEZA
#     # =========================
#     def extrair_texto_documento(self, html: str) -> str:
#         soup = BeautifulSoup(html, "html.parser")

#         for tag in soup(["script", "style", "head", "meta", "noscript"]):
#             tag.decompose()

#         texto = soup.get_text(separator="\n")

#         texto = re.sub(r'(\w+)\n(\w+)', r'\1\2', texto)
#         texto = re.sub(r'\n+', '\n', texto)
#         texto = re.sub(r'[ \t]+', ' ', texto)

#         texto = re.sub(r'(DESPACHO|SENTENÇA|DECISÃO)', r'\n\1\n', texto, flags=re.IGNORECASE)

#         inicio = re.search(r'(DESPACHO|SENTENÇA|DECISÃO)', texto, flags=re.IGNORECASE)
#         if inicio:
#             texto = texto[inicio.start():]

#         fim = re.search(r'Documento Assinado Eletronicamente', texto, re.IGNORECASE)
#         if fim:
#             texto = texto[:fim.start()]

#         linhas = [l.strip() for l in texto.split("\n") if l.strip()]
#         return "\n".join(linhas)

#     def limpar_texto(self, texto):
#         texto = texto.replace('\n', ' ')
#         texto = re.sub(r'\s+', ' ', texto)
#         return texto.lower()

#     # =========================
#     # EXTRAÇÃO
#     # =========================
#     def extrair_comandos_regex(self, texto):
#         encontrados = self.PADRAO_COMANDO.findall(texto)

#         vistos = set()
#         comandos = []

#         for c in encontrados:
#             c = c.strip()
#             if c not in vistos:
#                 comandos.append(c)
#                 vistos.add(c)

#         return comandos

#     def extrair_comandos_spacy(self, texto):
#         doc = self.nlp(texto)
#         comandos = []

#         for sent in doc.sents:
#             s = sent.text.lower()

#             if any(p in s for p in [
#                 "intime", "cite", "oficie", "expeça",
#                 "arquive", "cumpra", "determine",
#                 "proceda", "junte", "certifique"
#             ]):
#                 comandos.append(sent.text.strip())

#         return comandos

#     # =========================
#     # PROCESSAMENTO
#     # =========================
#     def normalizar_comandos(self, lista):
#         vistos = set()
#         resultado = []

#         for c in lista:
#             c = c.strip().lower()
#             c = re.sub(r'\s+', ' ', c)

#             if c not in vistos:
#                 vistos.add(c)
#                 resultado.append(c)

#         return resultado

#     def classificar_comando(self, cmd):
#         cmd = cmd.lower()

#         if "alvar" in cmd or "libere" in cmd:
#             return "ALVARA"

#         if "arquiv" in cmd:
#             return "ARQUIVAMENTO"

#         if "ofic" in cmd:
#             return "OFICIO"

#         if "junte" in cmd:
#             return "JUNTADA"

#         if "certifique" in cmd:
#             return "CERTIFICAR"

#         if "intim" in cmd or "p.r.i" in cmd:
#             return "INTIMACAO"

#         return "OUTROS"

#     def organizar_comandos(self, comandos):
#         agrupado = defaultdict(list)

#         for cmd in comandos:
#             tipo = self.classificar_comando(cmd)
#             agrupado[tipo].append(cmd)

#         return agrupado

#     # =========================
#     # PIPELINE COMPLETO
#     # =========================
#     def analisar_documento(self, html):
#         texto = self.extrair_texto_documento(html)
#         texto = self.limpar_texto(texto)

#         comandos_regex = self.extrair_comandos_regex(texto)
#         comandos_spacy = self.extrair_comandos_spacy(texto)

#         comandos = comandos_regex + comandos_spacy
#         comandos = self.normalizar_comandos(comandos)

#         return self.organizar_comandos(comandos)
