import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime
from pprint import pprint


class ProcessoParser:

    UFS = {
        "AC","AL","AP","AM","BA","CE","DF","ES","GO",
        "MA","MT","MS","MG","PA","PB","PR","PE","PI",
        "RJ","RN","RS","RO","RR","SC","SP","SE","TO"
    }
    MAPA_PROMOVENTES = {
        "exequente": "PROMOVENTE",
        "autor": "PROMOVENTE",
        "requerente": "PROMOVENTE",
        }
    MAPA_PROMOVIDOS = {
        "exequente": "PROMOVENTE",
        "autor": "PROMOVENTE",
        "requerente": "PROMOVENTE",
        }

    MAPA_PARTES = {
        "exequente": "PROMOVENTE",
        "autor": "PROMOVENTE",
        "requerente": "PROMOVENTE",
        "executado": "PROMOVIDO",
        "réu": "PROMOVIDO",
        "requerido": "PROMOVIDO",
        
    }

    # =========================
    # UTIL
    # =========================
    def limpar_texto(self, texto):
        texto = texto.replace('\xa0', ' ')
        texto = texto.replace('\r', ' ').replace('\n', ' ')
        texto = re.sub(r'\s+', ' ', texto)
        return texto.strip()

    def extrair_contatos(self, texto):
        email = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', texto)
        telefone = re.search(r'\d{10,11}', texto)

        return (
            email.group(0) if email else None,
            telefone.group(0) if telefone else None
        )

    def remover_contatos(self, texto, email, telefone):
        if email:
            texto = texto.replace(email, '')
        if telefone:
            texto = texto.replace(telefone, '')
        texto = texto.replace('(Contato:', '').replace(')', '')
        return texto.strip()

    # =========================
    # ENDEREÇO
    # =========================
    def corrigir_cidade_uf(self, dados):
        if dados.get("cidade") and dados.get("uf"):
            return dados

        bairro = dados.get("bairro") or ""

        match = re.search(
            r'([a-z\s]+)\s*-\s*([a-z]{2})\s*-\s*brasil',
            bairro, re.I
        )

        if match:
            dados["cidade"] = match.group(1).strip().upper()
            dados["uf"] = match.group(2).upper()
            dados["bairro"] = None

        return dados

    def organizar_endereco(self, texto):
        texto = texto.replace("Endereço", "").strip()

        cep_match = re.search(r'\b\d{8}\b', texto)
        cep = cep_match.group(0) if cep_match else None

        if cep:
            texto = texto.replace(cep, '')

        cidade = None
        uf = None

        cidade_match = re.search(
            r',\s*([A-ZÀ-Ú\s]+?)\s*-\s*([A-Z]{2})\s*-\s*BRASIL',
            texto
        )

        if cidade_match:
            cidade = cidade_match.group(1).strip()
            uf = cidade_match.group(2)
            texto = texto.replace(cidade_match.group(0), '')

        partes = [p.strip() for p in texto.split(',') if p.strip()]

        return {
            "logradouro": partes[0] if len(partes) > 0 else None,
            "numero": partes[1] if len(partes) > 1 else None,
            "complemento": partes[2] if len(partes) > 2 else None,
            "bairro": partes[3] if len(partes) > 3 else None,
            "cidade": cidade,
            "uf": uf,
            "cep": cep
        }

    # =========================
    # PARTES
    # =========================
    def extrair_partes(self, soup):
        resultado = []
        tabelas = soup.find_all("table", class_="tabelaLista")
        revelia = False

        for i, tabela in enumerate(tabelas):
            tipo = "EXEQUENTE" if i == 0 else "EXECUTADO"

            linhas = tabela.find_all("tr", class_=["linhaClara", "linhaEscura"])

            for linha in linhas:
                tds = linha.find_all("td")

                if len(tds) < 6:
                    continue

                nome = tds[1].get_text(strip=True)
                nome_normalizado = nome.lower().strip()
                nome_normalizado = re.sub(r'\s+', ' ', nome.lower().strip())
                cpf = tds[3].get_text(strip=True)
                rg = tds[2].get_text(strip=True) if len(tds) > 2 else ''

                recebe_email = bool(
                    tds[1].find("img", src=lambda x: x and "envelope" in x)
                )

                domicilio_cnj = bool(tds[1].find(
                    "img",src=lambda x: x and "favicon-domicilio-judicial-eletronico.png" in x)
                    )
                padrao_revel = re.search(r'\((?:revel|rev\.?\s*arg\.?)\)', nome, re.I)
                if padrao_revel:
                    revelia = True
                
                texto_adv = tds[4].get_text(" ", strip=True).lower()
                tem_advogado = "Nenhum" not in texto_adv
                email = None

                # tem_advogado = bool(texto_adv)
                
                # tem_advogado = "Nenhum advogado" not in tds[4].get_text()
		        
                telefone = None
                endereco_dict = {}

                id_linha = linha.get("id")

                if id_linha:
                    span_end = soup.find("span", id=f"spanEnd{id_linha.replace('tr','')}")

                    if span_end:
                        texto = span_end.get_text(" ", strip=True).upper()

                        email, telefone = self.extrair_contatos(texto)
                        texto = self.remover_contatos(texto, email, telefone)

                        endereco_dict = self.organizar_endereco(texto)
                        endereco_dict = self.corrigir_cidade_uf(endereco_dict)

                papel = self.MAPA_PARTES.get(tipo.lower())
                papel_ativo = self.MAPA_PROMOVENTES.get(tipo.lower())
                papel_passivo = self.MAPA_PROMOVIDOS.get(tipo.lower())

                # resultado.append({
                #     "nome": nome,
                #     "cpf/cnpj": cpf,
                #     "tipo": tipo,
                #     "parte": papel,
                #     'polo_ativo': papel_ativo,
                #     'polo_passivo' : papel_passivo,
                #     "recebe_intimacao_email": recebe_email,
                #     'domicilio_cnj' : domicilio_cnj,
                #     "tem_advogado": tem_advogado,
                #     "email": email,
                #     "tel": telefone,
                #     **endereco_dict
                # })
                resultado.append({
                    "nome": nome,
                    'nome_normalizado' : nome_normalizado,
                    "cpf/cnpj": cpf,
                    "rg": rg,
                    "tipo": tipo,
                    "papel": papel,
                    "recebe_intimacao_email": recebe_email,
                    "domicilio_cnj": domicilio_cnj,
                    "tem_advogado": tem_advogado,
                    "email": email,
                    "tel": telefone,
                    'revelia' : revelia,
                    **endereco_dict
                })

        return resultado

    # =========================
    # LINKS
    # =========================
    def extrair_links(self, soup, base_url):
        links = {}

        for a in soup.find_all("a", href=True):
            href = a["href"]
            texto = a.get_text(strip=True).lower()

            url = urljoin(base_url, href)

            if "movimentar processo" in texto:
                links["movimentar"] = url
            elif "peticionar" in texto:
                links["peticionar"] = url
            elif "alterar partes" in texto:
                links["alterar_partes"] = url
            elif "negociação" in texto:
                links["negociacao"] = url
            elif "dadosprocesso" in href.lower():
                links["dados_processo"] = url

        return links
    
    def analisar_movimentacao(self, ato, observacao=None):

        texto = f"{ato} {observacao or ''}".lower()

        dados = {
        "categoria": None,
        # "subcategoria": None,
        # "parte": None,
        "meio_comunicacao": None,
        "situacao_comunicacao": None,
        # "transitado_em_julgado": None,
        "destinatario": None,
    }

        if "citação" in texto:
            dados["categoria"] = "citacao"

        elif "intimação" in texto:
            dados["categoria"] = "intimacao"

        elif "audiência" in texto:
            dados["categoria"] = "audiencia"

        elif "julgada" in texto:
            dados["categoria"] = "sentenca"

        elif "embargos" in texto:
            dados["categoria"] = "embargos"

        elif "recurso inominado" in texto:
            dados["categoria"] = "recurso"

        elif "certidão" in texto:
            dados["categoria"] = "certidao"

        elif "petição" in texto:
            dados["categoria"] = "peticao"
        if "decurso_de_prazo" in texto:
            dados["categoria"] = "decorrido"


        if "expedid" in texto:
            dados["situacao_comunicacao"] = "expedida"

        elif "lido" in texto:
            dados["situacao_comunicacao"] = "lida"

        elif "realizada" in texto:
            dados["situacao_comunicacao"] = "realizada"

        if any(x in texto for x in ["advgs.", "djen", "(djen)"]):
            dados["meio_comunicacao"] = "domicilio_cnj"
        
        elif "mandado" in texto:
            dados["meio_comunicacao"] = "mandado"

        elif "precatória" in texto:
            dados["meio_comunicacao"] = "precatoria"

        elif "aviso de recebimento" in texto:
            dados["meio_comunicacao"] = "ar"

        if "trânsito em julgado" in texto:
            dados["transito_julgado"] = True

        return dados
    
    
    def extrair_parte_movimentacao(self, texto, partes=None):
        match = re.search(
            r'(p/|para)\s+(advgs\.\s+de\s+)?(.*?)(\*|$|\))',
            texto,
            re.I
        )

        if not match:
            return None

        destinatario = (match.group(3) or "").strip().lower()
        destinatario = re.sub(r'\s+', ' ', destinatario)

        if not destinatario:
            return None

        # sem partes → retorna só o texto limpo
        if not partes:
            return destinatario

        # tenta casar com parte do processo
        for parte in partes:
            nome = parte.get("nome_normalizado") or parte.get("nome", "")
            nome = nome.lower().strip()

            if not nome:
                continue

            if nome in destinatario or destinatario in nome:
                return {
                    "nome": parte.get("nome"),
                    "papel": parte.get("papel")
                }

        # fallback
        return {
            "nome": destinatario,
            "papel": None
        }
    
    def extrair_data_leitura_do_ato(self, texto):
        match = re.search(
            r'\bem\s+(\d{2}/\d{2}/\d{2,4})',
            texto,
            re.I
        )

        if match:
            return datetime.strptime(match.group(1), "%d/%m/%y").date()

        return None
        
    def extrair_data_referencia(self, texto):
        match = re.search(
            r'referente ao evento.*?\((\d{2}/\d{2}/\d{2})\)',
            texto,
            re.I
        )

        if match:
            return match.group(1)

        return None
    # =========================
    # MOVIMENTAÇÕES
    # =========================
    def extrair_movimentacoes(self, soup, base_url):
        rows = soup.find_all('tr')
        movimentacoes = []
        links_mov = []
        observacao = ''

        for tr in rows:
            tds = tr.find_all("td")
            print(len(tds))
            for i, td in enumerate(tds):
                print(f"TD {i}")
                print(td.prettify()[:1000])

            if len(tds) < 4:
                continue

            numero = tds[0].get_text(strip=True)
            if not numero.isdigit():
                continue
            
            for i, prox_tr in enumerate(tr.find_next_siblings("tr", limit=10), start=1):
                if numero == "314":
                    print(tr.prettify())
                print(f"\nIRMÃO {i}")
                print(prox_tr.get_text(" ", strip=True))

                for img in prox_tr.find_all("img"):
                    print("IMG:", img.get("title"))

                for a in prox_tr.find_all("a", href=True):
                    print("LINK:", a.get_text(strip=True))
            # for prox_tr in tr.find_next_siblings("tr", limit=10):
                # encontrou o ícone de observação
                if prox_tr.find("img", title=lambda x: x and 
                                "observações da movimentação" in x.lower()):

                    obs_tr = prox_tr.find_next_sibling("tr")

                    if obs_tr:
                        td_obs = obs_tr.find("td")

                        if td_obs:
                            observacao = td_obs.get_text(" ", strip=True)
                    continue
                
                for a in prox_tr.find_all("a", href=True):

                    href = a["href"]

                    if "DownloadArquivo" in href:

                        links_mov.append({
                            "nome": a.get_text(" ", strip=True),
                            "url": urljoin(base_url, href)
                        })

                # observacao = prox_tr.get_text(" ", strip=True)
                # for a in prox_tr.find_all("a", href=True):

                #     href = a["href"]

                #     links_mov.append({
                #         "nome": a.get_text(" ", strip=True),
                #         "url": urljoin(base_url, href)
                #     })
            # procura nas próximas linhas ligadas ao evento
            
                prox_tds = prox_tr.find_all("td")
                if (len(prox_tds) >= 4 and prox_tds[0].get_text(strip=True).isdigit()):
                    break
                # for a in prox_tr.find_all("a", href=True):
                #     links_mov.append({
                #         "texto": a.get_text(" ", strip=True),
                #         "url": urljoin(base_url, a["href"])
                #     })

            evento = tds[1].get_text(" ", strip=True)
            texto_evento = evento.lower()
            data_leitura_str = self.extrair_data_leitura_do_ato(texto_evento)
            data_refencia_str = self.extrair_data_referencia(texto_evento)

            data_str = tds[2].get_text(strip=True)
            data = datetime.strptime(data_str, "%d/%m/%y").date()
            autor = tds[3].get_text(" ", strip=True)
            # if obs:
            #     observacao = obs
            # if len(tds) > 4:
            #     observacao = tds[4].get_text(" ", strip=True)
           
            dados_mov = self.analisar_movimentacao(texto_evento)
            destinatario = self.extrair_parte_movimentacao(texto_evento)
            categoria = dados_mov.get("categoria")
            situacao = dados_mov.get("situacao_comunicacao")
            # filtro primeiro (evita trabalho inútil)
            categoria = dados_mov.get("categoria")
            if not categoria or not situacao:
               continue
            # só adiciona destinatário se fizer sentido
            if destinatario and dados_mov.get("situacao_comunicacao"):
               dados_mov["destinatario"] = destinatario
            
            

            # append FINAL (sem duplicação de dict)
            movimentacoes.append({
                "evento": numero,
                "ato": evento,
                "ato_normalizado": texto_evento,
                "data_texto": data_str,
                "data_obj": data,
                'data_leitura_str' : data_leitura_str,
                'data_referencia_str' : data_refencia_str,
                "autor": autor,
                'observacao' : observacao,
                "categoria": dados_mov.get("categoria"),
                "meio_comunicacao": dados_mov.get("meio_comunicacao"),
                "situacao_comunicacao": dados_mov.get("situacao_comunicacao"),
                "destinatario": dados_mov.get("destinatario"),
                'links_mov' : links_mov,
            })

        return movimentacoes
       ########################################################################     
            # lidas sem destinatario
            # lidas = [
            #     mov for mov in movimentacoes
            #     if mov.get("situacao_comunicacao") == "lida"
            # ]
            # for mov in movimentacoes:
            #     if data_str in mov.get('data_texto') or data_str in mov.get('texto_normalizado'):
            # eventos_encadeados = [mov for mov in movimentacoes if data_str in (
            #     mov.get('texto_normalizado') or mov.get('data_texto'))]
            # eventos_encadeados = [
            #     mov
            #     for mov in movimentacoes
            #     if mov.get("data_referencia_str") == data_str
            # ]
                
            # lidas = [
            #     mov for mov in movimentacoes
            #     if mov.get("categoria") == "intimacao"
            #     and mov.get("situacao_comunicacao") == "lida"
            #     and mov.get("destinatario")
            # ]
            # eventos_encadeados = [
            #     mov for mov in lidas
            #     if mov.get("data_referencia_str") == data_str
            # ]

            # if categoria and situacao:
            #     print(f"""
            # EVENTO: {evento}
            # DATA: {data_str}
            # DADOS: {dados_mov}
            # {'-'*80}
            # """)
            
                


            # for mov in eventos_encadeados:
            #     print("EVENTO ORIGINAL:", numero)
            #     print("DATA ORIGINAL:", data_str)

            #     print("LIDO NO EVENTO:", mov.get("evento"))
            #     print("DATA LEITURA:", mov.get("data_leitura_str"))
            #     print("DATA REFERENCIA:", mov.get("data_referencia_str"))
            #     print("DESTINATÁRIO:", mov.get("destinatario"))
            #     print("-" * 80)
                # print("-" * 80)
                # print("EVENTO:", mov.get("evento"))
                # print("ATO:", mov.get("ato"))
                # print("DATA:", mov.get("data_leitura_str"))
                # print( "DATA REF:", mov.get("data_referencia_str"))
                # print("DESTINATÁRIO:", mov.get("destinatario"))
                # print("SITUAÇÃO:", mov.get("situacao_comunicacao"))
            
            # for mov in eventos_encadeados:
            #     print("EVENTO:", mov.get("evento"))
            #     print("ATO:", mov.get("ato"))
            #     print("DATA_STR:", mov.get("data_str"))
            #     # print("DATA:", mov.get("data_leitura_str"))
            #     print( "DATA REF:", mov.get("data_referencia_str"))
            # for original in movimentacoes:

            #     eventos_encadeados = [
            #         mov for mov in lidas
            #         if mov.get("data_referencia_str") == original.get("data_texto")
            #     ]

            #     for lido in eventos_encadeados:

            #         print(f"""
            #         EVENTO ORIGINAL: {original.get('evento')}
            #         CATEGORIA: {original.get('categoria')}
            #         SITUAÇÃO: {original.get('situacao_comunicacao')}
            #         ATO: {original.get('ato')}
            #         DESTINATÁRIO: {original.get('destinatario')}
            #         DATA: {original.get('data_texto')}

            #         ↳ EVENTO LIDO: {lido.get('evento')}
            #         ↳ DESTINATÁRIO: {lido.get('destinatario')}
            #         ↳ DATA LEITURA: {lido.get('data_leitura_str')}
            #         {'-'*80}
            #         """)
  
            
     

    # =========================
    # PIPELINE COMPLETO
    # =========================
    def parse_processo(self, soup, base_url):
        
        return {
            "partes": self.extrair_partes(soup),
            "movimentacoes": self.extrair_movimentacoes(soup, base_url),
            "links": self.extrair_links(soup, base_url)
        }
        
    
############################################################

import re
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin
from datetime import datetime
from pprint import pprint
from bs4 import BeautifulSoup


class ProcessoParser:
    base_url = 'https://projudi.tjba.jus.br/projudi'
    def __init__(self, html):
        self.html = html
        self.soup = BeautifulSoup(html, "html.parser")


    UFS = {
        "AC","AL","AP","AM","BA","CE","DF","ES","GO",
        "MA","MT","MS","MG","PA","PB","PR","PE","PI",
        "RJ","RN","RS","RO","RR","SC","SP","SE","TO"
    }
    MAPA_PROMOVENTES = {
        "exequente": "PROMOVENTE",
        "autor": "PROMOVENTE",
        "requerente": "PROMOVENTE",
        }
    MAPA_PROMOVIDOS = {
        "exequente": "PROMOVENTE",
        "autor": "PROMOVENTE",
        "requerente": "PROMOVENTE",
        }

    MAPA_PARTES = {
        "exequente": "PROMOVENTE",
        "autor": "PROMOVENTE",
        "requerente": "PROMOVENTE",
        "executado": "PROMOVIDO",
        "réu": "PROMOVIDO",
        "requerido": "PROMOVIDO",
        
    }
    PADROES_SENTENCA = [
    "sentença",
    "julgada procedente",
    "julgado procedente",
    "julgado improcedente",
    "extinto o processo",
    "extinção do processo",
    "extinto com resolução do mérito",
    "extinto sem resolução do mérito",
    "homologada a transação",
    ]

    def detectar_sentenca(self, texto):
        texto = texto.lower()
        

        for padrao in self.PADROES_SENTENCA:
            if 'referente' in texto:
                continue
            if padrao in texto:
                return True, padrao  # retorna o motivo também

        return False, None

    # =========================
    # UTIL
    # =========================
    def limpar_texto(self, texto):
        texto = texto.replace('\xa0', ' ')
        texto = texto.replace('\r', ' ').replace('\n', ' ')
        texto = re.sub(r'\s+', ' ', texto)
        return texto.strip()

    def extrair_contatos(self, texto):
        email = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', texto)
        telefone = re.search(r'\d{10,11}', texto)

        return (
            email.group(0) if email else None,
            telefone.group(0) if telefone else None
        )

    def remover_contatos(self, texto, email, telefone):
        if email:
            texto = texto.replace(email, '')
        if telefone:
            texto = texto.replace(telefone, '')
        texto = texto.replace('(Contato:', '').replace(')', '')
        return texto.strip()

    # =========================
    # ENDEREÇO
    # =========================
    def corrigir_cidade_uf(self, dados):
        if dados.get("cidade") and dados.get("uf"):
            return dados

        bairro = dados.get("bairro") or ""

        match = re.search(
            r'([a-z\s]+)\s*-\s*([a-z]{2})\s*-\s*brasil',
            bairro, re.I
        )

        if match:
            dados["cidade"] = match.group(1).strip().upper()
            dados["uf"] = match.group(2).upper()
            dados["bairro"] = None

        return dados

    def organizar_endereco(self, texto):
        texto = texto.replace("Endereço", "").strip()

        cep_match = re.search(r'\b\d{8}\b', texto)
        cep = cep_match.group(0) if cep_match else None

        if cep:
            texto = texto.replace(cep, '')

        cidade = None
        uf = None

        cidade_match = re.search(
            r',\s*([A-ZÀ-Ú\s]+?)\s*-\s*([A-Z]{2})\s*-\s*BRASIL',
            texto
        )

        if cidade_match:
            cidade = cidade_match.group(1).strip()
            uf = cidade_match.group(2)
            texto = texto.replace(cidade_match.group(0), '')

        partes = [p.strip() for p in texto.split(',') if p.strip()]

        return {
            "logradouro": partes[0] if len(partes) > 0 else None,
            "numero": partes[1] if len(partes) > 1 else None,
            "complemento": partes[2] if len(partes) > 2 else None,
            "bairro": partes[3] if len(partes) > 3 else None,
            "cidade": cidade,
            "uf": uf,
            "cep": cep
        }

    # =========================
    # PARTES
    # =========================
    def extrair_partes(self, soup):
        resultado = []
        tabelas = soup.find_all("table", class_="tabelaLista")

        for i, tabela in enumerate(tabelas):
            tipo = "EXEQUENTE" if i == 0 else "EXECUTADO"

            linhas = tabela.find_all("tr", class_=["linhaClara", "linhaEscura"])

            for linha in linhas:
                tds = linha.find_all("td")

                if len(tds) < 6:
                    continue

                nome = tds[1].get_text(strip=True)
                revel = False
                nome_normalizado = nome.lower().strip()
                if 'rev. arg' in nome_normalizado:
                    revel = True
                nome_normalizado = re.sub(r'\s+', ' ', nome.lower().strip())
                cpf = tds[3].get_text(strip=True)
                rg = tds[2].get_text(strip=True) if len(tds) > 2 else ''

                recebe_email = bool(
                    tds[1].find("img", src=lambda x: x and "envelope" in x)
                )

                domicilio_cnj = bool(tds[1].find(
                    "img",src=lambda x: x and "favicon-domicilio-judicial-eletronico.png" in x)
                    )
                
                # texto_adv = tds[4].get_text(" ", strip=True)

                # tem_advogado = bool(texto_adv)
                
                tem_advogado = "Nenhum advogado" not in tds[4].get_text()

                email = None
                telefone = None
                endereco_dict = {}

                id_linha = linha.get("id")

                if id_linha:
                    span_end = soup.find("span", id=f"spanEnd{id_linha.replace('tr','')}")

                    if span_end:
                        texto = span_end.get_text(" ", strip=True).upper()

                        email, telefone = self.extrair_contatos(texto)
                        texto = self.remover_contatos(texto, email, telefone)

                        endereco_dict = self.organizar_endereco(texto)
                        endereco_dict = self.corrigir_cidade_uf(endereco_dict)

                papel = self.MAPA_PARTES.get(tipo.lower())
                papel_ativo = self.MAPA_PROMOVENTES.get(tipo.lower())
                papel_passivo = self.MAPA_PROMOVIDOS.get(tipo.lower())

                # resultado.append({
                #     "nome": nome,
                #     "cpf/cnpj": cpf,
                #     "tipo": tipo,
                #     "parte": papel,
                #     'polo_ativo': papel_ativo,
                #     'polo_passivo' : papel_passivo,
                #     "recebe_intimacao_email": recebe_email,
                #     'domicilio_cnj' : domicilio_cnj,
                #     "tem_advogado": tem_advogado,
                #     "email": email,
                #     "tel": telefone,
                #     **endereco_dict
                # })
                resultado.append({
                    "nome": nome,
                    'nome_normalizado' : nome_normalizado,
                    "cpf/cnpj": cpf,
                    "rg": rg,
                    "tipo": tipo,
                    "papel": papel,
                    'revel' : revel,
                    "recebe_intimacao_email": recebe_email,
                    "domicilio_cnj": domicilio_cnj,
                    "tem_advogado": tem_advogado,
                    "email": email,
                    "tel": telefone,
                    **endereco_dict
                })


        return resultado

    # =========================
    # LINKS
    # =========================
    def extrair_links(self, soup, base_url):
        links = {}

        for a in soup.find_all("a", href=True):
            href = a["href"]
            texto = a.get_text(strip=True).lower()

            url = urljoin(base_url, href)

            if "movimentar processo" in texto:
                links["movimentar"] = url
            elif "peticionar" in texto:
                links["peticionar"] = url
            elif "alterar partes" in texto:
                links["alterar_partes"] = url
            elif "negociação" in texto:
                links["negociacao"] = url
            elif "dadosprocesso" in href.lower():
                links["dados_processo"] = url

        return links
    
    def analisar_movimentacao(self, ato, observacao=None):

        texto = f"{ato} {observacao or ''}".lower()
        
        is_sentenca, motivo = self.detectar_sentenca(texto)

        dados = {
        "categoria": None,
        # "subcategoria": None,
        # "parte": None,
        "meio_comunicacao": None,
        "situacao_comunicacao": None,
        # "transitado_em_julgado": None,
        "destinatario": None,
        }

        if "citação" in texto:
            dados["categoria"] = "citacao"

        elif "intimação" in texto:
            dados["categoria"] = "intimacao"

        elif "audiência" in texto:
            dados["categoria"] = "audiencia"

        elif "disponibilização" in texto:
            dados["categoria"] = "disponibilizado no djen"

        elif is_sentenca:
            dados["categoria"] = "sentenca"
            

        elif "embargos" in texto:
            dados["categoria"] = "embargos"

        elif "recurso inominado" in texto:
            dados["categoria"] = "recurso"

        elif "certidão" in texto:
            dados["categoria"] = "certidao"

        elif "petição" in texto:
            dados["tipo_ato"] = "peticao"

        if "decurso_de_prazo" in texto:
            dados["categoria"] = "decorrido"

        if "expedid" in texto:
            dados["situacao_comunicacao"] = "expedida"

        elif "lido" in texto:
            dados["situacao_comunicacao"] = "lida"

        elif "realizada" in texto:
            dados["situacao_comunicacao"] = "realizada"

        if any(x in texto for x in ["advgs.", "djen", "(djen)"]):

            dados["meio_comunicacao"] = "domicilio_cnj"
        
        elif "mandado" in texto:
            dados["meio_comunicacao"] = "mandado"

        elif "precatória" in texto:
            dados["meio_comunicacao"] = "precatoria"

        elif "aviso de recebimento" in texto:
            dados["meio_comunicacao"] = "ar"

        # if "trânsito em julgado" in texto:
        #     dados["transito_julgado"] = True

        return dados
    
    
    def extrair_parte_movimentacao(self, texto, partes=None):
        match = re.search(
            r'(p/|para)\s+(advgs\.\s+de\s+)?(.*?)(\*|$|\))',
            texto,
            re.I
        )

        if not match:
            return None

        destinatario = (match.group(3) or "").strip().lower()
        destinatario = re.sub(r'\s+', ' ', destinatario)

        if not destinatario:
            return None

        # sem partes → retorna só o texto limpo
        if not partes:
            return destinatario

        # tenta casar com parte do processo
        for parte in partes:
            nome = parte.get("nome_normalizado") or parte.get("nome", "")
            nome = nome.lower().strip()

            if not nome:
                continue

            if nome in destinatario or destinatario in nome:
                return {
                    "nome": parte.get("nome"),
                    "papel": parte.get("papel")
                }

        # fallback
        return {
            "nome": destinatario,
            "papel": None
        }
    
    def extrair_data_leitura_do_ato(self, texto):
        match = re.search(
            r'\bem\s+(\d{2}/\d{2}/\d{2,4})',
            texto,
            re.I
        )

        if match:
            return datetime.strptime(match.group(1), "%d/%m/%y").date()

        return None
        
    def extrair_data_referencia(self, texto):
        match = re.search(
            r'referente ao evento.*?\((\d{2}/\d{2}/\d{2})\)',
            texto,
            re.I
        )

        if match:
            return match.group(1)

        return None
    def extrair_data_disponibilizacao_djen(self, texto):
        m = re.search(
            r'disponibilização.*?\((\d{2}/\d{2}/\d{2})\)',
            texto,
            re.I
        )

        if m:
            return datetime.strptime(
                m.group(1),
                "%d/%m/%y"
            ).date()

        return None


    def extrair_evento_referenciado(self, texto):

        m = re.search(
            r'referente ao evento\s+(.*)',
            texto,
            re.I
        )

        if not m:
            return {}

        bloco = m.group(1).strip()

        resultado = {
            "evento_referenciado": None,
            "data_referencia": None,
            "prazo_dias": None
        }

        # -----------------------------
        # evento + data (18/05/26)
        # -----------------------------
        m_evento = re.search(r'(.+?)\((\d{2}/\d{2}/\d{2})\)', bloco)

        if m_evento:
            resultado["evento_referenciado"] = m_evento.group(1).strip()
            resultado["data_referencia"] = m_evento.group(2)

        # -----------------------------
        # prazo
        # -----------------------------
        m_prazo = re.search(r'prazo:\s*(\d+)\s*dias', bloco, re.I)

        if m_prazo:
            resultado["prazo_dias"] = int(m_prazo.group(1))

        return resultado

    #     return None
    # =========================
    # MOVIMENTAÇÕES
    # =========================
    def extrair_movimentacoes(self):
        base_url = self.base_url
        soup= self.soup
        resultado = []
        movimentacoes = []
        relacoes_mov = {}
        anexos_mov = {}

        for tr in soup.find_all("tr"):
            tds = tr.find_all("td", recursive = False)
            if not tds:
                continue
        
            numero = tds[0].get_text(strip=True)
        
            if not re.fullmatch(r"\d+", numero):
                continue
            

            documentos = []
            observacao = ''
            id_mov = None
            # print("EVENTO:", numero)
            for a in tr.find_all("a", href=True):
                href = a["href"]
                m = re.search(r"mostra\('sub(\d+)'\)", a["href"])
                if m:
                    id_mov = m.group(1)
            if id_mov:
                span_sub = soup.find("span", id=f"sub{id_mov}")
                span_obs = soup.find("span", id=f"obs{id_mov}")
               
                # observação
                if span_obs:
                    observacao = span_obs.get_text(" ", strip=True)
                # documentos
                if span_sub:
                    for a in span_sub.find_all("a", href=True):
                        href = a["href"].lower()
                        if href.startswith("javascript"):
                            continue
                        if not any(x in href for x in [
                            "downloadarquivo",
                            "baixar",
                            "documento",
                            "visualizar"
                        ]):
                            continue
                        if "original=true" in href:
                            continue
                        documentos.append({
                            "nome": a.get_text(strip=True),
                            "url": urljoin(base_url, href)
                        })
                        mov_por_evento = {
                            # 'evento' : numero,
                            "observacao" : observacao, 
                            "documentos" : documentos,
                            }
            # print("EVENTO:", numero)
            # print("OBS:", observacao)
            # print("DOC:", documentos)


            evento = tds[1].get_text(" ", strip=True)
            texto_evento = evento.lower()
            data_leitura_str = self.extrair_data_leitura_do_ato(texto_evento)
            data_refencia_str = self.extrair_data_referencia(texto_evento)

            data_str = tds[2].get_text(strip=True)
            data = datetime.strptime(data_str, "%d/%m/%y").date()
            autor = tds[3].get_text(" ", strip=True)

            # if len(tds) > 4:
            #     observacao = tds[4].get_text(" ", strip=True)
           
           
            
            # append FINAL (sem duplicação de dict)
            movimentacoes.append({
                "evento": numero,
                "ato": evento,
                "ato_normalizado": texto_evento,
                "data_texto": data_str,
                "data_obj": data,
                'data_leitura_str' : data_leitura_str,
                'data_referencia_str' : data_refencia_str,
                "autor": autor, 
                })
            
            dados_mov = self.analisar_movimentacao(texto_evento)
            data_disponibilizacao_djen = self.extrair_data_disponibilizacao_djen(texto_evento)
            evento_ref = self.extrair_evento_referenciado(texto_evento) or {}

            destinatario = self.extrair_parte_movimentacao(texto_evento)
            categoria = dados_mov.get("categoria")
            situacao = dados_mov.get("situacao_comunicacao") or ''

            # filtro primeiro (evita trabalho inútil)
            categoria = dados_mov.get("categoria") or ''
            # if not categoria or not situacao:
            #     continue
            # só adiciona destinatário se fizer sentido
            if destinatario and dados_mov.get("situacao_comunicacao"):
                dados_mov["destinatario"] = destinatario

            relacoes_mov[numero] = {
                "categoria": dados_mov.get("categoria"),
                "meio_comunicacao": dados_mov.get("meio_comunicacao"),
                "situacao_comunicacao": dados_mov.get("situacao_comunicacao"),
                "destinatario": dados_mov.get("destinatario"),
                "data_leitura": self.extrair_data_leitura_do_ato(texto_evento),
                "data_referencia": self.extrair_data_referencia(texto_evento),
                'data_leitura_str' : data_leitura_str,
                'data_referencia_str' : data_refencia_str,
                "data_djen": data_disponibilizacao_djen,
                "evento_referenciado": evento_ref.get("evento_referenciado"),
                "prazo_dias_ev_ref": evento_ref.get("prazo_dias"),
                }
            anexos_mov[numero] = {
                "observacao": observacao,
                "documentos": documentos,
                }
        for mov in movimentacoes:
            evento = mov["evento"]
            mov_final = {
                **mov,
                **relacoes_mov.get(evento, {}),
                **anexos_mov.get(evento, {}),
                }
          

            resultado.append(mov_final)

        return resultado, movimentacoes
    
    # =========================
    # PIPELINE COMPLETO
    # =========================
    def parse_processo(self, soup, base_url):
        movimentacoes, resultado = self.extrair_movimentacoes(soup, base_url)
        return {
            "partes": self.extrair_partes(soup),
            "movimentacoes_raw": movimentacoes,
            "movimentacoes": resultado,
            "links": self.extrair_links(soup, base_url),
        }

    # =========================
    # CLASSE / NATUREZA DO PROCESSO
    # =========================
    PADROES_CRIMINAIS = [
        'ação penal', 'acao penal', 'procedimento criminal',
        'termo circunstanciado', 'transação penal', 'transacao penal',
        'inquérito policial', 'inquerito policial',
        'ação penal', 'representação criminal', 'representacao criminal',
        'habeas corpus', 'mandado de segurança criminal',
        'recurso criminal', 'execução penal', 'execucao penal',
        'medida protetiva', 'violência doméstica', 'violencia domestica',
        'crime', 'penal',
    ]

    def extrair_classe(self, soup=None) -> dict:
        """Extrai a classe/natureza do processo da página DadosProcesso.

        Retorna:
            {
                'classe': 'Procedimento do Juizado Especial Cível',
                'natureza': 'civel' | 'criminal' | None,
                'e_criminal': bool,
            }
        """
        soup = soup or self.soup
        classe = None

        try:
            # Procura na tabela de dados do processo um td com "Classe:"
            for td in soup.find_all('td'):
                texto_label = td.get_text(' ', strip=True).lower().strip()
                # Pode ser "Classe:" ou "Classe Judicial:" etc.
                if texto_label.startswith('classe') and texto_label.endswith(':'):
                    prox = td.find_next_sibling('td')
                    if prox:
                        classe = prox.get_text(' ', strip=True)
                        break

            if not classe:
                # Fallback: procura em qualquer lugar da página
                for tag in soup.find_all(['td', 'th', 'span', 'div']):
                    texto = tag.get_text(' ', strip=True)
                    m = re.search(r'Classe[:\s]+(.+)', texto, re.I)
                    if m:
                        classe = m.group(1).strip()
                        break
        except Exception:
            pass

        if not classe:
            return {'classe': None, 'natureza': None, 'e_criminal': False}

        # Detecta se é criminal
        classe_lower = classe.lower()
        e_criminal = any(p in classe_lower for p in self.PADROES_CRIMINAIS)
        natureza = 'criminal' if e_criminal else 'civel'

        return {
            'classe': classe,
            'natureza': natureza,
            'e_criminal': e_criminal,
        }
    # =========================
    # LOCALIZADOR
    # =========================
    def extrair_localizador(self, soup=None) -> dict:
        """Extrai o localizador atual do processo da página DadosProcesso.

        Retorna:
            {'codigo': '22614', 'descricao': 'SISBAJUD'} ou {}
        """
        soup = soup or self.soup
        try:
            # Tenta encontrar o select codTipoLocalizador (presente na página de movimentação)
            sel = soup.find('select', {'id': 'codTipoLocalizador'})
            if sel:
                opt = sel.find('option', selected=True)
                if opt and opt.get('value', '-1') != '-1':
                    return {
                        'codigo': opt['value'],
                        'descricao': opt.get_text(strip=True),
                    }
            # Fallback: procura na tabela de dados do processo
            for td in soup.find_all('td'):
                texto = td.get_text(' ', strip=True).lower()
                if 'localizador' in texto:
                    # Pega o próximo td
                    prox = td.find_next_sibling('td')
                    if prox:
                        cod = prox.get_text(' ', strip=True)
                        # Tenta extrair código numérico
                        m = re.search(r'(\d{4,6})', cod)
                        return {
                            'codigo': m.group(1) if m else cod,
                            'descricao': cod,
                        }
        except Exception:
            pass
        return {}


