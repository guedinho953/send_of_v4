"""Rastrear movimentações e expedir documentos automaticamente.
Varre movimentações do Projudi, compara com RAGExamples e expede
o documento adequado (mandado ou ofício) conforme o template vinculado.

Uso:
  python expedir_rapido.py                     # rastrear (padrão)
  python expedir_rapido.py --oficios-only      # só ofícios
  python expedir_rapido.py --mandados-only     # só mandados
  python expedir_rapido.py --processo CNJ      # expedir processo específico
"""
import os, sys, re, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import date
from django.template import Template, Context
from django.db.models import Max

from accounts.models import User
from processes.models import Process, DocumentTemplate, Party, RAGExample, GeneratedDocument
from processes.movimentacoes_service import buscar_cumprimentos_similares
from projudi.services import ProjudiService
from projudi_client import ProjudiClient
from processo_parser_ext import ProcessoParserExt


def session_projudi():
    """Obtém sessão Projudi via captura robusta de cookies."""
    user = User.objects.filter(is_active=True).first()
    if not user:
        print('❌ Nenhum usuário ativo')
        sys.exit(1)
    service = ProjudiService(user)
    result = service._get_session_from_cookies()
    if not result:
        print('❌ Não foi possível capturar a sessão do Projudi.')
        print('   Deixe o Firefox aberto e logado no Projudi.')
        sys.exit(1)
    return user, result[0], result[1]


def rastrear_e_expedir(tipo=None):
    """
    Varre movimentações, match RAG e expede.
    tipo=None (todos), 'mandado', 'oficio'
    """
    user, session, cookies_dict = session_projudi()

    print('\n========== RASTREAR E EXPEDIR ==========')
    if tipo:
        print(f'Filtrando: {tipo}')
    else:
        print('Tipo: todos (mandados + ofícios)')

    client = ProjudiClient()
    client.session = session
    client.cookies = cookies_dict

    pages = client.obter_paginas_finais_movimentacoes(quantidade=3)
    print(f'{len(pages)} página(s) para varrer')

    movs = []
    for p in pages:
        data = {'pagina': str(p), 'loginJuiz': ''}
        rp = session.post(client.URL_MOVIMENTACOES, data=data, timeout=15)
        if len(rp.text) > 1000:
            sp = BeautifulSoup(rp.text, 'html.parser')
            movs.extend(client.extrair_links_movimentacoes(sp))

    print(f'{len(movs)} movimentação(ões) encontrada(s)')

    if tipo == 'mandado':
        templates_validos = DocumentTemplate.objects.filter(template_type='mandado', active=True)
    elif tipo == 'oficio':
        templates_validos = DocumentTemplate.objects.filter(template_type='oficio', active=True)
    else:
        templates_validos = DocumentTemplate.objects.filter(template_type__in=['mandado', 'oficio'], active=True)

    expedidos = 0
    erros = 0

    for mov in movs:
        proc_num = mov.get('processo', '')
        if not proc_num:
            continue

        doc_url = mov.get('link_documento', '')
        if not doc_url:
            continue

        if not doc_url.startswith('http'):
            doc_url = urljoin('https://projudi.tjba.jus.br/projudi/', doc_url)

        try:
            r_doc = session.get(doc_url, timeout=30)
            if r_doc.status_code != 200:
                continue
            texto = BeautifulSoup(r_doc.text, 'html.parser').get_text(' ', strip=True)
            if len(texto) < 50:
                continue

            similares = buscar_cumprimentos_similares(texto, top_k=5)
            if not similares:
                continue

            melhor = None
            template = None
            rag = None
            palavras_texto = set(texto.lower().split())

            for s in similares:
                # Usa despacho_ato + observacao para comparação (mais preciso)
                # A observacao tem o conteúdo real da decisão (ex: detalhes do CIAP/RPV)
                texto_rag = s['despacho_ato'] + ' ' + s.get('despacho_observacao', '')
                palavras_rag_s = set(texto_rag.lower().split())
                total_s = max(len(palavras_rag_s), 1)
                if len(palavras_texto & palavras_rag_s) / total_s < 0.70:
                    continue
                try:
                    rag_cand = RAGExample.objects.get(id=s['id'])
                    # ── Filtro semântico de palavras-chave ──
                    # Para ofícios: exige que o texto da movimentação contenha
                    # ao menos uma palavra-chave específica do tipo de ofício.
                    # O despacho_ato curto (ex: "Homologação de Transação Penal")
                    # matcharia qualquer processo com essas palavras genéricas.
                    # O filtro usa o texto COMPLETO (ato + observação) para o
                    # threshold de similaridade, mas EXIGE um sinal forte no
                    # texto original da movimentação para confirmar o match.
                    if tipo == 'oficio' or (tipo is None and (
                        rag_cand.sequencia_cumprimento or
                        rag_cand.suggested_templates.filter(
                            template_type='oficio').exists()
                    )):
                        texto_lower = texto.lower()
                        tem_sinal_oficio = any(
                            kw in texto_lower
                            for kw in ['ofício', 'oficio', 'oficie-se',
                                       'expeça-se ofício', 'expeça-se oficio',
                                       'requisitório', 'requisitorio',
                                       'ciap', 'rpv',
                                       'requisição de pequeno valor',
                                       'requisicao de pequeno valor',
                                       'transação penal', 'transacao penal']
                        )
                        if not tem_sinal_oficio:
                            continue
                    if rag_cand.sequencia_cumprimento:
                        # Verifica tipo na sequência
                        seq_tipos = {p.get('tipo') for p in rag_cand.sequencia_cumprimento}
                        if tipo and tipo not in seq_tipos:
                            continue
                        # Valida que template_id existe e é do tipo certo (quando aplicável)
                        if tipo in ('mandado', 'oficio'):
                            ids_validos = set(templates_validos.values_list('id', flat=True))
                            tem_template_valido = any(
                                p.get('template_id') in ids_validos
                                for p in rag_cand.sequencia_cumprimento
                                if p.get('tipo') == tipo
                            )
                            if not tem_template_valido:
                                continue
                        melhor = s
                        template = None
                        rag = rag_cand
                        break
                    t = rag_cand.suggested_templates.filter(id__in=templates_validos).first()
                    if t:
                        melhor = s
                        template = t
                        rag = rag_cand
                        break
                except RAGExample.DoesNotExist:
                    continue

            if not melhor:
                continue

            if rag and rag.sequencia_cumprimento:
                print(f'\n  {proc_num}: match com sequência ({len(rag.sequencia_cumprimento)} passo(s))')
                _executar_sequencia_rapido(
                    rag.sequencia_cumprimento, mov, proc_num, texto,
                    session, cookies_dict, user, rag)
                expedidos += 1
                continue

            pct = len(palavras_texto & set(melhor['despacho_ato'].lower().split())) / max(len(set(melhor['despacho_ato'].lower().split())), 1)
            print(f'\n  {proc_num}: match {melhor["similaridade"]} pal ({pct:.0%}) → {template.name}')

            # ── CommandAnalyzer: classifica o texto antes de prosseguir ──
            from projudi.command_analyzer import CommandAnalyzer
            ca = CommandAnalyzer()
            ca_result = ca.analisar(texto)

            # Se o analyzer diz que não é cumprível, avisa e continua
            if not ca_result.get('cumprivel'):
                # Ainda pode ser processado se for ofício (ex: "expeça-se ofício RPV" tem condição)
                if template.template_type != 'oficio':
                    print(f'   ⏳ Comando não cumprível automaticamente ({ca_result["tipo"]})')
                    continue

            # Classifica o tipo de cumprimento para uso no FluxoDecisor
            tipo_cumprimento = None
            if ca_result.get('comandos'):
                tipo_cumprimento = ca_result['comandos'][0].get('tipo_cumprimento')
                print(f'   📋 CommandAnalyzer: {tipo_cumprimento} ({ca_result["tipo"]})')

            proc = Process.objects.filter(number=proc_num).first()
            if not proc:
                print('   — criando processo...', end='')
                proc = _criar_processo(session, mov, proc_num, user)
                if not proc:
                    print(' falhou')
                    continue
                print(' ✅')

            # ── ComunicacaoTracker: pre-check antes de expedir ──
            from projudi.comunicacao_tracker import ComunicacaoTracker
            try:
                # Baixa DadosProcesso para obter movimentações
                r_dados = session.get(proc.projudi_url, timeout=30)
                if r_dados.status_code == 200 and 'expirou' not in r_dados.text.lower():
                    from projudiProcessNavigator import ProcessoParser
                    parser = ProcessoParser(r_dados.text)
                    movs_parser, _ = parser.extrair_movimentacoes()
                    tracker = ComunicacaoTracker(movs_parser)
                else:
                    tracker = ComunicacaoTracker([])
            except Exception:
                tracker = ComunicacaoTracker([])

            tipo_ato = 'oficio' if (template and template.template_type == 'oficio') else 'mandado'

            # Para mandados: destinatário é o RÉU/EXECUTADO
            # Para ofícios CIAP (Transação Penal): destinatário é o AUTOR DO FATO
            # Para ofícios RPV: destinatário é o ENTE DEVEDOR (réu/executado)
            if template and template.template_type == 'mandado':
                partes = list(Party.objects.filter(
                    process=proc,
                    role__in=['reu', 'executado', 'PROMOVIDO', 'EXECUTADO']
                ))
                if not partes:
                    partes = [Party.objects.filter(process=proc).first()]
            elif template and template.template_type == 'oficio':
                eh_ciap = 'ciap' in template.name.lower()
                if eh_ciap:
                    # CIAP: autor do fato é o RÉU/EXECUTADO (quem aceitou a transação)
                    partes = list(Party.objects.filter(
                        process=proc,
                        role__in=['reu', 'executado', 'PROMOVIDO', 'EXECUTADO']
                    ))
                else:
                    # RPV: ente devedor
                    partes = list(Party.objects.filter(
                        process=proc,
                        role__in=['reu', 'executado', 'PROMOVIDO', 'EXECUTADO']
                    ))
                if not partes:
                    partes = [Party.objects.filter(process=proc).first()]
            else:
                partes = [Party.objects.filter(process=proc).first()]

            # Extrai dados da ata de audiência (CIAP) antes de gerar os ofícios
            dados_ata = None
            eh_oficio_ciap = (template and template.template_type == 'oficio'
                              and 'ciap' in template.name.lower())
            if eh_oficio_ciap:
                dados_ata = _extrair_dados_ata(session, proc, mov)
                # Filtra partes: só AUTORES DO FATO extraídos da ata
                if dados_ata and dados_ata.get('autores_do_fato'):
                    nomes_ata = [n.upper().strip() for n in dados_ata['autores_do_fato']]
                    partes_filtradas = []
                    for p in partes:
                        p_nome = p.name.upper().strip() if p.name else ''
                        if any(n in p_nome or p_nome in n for n in nomes_ata):
                            partes_filtradas.append(p)
                    if partes_filtradas:
                        print(f'   🎯 {len(partes_filtradas)} autor(es) do fato encontrado(s) nas partes')
                        partes = partes_filtradas
                    else:
                        # Cria parte temporária a partir do nome da ata
                        from types import SimpleNamespace
                        novas_partes = []
                        for nome_ata in nomes_ata[:5]:
                            nome_limpo = re.sub(r'\s+', ' ', nome_ata).strip()
                            novas_partes.append(SimpleNamespace(
                                name=nome_ata, address='', email='',
                                phone='', cpf_cnpj=''))
                        if novas_partes:
                            print(f'   🆕 {len(novas_partes)} autor(es) do fato criados da ata')
                            partes = novas_partes
                        else:
                            print('   ⏭️ Pulando processo')
                            continue

            for part in partes:
                if not part:
                    print('   — sem partes')
                    continue

                # ── PRE-CHECK: já foi expedido para esta parte? ──
                nome_parte_ex = part.name if hasattr(part, 'name') else str(part)
                ja_exp = tracker.ja_expedida(tipo_ato, nome_parte_ex)
                if ja_exp.get('existe'):
                    print(f'   ⏭️ {tipo_ato} já expedido para {nome_parte_ex[:40]} ({ja_exp["situacao"]})')
                    continue

                print(f'   ✅ {template.name} — {part.name}')

                html_doc = _gerar_html(proc, part, rag, template, dados_ata=dados_ata)
                if not html_doc:
                    continue

                if template.template_type == 'mandado':
                    sucesso = _expedir_mandado(proc, session, cookies_dict, html_doc, part)
                else:
                    sucesso = _expedir_oficio(proc, session, cookies_dict, html_doc, part, template)

                if sucesso:
                    expedidos += 1
                    print(f'   ✅ {template.name} expedido para {part.name}')
                    # ── POST-TRACK: registra expedição ──
                    try:
                        tracker.rastrear_resultado(proc.number, tipo_ato, nome_parte_ex, tipo_ato)
                    except Exception:
                        pass
            else:
                erros += 1

        except Exception as e:
            print(f'   ❌ Erro: {e}')
            import traceback; traceback.print_exc()
            erros += 1

    print(f'\n{"="*50}')
    print(f'Expedidos: {expedidos} | Erros: {erros}')
    print(f'{"="*50}')


def _executar_sequencia_rapido(sequencia, mov, proc_num, texto,
                                session, cookies_dict, user, rag=None):
    """Executa cada passo da sequencia_cumprimento."""
    from projudi.movimentacao_service import MovimentacaoService
    from processes.models import Process, Party, DocumentTemplate
    from projudi.rag_router import _mapear_categoria_por_obs
    from types import SimpleNamespace

    print(f'   📋 Sequência de {len(sequencia)} passo(s):')

    for i, passo in enumerate(sequencia, 1):
        tipo = passo.get('tipo', '')
        obs = passo.get('observacao', '')
        template_id = passo.get('template_id')
        subtipo = passo.get('subtipo')

        print(f'      [{i}/{len(sequencia)}] {tipo}...', end=' ')

        try:
            if tipo == 'movimentacao':
                service = MovimentacaoService(user)
                record = service.importar(
                    processo_numero=proc_num,
                    act_verb='movimentacao',
                    observacao=obs or texto[:500],
                    categoria=_mapear_categoria_por_obs(obs or texto),
                    processo_cnj=proc_num,
                    url_processo=mov.get('link_processo', ''),
                    codigo_movimentacao=str(passo.get('codigo_mov', '581')),
                    descricao_movimentacao=passo.get(
                        'descricao_mov', 'Cumprimento de Decisão'),
                )
                print(f'Movimentação #{record.id}')
                # Executa a Mov581 automaticamente
                print('  ▶️ Executando Mov581...')
                ok = service.executar(record)
                if ok:
                    print('   ✅ Mov581 concluída')
                else:
                    print('   ⚠️ Mov581 pode ter falhado')

            elif tipo == 'intimacao_eletronica':
                """Mov581 + intimação automática (MovimentarAnalise ou MovimentarProcesso)."""
                service = MovimentacaoService(user)
                print('  ▶️ Executando intimação eletrônica...')
                
                # Tenta extrair cod_analise da movimentação (se veio da lista de análises)
                cod_analise = None
                if mov:
                    mov_link = mov.get('movimentar', '')
                    if mov_link and 'codAnalise=' in mov_link:
                        cod_analise = mov_link.split('codAnalise=')[1].split('&')[0]
                
                ok = service.executar_com_intimacao(
                    processo_numero=proc_num,
                    observacao=obs or texto[:500],
                    codigo_mov=str(passo.get('codigo_mov', '581')),
                    descricao_mov=passo.get('descricao_mov', 'Intimação'),
                    cod_analise=cod_analise,
                )
                if ok:
                    print('   ✅ Intimação eletrônica concluída')
                else:
                    print('   ⚠️ Intimação eletrônica pode ter falhado')

            elif tipo in ('mandado', 'oficio'):
                if not template_id:
                    print('sem template_id, pulando')
                    continue
                try:
                    tmpl = DocumentTemplate.objects.get(id=template_id, active=True)
                except DocumentTemplate.DoesNotExist:
                    print(f'template #{template_id} não encontrado')
                    continue

                proc = Process.objects.filter(number=proc_num).first()
                if not proc:
                    proc = _criar_processo(session, mov, proc_num, user)
                if not proc:
                    print('processo não encontrado')
                    continue

                # Filtra partes: mandado → réu; ofício → role-based (exceto CIAP)
                dados_ata = None
                if tipo == 'mandado':
                    partes = Party.objects.filter(
                        process=proc,
                        role__in=['reu', 'executado', 'PROMOVIDO', 'EXECUTADO']
                    )
                    if not partes:
                        partes = Party.objects.filter(process=proc)[:1]
                else:
                    # CIAP: autor do fato vem EXCLUSIVAMENTE da ata (não usa role)
                    eh_oficio_ciap = (
                        tmpl and tmpl.template_type == 'oficio'
                        and 'ciap' in tmpl.name.lower()
                    )
                    if eh_oficio_ciap:
                        dados_ata = _extrair_dados_ata(session, proc, mov)
                        if dados_ata and dados_ata.get('autores_do_fato'):
                            nomes_ata = [n.upper().strip() for n in dados_ata['autores_do_fato']]
                            from types import SimpleNamespace
                            novas_partes = []
                            for nome_ata in nomes_ata[:5]:
                                nome_limpo = re.sub(r'\s+', ' ', nome_ata).strip()
                                # Tenta encontrar RG no Party existente
                                rg_parte = ''
                                try:
                                    party_existente = Party.objects.filter(
                                        process=proc, name__icontains=nome_limpo[:30]
                                    ).first()
                                    if party_existente:
                                        rg_parte = party_existente.rg or ''
                                except Exception:
                                    pass
                                novas_partes.append(SimpleNamespace(
                                    name=nome_ata, address='', email='',
                                    phone='', cpf_cnpj='', rg=rg_parte,
                                    nome_pai='', nome_mae=''))
                            if novas_partes:
                                print(f'   🆕 {len(novas_partes)} autor(es) do fato da ata')
                                partes = novas_partes
                            else:
                                print('   ⏭️ Pulando processo (sem autores do fato)')
                                continue
                        else:
                            # Fallback: usa qualquer parte como destinatário
                            print('   ⚠️ Ata sem autores do fato — usando parte do processo')
                            partes = list(Party.objects.filter(
                                process=proc,
                                role__in=['reu', 'executado', 'PROMOVIDO', 'EXECUTADO']
                            ))
                            if not partes:
                                partes = [Party.objects.filter(process=proc).first()]
                    else:
                        # Ofício comum (RPV, etc.): usa role-based
                        partes = list(Party.objects.filter(
                            process=proc,
                            role__in=['reu', 'executado', 'PROMOVIDO', 'EXECUTADO']
                        ))
                        if not partes:
                            partes = [Party.objects.filter(process=proc).first()]

                for part in partes:
                    rag_ctx = rag or SimpleNamespace(
                        despacho_ato='', despacho_observacao='',
                        despacho_data='', despacho_autor='MARTINHO FERRAZ DA NOBREGA JUNIOR')
                    html_doc = _gerar_html(proc, part, rag_ctx, tmpl, dados_ata=dados_ata)
                    if not html_doc:
                        continue

                    if tipo == 'mandado' or tmpl.template_type == 'mandado':
                        subtipo_val = subtipo or '11'
                        part._subtipo_mandado = str(subtipo_val)
                        sucesso = _expedir_mandado(
                            proc, session, cookies_dict, html_doc, part, subtipo=subtipo_val)
                    else:
                        sucesso = _expedir_oficio(proc, session, cookies_dict, html_doc, part, tmpl)

                    if sucesso:
                        print(f'{tmpl.name} — {part.name}')
                    else:
                        print(f'{tmpl.name} falhou — {part.name}')

            else:
                print(f'tipo desconhecido: {tipo}')

        except Exception as e:
            print(f'erro: {e}')
            import traceback; traceback.print_exc()


def _criar_processo(session, mov, proc_num, user):
    """Cria Process + Party acessando DadosProcesso do Projudi."""
    from projudiProcessNavigator import ProcessoParser
    from projudi.models import Vara, Court
    from base.utils import normalize_process_number

    link_proc = mov.get('link_processo', '')
    if not link_proc:
        return None

    try:
        r = session.get(link_proc, timeout=30)
        if r.status_code != 200 or 'expirou' in r.text.lower():
            return None

        parser = ProcessoParser(r.text)
        partes_raw = parser.extrair_partes(parser.soup)

        court, _ = Court.objects.get_or_create(
            code='TJBA', defaults={'name': 'TJBA', 'state': 'BA', 'tenant': user.tenant})
        vara, _ = Vara.objects.get_or_create(
            code='2VSJ-PA',
            defaults={'name': '2ª VSJ de Paulo Afonso', 'comarca': 'Paulo Afonso',
                      'court': court, 'tenant': user.tenant})

        proc = Process.objects.create(
            number=proc_num, number_normalized=normalize_process_number(proc_num),
            status='analyzing', vara=vara, court=court,
            projudi_url=link_proc, tenant=user.tenant)

        for p in partes_raw:
            nome = p.get('nome', '').strip()
            if not nome:
                continue
            role = 'autor' if p.get('tipo', '').upper() in ('EXEQUENTE', 'PROMOVENTE') else 'reu'
            end_parts = []
            logradouro = p.get('logradouro', '') or ''
            numero = p.get('numero', '') or ''
            complemento = p.get('complemento', '') or ''
            bairro = p.get('bairro', '') or ''
            cidade = p.get('cidade', '') or ''
            uf = p.get('uf', '') or ''
            cep = p.get('cep', '') or ''

            # Monta endereço formatado (mesmo padrão do enrichment de mandados)
            linha1 = logradouro
            if numero:
                linha1 += f', {numero}'
            if complemento:
                linha1 += f' - {complemento}'
            if bairro:
                if linha1:
                    linha1 += f', {bairro}'
                else:
                    linha1 = bairro
            endereco = linha1
            if cidade or uf:
                endereco += f'<br>{cidade}/{uf}' if cidade and uf else f'<br>{cidade or uf}'
            if cep:
                cep_fmt = f'{cep[:5]}-{cep[5:]}' if len(cep) == 8 else cep
                endereco += f'<br>CEP {cep_fmt}'

            Party.objects.get_or_create(
                process=proc, name=nome, tenant=user.tenant,
                defaults={
                    'name_normalized': nome.lower().strip(), 'role': role,
                    'cpf_cnpj': p.get('cpf/cnpj', ''), 'email': p.get('email', '') or '',
                    'phone': p.get('tel', '') or '', 'address': endereco,
                    'rg': p.get('rg', '') or '',
                    'nome_pai': p.get('nome_pai', '') or '',
                    'nome_mae': p.get('nome_mae', '') or '',
                })

        return proc
    except Exception:
        return None


def _extrair_dados_ata(session, proc, mov=None):
    """Extrai dados da ata de audiência (autores do fato, prestação, parcelas).

    A ata de audiência é um documento HTML vinculado à movimentação
    que contém os termos da transação penal (CIAP):
    - autor do fato (infrator) — SÓ esses devem receber ofício
    - tipo de prestação (pecuniária ou serviço comunitário)
    - valor, parcelas, forma de pagamento
    """
    import re
    from bs4 import BeautifulSoup

    dados = {
        'prestacao_tipo': '',
        'prestacao_valor': '',
        'prestacao_parcelas': '',
        'prestacao_descricao': '',
        'autores_do_fato': [],  # nomes extraídos da ata
        'ata_encontrada': False,
    }

    # 1. Acessa DadosProcesso para encontrar movimentos com atas
    projudi_url = getattr(proc, 'projudi_url', None) or (
        mov.get('link_processo', '') if mov else '')
    if not projudi_url:
        return dados

    try:
        r = session.get(projudi_url, timeout=30)
        if r.status_code != 200 or 'expirou' in r.text.lower():
            return dados

        soup = BeautifulSoup(r.text, 'html.parser')

        # 2. Percorre movimentos procurando eventos de audiência
        # (o documento pode ser "online.html" sem "ata" no nome)
        for tr in soup.find_all('tr'):
            tds = tr.find_all('td', recursive=False)
            if not tds:
                continue
            if not tds[0].get_text(strip=True).isdigit():
                continue

            texto_evento = tds[1].get_text(' ', strip=True).lower()
            if not any(x in texto_evento for x in
                       ['audiência', 'audiencia', 'termo de audiência',
                        'termo de audiencia', 'junta', 'termo']):
                continue

            id_mov = None
            for a in tr.find_all('a', href=True):
                m = re.search(r"mostra\('sub(\d+)'\)", a['href'])
                if m:
                    id_mov = m.group(1)
            if not id_mov:
                continue

            span_sub = soup.find('span', id=f'sub{id_mov}')
            if not span_sub:
                continue

            for a in span_sub.find_all('a', href=True):
                nome_doc = a.get_text(strip=True).lower()
                # Se o evento já é de audiência, processa TODOS os documentos
                # Senão, só processa se o nome conter "ata" ou "audiência"
                evento_eh_audiencia = any(x in texto_evento for x in
                    ['audiência', 'audiencia', 'termo de audiência', 'termo de audiencia'])
                if not evento_eh_audiencia and not any(x in nome_doc for x in
                    ['ata', 'audiência', 'audiencia']):
                    continue

                href = a['href']
                if href.startswith('javascript'):
                    continue
                from urllib.parse import urljoin
                url_doc = urljoin('https://projudi.tjba.jus.br/projudi/', href)

                # 3. Download do documento da audiência
                try:
                    r_ata = session.get(url_doc, timeout=30)
                    if r_ata.status_code != 200:
                        continue

                    # Detecta se é PDF ou HTML
                    content_type = r_ata.headers.get('Content-Type', '')
                    soup_ata = None
                    texto_limpo = ''
                    if 'pdf' in content_type.lower():
                        try:
                            import subprocess, tempfile
                            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                                tmp.write(r_ata.content)
                                tmp_path = tmp.name
                            result = subprocess.run(
                                ['pdftotext', tmp_path, '-l', '10', '-'],
                                capture_output=True, text=True, timeout=30)
                            texto_limpo = result.stdout
                            os.unlink(tmp_path)
                        except Exception as e:
                            try:
                                import io, PyPDF2
                                pdf_file = io.BytesIO(r_ata.content)
                                reader = PyPDF2.PdfReader(pdf_file)
                                texto_limpo = ' '.join(
                                    page.extract_text() or ''
                                    for page in reader.pages
                                )
                            except Exception:
                                print('   ⚠️ Erro ao extrair texto do PDF')
                                continue
                    else:
                        soup_ata = BeautifulSoup(r_ata.text, 'html.parser')
                        texto_limpo = soup_ata.get_text(' ', strip=True)

                    # Verifica se a ata é do MESMO processo
                    proc_num_ata = ''
                    for m_nproc in re.finditer(
                        r'(?:N[úu]mero do processo|Processo)\s*:?\s*([\d.-]+)',
                        texto_limpo, re.I):
                        proc_num_ata = m_nproc.group(1).strip()
                        break
                    if proc_num_ata:
                        proc_atual = re.sub(r'[^\d]', '', str(proc.number))
                        proc_ata = re.sub(r'[^\d]', '', proc_num_ata)
                        if proc_atual and proc_ata and proc_atual != proc_ata:
                            print(f'   ⏭️ Ata do processo {proc_num_ata} (atual: {proc.number})')
                            continue
                        else:
                            print(f'   ✅ Ata do processo {proc_num_ata}')

                    dados['ata_encontrada'] = True
                    texto_lower = texto_limpo.lower()

                    # ── Extrai AUTORES DO FATO ──
                    # Só extrai se ainda não encontramos (evita que PDFs
                    # sem texto sobrescrevam a extração do HTML)
                    if dados['autores_do_fato']:
                        continue

                    autores = []

                    # Padrão 0: linha direta "AUTOR DO FATO: NOME" (pdf/texto simples)
                    # Mais confiável para PDFs onde o nome está na mesma linha
                    for linha in texto_limpo.split('\n'):
                        if re.match(r'.*\bautor\s+do\s+fato\b\s*:', linha, re.I):
                            nome = linha.split(':', 1)[1].strip().upper()
                            if nome and len(nome) > 5:
                                # Remove sufixos indesejados
                                nome = re.sub(
                                    r'\s+(?:AOS|ACEITOU|ACEITA|PARA|NOS|EM|NA|ÀS|FICOU|COMPROMETEU|PRESTA|DEVER[ÁA]|OFICIAR[ÁA]).*',
                                    '', nome, flags=re.I
                                ).strip()
                                if nome:
                                    autores.append(nome)

                    # Padrão 1: "Autor do fato:" (HTML) - regex com stop words
                    if not autores:
                        for m in re.finditer(
                            r'autor(?:es)?\s+do\s+fato\s*:?\s*([A-ZÀ-Ú\s]{5,60}?)(?:\s+(?:Aos|Aceitou|Aceita|para|nos|em|Na|Às|Ficou|Compromete|Presta|Condições|Deverá|Devera|Oficiará|Oficiara)|\s*$|\.)',
                            texto_limpo, re.I):
                            raw = m.group(1).strip()
                        for nome in re.split(r'\s+e\s+|\s*,\s*', raw):
                            nome = nome.strip().upper()
                            if nome and len(nome) > 5:
                                autores.append(nome)

                    # Padrão 2: "AUTOR DO FATO" como cabeçalho de seção no PDF
                    if not autores:
                        blocos = re.split(
                            r'\n(?=AUTORIDADE|TESTEMUNHA|VÍTIMA|VITIMA|ÓRGÃO|ORGAO|DISTRIBUI)',
                            texto_limpo, flags=re.I)
                        for bloco in blocos:
                            if 'autor do fato' in bloco.lower():
                                linhas = bloco.split('\n')
                                dentro = False
                                for linha in linhas:
                                    if 'autor do fato' in linha.lower():
                                        dentro = True
                                        continue
                                    if dentro:
                                        nome = re.sub(r'\s+', ' ', linha).strip().upper()
                                        if (nome and len(nome) > 8
                                            and not any(x in nome.lower() for x in
                                                ['juízo', 'juizo', 'vara', 'comarca',
                                                 'paulo afonso', 'tribunal', 'justiça',
                                                 'brasil', 'protocolado', 'distribuído',
                                                 'distribuido', 'assinado',
                                                 'código', 'codigo', 'validação',
                                                 'documento', 'eletronicamente',
                                                 'advogada', 'registrado',
                                                 'termo', 'circunstanciado',
                                                 'petição', 'peticao', 'inicial',
                                                 'tamanho', 'assunto', 'autoridade',
                                                 'distribuição', 'distribuicao',
                                                 'audiência', 'audiencia', 'protocolo',
                                                 'comprovante', 'tribunal'])):
                                            if re.search(r'\b[A-Z]{2}$', nome):
                                                continue
                                            autores.append(nome)
                                break

                    # Padrão 3: tabelas HTML (fallback)
                    if not autores and soup_ata:
                        for table in soup_ata.find_all('table'):
                            for td in table.find_all('td'):
                                txt = td.get_text(strip=True).upper()
                                if len(txt) > 10 and not any(
                                    x in txt.lower()
                                    for x in ['endereço', 'telefone', 'cpf', 'rg',
                                              'e-mail', 'cep', 'página', 'protocolo']
                                ):
                                    if re.search(r'[A-ZÀ-Ú]{2,}\s+[A-ZÀ-Ú]{2,}', txt):
                                        autores.append(txt)

                    # Deduplica e limpa
                    autores = list(dict.fromkeys(
                        re.sub(r'\s+', ' ', a).strip()
                        for a in autores if a
                    ))
                    # Remove sufixos de data/hora/local dos nomes
                    autores_limpos = []
                    for a in autores:
                        a_clean = re.sub(
                            r'(?:\s+|^)(?:AOS|ACEITOU|ACEITA|PARA|NOS|EM|NA|ÀS|FICOU|COMPROMETEU|PRESTA|DEVER[ÁA]|OFICIAR[ÁA])\s+.*', '', a, flags=re.I
                        ).strip()
                        if a_clean:
                            autores_limpos.append(a_clean)
                    autores = autores_limpos
                    # Remove advogados
                    if autores:
                        texto_upper = texto_limpo.upper()
                        autores_filtrados = []
                        for nome in autores:
                            if re.search(
                                re.escape(nome) + r'\s*\(?\s*(ADVOGAD|OAB\b)',
                                texto_upper, re.I):
                                continue
                            autores_filtrados.append(nome)
                        autores = autores_filtrados
                    dados['autores_do_fato'] = autores
                    if autores:
                        print(f'   👤 Autor(es) do fato: {", ".join(autores[:3])}')

                    # ── 5. Extrai tipo de prestação ──
                    if 'pecuniária' in texto_lower or 'pecuniaria' in texto_lower:
                        dados['prestacao_tipo'] = 'PECUNIÁRIA'
                    elif any(x in texto_lower for x in
                             ['serviço', 'servico', 'comunitário', 'comunitario']):
                        dados['prestacao_tipo'] = 'SERVIÇO COMUNITÁRIO'

                    val_match = re.search(r'R\$\s*([\d.,]+)', texto_limpo)
                    if val_match:
                        dados['prestacao_valor'] = val_match.group(1)

                    parc_match = re.search(r'(\d+)\s*parcelas?', texto_lower)
                    if not parc_match:
                        # Tenta "em até X vezes", "X vezes", "parcelada em X vezes"
                        parc_match = re.search(r'(?:em\s+at[eé]\s+)?(\d+)\s*vezes', texto_lower)
                    if parc_match:
                        dados['prestacao_parcelas'] = parc_match.group(1)

                    desc_match = re.search(
                        r'prestação\s*(.{100,500}?)(?:\.\s+[A-Z]|$)',
                        texto_limpo, re.I | re.DOTALL)
                    if desc_match:
                        dados['prestacao_descricao'] = desc_match.group(1).strip()

                    tipo = dados.get('prestacao_tipo') or 'tipo nao identificado'
                    valor = dados.get('prestacao_valor', '')
                    parcelas = dados.get('prestacao_parcelas', '')
                    info = f'   📋 Ata de audiencia: {tipo}'
                    if valor:
                        info += f' R$ {valor}'
                    if parcelas:
                        info += f' {parcelas}x'
                    print(info)
                except Exception as e:
                    print(f'   ⚠️ Erro ao baixar doc: {e}')
    except Exception as e:
        print(f'   ⚠️ Erro ao buscar ata: {e}')

    return dados


def _gerar_html(proc, part, rag, template, dados_ata=None):
    """Gera o HTML do documento com os dados corretos."""
    ctx = {
        'processo': proc.number,
        'despacho_ato': rag.despacho_ato,
        'despacho_observacao': rag.despacho_observacao,
        'despacho_data': rag.despacho_data,
        'despacho_autor': rag.despacho_autor or 'MARTINHO FERRAZ DA NOBREGA JUNIOR',
        'parte': {
            'nome': part.name, 'endereco': part.address or '',
            'email': part.email or '', 'telefone': part.phone or '',
            'cpf_cnpj': part.cpf_cnpj or '', 'rg': part.rg or '',
            'nome_pai': part.nome_pai or '', 'nome_mae': part.nome_mae or '',
        },
        'partes': [{
            'nome': part.name, 'endereco': part.address or '',
            'email': part.email or '', 'telefone': part.phone or '',
            'cpf_cnpj': part.cpf_cnpj or '', 'rg': part.rg or '',
        }],
        'prazo_dias': '05', 'data': date.today().strftime('%d/%m/%Y'),
    }

    if template.template_type == 'mandado':
        num_doc = f'MAN-{proc.id:03d}/{date.today().year}'
    else:
        last = GeneratedDocument.objects.filter(process=proc).aggregate(Max('sequential_number'))
        seq = (last['sequential_number__max'] or 0) + 1
        num_doc = f'{seq:03d}/{date.today().year}'
    ctx['numero_documento'] = num_doc

    if template.template_type == 'oficio':
        ente = Party.objects.filter(process=proc, role='reu').first()
        if ente:
            ctx['ente_devedor'] = ente.name
            ctx['ente_endereco'] = ente.address or ''
            ctx['ente_email'] = ente.email or ''
            ctx['ente_telefone'] = ente.phone or ''
        else:
            ctx['ente_devedor'] = ''
            ctx['ente_endereco'] = ''
            ctx['ente_email'] = ''

        valor_match = re.search(r'R\$?\s*([\d.,]+)', rag.despacho_observacao or rag.despacho_ato)
        ctx['valor'] = valor_match.group(1) if valor_match else ''

        # Se CPF/CNPJ do credor estiver vazio, tenta extrair do despacho
        if not ctx['parte']['cpf_cnpj']:
            cpf_match = re.search(r'CPF\s*:?\s*([\d.-]+)|CNPJ\s*:?\s*([\d./-]+)', rag.despacho_observacao or rag.despacho_ato)
            if cpf_match:
                ctx['parte']['cpf_cnpj'] = cpf_match.group(1) or cpf_match.group(2) or ''

        # Se email do ente estiver vazio, deixa vazio
        if not ctx.get('ente_email'):
            ctx['ente_email'] = ''

        # Dados da ata de audiência (CIAP)
        if dados_ata:
            ctx['prestacao_tipo'] = dados_ata.get('prestacao_tipo', '')
            ctx['prestacao_valor'] = dados_ata.get('prestacao_valor', '')
            ctx['prestacao_parcelas'] = dados_ata.get('prestacao_parcelas', '')
            ctx['prestacao_descricao'] = dados_ata.get('prestacao_descricao', '')
            ctx['ata_encontrada'] = dados_ata.get('ata_encontrada', False)
            # Monta descricao_cumprimento com os dados reais da ata
            partes_desc = []
            tipo = dados_ata.get('prestacao_tipo', '')
            valor = dados_ata.get('prestacao_valor', '')
            parcelas = dados_ata.get('prestacao_parcelas', '')
            if tipo:
                partes_desc.append(tipo.lower())
            if valor:
                partes_desc.append(f'no valor de R$ {valor}')
            if parcelas:
                partes_desc.append(f'em {parcelas}x')
            desc_ata = dados_ata.get('prestacao_descricao', '')
            if desc_ata and not partes_desc:
                ctx['descricao_cumprimento'] = desc_ata
            elif partes_desc:
                ctx['descricao_cumprimento'] = ' '.join(partes_desc)
                if desc_ata:
                    ctx['descricao_cumprimento'] += f' - {desc_ata}'

    try:
        html = Template(template.html_template).render(Context(ctx))
        return html
    except Exception as e:
        print(f'   ❌ Erro renderizando template: {e}')
        return None


def _expedir_mandado(proc, session, cookies_dict, html_mandado, part, subtipo='11'):
    """Expede mandado via Playwright."""
    from playwright.sync_api import sync_playwright

    PROC_PROJUDI = None
    projudi_url = getattr(proc, 'projudi_url', None) or ''
    m = re.search(r'numeroProcesso=(\d+)', projudi_url)
    if m:
        PROC_PROJUDI = m.group(1)
    if not PROC_PROJUDI:
        print('   ❌ Número Projudi não encontrado')
        return False

    nome_parte = part.name if part else 'parte'
    sucesso = False
    subtipo_valor = subtipo or '11'

    # ── Party enrichment: busca endereço/telefone/email no DadosProcesso ──
    if part and (not part.address or not part.phone or not part.email):
        try:
            proc_url = projudi_url or f'https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?numeroProcesso={PROC_PROJUDI}'
            r = session.get(proc_url, timeout=30)
            if r.status_code == 200 and 'expirou' not in r.text.lower():
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r.text, 'html.parser')
                nome_busca_raw = part.name.lower().strip()
                # Remove parênteses e conteúdo (ex: "(REVEL)", "(Rev. Arg.)")
                nome_busca = re.sub(r'\([^)]*\)', '', nome_busca_raw).strip()
                for tr in soup.find_all('tr', id=lambda x: x and x.startswith('tr')):
                    tds = tr.find_all('td')
                    if len(tds) < 2:
                        continue
                    nome_td = tds[1].get_text(' ', strip=True).lower().strip()
                    nome_td_clean = re.sub(r'\([^)]*\)', '', nome_td).strip()
                    # Match flexível: contido ou contém
                    if nome_busca in nome_td_clean or nome_td_clean in nome_busca or \
                       nome_busca in nome_td or nome_td in nome_busca:
                        id_linha = tr.get('id', '').replace('tr', '')
                        span_end = soup.find('span', id=f'spanEnd{id_linha}')
                        if span_end:
                            texto = span_end.get_text(' ', strip=True)
                            # Regex mais flexível para extrair endereço
                            end_match = re.search(
                                r'(?:Endereço|Endereco)\s*(.*?)(?:\s+\d{10,11}|$)',
                                texto, re.I | re.DOTALL)
                            tel_match = re.search(r'(\d{10,11})', texto)
                            email_match = re.search(
                                r'[\w\.-]+@[\w\.-]+\.\w+', texto)
                            endereco = end_match.group(1).strip() if end_match else ''
                            telefone = tel_match.group(1) if tel_match else ''
                            email = email_match.group(0) if email_match else ''
                            if endereco:
                                # Formata endereço: componentes em linhas separadas
                                endereco = endereco.replace('\xa0', ' ') \
                                    .replace('\r\n', ', ') \
                                    .replace('\r', ', ').replace('\n', ', ')
                                endereco = re.sub(r'\s+', ' ', endereco) \
                                    .strip().rstrip(',').strip()
                                # Tenta separar CEP em linha própria
                                cep_match = re.search(r'(\d{8})', endereco)
                                if cep_match:
                                    cep = cep_match.group(1)
                                    endereco = endereco.replace(cep, f'<br>CEP {cep[:5]}-{cep[5:]}')
                                # Tenta separar cidade/UF em linha própria
                                endereco = re.sub(
                                    r',\s*([A-ZÀ-Ú]{2,}?\s*-\s*[A-Z]{2})',
                                    r'<br>\1', endereco)
                            if endereco or telefone or email:
                                if endereco:
                                    part.address = endereco
                                if telefone:
                                    part.phone = telefone
                                if email:
                                    part.email = email
                                part.save(update_fields=['address', 'phone', 'email'])
                                print(f'   📍 Endereço: {endereco[:100] if endereco else "—"}')
                                print(f'   📞 Tel: {telefone or "—"} | 📧 Email: {email or "—"}')
                        break
        except Exception as e:
            print(f'   ⚠️ Enrichment: {e}')

    try:
        with sync_playwright() as pw:
            browser = pw.firefox.launch(headless=False, slow_mo=500)
            ctx_b = browser.new_context(viewport={'width': 1500, 'height': 950}, locale='pt-BR')
            ctx_b.add_cookies([
                {'name': k, 'value': v, 'domain': 'projudi.tjba.jus.br', 'path': '/'}
                for k, v in cookies_dict.items()
            ])
            page = ctx_b.new_page()

            url_mov = f'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso={PROC_PROJUDI}'
            page.goto(url_mov, wait_until='networkidle')
            time.sleep(2)

            page.evaluate('''() => {
                var camp = document.getElementById('seqCategoriaMovimentacao');
                if (camp) camp.value = '581';
                var desc = document.getElementById('descCategoriaMovimentacao');
                if (desc) desc.value = 'Solicitada a Expedição de Mandado';
                var tr = document.getElementById('trTipoDocumento');
                if (tr) tr.style.display = 'table-row';
            }''')
            time.sleep(1)
            page.select_option('select[name="codTipoDocumento"]', '51')
            time.sleep(1)
            page.fill('#observacao', f'Solicitada Expedicao de Mandado - {nome_parte[:30]}')
            time.sleep(0.5)
            page.locator("a:text('Cumprimento')").first.click()
            time.sleep(1)
            page.select_option('#tipoCumprimento', '4')
            time.sleep(0.5)

            # subtipoCumprimento — só existe DEPOIS de tipoCumprimento=4
            subtipo_valor = subtipo or getattr(part, '_subtipo_mandado', None) or '11'
            try:
                st = page.locator('#subtipoCumprimento').first
                if st.count():
                    st.select_option(str(subtipo_valor))
                    time.sleep(0.3)
                    print(f'   ✅ Subtipo mandado: {subtipo_valor}')
            except Exception:
                print(f'   ⚠️ Subtipo não selecionado')

            nome_dest = part.name if part else ''
            if nome_dest:
                try:
                    opt = page.locator(f'#codigoDestinatario option:text("{nome_dest}")').first
                    if opt.count():
                        val = opt.get_attribute('value')
                        page.select_option('#codigoDestinatario', val)
                        print(f'   ✅ Destinatário: {nome_dest} ({val})')
                    else:
                        first_opt = page.locator('#codigoDestinatario option').first
                        if first_opt.count():
                            val = first_opt.get_attribute('value')
                            page.select_option('#codigoDestinatario', val)
                            print(f'   ✅ Destinatário: primeiro ({val})')
                except Exception as e:
                    print(f'   ⚠️ Destinatário fallback: {e}')
                page.click('#btnAddCumprimento')
                time.sleep(1.5)
                print(f'   ✅ Cumprimento adicionado')
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            time.sleep(0.5)
            page.click('#Concluir')
            time.sleep(4)
            try:
                alert = page.wait_for_event('dialog', timeout=5000)
                print(f'   📢 {alert.message}')
                alert.accept()
                time.sleep(2)
            except:
                pass
            try:
                page.wait_for_load_state('networkidle', timeout=10000)
            except:
                pass

            print(f'   ✅ Movimentação concluída. URL: {page.url}')

            # Captura codCumprimento da URL
            cod_cump = ''
            m = re.search(r'codCumprimento=(\d+)', page.url)
            if m:
                cod_cump = m.group(1)
            if not cod_cump:
                cod_cump = page.evaluate(r'''() => {
                    var body = document.body.innerHTML;
                    var m = body.match(/codCumprimento["']?\s*[:=]\s*["']?(\d+)/i);
                    return m ? m[1] : '';
                }''')
            print(f'   codCumprimento: {cod_cump or "não encontrado"}')

            # Usa link de movimentação genérica (DadosProcesso)
            link_mov = proc.projudi_url or f'https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?numeroProcesso={PROC_PROJUDI}'
            r_mov = session.get(link_mov, timeout=15)
            if r_mov.status_code == 200:
                from projudiProcessNavigator import ProcessoParser
                parser = ProcessoParser(r_mov.text)
                links = parser.extrair_links(parser.soup, parser.base_url)
                url_movimentar = links.get('movimentar', '')
                if url_movimentar:
                    page.goto(url_movimentar, wait_until='load')
                    time.sleep(3)
                    print(f'   🔗 Link movimentação genérica')
            else:
                page.goto(
                    'https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=mandado&acao=expedir',
                    wait_until='load')
                time.sleep(3)

            # Procura "Redigir sem AR" ou forms com select codModelo
            link = page.locator('a:has-text("Redigir sem AR")').last
            if link.count():
                with page.expect_navigation(timeout=20000):
                    link.click()
                time.sleep(3)
                print(f'   ✅ URL: {page.url}')
            else:
                r = page.evaluate('''() => {
                    var forms = document.querySelectorAll('form');
                    for (var i = forms.length - 1; i >= 0; i--) {
                        var sel = forms[i].querySelector('select[name="codModelo"]');
                        if (sel) {
                            for (var j = 0; j < sel.options.length; j++) {
                                if (sel.options[j].text.toLowerCase().includes('rpa')) {
                                    sel.value = sel.options[j].value; break;
                                }
                            }
                            if (sel.value == '-1') sel.value = sel.options[sel.options.length-1].value;
                            return {ok: true, form: forms[i].name || forms[i].id};
                        }
                    }
                    return {erro: 'nenhum form com codModelo'};
                }''')
                print(f'   {r}')
                if not r.get('ok'):
                    if cod_cump:
                        url_exp = f'https://projudi.tjba.jus.br/projudi/acoes/ExpedirCumprimentoCartorio?codCumprimento={cod_cump}&gerarar=false'
                        page.goto(url_exp, wait_until='load')
                        time.sleep(3)
                        print(f'   ✅ URL: {page.url}')
                    else:
                        print('   ❌ Não encontrado')
                        browser.close()
                        return False

            if 'ExpedirCumprimento' not in page.url:
                print(f'   ❌ Não foi pra ExpedirCumprimento. URL: {page.url}')
                browser.close()
                return False

            # ── FCKEDITOR ──
            print('   ✍️ Extraindo brasão e colando template...')
            time.sleep(3)

            html_original = page.evaluate('''() => {
                try { return FCKeditorAPI.GetInstance('FCKeditor1').GetHTML(); }
                catch(e) {
                    try { return window.parent.FCKeditorAPI.GetInstance('FCKeditor1').GetHTML(); }
                    catch(e2) { return ''; }
                }
            }''')

            img_match = re.search(r'(<img[^>]+src="[^"]*brasao[^"]*"[^>]*>)', html_original, re.I)
            brasao_html = ''
            if img_match:
                brasao_html = f'<div style="text-align:center; margin-bottom:8px;">{img_match.group(1)}</div>'
                print('   ✅ Brasão extraído')
            else:
                print('   ⚠️ Brasão não encontrado no RPA')

            html_final = brasao_html + html_mandado
            res = page.evaluate('''(html) => {
                try {
                    var ed = FCKeditorAPI.GetInstance('FCKeditor1');
                    ed.SetHTML(''); ed.SetHTML(html);
                    return 'OK SetHTML';
                } catch(e) {
                    try {
                        var ed2 = window.parent.FCKeditorAPI.GetInstance('FCKeditor1');
                        ed2.SetHTML(''); ed2.SetHTML(html);
                        return 'OK parent.SetHTML';
                    } catch(e2) {
                        var ifr = document.querySelector('iframe[title*="editor"], iframe[src*="FCKeditor"]');
                        if (ifr) {
                            var doc = ifr.contentDocument || ifr.contentWindow.document;
                            var body = doc.querySelector('body');
                            if (body) { body.innerHTML = html; return 'OK iframe'; }
                        }
                        return 'ERRO: ' + e2.message;
                    }
                }
            }''', html_final)
            print(f'   📝 {res}')
            time.sleep(2)

            # ── SUBMETER ──
            print('   🔄 Submeter...')
            botoes = page.evaluate('''() => {
                var btns = document.querySelectorAll('input[type="submit"], input[type="image"], input[type="button"], button');
                return Array.from(btns).map(function(b) {
                    return (b.id || '') + '=' + (b.value || b.textContent || '') + ' (' + (b.type || '') + ')';
                }).join(' | ');
            }''')
            print(f'   Botões: {botoes}')
            btn = page.locator('input[src*="bot-submeter"], input[type="image"]').first
            if btn.count():
                btn.scroll_into_view_if_needed()
                time.sleep(1)
                btn.click()
                time.sleep(5)
                print('   ✅ Submeter clicado')
            else:
                print('   ⚠️ Submeter não encontrado')

            # ── REGISTRAR ──
            print('   🔄 Registrando...')
            registrar = page.locator("input[value='Registrar'], button:has-text('Registrar')").first
            if registrar.count():
                registrar.scroll_into_view_if_needed()
                time.sleep(1)
                registrar.click()
                time.sleep(4)
                print('   ✅ Registrar clicado')
            else:
                print('   ⚠️ Registrar não encontrado')

            # ── VERIFICAR ──
            html_check = page.content()
            if any(k in html_check.lower() for k in
                   ['registrado', 'sucesso', 'confirmado',
                    'mandados para expedir', 'cumprimentocartorio']):
                print('   ✅ Mandado registrado com sucesso!')
            else:
                print('   ⚠️ Registrar pode não ter confirmado')
            browser.close()
            sucesso = True
    except Exception as e:
        print(f'   ❌ Playwright mandado: {e}')
        import traceback; traceback.print_exc()
    return sucesso


def _expedir_oficio(proc, session, cookies_dict, html_oficio, part, template):
    """Expede ofício via Playwright seguindo fluxo igual ao CIAP."""
    from playwright.sync_api import sync_playwright

    PROC_PROJUDI = None
    projudi_url = getattr(proc, 'projudi_url', None) or ''
    m = re.search(r'numeroProcesso=(\d+)', projudi_url)
    if m:
        PROC_PROJUDI = m.group(1)
    if not PROC_PROJUDI:
        print('   🔍 Buscando número Projudi...')
        busca_url = 'https://projudi.tjba.jus.br/projudi/processo/consultaProcesso'
        r = session.post(busca_url, data={'numeroProcesso': proc.number}, timeout=15)
        if r.status_code == 200:
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(r.url).query)
            PROC_PROJUDI = qs.get('numeroProcesso', [None])[0]
        if not PROC_PROJUDI:
            print('   ❌ Número Projudi não encontrado')
            return False

    nome_parte = part.name if part else 'parte'
    sucesso = False

    try:
        with sync_playwright() as pw:
            browser = pw.firefox.launch(headless=False, slow_mo=500)
            ctx_b = browser.new_context(viewport={'width': 1500, 'height': 950}, locale='pt-BR')
            ctx_b.add_cookies([
                {'name': k, 'value': v, 'domain': 'projudi.tjba.jus.br', 'path': '/'}
                for k, v in cookies_dict.items()
            ])
            page = ctx_b.new_page()

            # === 1. Mov 581 ===
            url_mov = f'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso={PROC_PROJUDI}'
            page.goto(url_mov, wait_until='networkidle')
            time.sleep(2)

            page.evaluate('''() => {
                var camp = document.getElementById('seqCategoriaMovimentacao');
                if (camp) camp.value = '581';
                var desc = document.getElementById('descCategoriaMovimentacao');
                if (desc) desc.value = 'Solicitada a Expedição de Ofício';
                var tr = document.getElementById('trTipoDocumento');
                if (tr) tr.style.display = 'table-row';
                var div = document.getElementById('rowDadosMovimentacaoComplemento');
                if (div) div.style.display = 'block';
                var panel = document.getElementById('divPanelCumprimento');
                if (panel) panel.style.display = 'block';
            }''')
            time.sleep(1.5)

            page.select_option('select[name="codTipoDocumento"]', '53')
            time.sleep(1)
                        # Observação com tipo de ofício
            eh_ciap = 'ciap' in template.name.lower()
            if eh_ciap:
                page.fill('#observacao', f'Solicitada Expedicao de Oficio CIAP - {nome_parte[:50]}')
            else:
                credor = Party.objects.filter(process=proc, role='autor').first()
                nome_credor = credor.name if credor else nome_parte
                page.fill('#observacao', f'Solicitada Expedicao de Oficio (RPV) - Credor: {nome_credor[:50]}')
            time.sleep(0.5)

            page.locator("a:text('Cumprimento')").first.click()
            time.sleep(1)
            page.select_option('#tipoCumprimento', '2')  # OFICIO
            time.sleep(0.5)

            # Destinatário conforme o template
            eh_ciap = 'ciap' in template.name.lower()
            # Busca o nome da parte no dropdown (igual mandados faz)
            nome_dest = part.name if part else ''
            if eh_ciap:
                # CIAP: destinatário é o autor do fato (parte passada)
                print(f'   🔍 Buscando destinatário: {nome_dest[:50]}')
            else:
                # RPV: destinatário é o ente devedor (réu)
                ente = Party.objects.filter(process=proc, role='reu').first()
                nome_dest = ente.name if ente else nome_dest

            # Tenta encontrar option pelo nome (mesma lógica do mandado)
            opt = page.locator(f'#codigoDestinatario option:text("{nome_dest}")').first
            if opt.count():
                val = opt.get_attribute('value')
                page.select_option('#codigoDestinatario', val)
                print(f'   ✅ Destinatário: {nome_dest[:40]} ({val})')
            else:
                # Fallback: texto parcial no dropdown
                nome_lower = nome_dest.lower()
                page.evaluate("""(termos) => {
                    var sel = document.getElementById('codigoDestinatario');
                    if (!sel) return;
                    for (var i = 0; i < sel.options.length; i++) {
                        var txt = sel.options[i].text.toLowerCase();
                        if (termos.some(t => txt.includes(t))) {
                            sel.value = sel.options[i].value;
                            return;
                        }
                    }
                    // Ultimo recurso: primeira opcao REAL (pula placeholder)
                    for (var i = 1; i < sel.options.length; i++) {
                        var v = sel.options[i].value;
                        if (v && v !== '-1' && v !== '') {
                            sel.value = v; return;
                        }
                    }
                }""", [nome_lower] + ([] if eh_ciap else
                      ['embasa', 'agua', 'saneamento', 'estado', 'municipio']))
                txt_selecionado = page.evaluate(
                    "() => { var s = document.getElementById('codigoDestinatario'); "
                    "return s ? s.options[s.selectedIndex].text : ''; }")
                print(f'   ✅ Destinatário (fallback): {txt_selecionado[:40]}')
            page.click('#btnAddCumprimento')
            time.sleep(2)

            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            time.sleep(0.5)
            page.click('#Concluir')
            time.sleep(4)
            try:
                alert = page.wait_for_event('dialog', timeout=5000)
                print(f'   📢 Alerta: "{alert.message}"')
                alert.accept()
                time.sleep(3)
            except:
                pass
            try:
                page.wait_for_load_state('networkidle', timeout=10000)
            except:
                pass

            # Captura codCumprimento da URL (fallback)
            cod_cump = ''
            m_cump = re.search(r'codCumprimento=(\d+)', page.url)
            if m_cump:
                cod_cump = m_cump.group(1)
            if not cod_cump:
                cod_cump = page.evaluate(r'''() => {
                    var body = document.body.innerHTML;
                    var m = body.match(/codCumprimento["']?\s*[:=]\s*["']?(\d+)/i);
                    return m ? m[1] : '';
                }''')
            print(f'   codCumprimento: {cod_cump or "não encontrado"}')

            # === 2. CumprimentoCartorio → "Redigir sem AR" ou forms RPA ===
            url_cump = 'https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=oficio&acao=expedir'
            page.goto(url_cump, wait_until='networkidle')
            time.sleep(3)

            # Primeira tentativa: "Redigir sem AR" (mais preciso)
            link_redigir = page.locator('a:has-text("Redigir sem AR")').last
            if link_redigir.count():
                with page.expect_navigation(timeout=20000):
                    link_redigir.click()
                time.sleep(3)
                print(f'   ✅ Redigir sem AR: {page.url[:80]}')
            else:
                # Fallback: forms com codModelo RPA
                cump_result = page.evaluate('''() => {
                    var forms = document.querySelectorAll('form[name^="formCumprimento"]');
                    if (forms.length === 0) return {erro: 'nenhum form encontrado'};
                    var form = forms[forms.length - 1];
                    var sel = form.querySelector('select[name="codModelo"]');
                    if (!sel) return {erro: 'select codModelo nao encontrado', form: form.name};
                    var rpaValue = null;
                    for (var i = 0; i < sel.options.length; i++) {
                        if (sel.options[i].text.toLowerCase().includes('rpa')) {
                            rpaValue = sel.options[i].value; break;
                        }
                    }
                    if (!rpaValue) {
                        // Fallback: ultima opcao
                        rpaValue = sel.options[sel.options.length - 1].value;
                    }
                    sel.value = rpaValue;
                    return {ok: true, form: form.name, codModelo: rpaValue};
                }''')
                print(f'   📝 {cump_result}')
                if not cump_result.get('ok'):
                    print(f'   ❌ ERRO: {cump_result.get("erro")}')
                    # Ultimo fallback: URL direta com codCumprimento
                    if cod_cump:
                        url_exp = f'https://projudi.tjba.jus.br/projudi/acoes/ExpedirCumprimentoCartorio?codCumprimento={cod_cump}&gerarar=false'
                        page.goto(url_exp, wait_until='load')
                        time.sleep(3)
                        print(f'   ✅ Fallback URL direta: {page.url[:80]}')
                    else:
                        print('   ❌ Sem codCumprimento para fallback')
                        browser.close()
                        return False
                else:
                    form_name = cump_result['form']
                    with page.expect_navigation(timeout=15000):
                        page.evaluate(f'''() => {{
                            var form = document.forms['{form_name}'];
                            form.gerarar.value = 'false';
                            form.submit();
                        }}''')
                    time.sleep(3)

            time.sleep(2)
            if 'ExpedirCumprimento' not in page.url:
                print(f'   ❌ ERRO: nao foi pra ExpedirCumprimento. URL: {page.url}')
                browser.close()
                return False

            # === 3. FCKeditor ===
            time.sleep(3)
            html_original = page.evaluate('''() => {
                try { return FCKeditorAPI.GetInstance('FCKeditor1').GetHTML(); }
                catch(e) {
                    try { return window.parent.FCKeditorAPI.GetInstance('FCKeditor1').GetHTML(); }
                    catch(e2) { return ''; }
                }
            }''')

            img_match = re.search(r'(<img[^>]+src="[^"]*brasao[^"]*"[^>]*>)', html_original, re.I)
            brasao_html = ''
            if img_match:
                brasao_html = f'<div style="text-align:center; margin-bottom:8px;">{img_match.group(1)}</div>'
                print('   ✅ Brasão extraído')
            else:
                print('   ⚠️ Brasão não encontrado')

            html_final = brasao_html + html_oficio
            result = page.evaluate('''(html) => {
                try { var ed = FCKeditorAPI.GetInstance('FCKeditor1'); ed.SetHTML(''); ed.SetHTML(html); return 'OK'; }
                catch(e) {
                    try { var ed2 = window.parent.FCKeditorAPI.GetInstance('FCKeditor1'); ed2.SetHTML(''); ed2.SetHTML(html); return 'OK parent'; }
                    catch(e2) { return 'ERRO: ' + e2.message; }
                }
            }''', html_final)
            print(f'   📝 FCKeditor: {result}')
            time.sleep(2)

            # === 4. Submeter ===
            submeter = page.locator('input[src*="bot-submeter"], input[type="image"]').first
            if submeter.count():
                submeter.scroll_into_view_if_needed()
                time.sleep(1)
                submeter.click()
                time.sleep(5)
            else:
                print('   ❌ Submeter nao encontrado')
                browser.close()
                return False

            # === 5. Registrar ===
            registrar = page.locator("input[value='Registrar'], button:has-text('Registrar'), input[src*='registrar']").first
            if registrar.count():
                registrar.scroll_into_view_if_needed()
                time.sleep(1)
                registrar.click()
                time.sleep(4)
                print('   ✅ Registrar clicado!')
            else:
                print('   ⚠️ Registrar nao encontrado')

            # Verificar sucesso
            html_check = page.content()
            if any(k in html_check.lower() for k in ['registrado', 'sucesso', 'confirmado', 'ofícios para expedir', 'cumprimentocartorio']):
                sucesso = True
                print('   ✅ CONFIRMADO: Ofício expedido!')
            else:
                print(f'   ⚠️ Nao confirmado automaticamente')
            browser.close()
    except Exception as e:
        print(f'   ❌ ERRO Playwright: {e}')
        import traceback; traceback.print_exc()
    return sucesso


# ══════════════════════════════════════════════════════════════════
def expedir_processo_especifico(proc_num: str):
    """Executa o fluxo expedir_rapido para um processo específico.
    
    Busca o processo no DB, encontra RAGExamples vinculados
    e executa a sequencia_cumprimento de cada um.
    """
    user, session, cookies_dict = session_projudi()
    
    from processes.models import Process, RAGExample
    
    proc = Process.objects.filter(number__icontains=proc_num).first()
    if not proc:
        print(f'❌ Processo {proc_num} não encontrado no banco.')
        # Tenta criar a partir do Projudi
        from projudi_client import ProjudiClient
        client = ProjudiClient()
        client.session = session
        client.cookies = cookies_dict
        movs = []
        pages = client.obter_paginas_finais_movimentacoes(quantidade=3)
        for p in pages:
            data = {'pagina': str(p), 'loginJuiz': ''}
            rp = session.post(client.URL_MOVIMENTACOES, data=data, timeout=15)
            if len(rp.text) > 1000:
                sp = BeautifulSoup(rp.text, 'html.parser')
                movs.extend(client.extrair_links_movimentacoes(sp))
        mov = None
        for m in movs:
            if proc_num in m.get('processo', ''):
                mov = m
                break
        if not mov:
            print('❌ Processo não encontrado nas movimentações recentes.')
            return
        proc = _criar_processo(session, mov, proc_num, user)
        if not proc:
            print('❌ Não foi possível criar o processo.')
            return
    
    # Busca RAGExamples do processo
    rags = RAGExample.objects.filter(process=proc, active=True)
    if not rags:
        print(f'⚠️ Nenhum RAGExample ativo para {proc.number}.')
        print('   Tente rastrear primeiro (sem --processo).')
        return
    
    for rag in rags:
        print(f'\n📋 RAGExample #{rag.id}: {rag.despacho_ato[:80]}')
        if rag.sequencia_cumprimento:
            print(f'   Sequência: {len(rag.sequencia_cumprimento)} passo(s)')
            _executar_sequencia_rapido(
                rag.sequencia_cumprimento, 
                {'processo': proc_num, 'link_processo': getattr(proc, 'projudi_url', '')},
                proc_num, rag.despacho_observacao or rag.despacho_ato,
                session, cookies_dict, user, rag
            )
        else:
            print('   ⏭️ Sem sequencia_cumprimento definida.')
    
    print(f'\n✅ Processo {proc.number} finalizado.')


# ══════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Rastrear e expedir documentos')
    parser.add_argument('--processo', type=str, help='CNJ do processo específico')
    parser.add_argument('--mandados-only', action='store_true', help='Só mandados')
    parser.add_argument('--oficios-only', action='store_true', help='Só ofícios')
    parser.add_argument('--mov-only', action='store_true', help='Só movimentações (intimações, certidões)')
    args = parser.parse_args()

    if args.mandados_only:
        rastrear_e_expedir(tipo='mandado')
    elif args.oficios_only:
        rastrear_e_expedir(tipo='oficio')
    elif args.mov_only:
        rastrear_e_expedir(tipo='movimentacao')
    elif args.processo:
        expedir_processo_especifico(args.processo)
    else:
        rastrear_e_expedir(tipo=None)
