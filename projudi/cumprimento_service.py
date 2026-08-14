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

        # ─── Análise de prazo (observação/certidão controlada por JSON) ───
        # Gera prazo_info + observacao_prazo a partir do rastreamento de
        # comunicações (data real da intimação), do despacho e da RAG.
        # Alimenta a observação do Mov581 / certidão nos fluxos abaixo.
        # Pula mandado/ofício (fluxo próprio de expedição) e edital
        # (publicação em diário, sem contagem de prazo de intimação).
        if fluxo in ('eletronico', 'advogado', 'ar', 'email',
                     'email_condicional', 'movimentacao_simples'):
            try:
                self.gerar_observacao_prazo(record)
            except Exception as e:
                self._log(record, 'erro',
                          f'Falha ao gerar análise de prazo: {e}')

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

        Liga a contagem de prazo ao envio real:
          - observação de prazo (se RAG 'observacao_prazo'=True) →
            campo observação do Mov581.
          - certidão de prazo (se RAG 'expede_certidao_prazo'=True) →
            HTML do DocumentTemplate 'Certidão de Prazo' injetado no
            FCKeditor (igual certidão criminal).
        Usa MovimentacaoService.executar_requests (já suporta certidao_html).
        """
        # Garante o cálculo de prazo (já feito em executar_cumprimento, mas
        # reaplica se por acaso não houver prazo_info).
        # Lê a config do RAG (observacao_prazo / expede_certidao_prazo /
        # polo_prazo) ANTES de gerar a observação, para que o polo
        # (autor/réu/ambos) seja refletido no texto e na certidão.
        cfg = self._config_prazo_do_rag(record)
        polo = cfg.get('polo_prazo')
        if polo and not record.parte_papel:
            record.parte_papel = polo
            record.save(update_fields=['parte_papel'])

        if not record.prazo_info:
            try:
                self.gerar_observacao_prazo(record)
            except Exception as e:
                self._log(record, 'erro',
                          f'Falha ao calcular prazo: {e}')
                record.status = 'falha'
                record.save(update_fields=['status'])
                return {'status': 'falha', 'fluxo': record.fluxo,
                        'erro': str(e)}

        cfg = self._config_prazo_do_rag(record)
        observacao = (self.observacao_para_movimentacao(record)
                      if cfg['observacao_prazo'] else '')
        certidao_html = (self._html_certidao_prazo(record)
                         if cfg['expede_certidao_prazo'] else '')

        # Papel final (autor/réu/ambos) — JSON da RAG (polo_prazo)
        # sobrepõe o parte_papel do record.
        papel = self._papel_resolvido(record)

        record.status = 'processando'
        record.save(update_fields=['status'])
        self._log(
            record, 'execucao',
            f"Mov581 ({record.fluxo}) — obs_prazo={bool(observacao)}, "
            f"certidao_prazo={bool(certidao_html)}, "
            f"polo={papel}.")

        # Cria o MovimentacaoRecord correspondente.
        from projudi.models import MovimentacaoRecord
        mov, _ = MovimentacaoRecord.objects.get_or_create(
            processo=record.processo,
            numero_processo_cnj=record.numero_processo_cnj or '',
            act_verb='certifique-se' if certidao_html else 'registre-se',
            defaults={
                'categoria': 'certidao' if certidao_html else 'registro',
                'observacao': observacao,
                'codigo_movimentacao': '581',
                'descricao_movimentacao': ('Certidão de Prazo'
                                           if certidao_html
                                           else 'Cumprimento de Decisão'),
                'parte_nome': record.parte_nome or '',
                'parte_papel': record.parte_papel or '',
                'url_processo': record.url_processo or '',
                'user': self.user,
                'rag_example': getattr(record, 'rag_example', None),
                'status': 'pendente',
            },
        )
        if mov.pk:  # já existia: atualiza observação/categoria
            mov.observacao = observacao
            mov.categoria = 'certidao' if certidao_html else 'registro'
            mov.act_verb = 'certifique-se' if certidao_html else 'registre-se'
            mov.parte_papel = record.parte_papel or ''
            mov.status = 'pendente'
            mov.save(update_fields=['observacao', 'categoria',
                                    'act_verb', 'parte_papel', 'status'])

        try:
            from projudi.movimentacao_service import MovimentacaoService
            svc = MovimentacaoService(self.user)
            ok = svc.executar_requests(
                mov,
                certidao_html=certidao_html,
                certidao_titulo=('Certidão de Prazo'
                                 if certidao_html else None) or '',
            )
        except Exception as e:
            record.status = 'falha'
            record.save(update_fields=['status'])
            self._log(record, 'erro', f'Erro ao executar Mov581: {e}')
            return {'status': 'falha', 'fluxo': record.fluxo,
                    'erro': str(e)}

        record.status = 'cumprido' if ok else 'falha'
        record.save(update_fields=['status'])
        self._log(
            record, 'execucao',
            "Mov581 concluída." if ok else "Falha na Mov581.")
        return {'status': record.status, 'fluxo': record.fluxo,
                'certidao': bool(certidao_html),
                'observacao': bool(observacao),
                'polo': record.parte_papel or ''}

    def _executar_via_movimentacao(self, record: CumprimentoRecord) -> Dict:
        """Helper para fluxos que vão a Mov581 (eletronico/advogado/etc.).

        Igual a _executar_movimentacao_simples, mas mantém o fluxo
        original no log/retorno.
        """
        return self._executar_movimentacao_simples(record)

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
        """Registra intimação via DJEN (Mov581 no Projudi).

        A contagem de prazo e (se o RAG pedir) a observação/certidão de
        prazo já foram preparadas em executar_cumprimento; aqui apenas
        executa a movimentação simples com esses dados.
        """
        return self._executar_via_movimentacao(record)

    def _executar_advogado(self, record: CumprimentoRecord) -> Dict:
        """Registra intimação ao advogado (via DJEN / Mov581)."""
        return self._executar_via_movimentacao(record)

    def _executar_edital(self, record: CumprimentoRecord) -> Dict:
        """Gera edital de intimação.
        Implementação real: gerar documento de edital.
        """
        self._log(record, 'execucao',
                  f"Edital para {record.parte_nome} necessário.")
        return {'status': 'pendente', 'fluxo': 'edital'}

    # =================================================================
    # PRAZOS (contagem processual)
    # =================================================================
    def calcular_prazo(self, data_inicio, prazo_dias, feriados_extra=None,
                       incluir_dia_inicio=False, modo='uteis', djen=False,
                       tenant=None, court=None, vara=None):
        """Calcula prazo processual em dias úteis (CPC/CNJ).

        Delega para PrazoService (projudi/prazo_service.py). Regras:
        dia da intimação não conta; fds/feriado/recesso (20/12 a 22/01)
        suspendem; 'ultimo_dia' = N-ésimo dia útil; 'data_decurso' =
        dia seguinte.

        Se 'tenant' for informado, carrega feriados e suspensões de prazo
        CADASTRADOS no banco (modelos Feriado/SuspensaoPrazo) em vez de
        usar só feriados_extra. O cadastro é isolado por tenant e filtrável
        por court/vara (escopos estadual/comarca/vara).

        Args:
            data_inicio: date da intimação/publicação (não conta).
            prazo_dias: int > 0.
            feriados_extra: {ano: [date, ...]} c/ feriados municipais,
                semana de baixa e feriados móveis do ano (fallback se não
                houver tenant).
            incluir_dia_inicio: True se o dia da intimação conta.
            modo: 'uteis' (padrão) ou 'corridos'.
            djen: True aplica a regra do CPC art. 5º §3º — intimação
                eletrônica (DJEN): o 1º dia da intimação e o 1º dia útil
                subsequente NÃO contam; a contagem inicia no 3º dia útil.
            tenant: accounts.Tenant p/ carregar cadastro de feriados/
                suspensões do banco.
            court/vara: filtros de escopo (opcionais).

        Returns:
            ResultadoPrazo (ultimo_dia, data_decurso, dias_contados,
            dias_excluidos, relatorio()).
        """
        from projudi.prazo_service import PrazoService

        if tenant is not None:
            svc = PrazoService.from_db(tenant=tenant, court=court, vara=vara)
        else:
            svc = PrazoService(feriados_extra=feriados_extra)

        return svc.contar_prazo(
            data_inicio, prazo_dias,
            incluir_dia_inicio=incluir_dia_inicio, modo=modo, djen=djen,
        )

    def contar_prazo_por_fluxo(self, fluxo, data_inicio, prazo_dias,
                               modo='uteis', tenant=None, court=None, vara=None):
        """Atalho que aplica a regra de contagem conforme o fluxo de
        comunicação (art. 5º §3º / art. 219 §1º do CPC):

          - 'eletronico' (DJEN): djen=True  → 1º dia da intimação + 1º
            dia útil subsequente NÃO contam; conta do 3º dia útil.
          - 'advogado': djen=False → dia do recebimento NÃO conta;
            conta do dia seguinte (regra padrão de intimação pessoal).
          - 'decadencial': modo='decadencial' → conta TODOS os dias,
            sem fds/feriado/recesso/suspensão (ex: decadência de 1 ano).
          - demais fluxos (ar, correio, mandado, edital...): djen=False
            (o dia do ato não conta; conta do dia seguinte).

        Args:
            fluxo: CumprimentoRecord.fluxo (ou string equivalente).
            data_inicio/prazo_dias/modo/tenant/court/vara: ver calcular_prazo.

        Returns:
            ResultadoPrazo.
        """
        djen = (fluxo == 'eletronico')
        if modo == 'decadencial':
            djen = False
        return self.calcular_prazo(
            data_inicio, prazo_dias, modo=modo, djen=djen,
            tenant=tenant, court=court, vara=vara,
        )

    def contar_decadencial(self, data_inicio, prazo_dias,
                           tenant=None, court=None, vara=None,
                           incluir_dia_inicio=False):
        """Prazo decadencial: corre diariamente, sem qualquer suspensão.

        Veja PrazoService.contar_decadencial. Útil p/ avaliar decadência
        (ex: art. 208 CC) a partir da data do fato/ato.
        """
        return self.calcular_prazo(
            data_inicio, prazo_dias, modo='decadencial',
            incluir_dia_inicio=incluir_dia_inicio,
            tenant=tenant, court=court, vara=vara,
        )

    # =================================================================
    # ANÁLISE DE PRAZO → OBSERVAÇÃO / CERTIDÃO (JSON CONTROLADO)
    # =================================================================
    @staticmethod
    def extrair_prazo_do_despacho(texto: str) -> Dict:
        """Extrai data de início e número de dias do despacho.

        Tenta identificar no texto do despacho/observação:
          - Data da intimação/publicação: "intimado em 09/02/2026",
            "publicado em 10/02/2026", "ciência em 09/02/2026", ou
            "data da intimação: 09/02/2026".
          - Prazo em dias: "prazo de 15 dias", "no prazo de 10 (dez)
            dias", "15 dias úteis", "intimo a parte em 15 dias".

        Returns:
            {'data_inicio': date|None, 'prazo_dias': int|None,
             'modo': 'uteis'|'corridos'|'decadencial', 'encontrado': bool}
        """
        import re
        from datetime import datetime

        resultado = {
            'data_inicio': None, 'prazo_dias': None,
            'modo': 'uteis', 'encontrado': False,
        }
        if not texto:
            return resultado

        # ── Data de início (intimação/publicação/ciência) ──
        padroes_data = [
            r'(?:intim|public|ci[êe]ncia|citad)[ãoa\w\s]*?em\s*(\d{1,2}/\d{1,2}/\d{4})',
            r'data\s+da\s+(?:intima[çc][ãa]o|public)[ãa\w\s]*?[:\s]*(\d{1,2}/\d{1,2}/\d{4})',
        ]
        for pad in padroes_data:
            m = re.search(pad, texto, re.IGNORECASE)
            if m:
                try:
                    resultado['data_inicio'] = datetime.strptime(
                        m.group(1), '%d/%m/%Y').date()
                    break
                except ValueError:
                    pass

        # ── Prazo em dias ──
        m_prazo = re.search(
            r'(\d{1,3})\s*(?:\([^)]*\)\s*)?dias?\s*(?:[úu]teis|corridos|)?',
            texto, re.IGNORECASE)
        if m_prazo:
            try:
                resultado['prazo_dias'] = int(m_prazo.group(1))
            except ValueError:
                pass

        # ── Modo ──
        txt_low = texto.lower()
        if re.search(r'decad', txt_low):
            resultado['modo'] = 'decadencial'
        elif re.search(r'dias?\s+corridos|corridos?', txt_low):
            resultado['modo'] = 'corridos'

        resultado['encontrado'] = bool(
            resultado['data_inicio'] and resultado['prazo_dias'])
        return resultado

    def gerar_observacao_prazo(self, record: CumprimentoRecord,
                               tenant=None, court=None, vara=None,
                               data_inicio=None, prazo_dias=None,
                               modo=None, forcar=False) -> Dict:
        """Conta o prazo e gera a observação/certidão controlada por JSON.

        Fontes de extração (prioridade):
          1. Rastreamento de comunicações (Movement do processo): DATA
             REAL em que a parte foi intimada (situação concluída/lida).
             É a fonte autorizada da data_inicio.
          2. Atos do despacho / RAG (record.snippet ou RAGExample
             despacho_observacao/despacho_ato): NÚMERO DE DIAS e o tipo
             de prazo (úteis/corridos/decadencial).
          Override manual via data_inicio / prazo_dias / modo.

        Salva:
          - record.prazo_info  → JSON serializável do PrazoService
          - record.observacao_prazo → texto controlado (padrão 2ª VSJ)

        O JSON resultante (ver montar_json_envio) é o que vai ser enviado
        na observação do Mov581 e/ou na certidão.

        Args:
            forcar: mesmo que já exista prazo_info, recalcula.
        """
        # Só pula se já houver cálculo E observação gerada (evita
        # recalcular à toa, mas permite regerar o texto se estiver vazio).
        if (record.prazo_info and record.observacao_prazo
                and not forcar and not (data_inicio or prazo_dias)):
            return {'status': 'ok', 'prazo_info': record.prazo_info,
                    'observacao': record.observacao_prazo,
                    'resultado': None, 'mensagem': 'Já calculado.'}

        tenant = tenant or (self.user.tenant if self.user else None)
        if not tenant:
            raise ValueError('gerar_observacao_prazo exige tenant.')

        # ── Fonte 1: rastreamento de comunicações (data real da intimação) ──
        data_tracker = self._data_intimacao_do_tracker(record)
        # ── Fonte 2: atos do despacho / RAG (prazo em dias + modo) ──
        texto_despacho = self._texto_despacho_record(record)
        extr = self.extrair_prazo_do_despacho(texto_despacho)

        data_inicio = data_inicio or data_tracker or extr['data_inicio']
        prazo_dias = prazo_dias or extr['prazo_dias']
        modo = modo or extr['modo'] or 'uteis'

        if not data_inicio or not prazo_dias:
            self._log(
                record, 'erro',
                'Não foi possível determinar data/prazo. Tracker='
                f'{data_tracker}, despacho='
                f'(início={extr["data_inicio"]}, dias={extr["prazo_dias"]}).',
                detalhes={'tracker': data_tracker, 'despacho': extr},
            )
            return {'status': 'erro',
                    'mensagem': 'Data/prazo não determinados (tracker+despacho).'}

        res = self.contar_prazo_por_fluxo(
            record.fluxo, data_inicio, prazo_dias, modo=modo,
            tenant=tenant, court=court, vara=vara,
        )

        observacao = self._texto_observacao_prazo(record, res, modo)
        record.prazo_info = res.to_dict()
        record.observacao_prazo = observacao

        # ── Decisão observação vs certidão ──
        # Lê do RAGExample vinculado (sequencia_cumprimento): cada item
        # pode trazer 'observacao_prazo' e 'expede_certidao_prazo'.
        # Isso É a fonte autorizada (você configura na RAG).
        cfg = self._config_prazo_do_rag(record)
        observacao_prazo_flag = cfg['observacao_prazo']
        certidao_prazo_flag = cfg['expede_certidao_prazo']

        # Persiste as flags no prazo_info p/ consulta/debug.
        record.prazo_info['observacao_prazo'] = observacao_prazo_flag
        record.prazo_info['expede_certidao_prazo'] = certidao_prazo_flag

        record.save(
            update_fields=['prazo_info', 'observacao_prazo'])

        self._log(
            record, 'decisao',
            f'Prazo calculado ({modo}, djen={res.djen}): '
            f'último dia {res.ultimo_dia:%d/%m/%Y}, '
            f'decurso {res.data_decurso:%d/%m/%Y}. '
            f'Fonte data: {"tracker" if data_tracker else "despacho"}. '
            f'RAG: observacao_prazo={observacao_prazo_flag}, '
            f'expede_certidao_prazo={certidao_prazo_flag}.',
            detalhes=res.to_dict(),
        )
        return {'status': 'ok', 'prazo_info': res.to_dict(),
                'observacao': observacao, 'resultado': res,
                'fonte_data': 'tracker' if data_tracker else 'despacho',
                'observacao_prazo': observacao_prazo_flag,
                'expede_certidao_prazo': certidao_prazo_flag}

    @staticmethod
    def _config_prazo_do_rag(record: CumprimentoRecord) -> Dict:
        """Lê a configuração de prazo do RAGExample vinculado ao cumprimento.

        O RAGExample.sequencia_cumprimento é uma lista ordenada de atos;
        cada item pode trazer:
          - 'observacao_prazo': bool  → colocar a contagem de prazo na
            observação da movimentação (Mov581).
          - 'expede_certidao_prazo': bool → expedir a CERTIDÃO DE PRAZO
            (documento à parte, diferente de outras certidões).
        O item é casado pelo 'tipo' (ex: 'movimentacao') ou, se não
        houver tipo, pelo trecho de 'observacao' presente no snippet.

        Retorna {'observacao_prazo': bool, 'expede_certidao_prazo': bool}.
        Default: ambos False se não houver RAG ou item correspondente.
        """
        rag = getattr(record, 'rag_example', None)
        if not rag:
            return {'observacao_prazo': False, 'expede_certidao_prazo': False,
                    'polo_prazo': None}
        seq = getattr(rag, 'sequencia_cumprimento', None) or []
        if not seq:
            return {'observacao_prazo': False, 'expede_certidao_prazo': False,
                    'polo_prazo': None}

        tipo_rag = {
            'eletronico': 'movimentacao', 'advogado': 'movimentacao',
            'ar': 'movimentacao', 'email': 'movimentacao',
            'email_condicional': 'movimentacao',
            'movimentacao_simples': 'movimentacao', 'edital': 'movimentacao',
            'mandado': 'mandado', 'mandado_precatorio': 'mandado',
            'oficio': 'oficio', 'intimacao': 'intimacao',
        }.get(record.fluxo, record.fluxo)
        item = None
        for it in seq:
            if isinstance(it, dict) and it.get('tipo') == tipo_rag:
                item = it
                break
        if item is None and record.snippet:
            snip = record.snippet.lower()
            for it in seq:
                if isinstance(it, dict):
                    obs = (it.get('observacao') or '').lower()
                    if obs and obs in snip:
                        item = it
                        break
        if item is None:
            return {'observacao_prazo': False, 'expede_certidao_prazo': False,
                    'polo_prazo': None}

        # polo_prazo: para quem corre o prazo — 'autor' | 'reu' | 'ambos'.
        # Se omitido no JSON, infere pelo fluxo (eletronico/advogado/ar
        # costumam ser para o réu; mandado/oficio têm polo próprio).
        polo = item.get('polo_prazo')
        if polo is None:
            polo = 'reu' if record.fluxo in (
                'eletronico', 'advogado', 'ar', 'email',
                'email_condicional', 'movimentacao_simples') else None

        return {
            'observacao_prazo': bool(item.get('observacao_prazo', False)),
            'expede_certidao_prazo': bool(
                item.get('expede_certidao_prazo', False)),
            'polo_prazo': polo,
        }

    def _texto_despacho_record(self, record: CumprimentoRecord) -> str:
        """Concatena as fontes textuais do ato: snippet + RAG matchada.

        O RAG (despacho_observacao/despacho_ato) é a âncora do conteúdo do
        ato; o snippet é o trecho da decisão. Ambos alimentam a extração
        do número de dias e do tipo de prazo.
        """
        partes = [record.snippet or '']
        # RAG vinculada ao cumprimento (se houver)
        if getattr(record, 'rag_example', None):
            rag = record.rag_example
            partes.append(rag.despacho_observacao or '')
            partes.append(rag.despacho_ato or '')
        # Template usado (pode conter metadados do ato)
        if record.template_used:
            partes.append(getattr(record.template_used, 'descricao', '') or '')
        return '\n'.join(p for p in partes if p)

    def _processo_resolvido(self, record: CumprimentoRecord):
        """Resolve o Process (ORM) a partir do CumprimentoRecord.

        Usa o CNJ (numero_processo_cnj) ou o número interno (processo) para
        achar o Process. Retorna None se não houver no banco.
        """
        from processes.models import Process
        import re
        cnj = (getattr(record, 'numero_processo_cnj', '') or '').strip()
        inter = (getattr(record, 'processo', '') or '').strip()
        if cnj:
            p = (Process.objects.filter(number=cnj).first()
                 or Process.objects.filter(
                     number_normalized=re.sub(r'\D', '', cnj)).first())
            if p:
                return p
        if inter:
            return (Process.objects.filter(number=inter).first()
                    or Process.objects.filter(
                        number_normalized__icontains=inter).first())
        return None

    def _data_intimacao_do_tracker(self, record: CumprimentoRecord):
        """Data REAL de início da intimação da parte, via rastreamento.

        Resolve o Process do cumprimento, lê as Movement do processo e
        escolhe a data de início do prazo:
          - fluxo eletronico/DJEN (e advogado): usa a DATA DE DISPONIBILIZAÇÃO
            no DJEN (Movement.reference_date) mais recente — marco de início
            da intimação eletrônica.
          - senão: usa a data de leitura (reading_date) mais recente; depois a
            data da intimação (act_date); por fim a última referência DJEN.
        Se record.parte_nome estiver preenchido, filtra por destinatário.
        """
        proc = self._processo_resolvido(record)
        if proc is None:
            return None
        from processes.models import Movement
        try:
            mvs = Movement.objects.filter(process=proc)
            if not mvs.exists():
                return None
            parte = (getattr(record, 'parte_nome', '') or '').strip()
            base = mvs
            if parte:
                f = mvs.filter(recipient__icontains=parte)
                if f.exists():
                    base = f
            # 1) DJEN/eletrônica → data de disponibilização no DJEN
            if getattr(record, 'fluxo', '') in ('eletronico', 'advogado'):
                djen = (base.filter(reference_date__isnull=False)
                        .order_by('-reference_date').first())
                if djen and djen.reference_date:
                    return djen.reference_date
            # 2) leitura real mais recente (intimação lida)
            lida = (base.exclude(reading_date__isnull=True)
                    .order_by('-reading_date').first())
            if lida and lida.reading_date:
                return lida.reading_date
            # 3) qualquer intimação (data do ato)
            inta = base.filter(category='intimacao').order_by('-act_date').first()
            if inta and inta.act_date:
                return inta.act_date
            # 4) última referência DJEN do processo todo (fora do filtro parte)
            ref = (Movement.objects.filter(process=proc,
                                           reference_date__isnull=False)
                   .order_by('-reference_date').first())
            if ref and ref.reference_date:
                return ref.reference_date
            return None
        except Exception:
            return None

    @staticmethod
    def _rotulo_intimacao(fluxo: str, djen: bool, modo: str) -> str:
        """Rótulo de COMO foi feita a intimação (prefixo do texto)."""
        if modo == 'decadencial':
            return 'Prazo decadencial'
        if djen or fluxo == 'eletronico':
            return 'Intimação eletrônica (DJEN)'
        return {
            'ar': 'Intimação via AR (Correios)',
            'email': 'Intimação eletrônica (e-mail)',
            'email_condicional': 'Intimação eletrônica (e-mail)',
            'advogado': 'Intimação ao advogado',
            'edital': 'Intimação por edital',
            'mandado': 'Intimação por mandado',
            'movimentacao_simples': 'Intimação',
        }.get(fluxo, 'Intimação')

    @staticmethod
    def _rotulo_parte(parte_papel: str, parte_nome: str) -> str:
        """Rótulo de PARA QUEM é a contagem de prazo (autor / réu / ambos).

        Usado na certidão de prazo e na observação para deixar claro se o
        prazo corre para a parte autora, para o réu, ou para ambos.
        """
        papel = (parte_papel or '').lower()
        nome = (parte_nome or '').strip()
        sufixo = f' {nome}' if nome else ''
        if papel in ('autor', 'autora', 'promovente', 'requerente'):
            return f'à parte autora{sufixo}'
        if papel in ('reu', 'reu_especifico', 'executado', 'requerido',
                     'promovido'):
            return f'ao réu{sufixo}'
        if papel in ('ambos', 'todos', 'autores', 'res'):
            return 'aos autores e réus'
        # Sem papel definido: cai no genérico (mas tenta o nome se houver).
        return f'à(s) parte(s){sufixo}' if nome else 'à(s) parte(s)'

    @staticmethod
    def _papel_resolvido(record: 'CumprimentoRecord') -> str:
        """Papel final para a contagem de prazo.

        Prioridade: JSON da RAG (polo_prazo: 'autor'/'reu'/'ambos')
        sobrepõe o parte_papel do record. Retorna o papel normalizado
        que _rotulo_parte entende ('autor'/'reu'/...).
        """
        cfg = CumprimentoService._config_prazo_do_rag(record)
        polo = cfg.get('polo_prazo')
        if polo:
            p = str(polo).lower()
            if p in ('autor', 'autora', 'promovente', 'requerente',
                     'autor_especifico', 'autores'):
                return 'autor'
            if p in ('reu', 'reu_especifico', 'executado', 'requerido',
                     'promovido', 'res'):
                return 'reu'
            if p in ('ambos', 'todos', 'autores_e_reus'):
                return 'ambos'
        # Fallback: parte_papel do record.
        return (getattr(record, 'parte_papel', '') or '').lower()

    @staticmethod
    def _texto_observacao_prazo(record, res, modo) -> str:
        """Gera o texto controlado da observação de prazo (padrão 2ª VSJ).

        Texto GENÉRICO e elegante: identifica COMO foi a intimação
        (DJEN / AR / advogado / e-mail / etc.) e os 4 marcos da contagem
        (leitura, início, término, decurso). Sem citar artigos.

        Regras de exclusão (refletidas no texto):
          - DJEN: não contam a LEITURA nem o 1º dia útil SEGUINTE à
            leitura (início no 3º dia útil).
          - demais meios: o dia da leitura/recebimento não conta.
          - decadencial: conta todos os dias (sem exclusão).
        """
        if modo == 'decadencial':
            return (
                f'Prazo decadencial de {res.prazo_dias} dias. '
                f'Início em {res.data_inicio:%d/%m/%Y}, '
                f'término em {res.ultimo_dia:%d/%m/%Y} '
                f'(decorrido o prazo em {res.data_decurso:%d/%m/%Y}).'
            )

        rotulo = CumprimentoService._rotulo_intimacao(
            record.fluxo, res.djen, modo)
        papel = CumprimentoService._papel_resolvido(record)
        parte = CumprimentoService._rotulo_parte(papel, record.parte_nome)
        inicio = res.dias_contados[0] if res.dias_contados else None

        if res.djen:
            regra_excl = ('; não contam a leitura nem o 1º dia útil '
                          'subsequente à leitura')
        else:
            regra_excl = '; o dia da leitura não conta'

        return (
            f'{rotulo} — Prazo de {res.prazo_dias} dias úteis '
            f'{parte}. '
            f'Leitura em {res.data_inicio:%d/%m/%Y}{regra_excl}; '
            f'início da contagem em {inicio:%d/%m/%Y}; '
            f'término em {res.ultimo_dia:%d/%m/%Y} '
            f'(decorrido o prazo em {res.data_decurso:%d/%m/%Y}).'
        )

    def observacao_para_movimentacao(self, record: CumprimentoRecord) -> str:
        """Observação a ser enviada no Mov581 (campo observação da movimentação).

        Regra (fonte autorizada = RAGExample.sequencia_cumprimento):
          - 'expede_certidao_prazo'=True → NÃO vai pra observação (a
            certidão é documento à parte). Retorna ''.
          - 'observacao_prazo'=True e não é certidão → retorna o texto
            controlado (observacao_prazo).
          - Caso contrário → retorna '' (não polui a movimentação).

        Garante que prazo_info esteja calculado.
        """
        if not record.prazo_info:
            self.gerar_observacao_prazo(record)
        tem_prazo = bool(record.prazo_info.get('ultimo_dia')) if isinstance(
            record.prazo_info, dict) else False
        if not tem_prazo:
            return ''
        cfg = self._config_prazo_do_rag(record)
        if cfg['expede_certidao_prazo']:
            # Mesmo expedindo certidão, a observação de prazo pode (ou não)
            # ir para a movimentação se 'observacao_prazo'=True.
            return record.observacao_prazo if cfg['observacao_prazo'] else ''
        return record.observacao_prazo if cfg['observacao_prazo'] else ''

    def montar_json_envio(self, record: CumprimentoRecord) -> Dict:
        """JSON controlado que será enviado (observação do Mov581 / certidão).

        Consolida prazo_info + observacao_prazo + dados do cumprimento.
        Se ainda não houver prazo_info, tenta gerar a partir do despacho.

        Flags de controle (true/false) — fonte = RAGExample:
          - 'prazo_calculado': True se há prazo calculado.
          - 'certidao': True se 'expede_certidao_prazo' (RAG) pede a
            certidão de prazo → 'texto_certidao' traz o HTML.
          - 'observacao_prazo': True se 'observacao_prazo' (RAG) pede que
            a contagem vá para a observação do Mov581 → 'observacao'.
        """
        if not record.prazo_info:
            self.gerar_observacao_prazo(record)

        tem_prazo = bool(
            record.prazo_info and record.prazo_info.get('ultimo_dia'))
        cfg = self._config_prazo_do_rag(record)
        certidao = cfg['expede_certidao_prazo']
        obs_prazo = cfg['observacao_prazo']

        texto_certidao = self._html_certidao_prazo(
            record) if (tem_prazo and certidao) else ''

        return {
            'processo': record.processo,
            'numero_processo_cnj': record.numero_processo_cnj,
            'fluxo': record.fluxo,
            'parte_nome': record.parte_nome,
            'prazo': record.prazo_info,
            'prazo_calculado': tem_prazo,            # true/false
            'observacao_prazo': obs_prazo,          # true/false
            'certidao': certidao,                   # true/false
            'observacao': record.observacao_prazo if (
                tem_prazo and obs_prazo) else '',
            'texto_certidao': texto_certidao,       # preenchido só se certidao=true
        }

    def _html_certidao_prazo(self, record: CumprimentoRecord) -> str:
        """HTML da certidão de prazo a partir do JSON controlado.

        Usa o mesmo texto genérico de observação (observacao_prazo),
        embrulhado no cabeçalho de certidão. Datas em %d/%m/%Y.
        """
        p = record.prazo_info or {}
        if not p:
            return ''
        # 1) Tenta o DocumentTemplate 'Certidão de Prazo' (base Ofício CIAP).
        try:
            from processes.models import DocumentTemplate
            from django.template import Template, Context
            tpl = DocumentTemplate.objects.get(
                name='Certidão de Prazo', active=True)
            from datetime import date as _date
            ctx = {
                'processo': record.numero_processo_cnj or record.processo,
                'parte': CumprimentoService._rotulo_parte(
                    self._papel_resolvido(record), record.parte_nome),
                'observacao_prazo': record.observacao_prazo or '',
                'data': _date.today().strftime('%d/%m/%Y'),
                'servidor': (getattr(self.user, 'full_name', '')
                             or getattr(self.user, 'first_name', '') or '...'),
            }
            return tpl.render(ctx)
        except Exception:
            pass
        # 2) Fallback: HTML simples.
        from datetime import datetime
        def _fmt(d):
            if isinstance(d, str):
                try:
                    d = datetime.strptime(d, '%Y-%m-%d').date()
                except ValueError:
                    return d
            if hasattr(d, 'strftime'):
                return d.strftime('%d/%m/%Y')
            return str(d)
        d_ini = _fmt(p.get('data_inicio', ''))
        d_fim = _fmt(p.get('ultimo_dia', ''))
        d_dec = _fmt(p.get('data_decurso', ''))
        dias = p.get('dias_contados', [])
        n = len(dias)
        # Texto genérico (mesmo da observação), sem repetir o óbvio.
        texto = record.observacao_prazo or (
            f'Prazo de {p.get("prazo_dias")} dias {p.get("modo")}. '
            f'Leitura em {d_ini}, término em {d_fim} '
            f'(decorrido o prazo em {d_dec}).'
        )
        return (
            f'<p><b>CERTIDÃO DE PRAZO</b></p>'
            f'<p>Certifico que, referente ao processo nº '
            f'{record.numero_processo_cnj or record.processo}, '
            f'a parte {record.parte_nome or "..."} — {texto}</p>'
            f'<p>O prazo encerra-se em <b>{d_fim}</b> '
            f'(decurso do prazo em {d_dec}), totalizando {n} dias '
            f'contados.</p>'
        )
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
