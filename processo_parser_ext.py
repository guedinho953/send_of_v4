"""Extensão do ProcessoParser com extração segura de movimentações."""
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

class ProcessoParserExt:
    """Parsing simplificado e seguro da página de DadosProcesso do Projudi."""
    base_url = 'https://projudi.tjba.jus.br/projudi'
    
    def __init__(self, html, session=None):
        self.html = html
        self.soup = BeautifulSoup(html, "html.parser")
        self.session = session  # requests.Session para baixar docs
    
    def extrair_partes(self):
        """Extrai partes do processo da página."""
        resultado = []
        tabelas = self.soup.find_all("table", class_="tabelaLista")
        for i, tabela in enumerate(tabelas):
            tipo = "EXEQUENTE" if i == 0 else "EXECUTADO"
            linhas = tabela.find_all("tr", class_=["linhaClara", "linhaEscura"])
            for linha in linhas:
                tds = linha.find_all("td")
                if len(tds) < 6:
                    continue
                nome = tds[1].get_text(strip=True)
                nome_normalizado = re.sub(r'\s+', ' ', nome.lower().strip())
                cpf = tds[3].get_text(strip=True)
                tem_advogado = "Nenhum advogado" not in tds[4].get_text()
                email = None
                telefone = None
                endereco_dict = {}
                id_linha = linha.get("id")
                if id_linha:
                    span_end = self.soup.find("span", id=f"spanEnd{id_linha.replace('tr','')}")
                    if span_end:
                        texto = span_end.get_text(" ", strip=True).upper()
                        email_m = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', texto)
                        tel_m = re.search(r'\d{10,11}', texto)
                        email = email_m.group(0) if email_m else None
                        telefone = tel_m.group(0) if tel_m else None
                resultado.append({
                    "nome": nome,
                    "nome_normalizado": nome_normalizado,
                    "cpf/cnpj": cpf,
                    "tipo": tipo,
                    "tem_advogado": tem_advogado,
                    "email": email,
                    "tel": telefone,
                })
        return resultado
    
    def extrair_movimentacoes(self):
        """Extrai movimentações de forma segura (sem recursão)."""
        resultado = []
        for tr in self.soup.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if not tds:
                continue
            numero = tds[0].get_text(strip=True)
            if not re.fullmatch(r"\d+", numero):
                continue
            # Evento
            evento = tds[1].get_text(" ", strip=True)
            # Data
            data_str = tds[2].get_text(strip=True)
            # Autor
            autor = tds[3].get_text(" ", strip=True) if len(tds) > 3 else ''
            # Observação e documentos
            obs = ''
            docs = []
            for a in tr.find_all("a", href=True):
                m = re.search(r"mostra\('sub(\d+)'\)", a["href"])
                if m:
                    id_mov = m.group(1)
                    span_sub = self.soup.find("span", id=f"sub{id_mov}")
                    span_obs = self.soup.find("span", id=f"obs{id_mov}")
                    if span_obs:
                        obs = span_obs.get_text(" ", strip=True)
                    if span_sub:
                        for a2 in span_sub.find_all("a", href=True):
                            href = a2["href"].lower()
                            if href.startswith("javascript"):
                                continue
                            docs.append({
                                "nome": a2.get_text(strip=True),
                                "url": urljoin(self.base_url, href),
                            })
            resultado.append({
                "evento": numero,
                "ato": evento,
                "ato_normalizado": evento.lower(),
                "data_texto": data_str,
                "autor": autor,
                "observacao": obs,
                "documentos": docs,
            })
        return resultado, []
    
    def buscar_dados_cumprimento(self, movimentacoes):
        """Busca dados de cumprimento (transação penal / sursis) nas movimentações."""
        dados = {
            'tipo': None, 'sub_tipo': None,
            'valor': None, 'parcelas': None, 'prazo': None,
            'documentos_ata': [],
            'ata_extraida': None,  # dados completos do parse_ata_audiencia
        }
        for mov in movimentacoes:
            texto = f"{mov.get('ato_normalizado','')} {mov.get('observacao','')}"
            texto_lower = texto.lower()

            # SURSIS - Suspensão Condicional do Processo
            if any(x in texto_lower for x in ['suspensão condicional', 'suspensao condicional', 'sursis']):
                dados['tipo'] = 'sursis'
                if 'prestação pecuniária' in texto_lower or 'prestacao pecuniaria' in texto_lower:
                    dados['sub_tipo'] = 'pecuniaria'
                    val = re.search(r'(?:R\$\s*|valor\s*(?:de\s*)?)([\d.,]+)', texto, re.I)
                    if val: dados['valor'] = val.group(1)
                    parc = re.search(r'(\d+)\s*parcelas?', texto, re.I)
                    if parc: dados['parcelas'] = int(parc.group(1))
                elif any(x in texto_lower for x in ['prestação de serviços', 'prestacao de servicos', 'serviços à comunidade', 'servicos a comunidade']):
                    dados['sub_tipo'] = 'servico'
                    prazo = re.search(r'prazo\s*(?:de\s*)?(\d+\s*(?:meses?|dias?))', texto, re.I)
                    if prazo: dados['prazo'] = prazo.group(1)
                # Coletar TODOS os docs da movimentação
                for doc in mov.get('documentos', []):
                    dados['documentos_ata'].append(doc)
                break

            # TRANSAÇÃO PENAL
            if 'homologada a transação' in texto_lower or 'homologada a transacao' in texto_lower:
                dados['tipo'] = 'transacao_penal'
                if 'prestação pecuniária' in texto_lower or 'prestacao pecuniaria' in texto_lower:
                    dados['sub_tipo'] = 'pecuniaria'
                    val = re.search(r'(?:R\$\s*|valor\s*(?:de\s*)?)([\d.,]+)', texto, re.I)
                    if val: dados['valor'] = val.group(1)
                    parc = re.search(r'(\d+)\s*parcelas?', texto, re.I)
                    if parc: dados['parcelas'] = int(parc.group(1))
                elif any(x in texto_lower for x in ['prestação de serviços', 'prestacao de servicos', 'serviços à comunidade', 'servicos a comunidade']):
                    dados['sub_tipo'] = 'servico'
                    prazo = re.search(r'prazo\s*(?:de\s*)?(\d+\s*(?:meses?|dias?))', texto, re.I)
                    if prazo: dados['prazo'] = prazo.group(1)
                elif 'prestação' in texto_lower:
                    val = re.search(r'(?:R\$\s*|valor\s*(?:de\s*)?)([\d.,]+)', texto, re.I)
                    if val:
                        dados['sub_tipo'] = 'pecuniaria'
                        dados['valor'] = val.group(1)
                        parc = re.search(r'(\d+)\s*parcelas?', texto, re.I)
                        if parc: dados['parcelas'] = int(parc.group(1))
                    else:
                        dados['sub_tipo'] = 'servico'
                # Coletar TODOS os docs da movimentação
                for doc in mov.get('documentos', []):
                    dados['documentos_ata'].append(doc)
                break

            # TAMBÉM: procurar em movimentos com termo de audiência
            if any(x in texto_lower for x in ['termo de audiência', 'termo de audiencia', 'ata de audiência', 'ata de audiencia']):
                for doc in mov.get('documentos', []):
                    dados['documentos_ata'].append(doc)

        data_obs = ''
        if movimentacoes:
            mov = movimentacoes[-1]
            data_obs = (mov.get('observacao') or '') + '\n'.join([d.get('nome','') for d in mov.get('documentos', [])])
        r_proc_obs = None
        # Tentar baixar via parser de dados do processo revisitado
        if not dados['documentos_ata']:
            pass  # sem docs para baixar

        return dados

    def _baixar_e_parsear_ata(self, dados):
        """Baixa o(s) documento(s) de ata e extrai dados estruturados."""
        import tempfile, os
        from projudi.ata_parser import parse_ata_audiencia, formatar_cumprimento_para_oficio
        
        texto_completo = ''
        for doc in dados['documentos_ata']:
            url = doc.get('url', '')
            nome = doc.get('nome', '')
            if not url:
                continue
            # PULAR online.html (visualizador) - pegar só a versão original
            if 'online' in url.lower() and 'original' not in url.lower():
                print(f'   >> Pulando online viewer: {url}')
                continue
            try:
                print(f'   >> Baixando: {url} (nome={nome})')
                r = self.session.get(url, timeout=30)
                if r.status_code != 200:
                    print(f'   >> Status: {r.status_code}')
                    continue
                content_type = r.headers.get('Content-Type', '')
                print(f'   >> Content-Type: {content_type}')
                # PDF
                if 'pdf' in content_type.lower() or url.endswith('.pdf') or 'original=true' in url:
                    import tempfile, os
                    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
                        f.write(r.content)
                        tmp = f.name
                    print(f'   >> PDF salvo em {tmp} ({len(r.content)} bytes)')
                    try:
                        import fitz
                        pdf = fitz.open(tmp)
                        for page in pdf:
                            texto_completo += page.get_text() + '\n'
                        pdf.close()
                        print(f'   >> PDF extraído com fitz: {len(texto_completo)} chars')
                    except ImportError:
                        print(f'   >> fitz não disponível, tentando PyPDF2')
                        try:
                            from PyPDF2 import PdfReader
                            reader = PdfReader(tmp)
                            for p in reader.pages:
                                texto_completo += p.extract_text() + '\n'
                            print(f'   >> PDF extraído com PyPDF2: {len(texto_completo)} chars')
                        except Exception as e:
                            print(f'   >> Erro PyPDF2: {e}')
                    except Exception as e:
                        print(f'   >> Erro fitz: {e}')
                    finally:
                        os.unlink(tmp)
                else:
                    # HTML ou texto
                    soup_doc = BeautifulSoup(r.text, 'html.parser')
                    body = soup_doc.find('body')
                    if body:
                        texto_completo += body.get_text(separator='\n', strip=True)
                    else:
                        texto_completo += soup_doc.get_text(separator='\n', strip=True)
                    print(f'   >> HTML extraído: {len(texto_completo)} chars')
            except Exception as e:
                print(f'   >> Erro download: {e}')
                continue
        
        if texto_completo:
            print(f'   >> Texto total: {len(texto_completo)} chars')
            print(f'   >> Primeiros 300: {texto_completo[:300]}')
            try:
                ata_parsed = parse_ata_audiencia(texto_completo)
                dados['ata_extraida'] = ata_parsed
                print(f'   >> ATA parseada: {ata_parsed}')
                # Sobrescrever dados com valores mais precisos da ata
                if ata_parsed.get('valor_total') and not dados.get('valor'):
                    dados['valor'] = ata_parsed['valor_total']
                if ata_parsed.get('valor_parcela'):
                    dados['valor_parcela'] = ata_parsed['valor_parcela']
                if ata_parsed.get('parcelas') and not dados.get('parcelas'):
                    dados['parcelas'] = ata_parsed['parcelas']
                if ata_parsed.get('prazo_meses') and not dados.get('prazo'):
                    dados['prazo'] = f"{ata_parsed['prazo_meses']} meses"
                if ata_parsed.get('modalidade') and not dados.get('sub_tipo'):
                    dados['sub_tipo'] = ata_parsed['modalidade']
                dados['condicoes'] = ata_parsed.get('condicoes', [])
                dados['beneficiario'] = ata_parsed.get('beneficiario')
            except Exception as e:
                print(f'   >> Erro parse ata: {e}')
                import traceback
                traceback.print_exc()
        else:
            print(f'   >> Sem texto para parsear!')
        
    def buscar_autor_vitima(self, partes):
        """Busca dados do autor/vítima nas partes."""
        for p in partes:
            tipo = (p.get('tipo') or '').lower()
            nome = (p.get('nome') or '').strip()
            if tipo == 'exequente':
                return {
                    'nome': nome,
                    'cpf': p.get('cpf/cnpj'),
                    'email': p.get('email'),
                    'tel': p.get('tel'),
                }
        return None
