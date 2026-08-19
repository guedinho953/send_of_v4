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


def _procurar_campo_senha(page, timeout=10):
    """Localiza o campo de senha da assinatura (#senha) em QUALQUER frame.

    O campo só aparece DEPOIS do 1º clique em Assinar, e às vezes é
    renderizado em iframe — por isso a busca é repetida em todos os frames
    até o timeout, em vez de uma checagem única (bug antigo: count()==0
    logo após o clique pulava o preenchimento e a assinatura ficava órfã).
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        for fr in [page.main_frame] + [f for f in page.frames if f != page.main_frame]:
            try:
                loc = fr.locator('#senha, input[name="senha"]')
                if loc.count():
                    try:
                        print(f'   🖼️ Campo senha no frame: name={fr.name!r}')
                        print(f'      url={fr.url[:120]}')
                    except Exception:
                        pass
                    return loc.first
            except Exception:
                continue
        time.sleep(0.5)
    return None


def _logar_frames(page):
    """Log de debug: descreve TODOS os frames da página no momento da
    assinatura — para documentar qual iframe hospeda o diálogo (senha +
    botão Assinar)."""
    try:
        print('   🖼️ Mapa de frames (momento da assinatura):')
        for i, fr in enumerate(page.frames):
            try:
                tem_senha = fr.locator('#senha, input[name="senha"]').count() > 0
                tem_assinar = fr.locator(
                    'img[src*="bot-assinar"], input[value="Assinar"], '
                    'input[value="assinar"]').count() > 0
                marc = []
                if tem_senha:
                    marc.append('SENHA')
                if tem_assinar:
                    marc.append('ASSINAR')
                sufixo = f'  ← {" + ".join(marc)}' if marc else ''
                print(f'      [{i}] name={fr.name!r} url={fr.url[:100]}{sufixo}')
            except Exception:
                continue
    except Exception:
        pass


def _clicar_botao_assinar(page, timeout=5):
    """Clica no botão Assinar.

    Prioriza o MESMO frame do campo de senha (o diálogo de assinatura —
    alvo exato, menos varredura genérica), com fallback para todos os
    frames. O botão é o <img src=".../botoes/bot-assinar.gif"> que fica
    ao lado do #senha, dentro do iframe do diálogo.
    """
    selectors = ['img[src*="bot-assinar"]', 'img[src*="assinar"]',
                 'input[value="Assinar"]', 'input[value="assinar"]',
                 'button:has-text("Assinar")', 'input[type="submit"][value*="assin"]']
    # Frame-alvo: o que contém o campo de senha (diálogo de assinatura)
    frame_alvo = None
    for fr in page.frames:
        try:
            if fr.locator('#senha, input[name="senha"]').count():
                frame_alvo = fr
                break
        except Exception:
            continue
    frames = ([frame_alvo] + [f for f in page.frames if f is not frame_alvo]
              if frame_alvo else page.frames)
    deadline = time.time() + timeout
    while time.time() < deadline:
        for fr in frames:
            for sel in selectors:
                try:
                    btn = fr.locator(sel).first
                    if btn.count():
                        btn.click(timeout=3000)
                        return True
                except Exception:
                    continue
        time.sleep(0.5)
    return False

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
                # NÃO incluir o parte_nome automaticamente aqui (o nome na obs
                # é decidido pelo chamador — parte_na_observacao etc.). Evita
                # nome duplicado e o mojibake do separador em-dash no Projudi.
                obs_texto = record.observacao or f"Cumprimento de {record.act_verb}"
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
                           tipo_parecer_mp: str = '6',
                           prazo_mp: str = '5',
                           promotor_mp: str = None,
                           cod_analise: str = None,
                           certidao_html: str = None,
                           certidao_titulo: str = 'Certidão Criminal - art. 76 Lei 9.099/95') -> bool:
        """Executa movimentação via Playwright headless + submit via JavaScript.

        Args:
            record: MovimentacaoRecord com os dados da movimentação.
            tipo_documento: Rótulo do Tipo de Documento no select codTipoDocumento
                           (default 'CUMPRIMENTO' — genérico; ex: '9376' = PESQUISA DE ENDEREÇO).
                           NO VISTAS_MP NÃO se usa (não há tipo documental) — só observação.
            envia_mp: Se True, ativa Vistas ao MP.
            cod_nucleo_mp: Código do Núcleo (default '31' = Paulo Afonso).
            tipo_parecer_mp: Código do tipo de parecer no select codTipoEnvioMP
                          (default '6' = Ciência — o mais usado). Valores:
                          0=Parecer genérico, 4=Denúncia, 5=Desistência, 6=Ciência,
                          7=Alegações Finais, 8=Parte não Localizada, 9=Prescrição,
                          10=Decadência, 11=Recurso/Contrarrazões, 12=Acordo Cível,
                          13=Medida Cautelar, 14=Proposta de TP, 15=TP Cumprida,
                          16=TP Aceita.
            prazo_mp: Código do prazo no select codPrazoEnviaMP (default '5' =
                          30 dias — padrão; 15 dias = '4'). Valores: 10=1dia,
                          1=2dias, 11=3dias, 47=4dias, 2=5dias, 48=6dias,
                          49=7dias, 3=10dias, 4=15dias, 5=30dias.
            promotor_mp: Nome (parcial) do promotor p/ selecionar DEPOIS do
                          núcleo no select loginPromotorNucleoMP (ex:
                          'SOSTENYS MARINHO BARRETO').
            cod_analise: Se informado (vem do link 'movimentar' da movimentação,
                          ex: 'MovimentarAnalise?codAnalise=X'), abre
                          cadastros/MovimentarAnalise?codAnalise=X (FLUXO A)
                          em vez do MovimentarProcesso genérico. Esse é o fluxo
                          que REMOVE a movimentação da fila de análises após
                          concluir.
            certidao_html: Se informado, insere documento certidão no FCKeditor
                          antes de Concluir (SelectArquivo + redigirTexto).
            certidao_titulo: Título (campo 'descricao') do documento certidão.
                          Default mantém o texto da certidão criminal (art. 76).
                          Para Certidão de Prazo, passe 'Certidão de Prazo'.

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

                # Abre MovimentarProcesso (genérico) OU MovimentarAnalise
                # (fluxo A — quando há cod_analise, tira da fila de análises).
                if cod_analise:
                    url_mov = (
                        'https://projudi.tjba.jus.br/projudi/cadastros/'
                        f'MovimentarAnalise?codAnalise={cod_analise}'
                    )
                else:
                    url_mov = (
                        'https://projudi.tjba.jus.br/projudi/movimentacao/'
                        f'MovimentarProcesso?numeroProcesso={proc_projudi}'
                    )
                page.goto(url_mov, wait_until='networkidle')
                time.sleep(2)

                # No fluxo analisar (MovimentarAnalise) a página abre com
                # um link "Movimentar"/"movimentar genericamente" que PRECISA
                # ser clicado para chegar ao formulário de movimentação — é
                # esse clique que remove a análise da fila ao concluir.
                if cod_analise:
                    try:
                        for sel in ['a:has-text("Movimentar Genericamente")',
                                    'a:has-text("Movimentar genericamente")',
                                    'a:has-text("Movimentar Processo Genericamente")',
                                    'a:has-text("Movimentar Processo")',
                                    'a:has-text("Movimentar")']:
                            el = page.query_selector(sel)
                            if el and el.is_visible():
                                with page.expect_navigation(wait_until='domcontentloaded',
                                                            timeout=15000):
                                    el.click()
                                time.sleep(2)
                                print(f'   ✅ Clicado no link de análise: {sel}')
                                break
                    except Exception as e:
                        print(f'   ⚠️ Clicando no link de análise: {e}')

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
                # No MovimentarAnalise (fluxo A) o #btnAddCumprimento já vem
                # visível — clicar direto. No MovimentarProcesso (fluxo B) pode
                # precisar expandir via link "Cumprimento" antes.
                try:
                    if cod_analise:
                        # fluxo A: botão já visível
                        page.click('#btnAddCumprimento', timeout=5000)
                    else:
                        # fluxo B: expande painel, depois clica
                        try:
                            page.locator("a:has-text('Cumprimento')").first.click()
                        except Exception:
                            pass
                        time.sleep(0.5)
                        page.click('#btnAddCumprimento', timeout=5000)
                    time.sleep(1)
                    print('   ✅ Cumprimento ativado (btnAddCumprimento)')
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
                            campo_desc.fill(certidao_titulo)
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
                        _logar_frames(page)
                        # Senha — espera o campo aparecer (pode demorar / iframe)
                        camp_senha = _procurar_campo_senha(page, timeout=10)
                        if camp_senha:
                            try:
                                camp_senha.fill(senha)
                                time.sleep(0.5)
                                print('   ✅ Senha preenchida')
                            except Exception as e:
                                print(f'   ⚠️ Falha ao preencher senha: {e}')
                        else:
                            print('   ⚠️ Campo senha não apareceu em 10s')
                        # Assinar 2ª
                        if _clicar_botao_assinar(page):
                            time.sleep(2)
                            print('   ✅ Assinar 2ª')
                        else:
                            print('   ⚠️ Botão Assinar 2ª não encontrado')
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

                if cod_mov in ('11383', '493'):
                    # Estes códigos não usam grid nem tipo documental — apenas
                    # a descrição. (493 = Vistas ao MP; 11383 = Cumprimento de
                    # Ofício / direto.)
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
                            time.sleep(0.8)  # aguarda DWR popular promotor
                    except Exception:
                        pass
                    # Tipo de parecer / motivo — codTipoEnvioMP (ex: 6 = Ciência)
                    if tipo_parecer_mp is not None:
                        try:
                            sel_tp = page.locator('select[name="codTipoEnvioMP"]')
                            if sel_tp.count():
                                sel_tp.select_option(str(tipo_parecer_mp))
                                print(f'   ✅ Tipo parecer MP: {tipo_parecer_mp}')
                                time.sleep(0.3)
                        except Exception as e:
                            print(f'   ⚠️ Tipo parecer MP: {e}')
                    # Prazo — codPrazoEnviaMP (ex: 5 = 30 dias, 4 = 15 dias)
                    if prazo_mp is not None:
                        try:
                            sel_pr = page.locator('select[name="codPrazoEnviaMP"]')
                            if sel_pr.count():
                                sel_pr.select_option(str(prazo_mp))
                                print(f'   ✅ Prazo MP: {prazo_mp}')
                                time.sleep(0.3)
                        except Exception as e:
                            print(f'   ⚠️ Prazo MP: {e}')
                    # Promotor — loginPromotorNucleoMP (aparece após o núcleo via DWR)
                    if promotor_mp:
                        try:
                            nome_proc = str(promotor_mp).strip()
                            sel_promotor = page.locator('select[name="loginPromotorNucleoMP"]')
                            achou = False
                            if sel_promotor.count():
                                for j in range(sel_promotor.locator('option').count()):
                                    txt = sel_promotor.locator('option').nth(j).inner_text().strip()
                                    if nome_proc.lower() in txt.lower():
                                        val = sel_promotor.locator('option').nth(j).get_attribute('value')
                                        sel_promotor.select_option(val)
                                        print(f'   ✅ Promotor MP: {txt.strip()}')
                                        achou = True
                                        break
                            if not achou:
                                # Fallback: varre qualquer select com o nome
                                for i in range(page.locator('select').count()):
                                    sel = page.locator('select').nth(i)
                                    try:
                                        for j in range(sel.locator('option').count()):
                                            txt = sel.locator('option').nth(j).inner_text().strip()
                                            if nome_proc.lower() in txt.lower():
                                                sel.select_option(sel.locator('option').nth(j).get_attribute('value'))
                                                print(f'   ✅ Promotor MP (fallback): {txt.strip()}')
                                                achou = True
                                                break
                                    except Exception:
                                        continue
                                    if achou:
                                        break
                            if not achou:
                                print(f'   ⚠️ Promotor "{nome_proc}" não achado (núcleo {cod_nucleo_mp})')
                        except Exception as e:
                            print(f'   ⚠️ Selecionando promotor MP: {e}')
                    time.sleep(0.3)

                # ─── PASSO 6: Observação ──
                obs_texto = record.observacao or f"Cumprimento de {record.act_verb}"
                if record.parte_nome:
                    obs_texto += f" — {record.parte_nome}"
                page.fill('#observacao', obs_texto[:500])
                time.sleep(0.5)

                # (Cumprimento já ativado no PASSO 2 — não repetir o clique
                # no #btnAddCumprimento aqui: ele trava 30s quando o botão já
                # não está visível após a adição.)

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
                            campo_desc.fill(certidao_titulo)
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
                    _logar_frames(page)

                    # Preenche senha (espera o campo aparecer em qualquer frame)
                    senha = getattr(self.user, 'projudi_password', '')
                    camp_senha = _procurar_campo_senha(page, timeout=10) if senha else None
                    if camp_senha:
                        try:
                            camp_senha.fill(senha)
                            time.sleep(0.5)
                            print('   ✅ Senha preenchida')
                        except Exception as e:
                            print(f'   ⚠️ Senha: {e}')
                    elif senha:
                        print('   ⚠️ Campo senha não apareceu em 10s')
                    else:
                        print('   ⚠️ Senha do Projudi não encontrada no usuário')

                    # Assinar 2ª vez
                    if _clicar_botao_assinar(page):
                        time.sleep(2)
                        print('   ✅ Assinar 2ª vez')
                    else:
                        print('   ⚠️ Botão Assinar 2ª vez não encontrado')

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
            # A observação carrega acentos (ç, ã, é...). Envia em UTF-8 para
            # o Projudi renderizar corretamente; demais campos seguem latin-1.
            if k == 'observacao':
                val_bytes = str(v).encode('utf-8', errors='replace')
            else:
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
        fallback_ar: bool = False,
        fallback_registrar: bool = False,
        prazo_intimacao: str = '3',
        fallback_polo=None,
        motivo_intimacao: str = '3',
        expedir_ar: bool = False,
        tipo_intimacao: str = 'geral',
        codigo_tipo_ar: str = None,
        natureza_override: str = None,
        assinar_ar: bool = True,
        fallback_template_id: int = None,
        fallback_subtipo: str = None,
        fallback_prazo: str = None,
        # ── Vistas ao MP + solicitação de ofício NA MESMA movimentação ──
        envia_mp: bool = False,
        cod_nucleo_mp: str = '31',
        tipo_parecer_mp: str = '6',
        prazo_mp: str = '5',
        promotor_mp: str = None,
        solicitar_oficio: bool = False,
        oficio_template_id: int = None,
        # ── Solicitação de expedição de MANDADO na MESMA movimentação ──
        solicitar_mandado: bool = False,
        mandado_polo=None,
        mandado_subtipo: str = '3',
        # Modo teste: preenche tudo (intimação, MP, ofício) mas NÃO clica em
        # Concluir nem expede/assina o AR — deixa a página aberta p/ revisão.
        nao_concluir: bool = False,
        # Polo no painel de intimação: 'todos' (default, Autoras+Rés) |
        # 'autores' (só aba Autoras, não clica Réus) | 'res' (só aba Rés).
        polo_intimacao: str = 'todos',
        # ── Localizador aplicado na MESMA movimentação da intimação ──
        tipo_localizador: str = '',
        localizador: str = '',
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
            fallback_ar: Se True, quando o canal da parte for AR (não tem
                          domicílio eletrônico — última intimação por AR),
                          NÃO pula: expede a intimação pelos CORREIOS com AR
                          digital (2º clique, como o passo intimacao_correio).
                          Combinar com assinar_ar (False = deixa página aberta
                          p/ assinatura manual). Se False (default), canal AR
                          continua pulando ("fazer manualmente").
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
            expedir_ar: Se True, APÓS o Concluir da intimação expede pelos
                          CORREIOS com AR digital: navega para
                          MovimentarProcessoAvancado (link genérico),
                          seleciona o modelo COJE no select name="tipo" e
                          clica em "expedir com ar digital" → página
                          ExpedirIntimacao?codIntimacao=...&arDigital=true
                          → assina (senha automática ou manual).
            assinar_ar: Se False, expede o AR mas NÃO assina — deixa a
                          página ExpedirIntimacao aberta para assinatura
                          manual (útil para testar o fluxo sem assinar).
            fallback_template_id: Quando fallback='mandado', ID do
                          DocumentTemplate do mandado para EXPEDIR o mandado
                          COMPLETO (tipoCumprimento=4 + subtipo +
                          destinatário + CumprimentoCartorio + FCKeditor) —
                          igual ao passo `mandado`. Se ausente, registra só
                          o Mov581 de solicitação (comportamento antigo).
            fallback_subtipo: subtipoCumprimento do mandado no fallback
                          (default '11' = Citação/Penhora/Avaliação).
            fallback_prazo: prazo em dias p/ o corpo do mandado (ex '15').
            tipo_intimacao: 'geral' (default) ou 'audiencia' — escolhe o
                          modelo COJE. Combinado com a natureza do processo
                          (cível/criminal) define o código do tipo:
                          cível+geral=12066, criminal+geral=14032,
                          cível+audiência=56061, criminal+audiência=55794.
            codigo_tipo_ar: Código do tipo COJE direto (override). Ex:
                          '12066'. Se definido, ignora tipo_intimacao.
            natureza_override: 'civel' ou 'criminal'. Se definido, ignora a
                          detecção automática via extrair_classe().
        """
        from playwright.sync_api import sync_playwright

        result = self.projudi_service._get_session_from_cookies()
        if not result:
            print('   ❌ Sessão do Projudi não disponível.')
            return False

        session, saved_cookies = result
        cookies = cookies_dict or saved_cookies

        # Natureza do processo (cível/criminal) — decide o modelo COJE do AR.
        # Default cível; override explícito no JSON tem prioridade.
        natureza_processo = natureza_override or 'civel'

        # ── Resolver prazo_intimacao: aceita o CÓDIGO (ex '4') ou o NÚMERO DE
        # DIAS (ex '15', '05', '30'). O RAG pode escrever prazo_intimacao como
        # o prazo literal do despacho — converte pro código do painel.
        # Quando vazio: extrai do texto da movimentação; sem prazo no texto,
        # segue a regra: despacho → 5 dias ('2'), sentença → 10 dias ('3'). ──
        prazo_dias_map = {
            '5': '2',   # 05 dias
            '10': '3',  # 10 dias
            '15': '4',  # 15 dias
            '30': '7',  # 30 dias
            '180': '29', '6': '29',  # 6 meses
        }
        if not prazo_intimacao:
            # Extração do prazo do texto (ex "prazo de 15 dias")
            try:
                from processes.movimentacoes_service import extrair_prazo_dias
                dias = extrair_prazo_dias(observacao or '')
                if dias and dias in prazo_dias_map:
                    prazo_intimacao = prazo_dias_map[dias]
                    print(f'   📅 Prazo extraído do texto: {dias} dias → código {prazo_intimacao}')
                else:
                    # Regra despacho/sentença
                    obs_low = (observacao or '').lower()
                    if 'senten' in obs_low or 'acórd' in obs_low or 'acord' in obs_low:
                        prazo_intimacao = '3'  # sentença → 10 dias
                    else:
                        prazo_intimacao = '2'  # despacho → 5 dias
                    print(f'   📅 Prazo por tipo (despacho=5/sentença=10): código {prazo_intimacao}')
            except Exception as e:
                prazo_intimacao = '2'  # padrão: despacho → 5 dias
                print(f'   📅 Prazo default 5 dias (erro extração: {e})')
        elif str(prazo_intimacao) in prazo_dias_map:
            prazo_intimacao = prazo_dias_map[str(prazo_intimacao)]
            print(f'   📅 prazo_intimacao → código {prazo_intimacao}')

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
        #   'ar'                          → PULA a eletrônica (fazer manual OU,
        #                                    se expedir_ar=True, seguir p/ correios)
        #   'mandado'/'precatoria'        → só registra solicitação de expedição
        #                                   de mandado (sem expedir o mandado)
        # Quando expedir_ar=True (passo intimacao_correio), o canal AR foi
        # decidido pelo FluxoDecisor — NÃO pular; seguir para a expedição
        # pelos correios.
        try:
            from projudiProcessNavigator import ProcessoParser
            url_dados = (
                'https://projudi.tjba.jus.br/projudi/listagens/'
                f'DadosProcesso?numeroProcesso={proc_projudi}'
            )
            r_dados = session.get(url_dados, timeout=15)
            if r_dados.status_code == 200 and 'expirou' not in r_dados.text.lower():
                parser = ProcessoParser(r_dados.text)
                # Detecta natureza (cível/criminal) para o modelo COJE do AR —
                # apenas se não veio override explícito no JSON.
                if not natureza_override:
                    try:
                        cls = parser.extrair_classe(parser.soup)
                        natureza_processo = cls.get('natureza') or 'civel'
                        print(f'   🏷️ Natureza detectada: {natureza_processo} '
                              f'({cls.get("classe") or "?"})')
                    except Exception:
                        pass
                if expedir_ar:
                    # Canal decidido pelo FluxoDecisor como AR/correios —
                    # o pre-check de canal da ELETRÔNICA não se aplica.
                    movs, _ = parser.extrair_movimentacoes()
                    print('   🚚 Fluxo AR (correios) — pre-check de canal da '
                          'eletrônica ignorado; prosseguindo p/ expedição.')
                    ints = []
                else:
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
                        if fallback_ar:
                            # fallback_ar: a parte não tem domicílio eletrônico
                            # (última comunicação por AR) → em vez de pular,
                            # expede a intimação pelos CORREIOS com AR digital
                            # (2º clique). Não retorna aqui; segue o fluxo da
                            # movimentação + expedição (expedir_ar forçado).
                            print(f'   🚚 Última intimação por AR ({ultimo.get("ato", "")[:60]})')
                            print('   🚚 fallback_ar=true → expedindo pelos CORREIOS (AR digital)')
                            expedir_ar = True
                        else:
                            print(f'   ⏸️ Última intimação por AR ({ultimo.get("ato", "")[:60]})')
                            print('   ⏸️ Pulando intimação eletrônica (fazer manualmente)')
                            return True
                    # ── Domicílio eletrônico tem precedência sobre o canal do
                    # histórico: parte com envelope (intimação eletrônica) ou
                    # Domicílio CNJ (favicon) intima eletronicamente — NUNCA
                    # cai no fallback de mandado. ──
                    tem_eletronico = False
                    try:
                        tem_eletronico = any(
                            (p.get('domicilio_cnj') or p.get('recebe_intimacao_email'))
                            for p in parser.extrair_partes(parser.soup)
                        )
                    except Exception:
                        tem_eletronico = False
                    if tem_eletronico:
                        print('   ✅ Parte(s) com Domicílio CNJ/eletrônico — intimando eletronicamente (sem fallback de mandado)')
                    elif ultimo_meio in ('mandado', 'precatoria'):
                        print(f'   ⏸️ Última intimação por mandado ({ultimo.get("ato", "")[:60]})')
                        if solicitar_mandado:
                            # Solicitação de mandado na MESMA movimentação: não
                            # retorna — segue para o Playwright, que intima
                            # eletronicamente (painel Autoras/Rés) e adiciona a
                            # linha de cumprimento de mandado no MESMO grid.
                            print('   🔄 solicitar_mandado=true na mesma mov — '
                                  'seguindo (linha de mandado no grid, sem Mov581 extra)')
                        elif mandado_explicito:
                            print('   ⏸️ Última intimação por mandado — sequência já tem passo explícito de mandado/solicitação; pulando intimação (sem solicitação duplicada)')
                            return True
                        elif not fallback_mandado:
                            print('   ⏸️ Última intimação por mandado — sem fallback configurado no JSON, pulando (fazer manual)')
                            return True
                        else:
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
                                if fallback_template_id:
                                    # ── EXPEDIR o mandado COMPLETO (não só Mov581):
                                    # tipoCumprimento=4 + subtipo + destinatário +
                                    # CumprimentoCartorio + FCKeditor — igual ao
                                    # passo `mandado`. ──
                                    return self._expedir_mandado_fallback(
                                        processo_numero, parte_nome,
                                        fallback_template_id,
                                        fallback_subtipo or '11',
                                        fallback_prazo or '',
                                        session, saved_cookies)
                                # Sem template → comportamento antigo (só Mov581
                                # de solicitação, sem confecção).
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
        self._ar_assinado = True  # default: sem AR, nada a assinar

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

                # FLUXO B (sem codAnalise): o link genérico "Movimentar Processo"
                # abre uma página onde se clica em "Movimentar Genericamente" —
                # a partir daí o fluxo é o MESMO do MovimentarAnalise (painel de
                # intimação Autoras/Rés + motivo/prazo + Concluir).
                if not cod_analise:
                    try:
                        for sel in ['a:has-text("Movimentar Genericamente")',
                                    'a:has-text("Movimentar genericamente")',
                                    'a:has-text("Movimentar Processo Genericamente")',
                                    'a:has-text("Movimentar Processo")',
                                    'a:has-text("Movimentar")']:
                            el = page.query_selector(sel)
                            if el:
                                el.click()
                                time.sleep(2)
                                print(f'   ✅ Clicado: {sel} (Movimentar genericamente)')
                                break
                    except Exception as e:
                        print(f'   ⚠️ Movimentar genericamente: {e}')

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

                # ─── PASSO 2: Clicar btnBuscaMovimentacao (abre a grade p/ escolher tipo) ───
                clicou_busca = False
                for sel in ['#btnBuscaMovimentacao', '#btnBuscaMovimentacao ',
                            'input[value*="Buscar Movimentação"]',
                            'button:has-text("Buscar Movimentação")']:
                    try:
                        el = page.query_selector(sel)
                        if el:
                            el.click()
                            clicou_busca = True
                            print(f'   ✅ Busca movimentação clicado ({sel})')
                            break
                    except Exception:
                        continue
                if not clicou_busca:
                    # Fallback JS: dispara a busca via clique JS
                    try:
                        page.evaluate('''() => {
                            const b = document.getElementById('btnBuscaMovimentacao');
                            if (b) { b.click(); return true; }
                            const inps = document.querySelectorAll('input,button,a');
                            for (const el of inps) {
                                if ((el.value||el.textContent||'').toLowerCase().includes('buscar') &&
                                    (el.value||el.textContent||'').toLowerCase().includes('movimenta')) {
                                    el.click(); return true;
                                }
                            }
                            return false;
                        }''')
                        clicou_busca = True
                        print('   ✅ Busca movimentação (fallback JS)')
                    except Exception as e:
                        print(f'   ⚠️ Busca movimentação não encontrada: {e}')
                time.sleep(2)

                # Tratar alerta
                try:
                    alert = page.wait_for_event('dialog', timeout=5000)
                    print(f'   ⚠️ Alerta: {alert.message}')
                    alert.accept()
                    time.sleep(2)
                except Exception:
                    pass

                # ─── PASSO 3: Selecionar Tipo de Documento = Intimação ───
                # Jeito dos fluxos que FUNCIONAM (executar_requests — certidão
                # 37, CUMPRIMENTO 55, etc.): desoculta a linha #trTipoDocumento,
                # espera o select codTipoDocumento popular e seleciona a opção
                # pelo LABEL (não por valor fixo — '5' hardcoded era o bug).
                # Clique em link a:has-text("Intimação") NÃO funciona: casa com
                # link de menu e não seleciona nada (falso "✅" no log).
                selecionou_grid = False
                try:
                    page.evaluate('''() => {
                        var tr = document.getElementById('trTipoDocumento');
                        if (tr) tr.style.display = 'table-row';
                    }''')
                except Exception:
                    pass
                try:
                    sel_tp = page.wait_for_selector(
                        'select[name="codTipoDocumento"]', timeout=8000)
                    if sel_tp:
                        # Match por label 'Intimação' (exclui
                        # Videoconferência/Telefônica) — label mais curto.
                        candidatos = []
                        for opt in sel_tp.query_selector_all('option'):
                            v = (opt.get_attribute('value') or '').strip()
                            t = (opt.inner_text() or '').strip()
                            tl = t.lower()
                            if v and 'intima' in tl and 'videoconf' not in tl \
                                    and 'telef' not in tl:
                                candidatos.append((len(t), v, t))
                        if candidatos:
                            candidatos.sort()
                            sel_tp.select_option(candidatos[0][1])
                            time.sleep(0.3)
                            confirmado = page.locator(
                                'select[name="codTipoDocumento"]').input_value()
                            selecionou_grid = True
                            print(f'   ✅ Tipo doc: "{candidatos[0][2]}" '
                                  f'→ valor {candidatos[0][1]} (confirmado={confirmado})')
                        else:
                            # Debug: mostra opções disponíveis p/ diagnosticar
                            opts = [f'{o.get_attribute("value")}={o.inner_text().strip()}'
                                    for o in sel_tp.query_selector_all('option')]
                            print('   ⚠️ "Intimação" não achada no codTipoDocumento.'
                                  f' Opções: {opts[:30]}')
                except Exception as e:
                    print(f'   ⚠️ codTipoDocumento: {e}')
                time.sleep(0.5)
                # Alerta opcional após selecionar tipo doc
                try:
                    alert = page.wait_for_event('dialog', timeout=3000)
                    print(f'   ⚠️ Alerta: {alert.message}')
                    alert.accept()
                    time.sleep(1)
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
                polo_norm = str(polo_intimacao or 'todos').lower()
                marcar_autoras = polo_norm in ('todos', 'ambos', 'autores', 'autoras',
                                               'autor', 'promovente', 'exequente')
                marcar_res = polo_norm in ('todos', 'ambos', 'res', 'réus', 'reus',
                                           'réu', 'reu', 'promovido', 'executado')
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

                    # Autoras (só se o polo incluir autoras)
                    if marcar_autoras:
                        try:
                            page.evaluate('''() => {
                                var aba = document.getElementById('Autoras');
                                if (aba) aba.click();
                            }''')
                            time.sleep(0.5)
                            page.evaluate(f'''() => {{
                                var sel = document.getElementById('codMotivoAutor');
                                if (sel) {{ sel.value = '{motivo_intimacao}'; sel.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                                var sel2 = document.getElementById('codPrazoAutor');
                                if (sel2) {{ sel2.value = '{prazo_intimacao}'; sel2.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                            }}''')
                            time.sleep(0.5)
                            print(f'   ✅ Autoras configuradas (motivo={motivo_intimacao}, prazo={prazo_intimacao})')
                        except Exception as e:
                            print(f'   ⚠️ Autoras: {e}')
                    else:
                        print('   ⏭️ Polo sem autoras — aba Autoras NÃO acionada')

                    # Rés (só se o polo incluir réus)
                    if marcar_res:
                        try:
                            page.evaluate('''() => {
                                var aba = document.getElementById('Res');
                                if (aba) aba.click();
                            }''')
                            time.sleep(0.5)
                            page.evaluate(f'''() => {{
                                var sel = document.getElementById('codMotivoReu');
                                if (sel) {{ sel.value = '{motivo_intimacao}'; sel.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                                var sel2 = document.getElementById('codPrazoReu');
                                if (sel2) {{ sel2.value = '{prazo_intimacao}'; sel2.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                            }}''')
                            time.sleep(0.5)
                            print(f'   ✅ Rés configurados (motivo={motivo_intimacao}, prazo={prazo_intimacao})')
                        except Exception as e:
                            print(f'   ⚠️ Rés: {e}')
                    else:
                        print('   ⏭️ Polo sem réus — aba Rés NÃO acionada')

                    # ── Vistas ao MP + solicitação de ofício (mêsma movimentação)
                    #    preenchidos ANTES do Concluir. ──
                    if envia_mp:
                        self._preencher_vistas_mp(
                            page, cod_nucleo_mp, tipo_parecer_mp,
                            prazo_mp, promotor_mp)
                    if solicitar_oficio:
                        self._preencher_solicitar_oficio(page, oficio_template_id)
                    if solicitar_mandado:
                        # Computar parte_nome baseando no polo (mandado_polo)
                        # reu_especifico -> tenta nome específico; fallback -> None (todos do polo)
                        polo_norm = str(mandado_polo or '').lower()
                        if polo_norm in ('reu_especifico', 'res', 'reus', 'róes',
                                         'executados', 'promovidos', 'autores', 'autoras'):
                            parte_nome = None  # todos do polo
                        else:
                            parte_nome = ''  # não filtrar
                        self._preencher_solicitar_mandado(
                            page, mandado_subtipo, parte_nome)

                    # ── Localizador na MESMA movimentação (se informado) ──
                    self._preencher_localizador(page, tipo_localizador, localizador)

                    time.sleep(2)

                    if nao_concluir:
                        print('   ⏸️ MODO TESTE (nao_concluir): tudo preenchido — '
                              'NÃO cliquei em Concluir. Revise e conclua manualmente.')
                        sucesso = True
                    else:
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
                    # ── Abrir painel de intimação e definir MOTIVO + PRAZO
                    # ANTES do Concluir (senão a movimentação não registra). ──
                    try:
                        pb = page.query_selector('#imgBotao_painelIntimacao')
                        if pb:
                            pb.click()
                            time.sleep(0.8)
                            print('   ✅ Painel de intimação aberto (FLUXO B)')
                        if marcar_autoras:
                            page.evaluate('''() => { const a = document.getElementById('Autoras'); if (a) a.click(); }''')
                            time.sleep(0.4)
                            page.evaluate(f'''() => {{
                                const m = document.getElementById('codMotivoAutor');
                                if (m) {{ m.value = '{motivo_intimacao}'; m.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                                const p = document.getElementById('codPrazoAutor');
                                if (p) p.value = '{prazo_intimacao}';
                            }}''')
                        else:
                            print('   ⏭️ Polo sem autoras — aba Autoras NÃO acionada (FLUXO B)')
                        if marcar_res:
                            page.evaluate('''() => { const r = document.getElementById('Res'); if (r) r.click(); }''')
                            time.sleep(0.4)
                            page.evaluate(f'''() => {{
                                const m = document.getElementById('codMotivoReu');
                                if (m) {{ m.value = '{motivo_intimacao}'; m.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                                const p = document.getElementById('codPrazoReu');
                                if (p) p.value = '{prazo_intimacao}';
                            }}''')
                        else:
                            print('   ⏭️ Polo sem réus — aba Rés NÃO acionada (FLUXO B)')
                        time.sleep(0.3)
                        print(f'   ✅ Motivo={motivo_intimacao}, prazo={prazo_intimacao} definidos ANTES do Concluir (FLUXO B)')
                    except Exception as e:
                        print(f'   ⚠️ Painel/motivo (FLUXO B): {e}')

                    # ── Vistas ao MP + solicitação de ofício (mêsma movimentação) ──
                    if envia_mp:
                        self._preencher_vistas_mp(
                            page, cod_nucleo_mp, tipo_parecer_mp,
                            prazo_mp, promotor_mp)
                    if solicitar_oficio:
                        self._preencher_solicitar_oficio(page, oficio_template_id)
                    if solicitar_mandado:
                        self._preencher_solicitar_mandado(
                            page, mandado_subtipo)

                    # ── Localizador na MESMA movimentação (se informado) ──
                    self._preencher_localizador(page, tipo_localizador, localizador)

                    # Concluir movimentação
                    if nao_concluir:
                        print('   ⏸️ MODO TESTE (nao_concluir): tudo preenchido — '
                              'NÃO cliquei em Concluir (FLUXO B). Revise manualmente.')
                        sucesso = True
                    else:
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

                    # FLUXO B encerra no painel (igual MovimentarAnalise):
                    # 581 → busca → grade → obs → Autoras/Rés (motivo+prazo) → Concluir.
                    sucesso = True

                # ═══════════════════════════════════════════════════
                # EXPEDIÇÃO PELOS CORREIOS (AR DIGITAL) — 2º clique
                # Após a intimação concluída, navega para o link genérico
                # (MovimentarProcessoAvancado), seleciona o modelo COJE no
                # select name="tipo" e clica em "expedir com ar digital".
                # ═══════════════════════════════════════════════════
                if nao_concluir:
                    print('   ⏸️ MODO TESTE: AR/expedição pulados (nada concluído).')
                    sucesso = True
                elif expedir_ar and sucesso:
                    sucesso = self._expedir_intimacao_ar(
                        page, proc_projudi, natureza_processo,
                        tipo_intimacao, codigo_tipo_ar,
                        assinar_ar=assinar_ar)

                browser.close()

        except Exception as e:
            print(f'   ❌ Erro no Playwright: {str(e)[:200]}')
            import traceback
            traceback.print_exc()
            # Guarda o erro p/ registrar no CumprimentoRecord (hoje os records
            # dessa função nascem SEM log — impossível fiscalizar o motivo).
            self._erro_mov = f'{type(e).__name__}: {str(e)[:300]}'
            sucesso = False

        # ── Registra no banco (CumprimentoRecord) para aparecer nos Cumprimentos ──
        try:
            from projudi.models import CumprimentoRecord
            # AR expedido mas NÃO assinado (assinar_ar=False ou falha na
            # assinatura) → fica 'pendente' (não conta como expedido de verdade)
            if getattr(self, '_ar_assinado', True):
                status = 'cumprido' if sucesso else 'falha'
                fluxo_just = ('Intimação eletrônica via DJEN (painel Autoras/Rés, '
                              'motivo+prazo, Concluir)')
            else:
                # Expediu o AR digital mas a assinatura não foi concluída
                status = 'pendente'
                fluxo_just = ('Intimação pelos Correios (AR digital): AR expedido '
                              'mas AGUARDANDO assinatura (assinar_ar=False ou '
                              'falha na assinatura)')
            record = CumprimentoRecord.objects.create(
                processo=proc_projudi or processo_numero[:20],
                numero_processo_cnj=processo_numero,
                fluxo='ar' if not getattr(self, '_ar_assinado', True) else 'eletronico',
                fluxo_justificativa=fluxo_just,
                act_verb='intimacao',
                snippet=observacao[:300],
                status=status,
                user=self.user if hasattr(self, 'user') else None,
            )
            print(f'   📝 Cumprimento #{record.id} registrado ({status})')
            # Log do desfecho — permite fiscalizar pelo CumprimentoLog (antes
            # os records dessa função nasciam SEM log, e o motivo da falha
            # ficava invisível mesmo a movimentação tendo entrado no Projudi).
            try:
                from projudi.models import CumprimentoLog
                msg = (f'{fluxo_just}. '
                       + (f'ERRO: {self._erro_mov} ' if getattr(self, '_erro_mov', None) else '')
                       + (f'sucesso={sucesso}')).strip()
                CumprimentoLog.objects.create(
                    cumprimento=record,
                    tipo='erro' if (getattr(self, '_erro_mov', None) or not sucesso) else 'info',
                    mensagem=msg,
                    detalhes={'sucesso': sucesso,
                              'erro': getattr(self, '_erro_mov', None) or '',
                              'cod_analise': cod_analise,
                              'polo': polo_intimacao},
                )
            except Exception as log_e:
                print(f'   ⚠️ Erro ao logar desfecho: {log_e}')
        except Exception as e:
            print(f'   ⚠️ Erro ao registrar cumprimento: {e}')

        return sucesso

    # =================================================================
    # FALLBACK DE MANDADO — EXPEDIR o mandado COMPLETO (tipoCumprimento=4
    # + subtipo + destinatário + CumprimentoCartorio + FCKeditor).
    # Usado quando fallback='mandado' vem com fallback_template_id no JSON.
    # =================================================================
    def _expedir_mandado_fallback(
        self,
        processo_numero: str,
        parte_nome: str,
        template_id: int,
        subtipo: str = '11',
        prazo: str = '',
        session=None,
        cookies_dict=None,
    ) -> bool:
        """Expende o mandado COMPLETO (igual ao passo `mandado`), delegando
        ao `_expedir_mandado`/`_gerar_html` do expedir_rapido."""
        from processes.models import Process, Party, DocumentTemplate, RAGExample
        from types import SimpleNamespace

        proc = Process.objects.filter(number=processo_numero).first()
        if not proc:
            print('   ⚠️ Fallback mandado: processo não encontrado no banco.')
            return False
        try:
            tmpl = DocumentTemplate.objects.get(id=template_id, active=True)
        except DocumentTemplate.DoesNotExist:
            print(f'   ⚠️ Fallback mandado: template #{template_id} não encontrado.')
            return False

        # Parte destinatária (réu/executado) — joga no banco se existir
        part = None
        qs = Party.objects.filter(process=proc,
                                  role__in=['reu', 'executado', 'PROMOVIDO', 'EXECUTADO'])
        if parte_nome:
            for p in qs:
                nome_p = (p.name or '').strip().upper()
                if parte_nome.upper() in nome_p or nome_p in parte_nome.upper():
                    part = p
                    break
        if not part:
            part = qs.first() or Party.objects.filter(process=proc).first()
        if not part:
            print('   ⚠️ Fallback mandado: nenhuma parte destinatária.')
            return False

        # RAG dummy (o fallback não tem despacho — usa template direto)
        rag = SimpleNamespace(despacho_ato='', despacho_observacao='',
                              despacho_data='', despacho_autor='MARTINHO FERRAZ DA NOBREGA JUNIOR')

        # Gera o HTML e expede (import lazy evita ciclo: expedir_rapido não
        # importa MovimentacaoService no topo).
        try:
            from expedir_rapido import _gerar_html, _expedir_mandado
            html_doc = _gerar_html(proc, part, rag, tmpl,
                                   prazo_dias=prazo or None)
            if not html_doc:
                print('   ⚠️ Fallback mandado: HTML não gerado.')
                return False
            print(f'   🚚 Fallback mandado: expedindo mandado COMPLETO '
                  f'tipoCumprimento=4, subtipo={subtipo}, dest={parte_nome[:50]}...')
            return _expedir_mandado(proc, session, cookies_dict, html_doc,
                                    part, subtipo=subtipo)
        except Exception as e:
            print(f'   ⚠️ Fallback mandado: {e}')
            import traceback; traceback.print_exc()
            return False

    # =================================================================
    # INTIMAÇÃO PELOS CORREIOS (AR DIGITAL)
    # =================================================================
    # Mapeamento natureza × finalidade → modelo COJE (select name="tipo"
    # da página MovimentarProcessoAvancado). "As mais usadas" (Ivan):
    #   geral → INTIMAÇÃO GERAL CÍVEL/CRIMINAL (12066/14032)
    #   audiencia → INTIMAÇÃO PARA AUDIÊNCIA CÍVEL/CRIMINAL (56061/55794)
    TABELA_TIPOS_AR = {
        ('civel', 'geral'):      ('12066', 'INTIMAÇÃO GERAL - CÍVEL'),
        ('criminal', 'geral'):   ('14032', 'INTIMAÇÃO GERAL - CRIMINAL'),
        ('civel', 'audiencia'):  ('56061', 'INTIMAÇÃO PARA AUDIÊNCIA CÍVEL'),
        ('criminal', 'audiencia'): ('55794', 'INTIMAÇÃO PARA AUDIÊNCIA CRIMINAL'),
    }

    def _preencher_vistas_mp(
        self, page, cod_nucleo_mp='31', tipo_parecer_mp='6',
        prazo_mp='5', promotor_mp=None,
    ) -> None:
        """Vistas ao MP na MESMA movimentação (ANTES do Concluir).

        Expande o painel envio órgão externo, marca enviaMP e seleciona
        Núcleo → tipo de parecer → prazo → promotor (via DWR).
        """
        import time as _t
        try:
            page.locator('#imgBotao_panelEnvioOrgaoExterno').first.click()
            _t.sleep(0.5)
            print('   ✅ Painel envio órgão externo expandido')
        except Exception:
            pass
        try:
            cb = page.locator('input[name="enviaMP"]')
            if cb.count():
                cb.check()
                print('   ✅ enviaMP marcado')
                _t.sleep(0.5)
        except Exception:
            pass
        try:
            sel_nucleo = page.locator('select[name="codNucleoMP"]')
            if sel_nucleo.count():
                sel_nucleo.select_option(cod_nucleo_mp)
                print(f'   ✅ Núcleo MP: {cod_nucleo_mp}')
                _t.sleep(0.8)  # DWR popula o promotor
        except Exception as e:
            print(f'   ⚠️ Núcleo MP: {e}')
        if tipo_parecer_mp is not None:
            try:
                sel_tp = page.locator('select[name="codTipoEnvioMP"]')
                if sel_tp.count():
                    sel_tp.select_option(str(tipo_parecer_mp))
                    print(f'   ✅ Tipo parecer MP: {tipo_parecer_mp}')
                    _t.sleep(0.3)
            except Exception as e:
                print(f'   ⚠️ Tipo parecer MP: {e}')
        if prazo_mp is not None:
            try:
                sel_pr = page.locator('select[name="codPrazoEnviaMP"]')
                if sel_pr.count():
                    sel_pr.select_option(str(prazo_mp))
                    print(f'   ✅ Prazo MP: {prazo_mp}')
                    _t.sleep(0.3)
            except Exception as e:
                print(f'   ⚠️ Prazo MP: {e}')
        if promotor_mp:
            try:
                nome_proc = str(promotor_mp).strip()
                sel_promotor = page.locator('select[name="loginPromotorNucleoMP"]')
                achou = False
                if sel_promotor.count():
                    for j in range(sel_promotor.locator('option').count()):
                        txt = sel_promotor.locator('option').nth(j).inner_text().strip()
                        if nome_proc.lower() in txt.lower():
                            val = sel_promotor.locator('option').nth(j).get_attribute('value')
                            sel_promotor.select_option(val)
                            print(f'   ✅ Promotor MP: {txt.strip()}')
                            achou = True
                            break
                if not achou:
                    print(f'   ⚠️ Promotor "{nome_proc}" não achado (núcleo {cod_nucleo_mp})')
            except Exception as e:
                print(f'   ⚠️ Promotor MP: {e}')

    def _preencher_solicitar_oficio(self, page, oficio_template_id=None) -> None:
        """Solicita a expedição do ofício na MESMA movimentação (ANTES do
        Concluir): adiciona a linha de cumprimento tipo OFÍCIO (12) no grid e
        seleciona o template quando oficio_template_id é dado (5 = CIAP,
        7 = RPV). Sem confecção (só a solicitação na movimentação)."""
        import time as _t
        try:
            # Abre o painel de cumprimento se ainda não estiver
            try:
                link_cump = page.locator("a:has-text('Cumprimento')").first
                if link_cump.count():
                    link_cump.click()
                    _t.sleep(0.4)
            except Exception:
                pass
            # Linha de cumprimento tipo OFÍCIO (12)
            page.select_option('#tipoCumprimento', '12')
            _t.sleep(0.3)
            print('   ✅ Linha de cumprimento: Ofício (tipoCumprimento=12)')
            # Seleciona o template/ofício no grid de documento quando id dado
            if oficio_template_id:
                try:
                    # codTipoDocumento do ofício: CIAP=5, RPV=7 → o
                    # código do select não é o id do template; busca
                    # pela descrição do template.
                    from processes.models import DocumentTemplate
                    tmpl = DocumentTemplate.objects.filter(
                        id=oficio_template_id, active=True).first()
                    if tmpl:
                        sel_td = page.locator('select[name="codTipoDocumento"]')
                        if sel_td.count():
                            desc_alvo = tmpl.name.lower()
                            valor = None
                            for opt in sel_td.locator('option').all():
                                t = (opt.inner_text() or '').strip()
                                if t and desc_alvo in t.lower():
                                    valor = opt.get_attribute('value')
                                    break
                            if valor:
                                sel_td.select_option(valor)
                                print(f'   ✅ Ofício selecionado: {tmpl.name}')
                                _t.sleep(0.3)
                except Exception as e:
                    print(f'   ⚠️ Template ofício: {e}')
            # Adiciona a linha (btnAddCumprimento)
            page.click('#btnAddCumprimento')
            _t.sleep(0.8)
            print('   ✅ Cumprimento de ofício adicionado')
        except Exception as e:
            print(f'   ⚠️ Solicitação de ofício: {e}')

    def _preencher_localizador(
            self, page, tipo_localizador: str = '', localizador: str = '') -> None:
        """Aplica o localizador na MESMA movimentação (ANTES do Concluir).

        Padrão que FUNCIONA (igual ao fluxo `localizar`): expande o painel
        #imgBotao_panelLocalizador, seta o #codTipoLocalizador por JS com
        dispatchEvent('change') e CLICA no botão "Adicionar"
        (img[src*="bot-adicionar"]) para persistir na lista — só select_option
        NÃO salva. Depois recolhe o painel.
        """
        if not tipo_localizador and not localizador:
            return
        import time as _t
        # Expande painel de localizadores (via JS, mais robusto)
        try:
            page.evaluate('''() => {
                var btn = document.getElementById('imgBotao_panelLocalizador');
                if (btn) btn.click();
            }''')
            _t.sleep(0.5)
            print('   📍 Painel localizador expandido')
        except Exception:
            pass

        if tipo_localizador:
            # Pre-check: só adiciona se NÃO tiver (linha da tabela por código)
            ja_tem = False
            try:
                linha = page.locator(f'#trTbTipoLocalizador{tipo_localizador}')
                ja_tem = linha.count() > 0
            except Exception:
                ja_tem = False
            if ja_tem:
                print(f'   ✅ Localizador {tipo_localizador} já está na lista — '
                      'não duplica')
            else:
                try:
                    page.evaluate(f'''() => {{
                        var sel = document.getElementById('codTipoLocalizador');
                        if (sel) {{ sel.value = '{tipo_localizador}';
                            sel.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                    }}''')
                    print(f'   📍 Tipo localizador selecionado: {tipo_localizador}')
                    _t.sleep(0.3)
                    # Clica botão "Adicionar" localizador (persiste na lista)
                    try:
                        btn_add = page.locator('img[src*="bot-adicionar"]')
                        if btn_add.count():
                            btn_add.click()
                            print('   ✅ Localizador adicionado à lista')
                            _t.sleep(0.5)
                    except Exception:
                        print('   ⚠️ Botão "Adicionar" localizador não encontrado')
                except Exception as e:
                    print(f'   ⚠️ Tipo localizador: {e}')

        if localizador:
            try:
                page.evaluate(f'''() => {{
                    var sel = document.getElementById('codLocalizador');
                    if (sel) {{ sel.value = '{localizador}';
                        sel.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                }}''')
                print(f'   📍 Localizador: {localizador}')
                _t.sleep(0.3)
            except Exception:
                pass

        # Recolhe painel (se ainda estiver aberto)
        try:
            page.evaluate('''() => {
                var btn = document.getElementById('imgBotao_panelLocalizador');
                if (btn) btn.click();
            }''')
            _t.sleep(0.3)
        except Exception:
            pass

    def _preencher_solicitar_mandado(
            self, page, mandado_subtipo: str = '3', parte_nome: 'str | None' = '') -> None:
        """Solicita a expedição do mandado na MESMA movimentação (ANTES do
        Concluir): adiciona a linha de cumprimento tipo MANDADO (4) +
        subtipoCumprimento + destinatário no grid — SEM criar uma Mov581
        extra. Independe de MP/ofício (pode vir sozinho)."""
        import time as _t
        try:
            # Abre o painel de cumprimento se ainda não estiver
            # (pode já estar aberto do ofício acima)
            try:
                link_cump = page.locator("a:has-text('Cumprimento')").first
                if link_cump.count():
                    link_cump.click()
                    _t.sleep(0.4)
            except Exception:
                pass
            # Linha de cumprimento tipo MANDADO (4) + subtipo
            page.select_option('#tipoCumprimento', '4')
            _t.sleep(0.3)
            subtipo = mandado_subtipo or '3'
            st = page.locator(
                '#subtipoCumprimento, select[name="subtipoCumprimento"]').first
            if st.count():
                st.select_option(subtipo)
                _t.sleep(0.3)
            print(f'   ✅ Linha de cumprimento: Mandado (tipoCumprimento=4, '
                  f'subtipo={subtipo})')
            # Seleciona o(s) destinatário(s) — #codigoDestinatario é SINGLE-SELECT.
            # Padrão correto (igual ao _expedir_mandado): para CADA destinatário:
            #   seleciona UM → clica btnAddCumprimento (um mandado por parte).
            # 1º) Tenta casar parte_nome; se não achar → usa TODAS as opções.
            try:
                sel_dest = page.locator(
                    '#codigoDestinatario, select[name="codigoDestinatario"]').first
                if not sel_dest.count():
                    print('   ⚠️ Select de destinatário não encontrado')
                    return
                opts = sel_dest.locator('option').all()
                # Lista (texto, value) ignorando placeholders
                alvos = []
                for opt in opts:
                    ot = (opt.inner_text() or '').strip()
                    ov = opt.get_attribute('value') or ''
                    if not ot or ot.lower().startswith('selecione'):
                        continue
                    if ot.lower().startswith('outro destinatar'):
                        continue
                    if ov and ov not in ('-1', '-2'):
                        alvos.append((ot, ov))
                # Filtra pelo nome específico se informado
                if parte_nome and alvos:
                    alvo = parte_nome.upper()
                    filtrados = [(t, v) for t, v in alvos
                                 if alvo in t.upper() or t.upper() in alvo]
                    if filtrados:
                        alvos = filtrados
                        print(f'   ✅ Filtrando por nome: {parte_nome[:40]}')
                    else:
                        print(f'   ⚠️ "{parte_nome[:40]}" não achado → '
                              f'fallback: todos do polo')
                # Loop: seleciona UM + clica Add Cumprimento
                adicionados = 0
                for ot, ov in alvos:
                    try:
                        page.select_option('#codigoDestinatario', ov)
                        _t.sleep(0.3)
                        page.click('#btnAddCumprimento')
                        _t.sleep(0.8)
                        adicionados += 1
                        print(f'   ✅ Mandado destinatário: {ot[:50]} ({ov})')
                    except Exception as e:
                        print(f'   ⚠️ Destinatário {ot[:40]}: {e}')
                if not adicionados:
                    print(f'   ❌ Nenhum destinatário selecionado — '
                          f'mandado NÃO adicionado')
            except Exception as e:
                print(f'   ⚠️ Erro ao selecionar destinatário: {e}')
        except Exception as e:
            print(f'   ⚠️ Solicitação de mandado: {e}')

    def executar_com_intimacao_ar(
        self,
        processo_numero: str,
        observacao: str,
        codigo_mov: str = '581',
        descricao_mov: str = 'Intimação',
        cookies_dict: dict = None,
        proc_projudi: str = None,
        prazo_intimacao: str = '3',
        motivo_intimacao: str = '3',
        tipo_intimacao: str = 'geral',
        codigo_tipo_ar: str = None,
        natureza_override: str = None,
        assinar_ar: bool = True,
    ) -> bool:
        """Executa a intimação PELOS CORREIOS (AR digital) no Projudi.

        Fluxo completo (feito pelo FluxoDecisor quando o melhor meio é 'ar'):
          1. Mov581 + observação + seleciona "Intimação" + painel Autoras/Rés
             (motivo+prazo) + Concluir  — igual à intimação eletrônica;
          2. SEGUNDO clique: navega para o link genérico
             MovimentarProcessoAvancado, seleciona o modelo COJE no select
             name="tipo" (conforme natureza cível/criminal e finalidade
             geral/audiência) e clica em "expedir com ar digital";
          3. Na página ExpedirIntimacao?codIntimacao=...&arDigital=true,
             assina (senha automática via User.projudi_password ou manual) —
             a menos que assinar_ar=False (só expede, sem assinar).

        Args:
            tipo_intimacao: 'geral' (default) ou 'audiencia'.
            codigo_tipo_ar: Código COJE direto (override) — ex '12066'.
            natureza_override: 'civel' ou 'criminal' (senão detecta via
                          extrair_classe no pre-check).
            assinar_ar: False → expede o AR mas NÃO assina (deixa a página
                          aberta para assinatura manual).
        """
        return self.executar_com_intimacao(
            processo_numero=processo_numero,
            observacao=observacao,
            codigo_mov=codigo_mov,
            descricao_mov=descricao_mov,
            cookies_dict=cookies_dict,
            proc_projudi=proc_projudi,
            prazo_intimacao=prazo_intimacao,
            motivo_intimacao=motivo_intimacao,
            expedir_ar=True,
            tipo_intimacao=tipo_intimacao or 'geral',
            codigo_tipo_ar=codigo_tipo_ar,
            natureza_override=natureza_override,
            assinar_ar=assinar_ar,
        )

    def _expedir_intimacao_ar(self, page, proc_projudi, natureza,
                              tipo_intimacao, codigo_tipo_ar=None,
                              assinar_ar: bool = True) -> bool:
        """2º clique: expede a intimação criada pelos CORREIOS com AR digital.

        Navega para o link genérico do processo (MovimentarProcessoAvancado),
        acha a intimação recém-criada, seleciona o modelo COJE no select
        name="tipo" e clica no link "expedir com ar digital". Em seguida
        cai na página ExpedirIntimacao e assina (senha ou manual).
        """
        import time as _t
        if not proc_projudi:
            print('   ⚠️ Sem proc_projudi p/ expedir por AR.')
            return False

        # ── 1. Resolve o código do tipo COJE ──
        cod_tipo = codigo_tipo_ar or ''
        texto_tipo = ''
        if not cod_tipo:
            chave = (str(natureza or 'civel'), str(tipo_intimacao or 'geral'))
            pair = self.TABELA_TIPOS_AR.get(chave)
            if pair:
                cod_tipo, texto_tipo = pair
            else:
                # Fallback: geral cível
                cod_tipo, texto_tipo = self.TABELA_TIPOS_AR[('civel', 'geral')]
        print(f'   🏷️ Modelo COJE: {cod_tipo}{" — " + texto_tipo if texto_tipo else ""}')

        # ── 2. Navega para a página de movimentação genérica ──
        try:
            url_avancado = (
                'https://projudi.tjba.jus.br/projudi/movimentacao/'
                f'MovimentarProcessoAvancado?numeroProcesso={proc_projudi}')
            page.goto(url_avancado, wait_until='load')
            _t.sleep(3)
        except Exception as e:
            print(f'   ⚠️ Ao abrir MovimentarProcessoAvancado: {e}')
            return False

        # ── 3. Localiza o select name="tipo" + link "expedir com ar digital" ──
        # Pode haver vários (uma linha por cumprimento pendente). A
        # intimação recém-criada é a última do DOM. Cada select vive no
        # mesmo container (tr) que o link de expedição.
        alvos = []
        try:
            for i in range(page.locator('select[name="tipo"]').count()):
                sel = page.locator('select[name="tipo"]').nth(i)
                container = sel.locator('xpath=ancestor::tr[1]')
                link_ar = container.locator(
                    'a:has-text("expedir"), a:has-text("Expedir"), '
                    'a:has-text("AR"), a:has-text("ar")')
                if link_ar.count():
                    alvos.append((sel, link_ar))
        except Exception as e:
            print(f'   ⚠️ Localizando selects tipo: {e}')

        if not alvos:
            # Fallback: varre frames e acha qualquer link "expedir ... ar"
            print('   ⚠️ Nenhuma linha com select tipo+expedir achada —' \
                  ' tentando fallback genérico...')
            try:
                for fr in page.frames:
                    cand = fr.locator(
                        'a:has-text("expedir"), a:has-text("Expedir")').last
                    if cand.count():
                        alvos.append((cand, cand))
                        break
            except Exception:
                pass

        if not alvos:
            print('   ❌ Não achei o select name="tipo" com link de expedição AR.')
            return False

        # Usa a ÚLTIMA linha (recém-criada)
        sel, link_ar = alvos[-1]
        _t.sleep(0.5)

        # ── 4. Seleciona o modelo COJE no select ──
        try:
            selado = False
            # Seletor por value (código exato) primeiro
            try:
                op = sel.locator(f'option[value="{cod_tipo}"]')
                if op.count():
                    sel.select_option(cod_tipo)
                    selado = True
            except Exception:
                pass
            if not selado and texto_tipo:
                # Fallback: procura opção por texto
                for j in range(sel.locator('option').count()):
                    txt = sel.locator('option').nth(j).inner_text().strip()
                    if texto_tipo.lower() in txt.lower():
                        sel.select_option(index=j)
                        selado = True
                        break
            if not selado:
                # Última opção como fallback
                n_opts = sel.locator('option').count()
                if n_opts:
                    sel.select_option(index=n_opts - 1)
                    selado = True
            print(f'   ✅ Tipo selecionado no select name="tipo"'
                  f' {"(" + cod_tipo + ")" if selado else ""}')
            _t.sleep(1)
        except Exception as e:
            print(f'   ⚠️ Selecionando modelo COJE: {e}')

        # ── 5. Clica em "expedir com ar digital" ──
        clicado = False
        # Prioriza o link dentro do mesmo container do select; senão varre
        # a página. "expedir com ar digital" é o alvo mais específico.
        seletores = ['a:has-text("expedir com ar digital")',
                     'a:has-text("expedir com AR digital")',
                     'a:has-text("Expedir com AR")',
                     'a:has-text("expedir")',
                     'a:has-text("Expedir")']
        for base in [link_ar, page]:
            for sel_link in seletores:
                try:
                    el = base.locator(sel_link).last if hasattr(base, 'locator') else base
                    if el.count():
                        try:
                            el.scroll_into_view_if_needed()
                            _t.sleep(0.5)
                        except Exception:
                            pass
                        el.click(timeout=8000)
                        clicado = True
                        break
                except Exception:
                    continue
            if clicado:
                break
        time.sleep(2)

        if not clicado:
            print('   ⚠️ Link "expedir com ar digital" não encontrado.')
            return False

        # ── 6. Verifica que caiu na ExpedirIntimacao e assina ──
        chegou = 'ExpedirIntimacao' in page.url or 'codIntimacao' in page.url
        if not chegou:
            try:
                page.wait_for_url(lambda u: 'ExpedirIntimacao' in u
                                  or 'codIntimacao' in u, timeout=15000)
                chegou = True
            except Exception:
                pass
        if not chegou:
            print(f'   ⚠️ Não caiu na ExpedirIntimacao (URL: {page.url[:100]})')
            return False

        print(f'   🚚 ExpedirIntimacao aberta — assinando o AR...')
        if not assinar_ar:
            print('   ⏸️ assinar_ar=False — NÃO vou assinar.')
            print('   ⏳ A página ExpedirIntimacao ficou aberta — assine')
            print('   ⏳ manualmente (senha + Assinar) se quiser concluir.')
            try:
                page.screenshot(path='/tmp/intimacao_ar_pendente.png')
                print('   📸 Screenshot: /tmp/intimacao_ar_pendente.png')
            except Exception:
                pass
            if sys.stdout.isatty():
                try:
                    input('   🔄 Pressione Enter após assinar manualmente (ou '
                          'feche o navegador)...')
                except Exception:
                    pass
            time.sleep(3)
            self._ar_assinado = False
            return True
        ok_ass = self._assinar_expedicao_ar(page)
        self._ar_assinado = bool(ok_ass)
        time.sleep(2)
        if ok_ass:
            print('   ✅ AR digital assinado e expedido pelos correios.')
        else:
            print('   ⚠️ AR expedido, mas assinatura pode ter ficado pendente.')
            self._ar_assinado = False
        return True  # expedição ocorreu; assinatura reportada no log

    def _assinar_expedicao_ar(self, page) -> bool:
        """Assina o documento na página ExpedirIntimacao.

        Reusa o padrão das certidões: senha automática via
        User.projudi_password; senão cai no modo manual (espera o usuário).
        """
        import time as _t
        senha = getattr(self.user, 'projudi_password', None)

        # Rola para o final (o botão Assinar fica no fim da página; o
        # usuário não consegue scroll manual confiável no Firefox do PW).
        try:
            page.evaluate('''() => {
                var alvo = document.querySelector('img[src*="bot-assinar"]') ||
                           document.querySelector('input[value="Assinar"]') ||
                           document.querySelector('button:has-text("Assinar")');
                window.scrollTo(0, document.body.scrollHeight);
                if (alvo) { alvo.scrollIntoView({block:'center'}); }
            }''')
            _t.sleep(0.8)
        except Exception:
            pass

        if not senha:
            print('   ⏳ Sem User.projudi_password — ASSINE MANUALMENTE o AR.')
            print('   ⏳ Digite a senha e clique em Assinar (até 3 min).')
            try:
                page.locator('img[src*="bot-assinar"]').first.click(timeout=3000)
            except Exception:
                pass
            try:
                page.screenshot(path='/tmp/intimacao_ar_assinatura.png')
                print('   📸 Screenshot: /tmp/intimacao_ar_assinatura.png')
            except Exception:
                pass
            if sys.stdout.isatty():
                try:
                    input('   🔄 Pressione Enter APÓS assinar o AR (ou aguarde)...')
                except Exception:
                    pass
            # Espera o usuário assinar (assina novamente ou muda de página)
            _t.sleep(5)
            return True

        # Senha automática
        try:
            page.locator('img[src*="bot-assinar"]').first.click(timeout=4000)
            _t.sleep(1)
            print('   ✅ Assinar 1ª (automático)')
        except Exception:
            pass
        _logar_frames(page)
        camp = _procurar_campo_senha(page, timeout=10)
        if camp:
            try:
                camp.fill(senha)
                _t.sleep(0.5)
                print('   ✅ Senha preenchida')
            except Exception as e:
                print(f'   ⚠️ Preenchendo senha: {e}')
        else:
            print('   ⚠️ Campo senha não apareceu em 10s')
        ok = _clicar_botao_assinar(page)
        if ok:
            _t.sleep(2)
            print('   ✅ Assinar 2ª (automático)')
        else:
            print('   ⚠️ Botão Assinar 2ª (automático) não achado')
        return ok

    # =================================================================
    # FECHAR
    # =================================================================
    def fechar(self):
        try:
            self.projudi_service.fechar()
        except Exception:
            pass
