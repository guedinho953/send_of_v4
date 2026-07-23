"""MovimentacaoService — Executa movimentações internas no Projudi (Mov581).

Análogo a MandadoService / OficioService.
Diferença: em vez de expedir documentos (CumprimentoCartorio + FCKeditor),
apenas registra o cumprimento via Mov581 (preencher observação + Concluir).
"""

import sys
import re
import time
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from django.conf import settings

PROJECT_ROOT = str(settings.BASE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from .models import MovimentacaoRecord, MovimentacaoLog
from .services import ProjudiService


class MovimentacaoService:
    """Serviço de orquestração de movimentações internas."""

    def __init__(self, user):
        self.user = user
        self.projudi_service = ProjudiService(user)

    # =================================================================
    # IMPORTAR
    # =================================================================
    def importar(
        self,
        processo_numero: str,
        act_verb: str,
        observacao: str,
        categoria: str = 'outro',
        processo_cnj: str = '',
        parte_nome: str = '',
        parte_papel: str = '',
        rag_example=None,
        template=None,
        url_processo: str = '',
        codigo_movimentacao: str = '581',
        descricao_movimentacao: str = 'Cumprimento de Decisão',
    ) -> MovimentacaoRecord:
        """Cria MovimentacaoRecord no banco."""
        record = MovimentacaoRecord.objects.create(
            processo=processo_numero,
            numero_processo_cnj=processo_cnj,
            act_verb=act_verb,
            categoria=categoria,
            observacao=observacao,
            codigo_movimentacao=codigo_movimentacao,
            descricao_movimentacao=descricao_movimentacao,
            parte_nome=parte_nome,
            parte_papel=parte_papel,
            rag_example=rag_example,
            template_used=template,
            url_processo=url_processo,
            status='pendente',
            user=self.user,
        )
        self._log(record, 'info',
                  f"Movimentação criada: {act_verb} — {observacao[:80]}...")
        return record

    # =================================================================
    # EXECUTAR (Playwright — apenas Mov581)
    # =================================================================
    def executar(self, record: MovimentacaoRecord) -> bool:
        """Executa a movimentação no Projudi via Playwright.

        FLUXO (simplificado — sem CumprimentoCartorio):
          1. Abre MovimentarProcesso
          2. Injeta código 581 (TD - Tipo Documental)
          3. Preenche descrição e observação
          4. Clica Concluir
          5. Verifica sucesso
        """
        from playwright.sync_api import sync_playwright

        # Pega sessão com cookies
        result = self.projudi_service._get_session_from_cookies()
        if not result:
            self._log(record, 'erro', 'Sessão do Projudi não disponível.')
            record.status = 'falha'
            record.save(update_fields=['status'])
            return False

        _, cookies_dict = result

        # Descobre número Projudi
        proc_projudi = self._extrair_numero_projudi(record)
        if not proc_projudi:
            self._log(record, 'erro', 'Número Projudi não encontrado.')
            record.status = 'falha'
            record.save(update_fields=['status'])
            return False

        self._log(record, 'execucao',
                  f"Iniciando Mov581 para {record.act_verb}...")
        record.status = 'processando'
        record.save(update_fields=['status'])

        sucesso = False
        try:
            with sync_playwright() as pw:
                browser = pw.firefox.launch(headless=False, slow_mo=500)
                ctx_b = browser.new_context(
                    viewport={'width': 1500, 'height': 950}, locale='pt-BR')
                ctx_b.add_cookies([
                    {'name': k, 'value': v,
                     'domain': 'projudi.tjba.jus.br', 'path': '/'}
                    for k, v in cookies_dict.items()
                ])
                page = ctx_b.new_page()

                # PASSO 1: Abrir MovimentarProcesso
                url_mov = (
                    'https://projudi.tjba.jus.br/projudi/movimentacao/'
                    f'MovimentarProcesso?numeroProcesso={proc_projudi}'
                )
                page.goto(url_mov, wait_until='networkidle')
                time.sleep(2)

                # Verifica se o formulário carregou
                tem_form = page.evaluate(
                    '!!document.getElementById("seqCategoriaMovimentacao")')
                if not tem_form:
                    if 'expirou' in page.title().lower():
                        self._log(record, 'erro', 'Sessão expirou durante execução.')
                    else:
                        self._log(record, 'erro',
                                  'Formulário MovimentarProcesso não carregou.')
                    browser.close()
                    record.status = 'falha'
                    record.save(update_fields=['status'])
                    return False

                # PASSO 2: Injetar código da movimentação (do registro ou padrão 581)
                cod_mov = record.codigo_movimentacao or '581'
                desc_mov = record.descricao_movimentacao or 'Cumprimento de Decisão'
                page.evaluate(f'''() => {{
                    var camp = document.getElementById('seqCategoriaMovimentacao');
                    if (camp) camp.value = '{cod_mov}';
                    var desc = document.getElementById('descCategoriaMovimentacao');
                    if (desc) desc.value = '{desc_mov}';
                    var tr = document.getElementById('trTipoDocumento');
                    if (tr) tr.style.display = 'none';
                }}''')
                time.sleep(1)

                # PASSO 3: Preencher observação
                obs_texto = record.observacao or f"Cumprimento de {record.act_verb}"
                if record.parte_nome:
                    obs_texto += f" — {record.parte_nome}"
                page.fill('#observacao', obs_texto[:500])
                time.sleep(0.5)

                # PASSO 4: Clicar Concluir
                page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                time.sleep(0.5)
                page.click('#Concluir')
                time.sleep(4)

                # Tratar alerta se aparecer
                try:
                    alert = page.wait_for_event('dialog', timeout=5000)
                    self._log(record, 'info', f'Alerta: {alert.message}')
                    alert.accept()
                    time.sleep(3)
                except Exception:
                    pass

                # PASSO 5: Verificar sucesso
                html_check = page.content()
                url_final = page.url
                record.url_movimentacao = url_final

                if any(k in html_check.lower() for k in
                       ['movimentação incluída', 'movimentacao incluida',
                        'operação realizada', 'operacao realizada',
                        'dados gravados', 'redirect']):
                    sucesso = True
                    self._log(record, 'execucao',
                              f"✅ Mov581 concluída. URL: {url_final}")
                elif 'DadosProcesso' in url_final or 'Historico' in url_final:
                    sucesso = True
                    self._log(record, 'execucao',
                              f"✅ Redirecionado ao processo. Mov581 concluída.")
                else:
                    self._log(record, 'erro',
                              f"Mov581 pode não ter sido registrada. "
                              f"URL final: {url_final}",
                              {'html_snippet': html_check[:500]})

                browser.close()

        except Exception as e:
            self._log(record, 'erro', f'Erro no Playwright: {str(e)[:200]}')
            import traceback
            traceback.print_exc()

        record.status = 'cumprido' if sucesso else 'falha'
        record.save(update_fields=['status', 'url_movimentacao'])

        if sucesso:
            self._log(record, 'execucao',
                      f"Movimentação cumprida com sucesso.")
        return sucesso

    def _extrair_numero_projudi(self, record: MovimentacaoRecord) -> Optional[str]:
        """Extrai o número Projudi da URL do processo."""
        import re
        from urllib.parse import urlparse, parse_qs

        projudi_url = record.url_processo or ''
        m = re.search(r'numeroProcesso=(\d+)', projudi_url)
        if m:
            return m.group(1)

        # Fallback: busca no Projudi
        if record.numero_processo_cnj:
            result = self.projudi_service._get_session_from_cookies()
            if result:
                session = result[0]
                busca_url = (
                    'https://projudi.tjba.jus.br/projudi/processo/consultaProcesso')
                r = session.post(busca_url,
                                 data={'numeroProcesso': record.numero_processo_cnj},
                                 timeout=15)
                if r.status_code == 200:
                    qs = parse_qs(urlparse(r.url).query)
                    return qs.get('numeroProcesso', [None])[0]
        return None

    # =================================================================
    # DISPENSAR
    # =================================================================
    def dispensar(self, record: MovimentacaoRecord) -> Dict:
        record.status = 'dispensado'
        record.save(update_fields=['status'])
        self._log(record, 'info',
                  f"Movimentação dispensada por {self.user.full_name}.")
        return {'dispensado': True, 'record': record}

    # =================================================================
    # LOGS
    # =================================================================
    def criar_log(self, record: MovimentacaoRecord, tipo: str, mensagem: str,
                  detalhes: dict = None):
        MovimentacaoLog.objects.create(
            movimentacao=record,
            tipo=tipo,
            mensagem=mensagem,
            detalhes=detalhes or {},
        )

    def _log(self, record, tipo, mensagem, detalhes=None):
        self.criar_log(record, tipo, mensagem, detalhes)

    def logs_humanizados(self, record: MovimentacaoRecord) -> List[Dict]:
        return list(
            MovimentacaoLog.objects.filter(movimentacao=record)
            .values('tipo', 'mensagem', 'created_at')
            .order_by('-created_at')
        )

    # =================================================================
    # BATCH
    # =================================================================
    def processar_fila(self, records: List[MovimentacaoRecord]) -> Dict:
        cumpridos = 0
        falhas = 0
        for rec in records:
            if rec.status not in ('pendente', 'falha'):
                continue
            try:
                if self.executar(rec):
                    cumpridos += 1
                else:
                    falhas += 1
            except Exception as e:
                rec.status = 'falha'
                rec.save(update_fields=['status'])
                self._log(rec, 'erro', str(e)[:200])
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
