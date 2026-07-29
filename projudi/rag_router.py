"""RAG Integration Router — Roteia matches RAG para o fluxo adequado.

Quando o RAG encontra um match, verifica primeiro se o RAGExample
possui uma sequencia_cumprimento. Se sim, executa cada passo na ordem.
Se não, usa o comportamento antigo (suggested_templates).
"""

from typing import List, Dict, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def rotear_match_rag(movimentacoes, session, cookies_dict, user, tipo=None):
    from processes.models import RAGExample, DocumentTemplate
    from processes.movimentacoes_service import buscar_cumprimentos_similares

    TIPO_PARA_TEMPLATE = {
        'mandado': {'mandado'},
        'oficio': {'oficio'},
        'cumprimento': {'intimacao', 'certidao', 'outro'},
    }

    if tipo:
        tipos_validos = TIPO_PARA_TEMPLATE.get(tipo, set())
        templates_validos = DocumentTemplate.objects.filter(
            active=True, template_type__in=tipos_validos)
    else:
        templates_validos = DocumentTemplate.objects.filter(active=True)

    resumo = {'mandados': 0, 'oficios': 0, 'cumprimentos': 0,
              'movimentacoes': 0, 'erros': 0}

    for mov in movimentacoes:
        proc_num = mov.get('processo', '')
        doc_url = mov.get('link_documento', '')
        if not proc_num or not doc_url:
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

            melhor, template, rag, ignorar = _melhor_match(texto, similares, templates_validos)
            if not melhor and not rag:
                continue

            if ignorar:
                print(f'   ⏭️ RAGExample #{rag.id} matchou mas não tem ação — ignorado.')
                continue

            # ─── PRIORIDADE: sequencia_cumprimento do RAGExample ───
            if rag and rag.sequencia_cumprimento:
                _executar_sequencia(
                    rag.sequencia_cumprimento, mov, proc_num, texto,
                    session, cookies_dict, user, resumo)
            else:
                # ─── Fallback: roteio por template (antigo) ───
                _rotear_por_template(
                    template, mov, proc_num, texto,
                    session, cookies_dict, user, tipo, resumo)

        except Exception as e:
            print(f'   ❌ Erro {proc_num}: {e}')
            resumo['erros'] += 1

    return resumo


# ═════════════════════════════════════════════════════════════════════
# EXECUTOR DE SEQUÊNCIA
# ═════════════════════════════════════════════════════════════════════
def _executar_sequencia(sequencia, mov, proc_num, texto,
                        session, cookies_dict, user, resumo):
    """Executa cada passo da sequencia_cumprimento em ordem."""
    from processes.models import DocumentTemplate
    from projudi.movimentacao_service import MovimentacaoService

    print(f'\n   📋 Sequência de {len(sequencia)} passo(s) para {proc_num}:')

    for i, passo in enumerate(sequencia, 1):
        tipo = passo.get('tipo', '')
        obs = passo.get('observacao', '')
        template_id = passo.get('template_id')

        print(f'      [{i}/{len(sequencia)}] {tipo}', end='')

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
                print(f' → Movimentação #{record.id}')
                resumo['movimentacoes'] += 1

            elif tipo == 'solicitar_expedicao':
                """Mov581 para solicitar expedição (sem confecção)."""
                service = MovimentacaoService(user)
                desc_padrao = passo.get('descricao_mov', 'Solicitada a Expedição de Mandado')
                record = service.importar(
                    processo_numero=proc_num,
                    act_verb='solicitar_expedicao',
                    observacao=obs or f'Solicitada Expedicao - {desc_padrao}',
                    categoria='outro',
                    processo_cnj=proc_num,
                    url_processo=mov.get('link_processo', ''),
                    codigo_movimentacao=str(passo.get('codigo_mov', '581')),
                    descricao_movimentacao=desc_padrao,
                )
                print(f' → Solicitação de expedição #{record.id}')
                resumo['movimentacoes'] += 1

            elif tipo in ('mandado', 'oficio', 'intimacao'):
                if not template_id:
                    print(f' ⚠️ sem template_id, pulando')
                    continue
                try:
                    tmpl = DocumentTemplate.objects.get(id=template_id, active=True)
                except DocumentTemplate.DoesNotExist:
                    print(f' ⚠️ template #{template_id} não encontrado, pulando')
                    continue

                tt = tmpl.template_type

                if tipo == 'mandado' or tt == 'mandado':
                    _rotear_mandado(mov, proc_num, session, cookies_dict, user, None, tmpl)
                    resumo['mandados'] += 1
                    print(f' → Mandado: {tmpl.name}')

                elif tipo == 'oficio' or tt == 'oficio':
                    _rotear_oficio(mov, proc_num, session, cookies_dict, user, None, tmpl)
                    resumo['oficios'] += 1
                    print(f' → Ofício: {tmpl.name}')

                else:
                    _rotear_cumprimento(
                        mov, proc_num, texto, session, cookies_dict, user, None, tmpl)
                    resumo['cumprimentos'] += 1
                    print(f' → Cumprimento: {tmpl.name}')

            elif tipo == 'intimacao_eletronica':
                """Mov581 + intimation click automático."""
                print(' → Iniciando Mov581 + Intimação eletrônica...')
                try:
                    service = MovimentacaoService(user)
                    ok = service.executar_com_intimacao(
                        processo_numero=proc_num,
                        observacao=obs or texto[:500],
                        codigo_mov=str(passo.get('codigo_mov', '581')),
                        descricao_mov=passo.get('descricao_mov', 'Intimação'),
                        fallback_mov=passo.get('fallback_mov'),
                        fallback_uf=passo.get('fallback_uf'),
                    )
                    if ok:
                        print(' → ✅ Intimação eletrônica concluída')
                        resumo['movimentacoes'] += 1
                    else:
                        print(' → ⚠️ Intimação eletrônica pode ter falhado')
                        resumo['erros'] += 1
                except Exception as e:
                    print(f' ❌ erro: {e}')
                    resumo['erros'] += 1

            else:
                print(f' ⚠️ tipo desconhecido: {tipo}')

        except Exception as e:
            print(f' ❌ erro: {e}')
            resumo['erros'] += 1


def _mapear_categoria_por_obs(texto: str) -> str:
    t = texto.lower()
    if 'arquive' in t:
        return 'arquivamento'
    if 'publique' in t:
        return 'publicacao'
    if 'registre' in t:
        return 'registro'
    if 'certifique' in t or 'certidao' in t:
        return 'certidao'
    return 'outro'


# ═════════════════════════════════════════════════════════════════════
# ROTEIO POR TEMPLATE (fallback)
# ═════════════════════════════════════════════════════════════════════
def _rotear_por_template(template, mov, proc_num, texto,
                         session, cookies_dict, user, tipo, resumo):
    if not template:
        return
    tt = template.template_type

    if tt == 'mandado' and (tipo is None or tipo == 'mandado'):
        _rotear_mandado(mov, proc_num, session, cookies_dict, user, None, template)
        resumo['mandados'] += 1

    elif tt == 'oficio' and (tipo is None or tipo == 'oficio'):
        _rotear_oficio(mov, proc_num, session, cookies_dict, user, None, template)
        resumo['oficios'] += 1

    else:
        if tipo is None or tipo == 'cumprimento':
            _rotear_cumprimento(
                mov, proc_num, texto, session, cookies_dict, user, None, template)
            resumo['cumprimentos'] += 1


# ═════════════════════════════════════════════════════════════════════
# MATCH RAG
# ═════════════════════════════════════════════════════════════════════
def _melhor_match(texto, similares, templates_validos):
    """Encontra o melhor match RAG.

    Retorna (similar_dict, template, rag_object, ignorar).
    ignorar=True significa que o RAGExample existe mas não tem
    sequencia_cumprimento nem suggested_templates (abstenção).
    """
    from processes.models import RAGExample
    palavras_texto = set(texto.lower().split())

    # Primeira passada: busca matches com ação (sequência ou template)
    for s in similares:
        palavras_rag = set(s['despacho_ato'].lower().split())
        total = max(len(palavras_rag), 1)
        if len(palavras_texto & palavras_rag) / total < 0.70:
            continue
        try:
            rag = RAGExample.objects.get(id=s['id'])

            # Tem sequência → prioritário
            if rag.sequencia_cumprimento:
                return s, None, rag, False

            # Tem template → executável
            t = rag.suggested_templates.filter(id__in=templates_validos).first()
            if t:
                return s, t, rag, False

        except RAGExample.DoesNotExist:
            continue

    # Segunda passada: busca matches de abstenção (sem ação alguma)
    # Só retorna se NENHUM match com ação foi encontrado
    for s in similares:
        palavras_rag = set(s['despacho_ato'].lower().split())
        total = max(len(palavras_rag), 1)
        if len(palavras_texto & palavras_rag) / total < 0.70:
            continue
        try:
            rag = RAGExample.objects.get(id=s['id'])
            if not rag.sequencia_cumprimento \
               and not rag.suggested_templates.exists():
                return s, None, rag, True
        except RAGExample.DoesNotExist:
            continue

    return None, None, None, False


# ═════════════════════════════════════════════════════════════════════
# ROTEADORES INDIVIDUAIS (stubs)
# ═════════════════════════════════════════════════════════════════════
def _rotear_mandado(mov, proc_num, session, cookies_dict, user, rag, template):
    from projudi.mandado_service import MandadoService
    service = MandadoService(user)
    try:
        print(f'   🔖 Mandado: {template.name if template else proc_num}')
    finally:
        service.fechar()


def _rotear_oficio(mov, proc_num, session, cookies_dict, user, rag, template):
    from projudi.oficio_service import OficioService
    service = OficioService(user)
    try:
        print(f'   📧 Ofício: {template.name if template else proc_num}')
    finally:
        pass


def _rotear_cumprimento(mov, proc_num, texto, session, cookies_dict, user, rag, template):
    from projudi.cumprimento_service import CumprimentoService
    from projudi.parte_classifier import ParteClassifier
    from projudi.fluxo_decisor import FluxoDecisor
    from processes.models import Process

    service = CumprimentoService(user)
    proc = Process.objects.filter(number=proc_num).first()
    if not proc:
        proc = service._criar_processo(session, mov, proc_num)
    if not proc:
        return

    partes_raw = service._extrair_partes_raw(proc, session)
    if not partes_raw:
        return

    classifier = ParteClassifier(partes_raw)
    partes_classif = classifier.classificar()['partes']
    tipo_ato = service._mapear_template_para_tipo_ato(template)
    ato_data = {'tipo_ato': tipo_ato, 'act_verb': ''}
    decisor = FluxoDecisor(partes_raw, partes_classif, ato_data)
    decisao = decisor.decidir()

    dec_data = {
        'processo': proc, 'decisao': decisao,
        'rag': rag, 'template': template, 'texto_mov': texto,
    }
    record = service.importar_cumprimento(dec_data)
    print(f'   ✅ Cumprimento #{record.id}')
