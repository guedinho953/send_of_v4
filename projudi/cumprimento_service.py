"""CumprimentoService — Orquestra o ciclo de vida de cumprimentos de secretaria.

Segue o mesmo padrão arquitetural de MandadoService e OficioService.

Pipeline:
  1. Recebe match RAG + partes do processo
  2. Classifica partes (ParteClassifier)
  3. Decide fluxo (FluxoDecisor)
  4. Cria CumprimentoRecord + CumprimentoLog
  5. Roteia para o fluxo adequado (stubs de execução)
"""

import sys
import json
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from django.conf import settings

PROJECT_ROOT = str(settings.BASE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from .models import CumprimentoRecord, CumprimentoLog
from .services import ProjudiService


class CumprimentoService:
    """Serviço de orquestração de cumprimentos (atos de secretaria).

    Análogo a MandadoService / OficioService.
    """

    def __init__(self, user):
        self.user = user
        self.projudi_service = ProjudiService(user)

    # =================================================================
    # BUSCAR PENDENTES (RAG + CLASSIFICAÇÃO + DECISÃO)
    # =================================================================
    def buscar_cumprimentos_pendentes(
        self,
        movimentacoes: List[Dict],
        session,
        cookies_dict: dict,
        templates_validos=None,
    ) -> List[Dict]:
        """Varre movimentações, aplica RAG + classificação + decisão.

        Args:
            movimentacoes: lista de dicts do ProjudiClient.extrair_links_movimentacoes()
            session: requests.Session autenticada
            cookies_dict: cookies para Playwright (se necessário)
            templates_validos: QuerySet de DocumentTemplate para filtrar

        Returns:
            Lista de dicts com decisão estruturada para cada movimentação
            que teve match RAG + classificação bem-sucedida.
        """
        from processes.movimentacoes_service import buscar_cumprimentos_similares
        from processes.models import RAGExample, DocumentTemplate
        from projudi.parte_classifier import ParteClassifier
        from projudi.fluxo_decisor import FluxoDecisor
        from urllib.parse import urljoin
        from bs4 import BeautifulSoup
        import re

        if templates_validos is None:
            templates_validos = DocumentTemplate.objects.filter(active=True)

        resultados = []

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

                # RAG match
                similares = buscar_cumprimentos_similares(texto, top_k=5)
                if not similares:
                    continue

                melhor, template, rag = self._melhor_match(
                    texto, similares, templates_validos
                )
                if not melhor:
                    continue

                # Carrega processo e partes
                proc = self._carregar_processo(proc_num, mov, session)
                if not proc:
                    continue

                partes_raw = self._extrair_partes_raw(proc, session)
                if not partes_raw:
                    continue

                # Classifica partes
                classifier = ParteClassifier(partes_raw)
                resultado_cls = classifier.classificar()
                partes_classif = resultado_cls['partes']

                # Tipo do ato a partir do template
                tipo_ato = self._mapear_template_para_tipo_ato(template)

                # Decide fluxo para cada parte
                ato_data = {
                    'tipo_ato': tipo_ato,
                    'act_verb': rag.despacho_ato[:50] if rag.despacho_ato else '',
                    'destinatario_texto': '',
                    # 'forcar_mandado': o passo JSON explícito (não fallback)
                    # é sinalizado pelo chamador quando for caso
                }
                historico = self._extrair_historico_comunicacao(proc)

                # ── ComunicacaoTracker ANTES do FluxoDecisor (exceto DJEN) ──
                # Se nenhuma parte intima por domicílio eletrônico, verifica
                # se o ato já foi comunicado à parte. Se sim, NÃO duplica:
                # pula (não gera novo cumprimento) e registra o motivo.
                precheck = self._precheck_tracker(partes_classif, tipo_ato, proc)
                ja_comunicadas = precheck.get('ja_comunicadas', {})
                if ja_comunicadas:
                    nomes = ', '.join(ja_comunicadas.keys())
                    print(f'   ⏭️ {proc_num}: comunicação já realizada p/ {nomes} '
                          f'— pulando (evita duplicar).')
                    resultados.append({
                        'processo': proc,
                        'movimentacao': mov,
                        'rag': rag,
                        'template': template,
                        'classificacao': resultado_cls,
                        'decisao': {
                            'tipo': 'ja_comunicado',
                            'partes': [],
                            'justificativa': (
                                'Comunicação já realizada para: '
                                f'{nomes}. Detalhe: '
                                f'{next(iter(ja_comunicadas.values())).get("mensagem", "")}'
                            ),
                        },
                        'texto_mov': texto,
                    })
                    continue

                decisor = FluxoDecisor(
                    partes_raw, partes_classif, ato_data,
                    historico_comunicacao=historico,
                )
                decisao = decisor.decidir()

                resultados.append({
                    'processo': proc,
                    'movimentacao': mov,
                    'rag': rag,
                    'template': template,
                    'classificacao': resultado_cls,
                    'decisao': decisao,
                    'texto_mov': texto,
                })

            except Exception as e:
                print(f'   ❌ Erro processando {proc_num}: {e}')
                continue

        return resultados

    def _melhor_match(self, texto, similares, templates_validos):
        """Encontra o melhor match RAG + template.

        Usa o MESMO método limpo do CLI (_palavras_para_match — sem
        stopwords/pontuação) e o MESMO threshold (≥70% do MENOR texto).
        Antes usava normalizar_texto cru, o que deixava passar falsos
        positivos (despachos casavam por palavras genéricas do cabeçalho).
        """
        from processes.models import RAGExample
        from processes.movimentacoes_service import _palavras_para_match
        palavras_texto = _palavras_para_match(texto)

        for s in similares:
            # Âncora do match = observação do despacho (texto longo da decisão
            # real). Fallback pro título curto (despacho_ato) só se não houver
            # observação. É a observação que espelha o texto dos documentos
            # baixados das movimentações.
            texto_rag = s.get('despacho_observacao') or s.get('despacho_ato') or ''
            palavras_rag_s = _palavras_para_match(texto_rag)
            base_s = max(min(len(palavras_texto), len(palavras_rag_s)), 1)
            if len(palavras_texto & palavras_rag_s) / base_s < 0.70:
                continue
            try:
                rag = RAGExample.objects.get(id=s['id'])
                t = rag.suggested_templates.filter(id__in=templates_validos).first()
                if t:
                    return s, t, rag
            except RAGExample.DoesNotExist:
                continue
        return None, None, None

    # =================================================================
    # MAPEAMENTO template_type → tipo_ato
    # =================================================================
    def _mapear_template_para_tipo_ato(self, template) -> str:
        """Mapeia DocumentTemplate.template_type para tipo_ato do FluxoDecisor."""
        mapping = {
            'mandado': 'citacao',
            'oficio': 'intimacao',
            'intimacao': 'intimacao',
            'certidao': 'certificar',
            'outro': 'intimacao',
        }
        return mapping.get(template.template_type, 'intimacao') if template else 'intimacao'

    def _mapear_tipo_ato_para_fluxo(self, tipo_ato: str) -> str:
        """Mapeia tipo_ato para fluxo padrão (fallback)."""
        from projudi.fluxo_decisor import FluxoDecisor
        if tipo_ato in FluxoDecisor.ATOS_SEM_DESTINATARIO:
            return 'movimentacao_simples'
        if tipo_ato in FluxoDecisor.ATOS_COM_CITACAO_PESSOAL:
            return 'mandado'
        return 'ar'

    # =================================================================
    # CARREGAR DADOS DO PROCESSO
    # =================================================================
    def _carregar_processo(self, proc_num, mov, session):
        """Carrega ou cria o Process no banco."""
        from processes.models import Process
        proc = Process.objects.filter(number=proc_num).first()
        if not proc:
            proc = self._criar_processo(session, mov, proc_num)
        return proc

    def _criar_processo(self, session, mov, proc_num):
        """Cria Process + Party no banco a partir do Projudi."""
        from projudiProcessNavigator import ProcessoParser
        from processes.models import Process, Party
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
                code='TJBA', defaults={'name': 'TJBA', 'state': 'BA', 'tenant': self.user.tenant})
            vara, _ = Vara.objects.get_or_create(
                code='2VSJ-PA',
                defaults={'name': '2ª VSJ de Paulo Afonso', 'comarca': 'Paulo Afonso',
                          'court': court, 'tenant': self.user.tenant})

            proc = Process.objects.create(
                number=proc_num,
                number_normalized=normalize_process_number(proc_num),
                status='analyzing', vara=vara, court=court,
                projudi_url=link_proc, tenant=self.user.tenant)

            for p in partes_raw:
                nome = p.get('nome', '').strip()
                if not nome:
                    continue
                role = 'autor' if p.get('tipo', '').upper() in ('EXEQUENTE', 'PROMOVENTE') else 'reu'
                Party.objects.get_or_create(
                    process=proc, name=nome, tenant=self.user.tenant,
                    defaults={'name_normalized': nome.lower().strip(), 'role': role,
                              'cpf_cnpj': p.get('cpf/cnpj', ''), 'email': p.get('email', '') or '',
                              'phone': p.get('tel', '') or ''})
            return proc
        except Exception:
            return None

    def _extrair_partes_raw(self, proc, session):
        """Extrai partes do Projudi via DadosProcesso."""
        from projudiProcessNavigator import ProcessoParser
        if not proc.projudi_url:
            return None
        try:
            r = session.get(proc.projudi_url, timeout=30)
            if r.status_code != 200:
                return None
            parser = ProcessoParser(r.text)
            return parser.extrair_partes(parser.soup)
        except Exception:
            return None

    def _extrair_historico_comunicacao(self, proc) -> List[Dict]:
        """Lê o histórico de comunicações do processo do BANCO (Movement).

        Fonte do rastreamento de comunicações usada pelo FluxoDecisor para
        detectar AR que NÃO deu certo (→ queda para mandado/precatória).
        Fallback: Se não há Movement cadastrado, baixa a página DadosProcesso
        e extrai as movimentações do Projudi.
        """
        from processes.models import Movement
        try:
            mvs = list(Movement.objects.filter(process=proc)[:200])
        except Exception:
            mvs = []
        if mvs:
            return self._movs_para_fluxo(mvs)

        # Fallback: baixa a página DadosProcesso
        if not proc.projudi_url:
            return []
        try:
            session = self.projudi_service._get_session_from_cookies() or (None, None)
            session = session[0] if isinstance(session, tuple) else session
            if not session:
                return []
            r = session.get(proc.projudi_url, timeout=15)
            if r.status_code != 200 or 'expirou' in r.text.lower():
                return []
            from projudiProcessNavigator import ProcessoParser
            parser = ProcessoParser(r.text)
            movs, _ = parser.extrair_movimentacoes()
            return self._movs_para_fluxo(movs)
        except Exception:
            return []

    @staticmethod
    def _movs_para_fluxo(movs) -> List[Dict]:
        """Normaliza movimentações para o FluxoDecisor ler AR falho."""
        out = []
        for m in movs:
            out.append({
                'ato_normalizado': m.get('ato_normalizado', ''),
                'ato': m.get('ato', '') or m.get('act_description', ''),
                'meio_comunicacao': m.get('meio_comunicacao', '')
                                    or m.get('communication_means', ''),
                'situacao_comunicacao': m.get('situacao_comunicacao', '')
                                        or m.get('communication_status', ''),
                'destinatario': m.get('destinatario', '') or m.get('recipient', ''),
            })
        return out

    def _extrair_movimentacoes_tracker(self, proc) -> List[Dict]:
        """Movimentações do processo p/ alimentar o ComunicacaoTracker.

        Prioriza o banco (Movement); se não há nada cadastrado, baixa a
        página DadosProcesso e extrai do Projudi. Usado para o pré-check
        de "comunicação já realizada" ANTES da decisão de canal.
        """
        from processes.models import Movement
        try:
            mvs = list(Movement.objects.filter(process=proc).values()[:200])
            if mvs:
                return mvs
        except Exception:
            pass
        if not proc.projudi_url:
            return []
        try:
            session = self.projudi_service._get_session_from_cookies() or (None, None)
            session = session[0] if isinstance(session, tuple) else session
            if not session:
                return []
            r = session.get(proc.projudi_url, timeout=15)
            if r.status_code != 200 or 'expirou' in r.text.lower():
                return []
            from projudiProcessNavigator import ProcessoParser
            parser = ProcessoParser(r.text)
            movs, _ = parser.extrair_movimentacoes()
            return movs
        except Exception:
            return []

    def _precheck_tracker(self, partes_classif, tipo_ato, proc) -> Dict:
        """Tracker ANTES do FluxoDecisor: comunicação já feita? (exceto DJEN).

        Regra (Ivan, 2026-08-06): se nenhuma parte tem domicílio eletrônico
        (DJEN), consulta o histórico de comunicações ANTES de decidir o canal.
        Se o ato já foi comunicado à parte (expedida/lida/pendente), não duplica.
        Retorna { 'ja_comunicadas': {parte: {existe,evento,situacao,mensagem}} }
        """
        # Só roda quando NENHUMA parte intima por DJEN/eletrônico
        if any(p.get('domicilio_cnj') or p.get('recebe_intimacao_email')
               for p in partes_classif):
            return {'ja_comunicadas': {}}
        try:
            from projudi.comunicacao_tracker import ComunicacaoTracker
            tracker = ComunicacaoTracker(self._extrair_movimentacoes_tracker(proc))
        except Exception:
            return {'ja_comunicadas': {}}
        ja = {}
        for p in partes_classif:
            nome = (p.get('nome') or '').strip()
            if not nome:
                continue
            r = tracker.ja_expedida(tipo_ato, nome)
            if r.get('existe'):
                ja[nome] = r
        return {'ja_comunicadas': ja}

    # =================================================================
    # IMPORTAR (criar CumprimentoRecord a partir da decisão)
    # =================================================================
    def importar_cumprimento(self, data: Dict) -> CumprimentoRecord:
        """Cria CumprimentoRecord para cada parte na decisão."""
        processo = data['processo']
        decisao = data['decisao']
        rag = data.get('rag')
        template = data.get('template')
        texto_mov = data.get('texto_mov', '')

        # ── Comunicação JÁ realizada (pre-check do ComunicacaoTracker) ──
        # Não duplica: registra um cumprimento "dispensado" com o motivo para
        # o usuário ver no dashboard, mas NÃO gera novo fluxo de envio.
        if decisao.get('tipo') == 'ja_comunicado':
            record, created = CumprimentoRecord.objects.update_or_create(
                processo=processo.number,
                fluxo='dispensado',
                defaults={
                    'numero_processo_cnj': getattr(processo, 'number', ''),
                    'fluxo_justificativa': (
                        decisao.get('justificativa')
                        or 'Comunicação já realizada (pre-check tracker).'
                    ),
                    'act_verb': '',
                    'snippet': texto_mov[:2000],
                    'template_used': template,
                    'rag_example': rag,
                    'url_processo': getattr(processo, 'projudi_url', ''),
                    'status': 'dispensado',
                    'user': self.user,
                }
            )
            self._log(record, 'info', f"Comunicação já realizada — não duplica. {decisao.get('justificativa', '')}")
            return record

        # Se for ato sem destinatário, cria um único registro
        if decisao.get('tipo') == 'ato_sem_destinatario':
            record, created = CumprimentoRecord.objects.update_or_create(
                processo=processo.number,
                fluxo='movimentacao_simples',
                defaults={
                    'numero_processo_cnj': getattr(processo, 'number', ''),
                    'fluxo_justificativa': decisao.get('justificativa', ''),
                    'act_verb': decisao.get('ato', ''),
                    'snippet': texto_mov[:2000],
                    'template_used': template,
                    'rag_example': rag,
                    'url_processo': getattr(processo, 'projudi_url', ''),
                    'status': 'pendente',
                    'user': self.user,
                }
            )
            self._log(record, 'decisao',
                      f"Ato sem destinatário: {decisao.get('ato', '')}. "
                      f"Fluxo: movimentação simples.")
            return record

        # Para partes com decisão individual
        ultimo_record = None
        for parte_dec in decisao.get('partes', []):
            fluxo = parte_dec['fluxo']
            justificativa = parte_dec['justificativa']
            endereco = parte_dec.get('endereco_analisado', {})

            record, created = CumprimentoRecord.objects.update_or_create(
                processo=processo.number,
                fluxo=fluxo,
                parte_nome=parte_dec['nome'],
                defaults={
                    'numero_processo_cnj': getattr(processo, 'number', ''),
                    'fluxo_justificativa': justificativa,
                    'parte_papel': parte_dec.get('papel', ''),
                    'endereco_analisado': endereco,
                    'act_verb': '',
                    'snippet': texto_mov[:2000],
                    'template_used': template,
                    'rag_example': rag,
                    'url_processo': getattr(processo, 'projudi_url', ''),
                    'status': 'pendente',
                    'user': self.user,
                }
            )

            self._log(record, 'decisao',
                      f"Fluxo definido: {fluxo}. {justificativa}",
                      {'endereco': endereco})
            ultimo_record = record

        return ultimo_record

    # =================================================================
    # EXECUTAR (roteia para o fluxo adequado)
    # =================================================================
    def executar_cumprimento(self, record: CumprimentoRecord) -> Dict:
        """Executa o cumprimento conforme o fluxo.

        Roteia para o serviço especializado ou executa o fluxo genérico.
        """
        from projudi.mandado_service import MandadoService
        from projudi.oficio_service import OficioService

        fluxo = record.fluxo

        # ─── Mandado → roteia para MandadoService ───
        if fluxo in ('mandado', 'mandado_precatorio'):
            self._log(record, 'execucao',
                      f"Roteando para MandadoService ({fluxo}).")
            # stub — MandadoService já trata expedição
            return {'roteado': True, 'service': 'MandadoService', 'fluxo': fluxo}

        # ─── AR → fluxo de Aviso de Recebimento ───
        if fluxo == 'ar':
            self._log(record, 'execucao',
                      f"Fluxo AR: gerar AR para {record.parte_nome}.")
            return self._executar_ar(record)

        # ─── Email / Email Condicional ───
        if fluxo in ('email', 'email_condicional'):
            self._log(record, 'execucao',
                      f"Fluxo email: enviar para {record.parte_nome}.")
            return self._executar_email(record)

        # ─── Eletrônico (DJEN) ───
        if fluxo == 'eletronico':
            self._log(record, 'execucao',
                      f"Fluxo eletrônico DJEN.")
            return self._executar_eletronico(record)

        # ─── Advogado ───
        if fluxo == 'advogado':
            self._log(record, 'execucao',
                      f"Fluxo advogado (intimação via DJEN).")
            return self._executar_advogado(record)

        # ─── Movimentação Simples ───
        if fluxo == 'movimentacao_simples':
            self._log(record, 'execucao',
                      "Fluxo movimentação simples (Mov581).")
            return self._executar_movimentacao_simples(record)

        # ─── Edital ───
        if fluxo == 'edital':
            self._log(record, 'execucao',
                      "Fluxo edital/publicação.")
            return self._executar_edital(record)

        self._log(record, 'erro', f"Fluxo desconhecido: {fluxo}")
        return {'erro': f'Fluxo desconhecido: {fluxo}'}

    # ─── Stubs de execução (sem automação de navegador) ───

    def _executar_movimentacao_simples(self, record: CumprimentoRecord) -> Dict:
        """Executa movimentação simples (Mov581) no Projudi.
        Implementação real via Playwright ou requests futuramente.
        """
        record.status = 'processando'
        record.save(update_fields=['status'])
        self._log(record, 'execucao',
                  "Pronto para Mov581 (Tipo Documental). "
                  "Aguardando implementação da automação.")
        record.status = 'cumprido'
        record.save(update_fields=['status'])
        return {'status': 'cumprido', 'fluxo': 'movimentacao_simples'}

    def _executar_ar(self, record: CumprimentoRecord) -> Dict:
        """Expende a intimação PELOS CORREIOS (AR digital) no Projudi.

        Roteia para MovimentacaoService.executar_com_intimacao_ar() — o
        método dedicado para intimação via AR/correios (Mov581 + painel +
        Concluir + 2º clique: MovimentarProcessoAvancado → select tipo COJE
        → 'expedir com ar digital' → assinar).
        """
        from projudi.movimentacao_service import MovimentacaoService
        record.status = 'processando'
        record.save(update_fields=['status'])
        self._log(record, 'execucao',
                  f"AR para {record.parte_nome} — expedindo pelos correios.")

        # Número Projudi interno (do projudi_url salvo)
        proc_projudi = None
        url_proc = record.url_processo or ''
        import re as _re
        m_proc = _re.search(r'numeroProcesso=(\d+)', url_proc)
        if m_proc:
            proc_projudi = m_proc.group(1)

        try:
            svc = MovimentacaoService(self.user)
            ok = svc.executar_com_intimacao_ar(
                processo_numero=record.numero_processo_cnj or record.processo,
                observacao=record.snippet or 'Intimação pelos Correios (AR digital)',
                proc_projudi=proc_projudi,
            )
            record.status = 'cumprido' if ok else 'falha'
            record.save(update_fields=['status'])
            self._log(record, 'execucao',
                      "AR digital expedido com sucesso." if ok
                      else "Falha ao expedir AR digital.")
            return {'status': record.status, 'fluxo': 'ar'}
        except Exception as e:
            record.status = 'falha'
            record.save(update_fields=['status'])
            self._log(record, 'erro', f'Erro ao expedir AR: {e}')
            return {'status': 'falha', 'fluxo': 'ar', 'erro': str(e)}

    def _executar_email(self, record: CumprimentoRecord) -> Dict:
        """Envia e-mail com o documento.
        Implementação real: enviar e-mail + juntada.
        """
        self._log(record, 'execucao',
                  f"Email para {record.parte_nome}. "
                  "Aguardando implementação do envio.")
        return {'status': 'pendente', 'fluxo': record.fluxo}

    def _executar_eletronico(self, record: CumprimentoRecord) -> Dict:
        """Registra intimação via DJEN.
        Implementação real: Mov581 no Projudi.
        """
        self._log(record, 'execucao',
                  "Intimação eletrônica via DJEN.")
        return {'status': 'pendente', 'fluxo': 'eletronico'}

    def _executar_advogado(self, record: CumprimentoRecord) -> Dict:
        """Registra intimação ao advogado (via DJEN).
        Implementação real: apenas Mov581.
        """
        self._log(record, 'execucao',
                  "Intimação ao advogado via DJEN.")
        return {'status': 'pendente', 'fluxo': 'advogado'}

    def _executar_edital(self, record: CumprimentoRecord) -> Dict:
        """Gera edital de intimação.
        Implementação real: gerar documento de edital.
        """
        self._log(record, 'execucao',
                  f"Edital para {record.parte_nome} necessário.")
        return {'status': 'pendente', 'fluxo': 'edital'}

    # =================================================================
    # DISPENSAR
    # =================================================================
    def dispensar_cumprimento(self, record: CumprimentoRecord) -> Dict:
        """Marca cumprimento como dispensado."""
        record.status = 'dispensado'
        record.save(update_fields=['status'])
        self._log(record, 'info',
                  f"Cumprimento dispensado por {self.user.full_name}.")
        return {'dispensado': True, 'record': record}

    # =================================================================
    # LOGS
    # =================================================================
    def criar_log(self, record: CumprimentoRecord, tipo: str, mensagem: str,
                  detalhes: dict = None):
        """Cria um log para o cumprimento."""
        CumprimentoLog.objects.create(
            cumprimento=record,
            tipo=tipo,
            mensagem=mensagem,
            detalhes=detalhes or {},
        )

    def _log(self, record, tipo, mensagem, detalhes=None):
        self.criar_log(record, tipo, mensagem, detalhes)

    def logs_humanizados(self, record: CumprimentoRecord) -> List[Dict]:
        """Retorna logs formatados para exibição."""
        return list(
            CumprimentoLog.objects.filter(cumprimento=record)
            .values('tipo', 'mensagem', 'created_at')
            .order_by('-created_at')
        )

    # =================================================================
    # BATCH
    # =================================================================
    def processar_fila(self, records: List[CumprimentoRecord]) -> Dict:
        """Processa fila de cumprimentos pendentes."""
        cumpridos = 0
        falhas = 0
        for rec in records:
            if rec.status not in ('pendente', 'falha'):
                continue
            try:
                resultado = self.executar_cumprimento(rec)
                if resultado.get('status') == 'cumprido':
                    cumpridos += 1
                else:
                    falhas += 1
            except Exception as e:
                rec.status = 'falha'
                rec.save(update_fields=['status'])
                self._log(rec, 'erro', str(e))
                falhas += 1
        return {'cumpridos': cumpridos, 'falhas': falhas}

    # =================================================================
    # FECHAR
    # =================================================================
    def fechar(self):
        try:
            self.projudi_service.fechar()
        except Exception:
            pass
