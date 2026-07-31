"""MovimentacaoService — Executa movimentações internas no Projudi (Mov581).

Análogo a MandadoService / OficioService.
Diferença: em vez de expedir documentos (CumprimentoCartorio + FCKeditor),
apenas registra o cumprimento via Mov581 (preencher observação + Concluir).
"""

import sys
import os
import re
import time
from typing import List, Dict, Optional, Tuple
from datetime import datetime, date

from django.conf import settings

PROJECT_ROOT = str(settings.BASE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from .models import MovimentacaoRecord, MovimentacaoLog

# Código do localizador → descrição (para pre-check por conteúdo —
# localizadores compostos tipo "AGUARDAR ASSINAR; PESQUISA DE ENDEREÇO")
# WSLg: sem renderização por software o Firefox do Playwright abre a janela
# EM BRANCO (só o ícone "pinguim") — o usuário não vê a assinatura pra clicar.
_FIREFOX_ENV = {**os.environ, 'MOZ_DISABLE_GPU_SANDBOX': '1',
                'LIBGL_ALWAYS_SOFTWARE': '1'}
_FIREFOX_PREFS = {'gfx.webrender.software': True}

LOCALIZADORES_POR_CODIGO = {
    '9376': 'PESQUISA DE ENDEREÇO',
    '22614': 'SISBAJUD',
    '9205': 'AGUARDAR CUMPRIR TRANSAÇÃO',
    '30586': 'AGUARDAR DISTRIBUIÇÃO',
    '15286': 'AGUARDAR DECURSO DO PRAZO',
    '14396': 'AGUARDAR RETORNO DE AR',
    '11916': 'RENAJUD',
    '24012': 'SERASAJUD',
    '22644': 'SNIPER',
    '10248': 'CERTIFICAÇÃO TRANSITO EM JULGADO',
}
from .services import ProjudiService


class MovimentacaoService:
    """Serviço de orquestração de movimentações internas."""

    def __init__(self, user):
        self.user = user
        self.projudi_service = ProjudiService(user)

    def _localizador_ja_definido(self, record, atual: dict) -> bool:
        """True se o localizador desejado já está definido no processo.

        Aceita igualdade exata do código OU o conteúdo da descrição dentro de
        um localizador composto (ex: 'AGUARDAR ASSINAR CP; PESQUISA DE ENDEREÇO').
        """
        if not atual:
            return False
        if atual.get('codigo') == record.tipo_localizador:
            return True
        desc = LOCALIZADORES_POR_CODIGO.get(record.tipo_localizador, '')
        if desc and desc in (atual.get('descricao') or '').upper():
            return True
        return False

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
        """Executa a movimentação no Projudi via Playwright (+ fallback requests).

        FLUXO:
          1. Abre MovimentarProcesso
          2. Injeta código (581 = grid+TD, 11383 = direto sem grid)
          3. Preenche observação + cumprimento + localizador
          4. Clica Concluir (com 3 tentativas: click normal → JS dispatch → POST direto)
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
                        if self._localizador_ja_definido(record, atual):
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
                browser = pw.firefox.launch(headless=False, slow_mo=500,
                                            env=_FIREFOX_ENV, firefox_user_prefs=_FIREFOX_PREFS)
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

                if cod_mov == '11383':
                    # 11383 (Cumprimento de Ofício) — não precisa de grid
                    # Só injeta a descrição direto
                    page.evaluate(f'''() => {{
                        var desc = document.getElementById('descCategoriaMovimentacao');
                        if (desc) {{ desc.value = '{desc_mov}'; desc.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                    }}''')
                    time.sleep(1)
                    print(f'   ✅ Código 11383 injetado: {desc_mov}')
                else:
                    # Código 581 (TD) — precisa abrir grid e selecionar documento
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
                        page.evaluate(f'''() => {{
                            var desc = document.getElementById('descCategoriaMovimentacao');
                            if (desc) desc.value = '{desc_mov}';
                        }}''')
                        time.sleep(0.5)

                    # Solicitar expedição: Tipo Documento = 51 (Mandado) é obrigatório
                    if record.act_verb == 'solicitar_expedicao':
                        try:
                            sel_tipo = page.locator('select[name="codTipoDocumento"]')
                            if sel_tipo.count():
                                sel_tipo.select_option('51')
                                print('   ✅ Tipo Documento: 51 (Mandado)')
                                time.sleep(0.5)
                        except Exception as e:
                            print(f'   ⚠️ Tipo Documento: {e}')

                # PASSO 3: Preencher observação
                obs_texto = record.observacao or f"Cumprimento de {record.act_verb}"
                if record.parte_nome:
                    obs_texto += f" — {record.parte_nome}"
                page.fill('#observacao', obs_texto[:500])
                time.sleep(0.5)

                # PASSO 3.2: Adicionar cumprimento (obrigatório para Concluir)
                try:
                    page.locator("a:text('Cumprimento')").first.click()
                    time.sleep(0.5)
                    # Solicitar expedição: configurar linha de MANDADO antes do
                    # btnAddCumprimento (tipoCumprimento=4, subtipo=3, destinatário)
                    # — sem isso o grid exige prazo de Autor/Testemunha e o
                    # tipo de documento fica pendente na validação.
                    if record.act_verb == 'solicitar_expedicao':
                        try:
                            page.select_option('#tipoCumprimento', '4')
                            time.sleep(0.3)
                            st = page.locator(
                                '#subtipoCumprimento, select[name="subtipoCumprimento"]').first
                            if st.count():
                                st.select_option('3')
                                time.sleep(0.3)
                            if record.parte_nome:
                                # Parte pode ter vários nomes ("NOME1 / NOME2"):
                                # seleciona TODOS no campo destinatário
                                nomes = [n.strip() for n in
                                         re.split(r'\s*/\s*', record.parte_nome) if n.strip()]
                                valores = []
                                for nome in nomes:
                                    try:
                                        opt = page.locator(
                                            f'#codigoDestinatario option:text("{nome}")').first
                                        if opt.count():
                                            valores.append(opt.get_attribute('value'))
                                    except Exception:
                                        pass
                                if valores:
                                    try:
                                        page.select_option('#codigoDestinatario', valores)
                                    except Exception:
                                        try:
                                            page.select_option('#codigoDestinatario', valores[0])
                                        except Exception:
                                            pass
                                    print(f'   ✅ Destinatário(s) ({len(valores)}): '
                                          f'{record.parte_nome[:60]}')
                                else:
                                    print(f'   ⚠️ Destinatário não encontrado no select: {record.parte_nome[:40]}')
                        except Exception as e:
                            print(f'   ⚠️ Setup mandado: {e}')
                    page.click('#btnAddCumprimento')
                    time.sleep(1)
                    print('   ✅ Cumprimento adicionado')
                except Exception as e:
                    print(f'   ⚠️ Cumprimento: {e}')

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
                                print(f'   📍 Localizador alterado: {record.tipo_localizador}')
                                time.sleep(0.5)
                            # Recolhe painel
                            try:
                                btn = page.locator('#imgBotao_panelLocalizador').first
                                if btn.count():
                                    btn.click()
                                    time.sleep(0.5)
                            except Exception:
                                pass
                    except Exception:
                        pass
                if record.localizador:
                    try:
                        sel = page.locator('#codLocalizador').first
                        if sel.count():
                            sel.select_option(record.localizador)
                            time.sleep(0.5)
                    except Exception:
                        pass

                # PASSO 4: Clicar Concluir
                time.sleep(1)
                page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                time.sleep(0.5)

                # Tenta clique normal no Concluir (input type=image)
                concluir_ok = False
                try:
                    # Usa locator com posição explícita para <input type="image">
                    btn_concluir = page.locator('#Concluir')
                    if btn_concluir.count():
                        btn_concluir.click(position={'x': 5, 'y': 5})
                        time.sleep(3)
                        # Aceita alerta (se houver)
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
                        # Verifica se navegou
                        url_apos = page.url
                        if 'DadosProcesso' in url_apos or 'Historico' in url_apos or 'movimentacao incluida' in page.content().lower():
                            concluir_ok = True
                except Exception:
                    pass

                if not concluir_ok:
                    # Fallback 1: Tenta via JavaScript submit com coordenadas
                    print('   ⚠️ Clique normal falhou, tentando submit via JS...')
                    try:
                        page.evaluate('''() => {
                            var concluir = document.getElementById('Concluir');
                            if (concluir) {
                                // Cria evento de clique com coordenadas
                                var rect = concluir.getBoundingClientRect();
                                var event = new MouseEvent('click', {
                                    bubbles: true,
                                    cancelable: true,
                                    clientX: rect.left + 5,
                                    clientY: rect.top + 5,
                                    button: 0
                                });
                                concluir.dispatchEvent(event);
                            }
                        }''')
                        time.sleep(3)
                        try:
                            alert = page.wait_for_event('dialog', timeout=5000)
                            alert.accept()
                            time.sleep(2)
                        except Exception:
                            pass
                        try:
                            page.wait_for_load_state('networkidle', timeout=10000)
                        except Exception:
                            pass
                        url_apos = page.url
                        if 'DadosProcesso' in url_apos or 'Historico' in url_apos or 'movimentacao incluida' in page.content().lower():
                            concluir_ok = True
                    except Exception:
                        pass

                if not concluir_ok:
                    # Fallback 2: Tenta submit direto via requests (extrai form HTML da página)
                    print('   ⚠️ JS submit falhou, tentando POST direto via requests...')
                    try:
                        html_form = page.content()
                        result_fb = self.projudi_service._get_session_from_cookies()
                        session_fb = result_fb[0] if result_fb else None
                        if session_fb:
                            ok_post, msg_post = self._submeter_via_requests(
                                session=session_fb,
                                html=html_form,
                                record=record,
                                proc_projudi=proc_projudi,
                            )
                            if ok_post:
                                concluir_ok = True
                                print(f'   ✅ POST direto funcionou: {msg_post}')
                            else:
                                print(f'   ⚠️ POST direto falhou: {msg_post}')
                    except Exception as e:
                        print(f'   ⚠️ Erro no POST direto: {e}')

                # PASSO 5: Verificar sucesso (executa sempre, mesmo se concluir_ok = False)
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
                elif concluir_ok:
                    # Se algum fallback funcionou mas a verificação normal não pegou
                    sucesso = True
                    self._log(record, 'execucao',
                              f"✅ Concluir acionado via fallback. URL: {url_final}")
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

    # =================================================================
    # EXECUTAR VIA REQUESTS (sem Playwright — ideal para 11383)
    # =================================================================
    def executar_requests(self, record: MovimentacaoRecord,
                           tipo_documento: str = 'CUMPRIMENTO',
                           envia_mp: bool = False,
                           cod_nucleo_mp: str = '31',
                           certidao_html: str = None) -> bool:
        """Executa movimentação via Playwright headless + submit via JavaScript.

        Args:
            record: MovimentacaoRecord com os dados da movimentação.
            tipo_documento: Rótulo do Tipo de Documento no select codTipoDocumento
                           (default 'CUMPRIMENTO' — genérico; ex: '9376' = PESQUISA DE ENDEREÇO).
            envia_mp: Se True, ativa Vistas ao MP.
            cod_nucleo_mp: Código do Núcleo (default '31' = Paulo Afonso).
            certidao_html: Se informado, insere documento certidão no FCKeditor
                          antes de Concluir (SelectArquivo + redigirTexto).

        FLUXO:
          1. Abre MovimentarProcesso via Playwright (headless)
          2. Injeta código, descrição
          3. [581] Mostra campos ocultos + btnBuscaMovimentacao + seleciona Tipo Documento
          4. [envia_mp] Expande painel envio órgão externo + marca enviaMP + seleciona Núcleo
          5. Preenche observação
          6. Ativa Cumprimento + btnAddCumprimento
          7. Configura localizador
          8. Submete o form via JavaScript com Concluir.x/y
          9. Verifica redirect / mensagem de sucesso
          9. Fecha browser

        Tudo no mesmo contexto do browser — sem risco de token mismatch.
        """
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
                  f"Iniciando execução (Playwright + JS submit) para {record.act_verb}...")
        record.status = 'processando'
        record.save(update_fields=['status'])

        # ─── PRE-CHECK: localizador já está definido? ───
        session, _ = result
        if record.tipo_localizador:
            try:
                url_dados = (
                    'https://projudi.tjba.jus.br/projudi/listagens/'
                    f'DadosProcesso?numeroProcesso={proc_projudi}'
                )
                r = session.get(url_dados, timeout=15)
                if r.status_code == 200:
                    from projudiProcessNavigator import ProcessoParser
                    parser = ProcessoParser(r.text)
                    atual = parser.extrair_localizador()
                    if self._localizador_ja_definido(record, atual):
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
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.firefox.launch(headless=False, slow_mo=500,
                                            env=_FIREFOX_ENV, firefox_user_prefs=_FIREFOX_PREFS)
                ctx_b = browser.new_context(
                    viewport={'width': 1500, 'height': 950}, locale='pt-BR')
                ctx_b.add_cookies([
                    {'name': k, 'value': v,
                     'domain': 'projudi.tjba.jus.br', 'path': '/'}
                    for k, v in cookies_dict.items()
                ])
                page = ctx_b.new_page()

                # Abre MovimentarProcesso
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
                    self._log(record, 'erro', 'Formulário MovimentarProcesso não carregou.')
                    browser.close()
                    record.status = 'falha'
                    record.save(update_fields=['status'])
                    return False

                # ─── PASSO 1: Mostrar campos ocultos (necessários para Cumprimento) ──
                page.evaluate('''() => {
                    var tr = document.getElementById('trTipoDocumento');
                    if (tr) tr.style.display = 'table-row';
                    var div = document.getElementById('rowDadosMovimentacaoComplemento');
                    if (div) div.style.display = 'block';
                    var p = document.getElementById('divPanelCumprimento');
                    if (p) p.style.display = 'block';
                }''')
                time.sleep(0.5)

                cod_mov = record.codigo_movimentacao or '581'
                desc_mov = record.descricao_movimentacao or (
                    'Cumprimento de Oficio' if cod_mov == '11383' else 'TD - Tipo Documental')

                # ─── PASSO 2: Cumprimento + btnAddCumprimento (obrigatório) ──
                # Ativa o grid MP para que os campos de documento fiquem disponíveis
                try:
                    page.locator("a:text('Cumprimento')").first.click()
                    time.sleep(0.5)
                    page.click('#btnAddCumprimento')
                    time.sleep(1)
                    print('   ✅ Cumprimento ativado')
                except Exception as e:
                    print(f'   ⚠️ Cumprimento: {e}')

                # ─── PASSO 3: Inserir Documento (certidão) — ANTES do código ──
                if certidao_html:
                    try:
                        radio = page.locator('input[name="SelectArquivo"][value="DigitarTexto"]')
                        if radio.count():
                            radio.check()
                            print('   ✅ SelectArquivo: DigitarTexto')
                            time.sleep(0.5)
                    except Exception:
                        pass

                    try:
                        sel_desc = page.locator('select[name="codDescricao1"]')
                        if sel_desc.count():
                            sel_desc.select_option('37')
                            print('   ✅ Tipo doc: Certidão (37)')
                            time.sleep(0.5)
                    except Exception:
                        pass

                    try:
                        campo_desc = page.locator('input[name="descricao"]')
                        if campo_desc.count():
                            campo_desc.fill('Certidão Criminal - art. 76 Lei 9.099/95')
                            time.sleep(0.3)
                    except Exception:
                        pass

                    # Clica redigirTexto → navega para FCKeditor
                    try:
                        with page.expect_navigation(timeout=15000):
                            link = page.locator('a[href*="redigirTexto"]')
                            if link.count():
                                link.first.click()
                            else:
                                page.evaluate('redigirTexto()')
                        time.sleep(3)
                        print(f'   ✅ FCKeditor aberto: {page.url[:100]}')
                    except Exception as e:
                        print(f'   ⚠️ redigirTexto: {e}')
                        try:
                            page.evaluate('document.forms[0].submit()')
                            time.sleep(3)
                        except Exception:
                            pass

                    # Seta HTML no FCKeditor — tenta API, fallback Source button
                    try:
                        result = page.evaluate('''(html) => {
                            // Tenta API direta (frame principal)
                            try {
                                var oEditor = FCKeditorAPI.GetInstance('FCKeditor1');
                                oEditor.SetHTML(html);
                                return 'OK:API';
                            } catch(e) {}
                            // Tenta parent
                            try {
                                var oEditor2 = window.parent.FCKeditorAPI.GetInstance('FCKeditor1');
                                oEditor2.SetHTML(html);
                                return 'OK:parent';
                            } catch(e2) {}
                            // Fallback: clica Source, seta textarea, volta
                            try {
                                var fckFrame = document.getElementById('FCKeditor1___Frame');
                                if (fckFrame) {
                                    var doc = fckFrame.contentDocument || fckFrame.contentWindow.document;
                                    // Procura botão Source (último da toolbar)
                                    var btns = doc.querySelectorAll('td.ToolbarActive');
                                    if (btns.length > 0) {
                                        btns[btns.length-1].click(); // Source
                                        setTimeout(function() {
                                            var ta = doc.getElementById('eEditorField');
                                            if (ta) { ta.value = html; }
                                            btns[btns.length-1].click(); // Volta
                                        }, 200);
                                    }
                                }
                                return 'OK:source_click';
                            } catch(e3) {}
                            return 'Erro: todas falharam';
                        }''', certidao_html)
                        print(f'   ✅ FCKeditor: {result}')
                        time.sleep(1)
                    except Exception as e:
                        print(f'   ⚠️ FCKeditor: {e}')

                    # Submeter
                    try:
                        btn_sub = page.locator('input[value="Submeter"]')
                        if btn_sub.count():
                            btn_sub.first.click()
                            time.sleep(2)
                            print('   ✅ Submeter')
                    except Exception:
                        pass

                    # Tenta assinar automaticamente (só se tiver senha)
                    senha = getattr(self.user, 'projudi_password', None)
                    max_espera_form = 10  # c/ senha: detecção rápida (20s)
                    if senha:
                        # Assinar 1ª
                        try:
                            page.locator('img[src*="bot-assinar"]').first.click()
                            time.sleep(1)
                            print('   ✅ Assinar 1ª')
                        except Exception:
                            pass
                        # Senha
                        try:
                            camp_senha = page.locator('input[name="senha"]')
                            if camp_senha.count() and senha:
                                camp_senha.fill(senha)
                                time.sleep(0.5)
                                print('   ✅ Senha')
                        except Exception:
                            pass
                        # Assinar 2ª
                        try:
                            page.locator('img[src*="bot-assinar"]').first.click()
                            time.sleep(2)
                            print('   ✅ Assinar 2ª')
                        except Exception:
                            pass
                    else:
                        # Assinatura salva no Projudi (só precisa CLICAR):
                        # tenta clique direto no Assinar. Se aparecer campo de
                        # senha (assinatura não salva), cai no modo manual.
                        print('   ⏳ Assinatura: tentando clique automático no Assinar...')
                        try:
                            page.locator('img[src*="bot-assinar"]').first.click()
                            time.sleep(1.5)
                            print('   ✅ Assinar (clique automático)')
                        except Exception:
                            pass
                        tem_senha = False
                        try:
                            camp_senha = page.locator('input[name="senha"]')
                            tem_senha = camp_senha.count() > 0 and camp_senha.first.is_visible()
                        except Exception:
                            tem_senha = False
                        if tem_senha:
                            print('   ⏳ Campo senha apareceu — ASSINE MANUALMENTE no navegador')
                            print('   ⏳ Digite a senha e clique em Assinar — aguardo até 3 min pelo retorno ao formulário')
                            # Rola até o campo senha / botão Assinar (o usuário não
                            # consegue scroll manual confiável no Firefox do Playwright)
                            try:
                                page.evaluate('''() => {
                                    var alvo = document.querySelector('input[name="senha"]') ||
                                               document.querySelector('img[src*="bot-assinar"]') ||
                                               document.querySelector('input[value="Assinar"]');
                                    window.scrollTo(0, document.body.scrollHeight);
                                    if (alvo) { alvo.scrollIntoView({block:'center'}); }
                                }''')
                                time.sleep(0.8)
                                print('   📜 Rolado até o campo de assinatura')
                            except Exception:
                                pass
                            # Screenshot do estado atual (assinatura?) pra debug
                            try:
                                page.screenshot(path='/tmp/certidao_assinatura.png')
                                print('   📸 Screenshot: /tmp/certidao_assinatura.png')
                            except Exception:
                                pass
                            if sys.stdout.isatty():
                                try:
                                    input('   🔄 Pressione Enter APÓS assinar (ou aguarde a detecção automática)...')
                                except Exception:
                                    pass
                            max_espera_form = 90  # 90 x 2s = 3 min pra assinatura manual
                        else:
                            print('   ✅ Assinatura direta (sem campo senha — salva no Projudi)')
                            max_espera_form = 20

                    # O Submeter do DigitarTexto re-renderiza a PRÓPRIA página
                    # como formulário de movimentação (URL continua DigitarTexto,
                    # mas o conteúdo é o MovimentarProcesso com o documento já
                    # anexado). Detectar pelo CONTEÚDO, não pela URL.
                    form_ok = False
                    for _ in range(max_espera_form):
                        try:
                            page.wait_for_load_state('networkidle', timeout=5000)
                        except Exception:
                            pass
                        try:
                            form_ok = page.evaluate(
                                '!!document.getElementById("seqCategoriaMovimentacao")')
                        except Exception:
                            form_ok = False
                        if form_ok:
                            print('   ✅ De volta ao formulário de movimentação (certidão anexada)')
                            break
                        print(f'   ⏳ Aguardando formulário... {page.url[:60]}')
                        time.sleep(2)
                    time.sleep(1)
                    if not form_ok:
                        print(f'   ⚠️ Pós-certidão sem formulário de movimentação: {page.url}')

                # ─── PASSO 4: Injeta código da movimentação ──
                page.evaluate(f'''() => {{
                    var camp = document.getElementById('seqCategoriaMovimentacao');
                    if (camp) {{ camp.value = '{cod_mov}'; camp.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                }}''')
                time.sleep(0.5)

                if cod_mov == '11383':
                    page.evaluate(f'''() => {{
                        var desc = document.getElementById('descCategoriaMovimentacao');
                        if (desc) {{ desc.value = '{desc_mov}'; desc.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                    }}''')
                    time.sleep(0.5)
                else:
                    # btnBuscaMovimentacao + seleciona Tipo Documento
                    try:
                        page.click('#btnBuscaMovimentacao', timeout=5000)
                        time.sleep(2)
                        try:
                            alert = page.wait_for_event('dialog', timeout=5000)
                            alert.accept()
                            time.sleep(1)
                        except Exception:
                            pass
                    except Exception:
                        pass

                    try:
                        sel_tipo = page.locator('select[name="codTipoDocumento"]')
                        if sel_tipo.count():
                            # Busca robusta: valor exato → label exato → label
                            # case-insensitive contém (escolhe a mais curta).
                            # Ex: 'Certidão' → valor '37'; 'CUMPRIMENTO' → '55'.
                            valor = None
                            for opt in sel_tipo.locator('option').all():
                                v = (opt.get_attribute('value') or '').strip()
                                t = (opt.inner_text() or '').strip()
                                if v and (v == tipo_documento or t == tipo_documento):
                                    valor = v
                                    break
                            if valor is None:
                                td = tipo_documento.lower()
                                candidatos = []
                                for opt in sel_tipo.locator('option').all():
                                    v = (opt.get_attribute('value') or '').strip()
                                    t = (opt.inner_text() or '').strip()
                                    if v and t and (td in t.lower() or t.lower() in td):
                                        candidatos.append((len(t), v))
                                if candidatos:
                                    candidatos.sort()
                                    valor = candidatos[0][1]
                            if valor:
                                sel_tipo.select_option(valor)
                                print(f'   ✅ Tipo Documento: {tipo_documento} → {valor}')
                            else:
                                print(f'   ⚠️ Tipo Documento "{tipo_documento}" não encontrado no select')
                            time.sleep(0.5)
                    except Exception as e:
                        print(f'   ⚠️ Tipo Documento: {e}')
                    print('   ✅ Código 581 injetado')

                # ─── PASSO 5: Vistas ao MP ──
                if envia_mp:
                    try:
                        page.locator('#imgBotao_panelEnvioOrgaoExterno').first.click()
                        time.sleep(0.5)
                        print('   ✅ Painel envio órgão externo expandido')
                    except Exception:
                        pass
                    try:
                        cb = page.locator('input[name="enviaMP"]')
                        if cb.count():
                            cb.check()
                            print('   ✅ enviaMP marcado')
                            time.sleep(0.5)
                    except Exception:
                        pass
                    try:
                        sel_nucleo = page.locator('select[name="codNucleoMP"]')
                        if sel_nucleo.count():
                            sel_nucleo.select_option(cod_nucleo_mp)
                            print(f'   ✅ Núcleo MP: {cod_nucleo_mp}')
                            time.sleep(0.3)
                    except Exception:
                        pass

                # ─── PASSO 6: Observação ──
                obs_texto = record.observacao or f"Cumprimento de {record.act_verb}"
                if record.parte_nome:
                    obs_texto += f" — {record.parte_nome}"
                page.fill('#observacao', obs_texto[:500])
                time.sleep(0.5)

                # Ativa Cumprimento + btnAddCumprimento
                try:
                    page.locator("a:text('Cumprimento')").first.click()
                    time.sleep(0.5)
                    page.click('#btnAddCumprimento')
                    time.sleep(1)
                    print('   ✅ Cumprimento ativado')
                except Exception as e:
                    print(f'   ⚠️ Cumprimento: {e}')

                # ─── Inserir Documento (certidão) ──────────────────────
                # ⚠️ DESATIVADO 2026-07-31: certidão já inserida no PASSO 3.
                # Este bloco duplicado causava 2ª assinatura + re-navegação
                # que perdia o estado do formulário (581/obs/certidão).
                if certidao_html and False:
                    try:
                        # Radio SelectArquivo = DigitarTexto
                        radio = page.locator('input[name="SelectArquivo"][value="DigitarTexto"]')
                        if radio.count():
                            radio.check()
                            print('   ✅ SelectArquivo: DigitarTexto')
                            time.sleep(0.5)
                    except Exception:
                        pass

                    try:
                        # Select codDescricao1 = 37 (Certidão)
                        sel_desc = page.locator('select[name="codDescricao1"]')
                        if sel_desc.count():
                            sel_desc.select_option('37')
                            print('   ✅ Tipo doc: Certidão (37)')
                            time.sleep(0.5)
                    except Exception:
                        pass

                    try:
                        # Campo descricao (título da certidão)
                        campo_desc = page.locator('input[name="descricao"]')
                        if campo_desc.count():
                            campo_desc.fill('Certidão Criminal - art. 76 Lei 9.099/95')
                            time.sleep(0.3)
                    except Exception:
                        pass

                    # Clica link redigirTexto() → abre FCKeditor
                    try:
                        with page.expect_navigation(timeout=15000):
                            link = page.locator('a[href*="redigirTexto"]')
                            if link.count():
                                link.first.click()
                            else:
                                page.evaluate('redigirTexto()')
                        time.sleep(3)
                        print(f'   ✅ FCKeditor aberto: {page.url}')
                    except Exception as e:
                        print(f'   ⚠️ redigirTexto: {e}')
                        # Se falhou, tenta submit do form
                        try:
                            page.evaluate('document.forms[0].submit()')
                            time.sleep(3)
                        except Exception:
                            pass

                    # Seta o HTML no FCKeditor
                    try:
                        result = page.evaluate('''(html) => {
                            try {
                                var oEditor = FCKeditorAPI.GetInstance('FCKeditor1');
                                oEditor.SwitchToSourceMode();
                                oEditor.SetHTML(html);
                                oEditor.SwitchToWysiwygMode();
                                return 'OK';
                            } catch(e) {
                                try {
                                    var oEditor2 = window.parent.FCKeditorAPI.GetInstance('FCKeditor1');
                                    oEditor2.SwitchToSourceMode();
                                    oEditor2.SetHTML(html);
                                    oEditor2.SwitchToWysiwygMode();
                                    return 'OK:parent';
                                } catch(e2) {
                                    return 'Erro: ' + e2.message;
                                }
                            }
                        }''', certidao_html)
                        print(f'   ✅ FCKeditor HTML setado: {result}')
                        time.sleep(1)
                    except Exception as e:
                        print(f'   ⚠️ FCKeditor API: {e}')

                    # Submeter
                    try:
                        btn_sub = page.locator('input[value="Submeter"]')
                        if btn_sub.count():
                            btn_sub.first.click()
                            time.sleep(2)
                            print('   ✅ Submeter clicado')
                    except Exception:
                        try:
                            page.evaluate('''() => {
                                var b = document.querySelector('input[value="Submeter"]');
                                if (b) b.click();
                            }''')
                            time.sleep(2)
                        except Exception:
                            pass

                    # Assinar 1ª vez
                    try:
                        btn_ass = page.locator('img[src*="bot-assinar"]')
                        if btn_ass.count():
                            btn_ass.first.click()
                            time.sleep(1)
                            print('   ✅ Assinar 1ª vez')
                    except Exception:
                        pass

                    # Preenche senha
                    try:
                        camp_senha = page.locator('input[name="senha"]')
                        if camp_senha.count():
                            senha = getattr(self.user, 'projudi_password', '')
                            if not senha:
                                print('   ⚠️ Senha do Projudi não encontrada no usuário')
                            else:
                                camp_senha.fill(senha)
                                time.sleep(0.5)
                                print('   ✅ Senha preenchida')
                    except Exception as e:
                        print(f'   ⚠️ Senha: {e}')

                    # Assinar 2ª vez
                    try:
                        btn_ass2 = page.locator('img[src*="bot-assinar"]')
                        if btn_ass2.count():
                            btn_ass2.first.click()
                            time.sleep(2)
                            print('   ✅ Assinar 2ª vez')
                    except Exception:
                        pass

                    # Aguarda processamento
                    try:
                        page.wait_for_load_state('networkidle', timeout=15000)
                    except Exception:
                        pass
                    time.sleep(2)
                    print(f'   📍 URL após certidão: {page.url}')

                # ─── Garantir que estamos no formulário Mov581 ──
                # Detecção por CONTEÚDO (seqCategoriaMovimentacao), não URL:
                # após o Submeter do DigitarTexto, a MESMA página re-renderiza
                # como formulário de movimentação (URL continua DigitarTexto).
                url_atual = page.url
                tem_form = False
                try:
                    tem_form = page.evaluate(
                        '!!document.getElementById("seqCategoriaMovimentacao")')
                except Exception:
                    tem_form = False
                if not tem_form:
                    print(f'   ⚠️ Sem formulário Mov581 ({url_atual[:60]}). Re-navegando...')
                    url_mov = (
                        'https://projudi.tjba.jus.br/projudi/movimentacao/'
                        f'MovimentarProcesso?numeroProcesso={proc_projudi}'
                    )
                    page.goto(url_mov, wait_until='networkidle')
                    time.sleep(2)
                    # Re-mostra campos ocultos
                    page.evaluate('''() => {
                        var tr = document.getElementById('trTipoDocumento');
                        if (tr) tr.style.display = 'table-row';
                        var div = document.getElementById('rowDadosMovimentacaoComplemento');
                        if (div) div.style.display = 'block';
                        var p = document.getElementById('divPanelCumprimento');
                        if (p) p.style.display = 'block';
                    }''')
                    time.sleep(0.5)
                    print('   ✅ Re-navegado para Mov581')
                else:
                    print(f'   ✅ Formulário Mov581 presente ({url_atual[:50]})')

                # Configura localizador (via JS direto, mais robusto)
                if record.tipo_localizador or record.localizador:
                    try:
                        # Expande painel via JS
                        page.evaluate('''() => {
                            var btn = document.getElementById('imgBotao_panelLocalizador');
                            if (btn) btn.click();
                        }''')
                        time.sleep(0.5)
                    except Exception:
                        pass

                    if record.tipo_localizador:
                        try:
                            page.evaluate(f'''() => {{
                                var sel = document.getElementById('codTipoLocalizador');
                                if (sel) {{ sel.value = '{record.tipo_localizador}';
                                    sel.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                            }}''')
                            print(f'   📍 Tipo localizador: {record.tipo_localizador}')
                            time.sleep(0.3)
                            # Clica botão "Adicionar" localizador
                            try:
                                btn_add = page.locator('img[src*="bot-adicionar"]')
                                if btn_add.count():
                                    btn_add.click()
                                    print('   ✅ Localizador adicionado à lista')
                                    time.sleep(0.5)
                            except Exception:
                                pass
                        except Exception:
                            pass
                    if record.localizador:
                        try:
                            page.evaluate(f'''() => {{
                                var sel = document.getElementById('codLocalizador');
                                if (sel) {{ sel.value = '{record.localizador}';
                                    sel.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                            }}''')
                            print(f'   📍 Localizador: {record.localizador}')
                            time.sleep(0.3)
                        except Exception:
                            pass

                # Submete o form — tenta clique real no Concluir (input type=image)
                # importante: clique real dispara JS handlers que serializam a certidão
                time.sleep(0.5)
                page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                time.sleep(0.3)

                concluir_submetido = False
                try:
                    btn = page.locator('#Concluir')
                    if btn.count():
                        btn.click(position={'x': 5, 'y': 5}, timeout=5000)
                        time.sleep(3)
                        # Verifica se navegou
                        try:
                            page.wait_for_load_state('networkidle', timeout=10000)
                        except Exception:
                            pass
                        url_pos = page.url
                        if 'DadosProcesso' in url_pos or 'Historico' in url_pos:
                            concluir_submetido = True
                            print('   ✅ Concluir clicado com coordenadas')
                        else:
                            print('   ⚠️ Clique no Concluir não navegou')
                except Exception as e:
                    print(f'   ⚠️ Clique Concluir: {e}')

                if not concluir_submetido:
                    # Fallback: submit via JS com Concluir.x/y hidden
                    print('   ⚠️ Fallback: submit via JS')
                    page.evaluate('''() => {
                        var concluir = document.getElementById('Concluir');
                        if (concluir && concluir.form) {
                            var form = concluir.form;
                            var x = document.createElement('input');
                            x.type = 'hidden'; x.name = 'Concluir.x'; x.value = '10';
                            form.appendChild(x);
                            var y = document.createElement('input');
                            y.type = 'hidden'; y.name = 'Concluir.y'; y.value = '10';
                            form.appendChild(y);
                            form.submit();
                        }
                    }''')
                    time.sleep(3)
                    try:
                        page.wait_for_load_state('networkidle', timeout=10000)
                    except Exception:
                        pass

                # Aguarda navegação
                try:
                    page.wait_for_load_state('networkidle', timeout=15000)
                except Exception:
                    pass
                time.sleep(2)

                # Verifica sucesso
                html_check = page.content()
                url_final = page.url
                record.url_movimentacao = url_final

                if any(k in html_check.lower() for k in
                       ['movimentação incluída', 'movimentacao incluida',
                        'operação realizada', 'operacao realizada',
                        'dados gravados', 'redirect']):
                    sucesso = True
                    self._log(record, 'execucao',
                              f"✅ Movimentação concluída. URL: {url_final}")
                elif 'DadosProcesso' in url_final or 'Historico' in url_final:
                    sucesso = True
                    self._log(record, 'execucao',
                              f"✅ Redirecionado ao processo. URL: {url_final}")
                else:
                    self._log(record, 'erro',
                              f"Movimentação pode não ter sido registrada. "
                              f"URL final: {url_final}")

                browser.close()

        except Exception as e:
            self._log(record, 'erro', f'Erro no Playwright: {str(e)[:200]}')
            import traceback
            traceback.print_exc()

        record.status = 'cumprido' if sucesso else 'falha'
        record.save(update_fields=['status', 'url_movimentacao'])
        if sucesso:
            print(f'   ✅ Movimentação (JS submit) concluída')
        else:
            print(f'   ⚠️ Falha na movimentação (JS submit)')
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
    # SUBMETER VIA REQUESTS (fallback quando Playwright não consegue Concluir)
    # =================================================================
    def _submeter_via_requests(self, session, html: str, record: MovimentacaoRecord,
                                proc_projudi: str) -> Tuple[bool, str]:
        """Extrai o form MovimentarProcesso do HTML e submete via POST direto.

        Funciona como _juntar_via_requests do OficioService:
        parseia o formulário, adiciona Concluir.x/y, e posta.
        """
        from bs4 import BeautifulSoup
        import re as _re

        soup = BeautifulSoup(html, 'html.parser')
        form = soup.find('form')
        if not form:
            return False, "Formulário não encontrado no HTML"

        post_url = form.get('action', '')
        if post_url and post_url.startswith('/'):
            post_url = f'https://projudi.tjba.jus.br{post_url}'
        elif not post_url:
            post_url = (f'https://projudi.tjba.jus.br/projudi/movimentacao/'
                        f'MovimentarProcesso?numeroProcesso={proc_projudi}')

        # Extrai todos os campos do formulário
        payload = {}
        for inp in form.find_all(['input', 'select', 'textarea']):
            name = inp.get('name')
            if not name or name in ('Concluir.x', 'Concluir.y'):
                continue
            if inp.name == 'select':
                selected = inp.find('option', selected=True)
                val = selected.get('value', '') if selected else ''
            elif inp.name == 'textarea':
                val = inp.get_text()
            else:
                # input type="image" (submit de imagem) — ignorar, usamos Concluir.x/y
                if inp.get('type') == 'image':
                    continue
                val = inp.get('value', '')
            if val:
                payload[name] = val

        # Sobrescreve com dados do record
        payload['seqCategoriaMovimentacao'] = record.codigo_movimentacao or '581'
        if record.codigo_movimentacao == '11383':
            payload['descCategoriaMovimentacao'] = record.descricao_movimentacao or 'Cumprimento de Oficio'
        else:
            payload['descCategoriaMovimentacao'] = record.descricao_movimentacao or 'TD - Tipo Documental'
        if record.observacao:
            payload['observacao'] = record.observacao[:500]

        # Concluir.x e Concluir.y (obrigatório para input type=image)
        payload['Concluir.x'] = '10'
        payload['Concluir.y'] = '10'

        # Remove campos indesejados que podem causar erro de validação
        for campo in ['codDelegacia', 'codPrazoEnviaDelegacia',
                        'enviaDelegacia', 'enviaMP', 'enviaTurmaRecursal',
                        'enviaCartorioExtrajudicial', 'arquivar',
                        'psicossocial', 'contador']:
            payload.pop(campo, None)

        # Localizador
        if record.tipo_localizador:
            payload['codTipoLocalizador'] = record.tipo_localizador
        if record.localizador:
            payload['codLocalizador'] = record.localizador

        # Envia multipart/form-data
        from io import BytesIO
        import time as _time
        _time.sleep(1)
        multipart = {}
        for k, v in payload.items():
            val_bytes = str(v).encode('latin-1', errors='replace')
            multipart[k] = (None, val_bytes)

        resp = session.post(post_url, files=multipart, timeout=15)

        # Verifica sucesso
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"

        texto = resp.text.lower()
        url_resp = resp.url.lower()

        if 'login' in url_resp:
            return False, "Sessão expirada"

        if any(k in texto for k in
               ['movimentação incluída', 'movimentacao incluida',
                'operação realizada', 'operacao realizada',
                'dados gravados']):
            record.url_movimentacao = resp.url
            return True, "Movimentação registrada via POST direto"

        if 'DadosProcesso' in resp.url or 'Historico' in resp.url:
            record.url_movimentacao = resp.url
            return True, "Redirect para DadosProcesso via POST direto"

        # Tenta extrair mensagem de validação do HTML de resposta
        try:
            soup_resp = BeautifulSoup(resp.text, 'html.parser')
            # Procura spans/labels com mensagens de erro
            erros = []
            for tag in soup_resp.find_all(['span', 'label', 'div', 'li']):
                texto_tag = tag.get_text(strip=True)
                if any(p in texto_tag.lower() for p in
                       ['obrigatório', 'obrigatorio', 'inválido', 'invalido',
                        'erro', 'não permitido', 'nao permitido',
                        'preenchimento', 'campo']):
                    if len(texto_tag) < 200:
                        erros.append(texto_tag)
            if erros:
                return False, f"Validação: {'; '.join(erros[:3])}"

            # Verifica se o form ainda está na página (com validação específica)
            form_resp = soup_resp.find('form')
            if form_resp and 'MovimentarProcesso' in str(form_resp.get('action', '')):
                return False, f"Formulário ainda presente (possível erro de validação)"
        except Exception:
            pass

        return False, f"Resposta inesperada: {resp.url}"

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
                # 11383 = requests direto (sem Playwright)
                if rec.codigo_movimentacao == '11383':
                    ok = self.executar_requests(rec)
                else:
                    ok = self.executar(rec)
                if ok:
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
        fallback_mandado: bool = False,
        mandado_explicito: bool = False,
        prazo_intimacao: str = '3',
        fallback_polo=None,
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
            fallback_mandado: Se True, quando o canal da parte for mandado
                          (match do histórico de comunicações), registra a
                          solicitação de expedição de mandado (sem expedir)
                          em vez da intimação eletrônica. Canal AR → pula.
            mandado_explicito: Se True, a sequência já tem passo explícito
                          de mandado/solicitação — o pre-check só pula a
                          intimação (não registra solicitação duplicada).
            prazo_intimacao: Código do prazo no painel de intimação
                          (codPrazoAutor/codPrazoReu). Default '3' (10 dias
                          nas sentenças). Ex: prazo de 05 dias usa outro
                          código — ver opções do select no Projudi.
            fallback_polo: Polo da identificação no fallback de mandado
                          (mesmo vocabulário do mandado: reu_especifico,
                          autor_especifico, autores, res, todos ou lista).
                          Default: reu_especifico (só réus).
        """
        from playwright.sync_api import sync_playwright

        result = self.projudi_service._get_session_from_cookies()
        if not result:
            print('   ❌ Sessão do Projudi não disponível.')
            return False

        session, saved_cookies = result
        cookies = cookies_dict or saved_cookies

        if not proc_projudi and not cod_analise:
            m = re.search(r'(\d{13,20})', processo_numero.replace('-', '').replace('.', ''))
            if m:
                proc_projudi = m.group(1)
            # Número Projudi interno (14 dígitos) vs CNJ (20 dígitos):
            # o MovimentarProcesso exige o interno. O endpoint antigo de
            # consulta (consultaProcesso) foi removido do Projudi (404).
            if proc_projudi and len(proc_projudi) > 15:
                print('   ⚠️ Só o CNJ foi informado — o MovimentarProcesso exige o '
                      'número Projudi interno. No batch, ele vem do link_processo '
                      'da movimentação; em chamadas diretas, passe proc_projudi.')
            if not proc_projudi:
                print('   ❌ Número Projudi não encontrado.')
                return False

        # ── PRE-CHECK: como a parte recebe as comunicações (match do histórico) ──
        # Usa analisar_movimentacao/meio_comunicacao das movimentações do processo:
        #   'domicilio_cnj' (DJEN/advgs.) → intimação eletrônica (segue)
        #   'ar'                          → pula (por ora — fazer manual)
        #   'mandado'/'precatoria'        → só registra solicitação de expedição
        #                                   de mandado (sem expedir o mandado)
        try:
            from projudiProcessNavigator import ProcessoParser
            url_dados = (
                'https://projudi.tjba.jus.br/projudi/listagens/'
                f'DadosProcesso?numeroProcesso={proc_projudi}'
            )
            r_dados = session.get(url_dados, timeout=15)
            if r_dados.status_code == 200 and 'expirou' not in r_dados.text.lower():
                parser = ProcessoParser(r_dados.text)
                movs, _ = parser.extrair_movimentacoes()
                ints = [m for m in movs
                        if m.get('categoria') == 'intimacao'
                        and m.get('meio_comunicacao')]
                if ints:
                    # Última intimação (pela data) indica o canal atual da parte
                    ints.sort(key=lambda m: m.get('data_obj') or date.min)
                    ultimo = ints[-1]
                    ultimo_meio = ultimo.get('meio_comunicacao')
                    if ultimo_meio == 'ar':
                        print(f'   ⏸️ Última intimação por AR ({ultimo.get("ato", "")[:60]})')
                        print('   ⏸️ Pulando intimação eletrônica (fazer manualmente)')
                        return True
                    if ultimo_meio in ('mandado', 'precatoria'):
                        if mandado_explicito:
                            print('   ⏸️ Última intimação por mandado — sequência já tem passo explícito de mandado/solicitação; pulando intimação (sem solicitação duplicada)')
                            return True
                        if not fallback_mandado:
                            print('   ⏸️ Última intimação por mandado — sem fallback configurado no JSON, pulando (fazer manual)')
                            return True
                        print('   ⏸️ Última intimação por mandado — fallback: registrando solicitação de expedição (sem expedir)')
                        try:
                            # Identifica a(s) parte(s) — 'fallback_polo' no JSON
                            # (mesmo vocabulário do mandado); default: réus.
                            parte_nome = ''
                            try:
                                partes_raw = parser.extrair_partes(parser.soup)
                                autoras = [p.get('nome', '').strip() for p in partes_raw
                                           if p.get('tipo', '').upper() in ('EXEQUENTE', 'PROMOVENTE')]
                                reus = [p.get('nome', '').strip() for p in partes_raw
                                        if p.get('tipo', '').upper() not in ('EXEQUENTE', 'PROMOVENTE')]

                                def _escolher(candidatos):
                                    """1 → direto; vários → específico pelo
                                    histórico; não achou → TODOS os candidatos."""
                                    cands = [c for c in candidatos if c]
                                    if len(cands) <= 1:
                                        return cands
                                    dests = [(m.get('data_obj') or date.min,
                                              str(m.get('destinatario') or '').upper())
                                             for m in movs if m.get('destinatario')
                                             and m.get('categoria') in ('intimacao', 'citacao')]
                                    dests.sort(key=lambda x: x[0], reverse=True)
                                    for _, dest in dests:
                                        if dest and len(dest) >= 5:
                                            for nome in cands:
                                                nr = nome.upper()
                                                if dest in nr or nr in dest:
                                                    return [nome]
                                    return cands

                                polos = fallback_polo or 'reu_especifico'
                                if isinstance(polos, str):
                                    polos = [polos]
                                nomes = []
                                for polo in polos:
                                    polo = str(polo).lower().strip()
                                    if polo in ('todos', 'ambos', 'todas', 'todas_as_partes',
                                                'autores_e_res', 'autoreseres'):
                                        nomes.extend(autoras + reus)
                                    elif polo in ('autores', 'autoras', 'promoventes', 'exequentes'):
                                        nomes.extend(a for a in autoras if a)
                                    elif polo in ('autor_especifico', 'autora_especifica',
                                                  'autora_especifico', 'especifico_autor',
                                                  'especifica_autora'):
                                        nomes.extend(_escolher(autoras))
                                    elif polo in ('res', 'rés', 'reus', 'réus', 'executados', 'promovidos'):
                                        nomes.extend(r for r in reus if r)
                                    else:  # 'reu_especifico', 'especifico' ou default
                                        nomes.extend(_escolher(reus))
                                parte_nome = ' / '.join(dict.fromkeys(n for n in nomes if n))
                                if parte_nome:
                                    print(f'   🎯 Parte: {parte_nome[:60]}')
                            except Exception:
                                pass
                            record = self.importar(
                                processo_numero=processo_numero,
                                act_verb='solicitar_expedicao',
                                observacao=observacao or 'Solicitada Expedicao de Mandado',
                                categoria='outro',
                                processo_cnj=processo_numero,
                                parte_nome=parte_nome,
                                url_processo=url_dados,
                                codigo_movimentacao='581',
                                descricao_movimentacao='Solicitada a Expedição de Mandado',
                            )
                            return bool(self.executar(record))
                        except Exception as e:
                            print(f'   ⚠️ Solicitação de expedição falhou: {e}')
                            return False
        except Exception as e:
            print(f'   ⚠️ Pre-check canal comunicação: {e}')

        print(f'   🔷 Iniciando intimação eletrônica...')
        if cod_analise:
            print(f'      Via MovimentarAnalise?codAnalise={cod_analise}')
        else:
            print(f'      Via MovimentarProcesso?numeroProcesso={proc_projudi}')

        sucesso = False
        import time

        try:
            with sync_playwright() as pw:
                browser = pw.firefox.launch(headless=False, slow_mo=400,
                                            env=_FIREFOX_ENV, firefox_user_prefs=_FIREFOX_PREFS)
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
                        page.evaluate(f'''() => {{
                            var sel = document.getElementById('codMotivoAutor');
                            if (sel) {{ sel.value = '3'; sel.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                            var sel2 = document.getElementById('codPrazoAutor');
                            if (sel2) {{ sel2.value = '{prazo_intimacao}'; sel2.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                        }}''')
                        time.sleep(0.5)
                        print(f'   ✅ Autoras configuradas (motivo=3, prazo={prazo_intimacao})')
                    except Exception as e:
                        print(f'   ⚠️ Autoras: {e}')

                    # Rés
                    try:
                        page.evaluate('''() => {
                            var aba = document.getElementById('Res');
                            if (aba) aba.click();
                        }''')
                        time.sleep(0.5)
                        page.evaluate(f'''() => {{
                            var sel = document.getElementById('codMotivoReu');
                            if (sel) {{ sel.value = '3'; sel.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                            var sel2 = document.getElementById('codPrazoReu');
                            if (sel2) {{ sel2.value = '{prazo_intimacao}'; sel2.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                        }}''')
                        time.sleep(0.5)
                        print(f'   ✅ Rés configurados (motivo=3, prazo={prazo_intimacao})')
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
                                    # re já é importado no topo do módulo —
                                    # import local aqui tornava 're' local da
                                    # função e quebrava re.search antes dele
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
