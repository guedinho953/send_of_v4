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
    "julgada procedente em parte a ação",
    'extinto o processo por perempção, litispendência ou coisa julgada',
    "julgada parcialmente procedente",
    'extinto o processo por incompetência em razão da pessoa',
    "julgada improcedente",
    "julgado improcedente",
    "extinto o processo",
    "extinção do processo",
    "extinto com resolução do mérito",
    "extinto sem resolução do mérito",
    "homologada a transação",
    ]
    PADROES_DECISAO_URGENCIA = [
        'conclusos para pedido urgência',
        'concedida a medida liminar',
        'não concedida a medida liminar',
    ]
    PADROES_AUDIENCIAS = [
        'audiência conciliação cancelada',
        'audiência de conciliação designada (telepresencial)',
        'juntada de termo de audiência',
        ]
    PADROES_RECURSOS = [
        'juntada de petição de embargos de declaração',
        'juntada de petição de contrarrazões recursais',
        'recebido o recurso sem efeito suspensivo',
        'remetidos os autos para turmas recursais',
    ]

    PADROES_JUNTADA_DOCS = [
        'juntada de outros tipos de oocumentos',
        
    ]
    PADROES_CERTIDAO = [
        'juntada de certidão',
        'ato ordinatório praticado',
    ]
    PADROES_MANDADOS = {
        "mandado assinado": "assinado",
        "juntada de mandado": "juntado",
        "mandado devolvido entregue ao destinatário": "devolvido_entregue",
        "mandado devolvido não entregue ao destinatário": "devolvido_nao_entregue",
    }
    PADROES_DJEN = [
        'disponibilização no diário da justiça eletrônico - djen',
        'juntada de não confirmação da citação eletrônica',
        'não confirmada a citação eletrônica',
        'leitura realizada via domicílio eletrônico',
    ]
    PADRAO_INTIMACOES = [
        'intimação à disposição',
    ]
    PADRAO_DESPACHOS = [
        'proferido despacho de mero expediente',
    ]
    PADRAO_AR = [
        'juntada de ar - aviso de recebimento',
        'devolução sem leitura',
    ]
    PADROES_DECURSO_PRAZO = [
        'transitado em julgado',
        ]

    # def detectar_sentenca(self, texto):
    #     texto = texto.lower()
        
    #     for padrao in self.PADROES_SENTENCA:
    #         if 'referente' in texto:
    #             continue
    #         if padrao in texto:
    #             return True, padrao  # retorna o motivo também

    #     return False, None

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

                revel = False
                nome = tds[1].get_text(strip=True)

                nome_normalizado = re.sub(r'\s+', ' ', nome.lower().strip())

                if 'rev. arg' in nome_normalizado:
                    revel = True

                cpf = tds[3].get_text(strip=True)

                recebe_email = bool(
                    tds[1].find("img", src=lambda x: x and "envelope" in x)
                )

                domicilio_cnj = bool(
                    tds[1].find("img", src=lambda x: x and "favicon-domicilio-judicial-eletronico.png" in x)
                )

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

                resultado.append({
                    "nome": nome,
                    "nome_normalizado": nome_normalizado,
                    "cpf/cnpj": cpf,
                    "tipo": tipo,
                    "papel": papel,
                    "revel": revel,
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
    
    def analisar_movimentacao(self, texto, observacao=None, dados_partes=None):

        texto = f"{texto} {observacao or ''}".lower()

        dados = {
            "categoria": None,
            "subcategoria": None,
            "meio_comunicacao": None,
            "situacao_comunicacao": None,
            "destinatario": None,
        }

        # ======================
        # CATEGORIAS BÁSICAS
        # ======================
        if "citação" in texto:
            dados["categoria"] = "citacao"

        elif "intimação" in texto:
            dados["categoria"] = "intimacao"

        elif "petição" in texto:
            dados["categoria"] = "peticao"

        elif "decorrido" in texto:
            dados["categoria"] = "decurso de prazo"

        # ======================
        # DJEN
        # ======================
        if "disponibilização" in texto:
            dados["categoria"] = "disponibilizado no djen"
            dados["meio_comunicacao"] = True

        elif "não confirmação da citação eletrônica" in texto:
            dados["categoria"] = "disponibilizado no djen"
            dados["meio_comunicacao"] = 'djen'
            dados['situacao_comunicacao'] = 'não confirmada'

            # só altera dados já prontos
            if dados_partes:
                for p in dados_partes:
                    if p.get("papel") == "destinatário":
                        p["domicilio_cnj"] = False

        # ======================
        # SENTENÇA
        # ======================
        padrao_sentenca = next(
            (p for p in self.PADROES_SENTENCA if p in texto),
            None
        )
        if padrao_sentenca and not dados.get("categoria"):
            dados["categoria"] = "sentença"
            # dados["subcategoria"] = padrao_sentenca

        # ======================
        # RECURSOS
        # ======================
        padrao_recurso = next(
            (p for p in self.PADROES_RECURSOS if p in texto),
            None
        )
        if padrao_recurso:
            dados["categoria"] = "recurso"
            dados["subcategoria"] = padrao_recurso

        # ======================
        # AUDIÊNCIA
        # ======================
        padrao_audiencia = next(
            (p for p in self.PADROES_AUDIENCIAS if p in texto),
            None
        )
        if padrao_audiencia:
            dados["categoria"] = "audiencia"
            dados["subcategoria"] = padrao_audiencia

        # ======================
        # MANDADO
        # ======================
        padrao_mandado = next(
            (p for p in self.PADROES_MANDADOS if p in texto),
            None
        )
        if padrao_mandado:
            dados["meio_comunicacao"] = "mandado"
            dados["situacao_comunicacao"] = padrao_mandado

        # ======================
        # AR
        # ======================
        padrao_ar = next(
            (p for p in self.PADRAO_AR if p in texto),
            None
        )
        if padrao_ar:
            dados["meio_comunicacao"] = "ar"
            dados["situacao_comunicacao"] = padrao_ar
        situacao = None

        if any(x in texto for x in ["expedid", "expedição", "expedicao"]):
            situacao = "expedida"

        elif any(x in texto for x in ["lido", "leitura"]):
            situacao = "lida"

        elif "realizada" in texto:
            situacao = "realizada"

        elif "devolvido" in texto:
            situacao = "devolvida"

        elif "não confirmação" in texto or "nao confirmacao" in texto:
            situacao = "não confirmada"
            
        elif 'leitura realizada via domicílio eletrônico' in texto:
            dados["meio_comunicacao"] = "djen"
            dados["situacao_comunicacao"] = "confirmada"


        if situacao:
            dados["situacao_comunicacao"] = situacao

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
            r'referente ao evento\s+(.+?)(?:\(|$)',
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

        # evento + data (18/05/26)
        m_evento = re.search(r'(.+?)\((\d{2}/\d{2}/\d{2})\)', bloco)

        if m_evento:
            resultado["evento_referenciado"] = m_evento.group(1).strip()
            resultado["data_referencia"] = m_evento.group(2)

        # prazo
        m_prazo = re.search(r'prazo:\s*(\d+)\s*dias', bloco, re.I)

        if m_prazo:
            resultado["prazo_dias"] = int(m_prazo.group(1))

        return resultado
    # def extrair_evento_referenciado(self, texto):

    #     m = re.search(
    #         r'referente ao evento\s+(.*)',
    #         texto,
    #         re.I
    #     )

    #     if not m:
    #         return {}

    #     bloco = m.group(1).strip()

    #     resultado = {
    #         "evento_referenciado": None,
    #         "data_referencia": None,
    #         "prazo_dias": None
    #     }

    #     # -----------------------------
    #     # evento + data (18/05/26)
    #     # -----------------------------
    #     m_evento = re.search(r'(.+?)\((\d{2}/\d{2}/\d{2})\)', bloco)

    #     if m_evento:
    #         resultado["evento_referenciado"] = m_evento.group(1).strip()
    #         resultado["data_referencia"] = m_evento.group(2)

    #     # -----------------------------
    #     # prazo
    #     # -----------------------------
    #     m_prazo = re.search(r'prazo:\s*(\d+)\s*dias', bloco, re.I)

    #     if m_prazo:
    #         resultado["prazo_dias"] = int(m_prazo.group(1))

    #     return resultado

    #     return None
    # =========================
    # MOVIMENTAÇÕES
    # =========================
    def extrair_movimentacoes(self):

        soup = self.soup
        base_url = self.base_url

        resultado = []
        movimentacoes = []

        relacoes_mov = {}
        anexos_mov = {}

        # 🔥 EXTRAI UMA VEZ SÓ
        dados_partes = self.extrair_partes(soup)

        for tr in soup.find_all("tr"):
            tds = tr.find_all("td", recursive=False)

            if not tds:
                continue

            numero = tds[0].get_text(strip=True)
            if not re.fullmatch(r"\d+", numero):
                continue

            documentos = []
            observacao = ''
            id_mov = None

            for a in tr.find_all("a", href=True):
                m = re.search(r"mostra\('sub(\d+)'\)", a["href"])
                if m:
                    id_mov = m.group(1)

            if id_mov:
                span_sub = soup.find("span", id=f"sub{id_mov}")
                span_obs = soup.find("span", id=f"obs{id_mov}")

                if span_obs:
                    observacao = span_obs.get_text(" ", strip=True)

                if span_sub:
                    for a in span_sub.find_all("a", href=True):
                        href = a["href"].lower()

                        if "javascript" in href:
                            continue
                        if not any(x in href for x in ["downloadarquivo", "baixar", "documento", "visualizar"]):
                            continue
                        if "original=true" in href:
                            continue

                        documentos.append({
                            "nome": a.get_text(strip=True),
                            "url": urljoin(base_url, href)
                        })

            evento = tds[1].get_text(" ", strip=True)
            texto_evento = evento.lower()

            data_str = tds[2].get_text(strip=True)
            data = datetime.strptime(data_str, "%d/%m/%y").date()

            autor = tds[3].get_text(" ", strip=True)

            movimentacoes.append({
                "evento": numero,
                "ato": evento,
                "ato_normalizado": texto_evento,
                "data_texto": data_str,
                "data_obj": data,
                "autor": autor,
            })

            # 🔥 análise leve (SEM HTML)
            dados_mov = self.analisar_movimentacao(
                texto_evento,
                observacao=observacao,
                dados_partes=dados_partes
            )
            relacoes_mov[numero] = dados_mov

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
