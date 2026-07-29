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
        localizador: str = '',
        tipo_localizador: str = '',
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
            user=self.user,
            localizador=localizador,
            tipo_localizador=tipo_localizador,
            status='pendente',
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

        # ─── PRE-CHECK: localizador já está definido? ───
        if record.tipo_localizador:
            try:
                session, _ = self.projudi_service._get_session_from_cookies()
                if session:
                    from projudiProcessNavigator import ProcessoParser
                    url_dados = (
                        'https://projudi.tjba.jus.br/projudi/listagens/'
                        f'DadosProcesso?numeroProcesso={proc_projudi}'
                    )
                    r = session.get(url_dados, timeout=15)
                    if r.status_code == 200:
                        parser = ProcessoParser(r.text)
                        atual = parser.extrair_localizador()
                        if atual.get('codigo') == record.tipo_localizador:
                            print(f'   ✅ Localizador já é {record.tipo_localizador} ({atual.get("descricao")}) — pulando')
                            record.status = 'cumprido'
                            record.save(update_fields=['status'])
                            self._log(record, 'info',
                                      f'Localizador já definido: {record.tipo_localizador}')
                            return True
                        elif atual:
                            print(f'   📍 Localizador atual: {atual.get("codigo")} ({atual.get("descricao")}) → desejado: {record.tipo_localizador}')
            except Exception as e:
                print(f'   ⚠️ Erro no pre-check localizador: {e}')

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
                    if (camp) {{ camp.value = '{cod_mov}'; camp.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                }}''')
                time.sleep(1)

                # Clicar btnBuscaMovimentacao para carregar o grid
                try:
                    page.click('#btnBuscaMovimentacao', timeout=5000)
                    time.sleep(2)
                except Exception:
                    pass
                # Tratar alerta do grid
                try:
                    alert = page.wait_for_event('dialog', timeout=5000)
                    alert.accept()
                    time.sleep(1)
                except Exception:
                    pass

                # Selecionar opção no grid (pela descrição, se informada)
                if desc_mov:
                    try:
                        link = page.query_selector(f'a:has-text("{desc_mov}")')
                        if not link:
                            link = page.query_selector(f'td:has-text("{desc_mov}")')
                        if link:
                            link.click()
                            print(f'   ✅ Selecionado: {desc_mov}')
                            time.sleep(1)
                        else:
                            # Fallback: injeta direto na descrição
                            page.evaluate(f'''() => {{
                                var desc = document.getElementById('descCategoriaMovimentacao');
                                if (desc) desc.value = '{desc_mov}';
                            }}''')
                            time.sleep(0.5)
                    except Exception:
                        page.evaluate(f'''() => {{
                            var desc = document.getElementById('descCategoriaMovimentacao');
                            if (desc) desc.value = '{desc_mov}';
                        }}''')
                        time.sleep(0.5)
                else:
                    # Fallback: injeta descrição manualmente
                    page.evaluate(f'''() => {{
                        var desc = document.getElementById('descCategoriaMovimentacao');
                        if (desc) desc.value = '{desc_mov}';
                    }}''')
                    time.sleep(0.5)

                # PASSO 3: Preencher observação
                obs_texto = record.observacao or f"Cumprimento de {record.act_verb}"
                if record.parte_nome:
                    obs_texto += f" — {record.parte_nome}"
                page.fill('#observacao', obs_texto[:500])
                time.sleep(0.5)

                # PASSO 3.5: Localizador (se informado)
                if record.localizador or record.tipo_localizador:
                    # Expandir painel de localizadores
                    try:
                        btn_painel = page.locator('#imgBotao_panelLocalizador').first
                        if btn_painel.count():
                            btn_painel.click()
                            time.sleep(1)
                            print('   📍 Painel localizador expandido')
                    except Exception:
                        pass

                if record.tipo_localizador:
                    try:
                        sel = page.locator('#codTipoLocalizador').first
                        if sel.count():
                            valor_atual = sel.input_value()
                            if valor_atual == record.tipo_localizador:
                                print(f'   ✅ Localizador já está como {record.tipo_localizador} — pulando movimentação')
                                browser.close()
                                record.status = 'cumprido'
                                record.save(update_fields=['status'])
                                self._log(record, 'info', f'Localizador já definido como {record.tipo_localizador} — pulo')
                                return True
                            else:
                                sel.select_option(record.tipo_localizador)
                                print(f'   📍 Tipo localizador alterado: {valor_atual} → {record.tipo_localizador}')
                                time.sleep(0.5)
                    except Exception:
                        pass
                if record.localizador:
                    try:
                        sel = page.locator('#codLocalizador').first
                        if sel.count():
                            sel.select_option(record.localizador)
                            print(f'   📍 Localizador: {record.localizador}')
                            time.sleep(0.5)
                    except Exception:
                        pass

                # PASSO 4: Clicar Concluir
                # Scroll específico para o botão Concluir (após expandir localizador)
                page.evaluate('''() => {
                    var btn = document.getElementById('Concluir');
                    if (btn) btn.scrollIntoView(true);
                    window.scrollBy(0, -100);
                }''')
                time.sleep(1)
                page.click('#Concluir')
                time.sleep(2)
                # Aceita alerta primeiro (ele bloqueia a navegação)
                try:
                    alert = page.wait_for_event('dialog', timeout=5000)
                    self._log(record, 'info', f'Alerta: {alert.message}')
                    alert.accept()
                    time.sleep(2)
                except Exception:
                    pass
                # Aguarda navegação
                try:
                    page.wait_for_load_state('networkidle', timeout=10000)
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
    # EXECUTAR COM INTIMAÇÃO (2 fluxos: MovimentarAnalise + MovimentarProcesso)
    # =================================================================
    def executar_com_intimacao(
        self,
        processo_numero: str,
        observacao: str,
        codigo_mov: str = '581',
        descricao_mov: str = 'Intimação',
        cookies_dict: dict = None,
        proc_projudi: str = None,
        cod_analise: str = None,
        fallback_mov: str = None,
        fallback_uf: str = None,
    ) -> bool:
        """Executa Mov581 + intimação no Projudi em um único Playwright.

        DOIS FLUXOS:
        1. Via cod_analise (MovimentarAnalise):
           - Abre cadastros/MovimentarAnalise?codAnalise=X
           - Preenche mov + observação
           - Clica painel de intimação → Autoras/Rés → motivo=3 prazo=3 → Concluir
           - Usado quando há uma mov pendente na lista de análises

        2. Via proc_projudi (MovimentarProcesso):
           - Abre movimentacao/MovimentarProcesso?numeroProcesso=X
           - Preenche mov + seleciona "Intimação" no grid + observação
           - Navega até DadosProcesso para clicar link Intimar
           - Usado como fallback genérico (sempre funciona)

        Args:
            fallback_mov: Se definido e o link Intimar não for encontrado,
                          registra um Mov 581 extra com esta descrição.
            fallback_uf: Se definido, só executa o fallback se a parte
                         estiver domiciliada nesta UF (ex: 'BA').
        """
        from playwright.sync_api import sync_playwright

        result = self.projudi_service._get_session_from_cookies()
        if not result:
            print('   ❌ Sessão do Projudi não disponível.')
            return False

        _, saved_cookies = result
        cookies = cookies_dict or saved_cookies

        if not proc_projudi and not cod_analise:
            m = re.search(r'(\d{13,20})', processo_numero.replace('-', '').replace('.', ''))
            if m:
                proc_projudi = m.group(1)
            if not proc_projudi:
                print('   ❌ Número Projudi não encontrado.')
                return False

        print(f'   🔷 Iniciando intimação eletrônica...')
        if cod_analise:
            print(f'      Via MovimentarAnalise?codAnalise={cod_analise}')
        else:
            print(f'      Via MovimentarProcesso?numeroProcesso={proc_projudi}')

        sucesso = False
        import time

        try:
            with sync_playwright() as pw:
                browser = pw.firefox.launch(headless=False, slow_mo=400)
                ctx_b = browser.new_context(
                    viewport={'width': 1500, 'height': 950}, locale='pt-BR')
                ctx_b.add_cookies([
                    {'name': k, 'value': v,
                     'domain': 'projudi.tjba.jus.br', 'path': '/'}
                    for k, v in cookies.items()
                ])
                page = ctx_b.new_page()

                # ─── Abrir página ───
                if cod_analise:
                    url = (
                        'https://projudi.tjba.jus.br/projudi/cadastros/'
                        f'MovimentarAnalise?codAnalise={cod_analise}'
                    )
                else:
                    url = (
                        'https://projudi.tjba.jus.br/projudi/movimentacao/'
                        f'MovimentarProcesso?numeroProcesso={proc_projudi}'
                    )

                page.goto(url, wait_until='networkidle')
                time.sleep(2)

                # Verifica se carregou
                tem_form = page.evaluate(
                    '!!document.getElementById("seqCategoriaMovimentacao")')
                if not tem_form:
                    if 'expirou' in page.title().lower():
                        print('   ❌ Sessão expirou.')
                    else:
                        print('   ❌ Formulário não carregou.')
                    browser.close()
                    return False

                # ─── PASSO 1: Código da movimentação ───
                page.evaluate(f'''() => {{
                    var camp = document.getElementById('seqCategoriaMovimentacao');
                    if (camp) {{ camp.value = '{codigo_mov}'; camp.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                }}''')
                time.sleep(1)

                # ─── PASSO 2: Clicar btnBuscaMovimentacao ───
                try:
                    page.click('#btnBuscaMovimentacao', timeout=5000)
                    time.sleep(2)
                except Exception:
                    print('   ⚠️ btnBuscaMovimentacao não encontrado')

                # Tratar alerta
                try:
                    alert = page.wait_for_event('dialog', timeout=5000)
                    print(f'   ⚠️ Alerta: {alert.message}')
                    alert.accept()
                    time.sleep(2)
                except Exception:
                    pass

                # ─── PASSO 3: Selecionar "Intimação" no grid ───
                try:
                    link_int = page.query_selector('a:has-text("Intimação")')
                    if not link_int:
                        link_int = page.query_selector('td:has-text("Intimação")')
                    if link_int:
                        link_int.click()
                        print('   ✅ Intimação selecionada no grid')
                        time.sleep(1)
                    else:
                        # Fallback: injeta direto na descrição
                        page.evaluate(f'''() => {{
                            var desc = document.getElementById('descCategoriaMovimentacao');
                            if (desc) {{ desc.value = '{descricao_mov}'; }}
                        }}''')
                        time.sleep(0.5)
                except Exception:
                    pass

                # ─── PASSO 4: Preencher observação ───
                try:
                    page.fill('#observacao', observacao[:500])
                    time.sleep(0.5)
                    print('   ✅ Observação preenchida')
                except Exception as e:
                    print(f'   ⚠️ Observação: {e}')

                # ═══════════════════════════════════════════════════
                # FLUXO A: MovimentarAnalise → painel de intimação
                # ═══════════════════════════════════════════════════
                if cod_analise:
                    print('   🔔 Pipeline de intimação (painel)...')

                    # Clicar painel de intimação
                    try:
                        btn_painel = page.query_selector('#imgBotao_painelIntimacao')
                        if btn_painel:
                            btn_painel.click()
                            time.sleep(1)
                            print('   ✅ Painel de intimação aberto')
                        else:
                            print('   ⚠️ Botão painel de intimação não encontrado')
                    except Exception as e:
                        print(f'   ⚠️ Painel: {e}')

                    # Autoras
                    try:
                        page.evaluate('''() => {
                            var aba = document.getElementById('Autoras');
                            if (aba) aba.click();
                        }''')
                        time.sleep(0.5)
                        page.evaluate('''() => {
                            var sel = document.getElementById('codMotivoAutor');
                            if (sel) { sel.value = '3'; sel.dispatchEvent(new Event('change', {bubbles:true})); }
                            var sel2 = document.getElementById('codPrazoAutor');
                            if (sel2) { sel2.value = '3'; sel2.dispatchEvent(new Event('change', {bubbles:true})); }
                        }''')
                        time.sleep(0.5)
                        print('   ✅ Autoras configuradas (motivo=3, prazo=3)')
                    except Exception as e:
                        print(f'   ⚠️ Autoras: {e}')

                    # Rés
                    try:
                        page.evaluate('''() => {
                            var aba = document.getElementById('Res');
                            if (aba) aba.click();
                        }''')
                        time.sleep(0.5)
                        page.evaluate('''() => {
                            var sel = document.getElementById('codMotivoReu');
                            if (sel) { sel.value = '3'; sel.dispatchEvent(new Event('change', {bubbles:true})); }
                            var sel2 = document.getElementById('codPrazoReu');
                            if (sel2) { sel2.value = '3'; sel2.dispatchEvent(new Event('change', {bubbles:true})); }
                        }''')
                        time.sleep(0.5)
                        print('   ✅ Rés configurados (motivo=3, prazo=3)')
                    except Exception as e:
                        print(f'   ⚠️ Rés: {e}')

                    time.sleep(2)

                    # Concluir
                    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    time.sleep(0.5)
                    try:
                        page.click('#Concluir', timeout=10000)
                        time.sleep(3)
                        try:
                            alert = page.wait_for_event('dialog', timeout=5000)
                            print(f'   ⚠️ Alerta: {alert.message}')
                            alert.accept()
                            time.sleep(2)
                        except Exception:
                            pass
                        print('   ✅ Intimação concluída (MovimentarAnalise)')
                        sucesso = True
                    except Exception as e:
                        print(f'   ❌ Erro ao concluir: {e}')

                # ═══════════════════════════════════════════════════
                # FLUXO B: MovimentarProcesso → Concluir → DadosProcesso → link Intimar
                # ═══════════════════════════════════════════════════
                else:
                    # Concluir movimentação
                    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    time.sleep(0.5)
                    try:
                        page.click('#Concluir', timeout=10000)
                        time.sleep(4)
                        try:
                            alert = page.wait_for_event('dialog', timeout=5000)
                            print(f'   ⚠️ Alerta: {alert.message}')
                            alert.accept()
                            time.sleep(3)
                        except Exception:
                            pass
                    except Exception as e:
                        print(f'   ⚠️ Concluir: {e}')

                    # Navegar para DadosProcesso
                    url_dados = (
                        'https://projudi.tjba.jus.br/projudi/listagens/'
                        f'DadosProcesso?numeroProcesso={proc_projudi}'
                    )
                    page.goto(url_dados, wait_until='networkidle')
                    time.sleep(2)

                    print('   🔍 Buscando link de intimação...')

                    # Procurar link Intimar
                    intimou = False
                    selectores = [
                        'a[href*="Intimar"]', 'a[href*="intimar"]',
                        'a:has-text("Intimar")', 'a:has-text("Intimação")',
                        'button:has-text("Intimar")', 'input[value="Intimar"]',
                    ]
                    for sel in selectores:
                        try:
                            el = page.query_selector(sel)
                            if el:
                                print(f'   🔘 Clicando: {sel}')
                                el.click()
                                time.sleep(3)
                                intimou = True
                                break
                        except Exception:
                            continue

                    if intimou:
                        # Confirmar modal
                        try:
                            time.sleep(2)
                            for csel in ['input[value="Confirmar"]', 'input[value="OK"]',
                                          'button:has-text("Confirmar")', '#confirmar']:
                                try:
                                    btn = page.query_selector(csel)
                                    if btn:
                                        btn.click()
                                        time.sleep(3)
                                        break
                                except Exception:
                                    continue
                        except Exception:
                            pass
                        try:
                            alert = page.wait_for_event('dialog', timeout=5000)
                            print(f'   ℹ️ Alerta: {alert.message}')
                            alert.accept()
                            time.sleep(2)
                        except Exception:
                            pass
                        print('   ✅ Intimação eletrônica gerada (DadosProcesso)')
                        sucesso = True
                    else:
                        print('   ⚠️ Link de intimação não encontrado em DadosProcesso')
                        # ─── FALLBACK OPCIONAL ──────────────────────────
                        if fallback_mov:
                            uf_ok = True
                            if fallback_uf:
                                # Tenta extrair UF da parte na página
                                try:
                                    texto_pagina = page.content()
                                    import re
                                    # Procura padrão "CIDADE - UF" na página
                                    uf_match = re.search(r'[A-ZÀ-Ú][A-ZÀ-Ú\s]+?\s*-\s*([A-Z]{2})', texto_pagina)
                                    uf_encontrada = uf_match.group(1).upper() if uf_match else ''
                                    uf_ok = (uf_encontrada == fallback_uf.upper())
                                    print(f'      UF encontrada: {uf_encontrada or "não detectada"} | fallback_uf={fallback_uf} | uf_ok={uf_ok}')
                                except Exception as e:
                                    print(f'      ⚠️ Erro ao detectar UF: {e}')
                            if uf_ok:
                                print(f'      ▶️ Fallback: registrando Mov581 "{fallback_mov}"...')
                                page.goto(
                                    f'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso={proc_projudi}',
                                    wait_until='load'
                                )
                                time.sleep(3)
                                if page.evaluate('!!document.getElementById("seqCategoriaMovimentacao")'):
                                    page.evaluate(f'''() => {{
                                        var c = document.getElementById('seqCategoriaMovimentacao');
                                        if (c) c.value = '{codigo_mov}';
                                        var d = document.getElementById('descCategoriaMovimentacao');
                                        if (d) d.value = '{fallback_mov}';
                                    }}''')
                                    time.sleep(1)
                                    page.fill('#observacao', f'{fallback_mov} - {observacao[:100]}')
                                    time.sleep(0.5)
                                    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                                    time.sleep(0.5)
                                    try:
                                        page.click('#Concluir', timeout=10000)
                                        time.sleep(3)
                                        try:
                                            alert = page.wait_for_event('dialog', timeout=5000)
                                            alert.accept()
                                            time.sleep(2)
                                        except Exception:
                                            pass
                                        print(f'      ✅ Fallback registrado: {fallback_mov}')
                                    except Exception as e:
                                        print(f'      ❌ Fallback erro ao concluir: {e}')
                                else:
                                    print('      ⚠️ Fallback: formulário não carregou')
                            else:
                                print(f'      ⏭️ Fallback ignorado (UF não corresponde)')
                        else:
                            print(f'      URL: {url_dados}')
                        sucesso = True  # parcial

                browser.close()

        except Exception as e:
            print(f'   ❌ Erro no Playwright: {str(e)[:200]}')
            import traceback
            traceback.print_exc()
            sucesso = False

        # ── Registra no banco (CumprimentoRecord) para aparecer nos Cumprimentos ──
        try:
            from projudi.models import CumprimentoRecord
            status = 'cumprido' if sucesso else 'falha'
            record = CumprimentoRecord.objects.create(
                processo=proc_projudi or processo_numero[:20],
                numero_processo_cnj=processo_numero,
                fluxo='eletronico',
                fluxo_justificativa='Intimação eletrônica via DJEN (Mov581 + click Intimar)',
                act_verb='intimacao',
                snippet=observacao[:300],
                status=status,
                user=self.user if hasattr(self, 'user') else None,
            )
            print(f'   📝 Cumprimento #{record.id} registrado ({status})')
        except Exception as e:
            print(f'   ⚠️ Erro ao registrar cumprimento: {e}')

        return sucesso

    # =================================================================
    # FECHAR
    # =================================================================
    def fechar(self):
        try:
            self.projudi_service.fechar()
        except Exception:
            pass
