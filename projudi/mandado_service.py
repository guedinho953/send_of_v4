"""
MandadoService - Orquestra busca e expedição de mandados no Projudi.

Fluxo:
1. Pega cookies salvos no Django (ProjudiSession)
2. Acessa CumprimentoCartorio?tipo=mandado&acao=expedir
3. Navega nas páginas e extrai mandados pendentes
4. Para cada mandado:
   a) Extrai dados (número, processo, URLs)
   b) Salva no banco (MandadoRecord)
   c) Registra log (MandadoLog)
"""

import re
import sys
from datetime import datetime
from typing import List, Dict, Optional

from django.conf import settings

PROJECT_ROOT = str(settings.BASE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from .models import MandadoRecord, MandadoLog
from .services import ProjudiService


class MandadoService:
    """Serviço de orquestração de mandados."""

    URL_MANDADOS = "https://projudi.tjba.jus.br/projudi/listagens/CumprimentoCartorio?tipo=mandado&acao=expedir"

    def __init__(self, user):
        self.user = user
        self.projudi_service = ProjudiService(user)

    # ------------------------------------------------------------------
    # BUSCA
    # ------------------------------------------------------------------
    def buscar_mandados_pendentes(self, quantidade: int = 3) -> List[Dict]:
        """
        Busca mandados pendentes no Projudi.
        Usa a sessão salva para acessar CumprimentoCartorio?tipo=mandado&acao=expedir.
        """
        result = self.projudi_service._get_session_from_cookie_jar()
        if result is None:
            raise Exception(
                "Sessão do Projudi não disponível. "
                "Sincronize a sessão primeiro (Sessão > Sincronizar)."
            )

        session = result
        import requests
        from bs4 import BeautifulSoup

        # Aquece a sessão
        session.get("https://projudi.tjba.jus.br/projudi/cadastros/AnalisarMovimentacao")

        # Acessa a listagem de mandados
        resp = session.get(self.URL_MANDADOS, timeout=15)
        if resp.status_code != 200:
            raise Exception(f"Erro ao acessar mandados: HTTP {resp.status_code}")

        expirou = 'sess\u00e3o expirou' in resp.text.lower()
        if expirou or len(resp.text) < 500:
            raise Exception("Sessão do Projudi expirada. Sincronize novamente.")

        soup = BeautifulSoup(resp.text, 'html.parser')

        # Descobre última página
        ultima = self._obter_ultima_pagina(soup)
        paginas = self._gerar_paginas_finais(ultima, quantidade)

        # Busca mandados de cada página
        mandados = []
        for pagina in paginas:
            data = {
                'tipo': 'mandado',
                'acao': 'expedir',
                'codTipoJustica': '2',
                'pagina': str(pagina),
                'coluna': 'CumprimentoCartorio.CODCUMPRIMENTO',
                'ordem': 'ASC',
            }
            page_resp = session.post(self.URL_MANDADOS, data=data, timeout=15)
            if page_resp.status_code != 200:
                continue

            page_soup = BeautifulSoup(page_resp.text, 'html.parser')
            links = self._extrair_links_mandados(page_soup)

            if not links:
                continue

            # Extrai informações de cada mandado
            oficios_links = links.get('oficios', [])
            processos_links = links.get('processos', [])
            textos = links.get('textos_processos', [])

            for i, url_mandado in enumerate(oficios_links):
                url_proc = processos_links[i] if i < len(processos_links) else ''
                match = re.search(r'numeroProcesso=([^&]+)', url_proc)
                processo = match.group(1) if match else ''
                processo_cnj = textos[i] if i < len(textos) else ''

                # Extrai número do mandado e nome da parte da URL/texto
                numero_mandado = self._extrair_numero_mandado(url_mandado, url_proc)
                parte_nome = textos[i] if i < len(textos) else ''

                mandados.append({
                    'processo': processo,
                    'processo_cnj': processo_cnj,
                    'numero_mandado': numero_mandado,
                    'url_mandado': url_mandado,
                    'url_processo': url_proc,
                    'parte_nome': parte_nome,
                })

        return mandados

    def extrair_mandado(self, dados: Dict) -> Optional[Dict]:
        """
        Faz GET no URL do mandado e extrai dados.
        """
        result = self.projudi_service._get_session_from_cookie_jar()
        if result is None:
            return None
        session = result

        url_mandado = dados.get('url_mandado')
        if not url_mandado:
            return None

        resp = session.get(url_mandado, timeout=15)
        if resp.status_code != 200:
            return None

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Tenta extrair nome da parte do HTML do mandado
        parte_nome = dados.get('parte_nome', '')
        if not parte_nome:
            # Tenta extrair do texto da página
            texto = soup.get_text(' ', strip=True)
            m = re.search(r'(?:parte|destinat[áa]rio)[:\s]+([A-ZÀ-Ú\s]{5,80})', texto, re.I)
            if m:
                parte_nome = m.group(1).strip()

        return {
            'processo': dados.get('processo', ''),
            'processo_cnj': dados.get('processo_cnj', ''),
            'numero_mandado': dados.get('numero_mandado', ''),
            'url_mandado': url_mandado,
            'url_processo': dados.get('url_processo', ''),
            'parte_nome': parte_nome,
            'texto_html': resp.text[:10000],
        }

    # ------------------------------------------------------------------
    # PERSISTENCIA
    # ------------------------------------------------------------------
    def importar_mandado(self, mandado_data: Dict) -> MandadoRecord:
        """Cria ou atualiza MandadoRecord no banco."""
        record, created = MandadoRecord.objects.update_or_create(
            processo=mandado_data.get('processo', ''),
            numero_mandado=mandado_data.get('numero_mandado', ''),
            defaults={
                'numero_processo_cnj': mandado_data.get('processo_cnj', ''),
                'status': 'pendente',
                'url_mandado': mandado_data.get('url_mandado', ''),
                'url_processo': mandado_data.get('url_processo', ''),
                'parte_nome': mandado_data.get('parte_nome', ''),
                'texto_html': mandado_data.get('texto_html', ''),
                'user': self.user,
            },
        )

        MandadoLog.objects.create(
            mandado=record,
            tipo='info',
            mensagem=f"{'Importado' if created else 'Atualizado'} do Projudi. Mandado {record.numero_mandado}.",
        )

        return record

    def expedir_mandado(self, record: MandadoRecord) -> Dict:
        """Marca mandado como expedido (simulação - a expedição real é manual pelo Projudi)."""
        record.status = 'expedido'
        record.save(update_fields=['status'])

        MandadoLog.objects.create(
            mandado=record,
            tipo='expedicao',
            mensagem=f"Mandado {record.numero_mandado} expedido.",
        )

        return {'expedido': True, 'mandado': record}

    def solicitar_expedicao(self, record: MandadoRecord) -> Dict:
        """
        Abre Playwright e faz SOMENTE o Mov 581 (Solicitada a Expedição de Mandado),
        SEM confeccionar o documento no FCKeditor.
        """
        import time, re
        from playwright.sync_api import sync_playwright
        from urllib.parse import urlparse, parse_qs
        import requests

        # 1. Descobrir número Projudi do processo
        PROC_PROJUDI = None
        if record.url_processo:
            m = re.search(r'numeroProcesso=(\d+)', record.url_processo)
            if m:
                PROC_PROJUDI = m.group(1)

        if not PROC_PROJUDI:
            # Tenta pelo CNJ via consulta
            session = self.projudi_service._get_session_from_cookie_jar()
            if session and record.numero_processo_cnj:
                r = session.post(
                    'https://projudi.tjba.jus.br/projudi/processo/consultaProcesso',
                    data={'numeroProcesso': record.numero_processo_cnj}, timeout=15
                )
                if r.status_code == 200:
                    qs = parse_qs(urlparse(r.url).query)
                    PROC_PROJUDI = qs.get('numeroProcesso', [None])[0]

        if not PROC_PROJUDI:
            return {'expedido': False, 'erro': 'Número Projudi do processo não encontrado'}

        # 2. Capturar sessão e cookies
        result = self.projudi_service._get_session_from_cookies()
        if not result:
            return {'expedido': False, 'erro': 'Sessão do Projudi não disponível. Sincronize primeiro.'}

        _, cookies_dict = result

        parte_nome = record.parte_nome or 'parte'
        sucesso = False
        browser = None
        try:
            with sync_playwright() as pw:
                browser = pw.firefox.launch(headless=False, slow_mo=500)
                ctx_b = browser.new_context(viewport={'width': 1500, 'height': 950}, locale='pt-BR')
                ctx_b.add_cookies([
                    {'name': k, 'value': v, 'domain': 'projudi.tjba.jus.br', 'path': '/'}
                    for k, v in cookies_dict.items()
                ])
                page = ctx_b.new_page()

                # ── MOV 581: Solicitar Expedição ──────────────────
                url_mov = f'https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso={PROC_PROJUDI}'
                page.goto(url_mov, wait_until='load')
                time.sleep(3)

                if not page.evaluate('!!document.getElementById("seqCategoriaMovimentacao")'):
                    browser.close()
                    return {'expedido': False, 'erro': 'Formulário de movimentação não encontrado (sessão expirou?)'}

                # Injetar Mov 581
                page.evaluate('''() => {
                    var c = document.getElementById('seqCategoriaMovimentacao');
                    if (c) c.value = '581';
                    var d = document.getElementById('descCategoriaMovimentacao');
                    if (d) d.value = 'Solicitada a Expedição de Mandado';
                    var tr = document.getElementById('trTipoDocumento');
                    if (tr) tr.style.display = 'table-row';
                    var div = document.getElementById('rowDadosMovimentacaoComplemento');
                    if (div) div.style.display = 'block';
                    var p = document.getElementById('divPanelCumprimento');
                    if (p) p.style.display = 'block';
                }''')
                time.sleep(1)

                page.select_option('select[name="codTipoDocumento"]', '51')
                time.sleep(1)
                page.fill('#observacao', f'Solicitada Expedicao de Mandado - {parte_nome[:30]}')
                time.sleep(0.5)

                # Aba Cumprimento
                page.locator("a:text('Cumprimento')").first.click()
                time.sleep(1)
                page.select_option('#tipoCumprimento', '4')  # 4 = Mandado
                time.sleep(0.5)

                # Subtipo: tentar Intimação (3), fallback para primeira opção
                try:
                    st = page.locator('#subtipoCumprimento, select[name="subtipoCumprimento"]').first
                    if st.count():
                        st.select_option('3')
                except Exception:
                    pass

                # Seleciona destinatário
                nome_dest = parte_nome
                if nome_dest:
                    try:
                        opt = page.locator(f'#codigoDestinatario option:text("{nome_dest}")').first
                        if opt.count():
                            val = opt.get_attribute('value')
                            page.select_option('#codigoDestinatario', val)
                    except Exception:
                        pass

                page.click('#btnAddCumprimento')
                time.sleep(1)

                # Concluir
                page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                time.sleep(0.5)
                page.click('#Concluir')
                time.sleep(2)

                # Aceitar alerta
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

                sucesso = True
                print(f'   ✅ Mov 581 concluído para {record.numero_mandado}')

        except Exception as e:
            return {'expedido': False, 'erro': f'Erro no Playwright: {str(e)[:200]}'}
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass

        if sucesso:
            record.status = 'expedido'
            record.save(update_fields=['status'])
            MandadoLog.objects.create(
                mandado=record,
                tipo='expedicao',
                mensagem=f"Solicitação de expedição realizada (Mov 581) - Mandado {record.numero_mandado}",
                detalhes={'etapa': 'solicitar_expedicao', 'projudi': PROC_PROJUDI},
            )
            return {'expedido': True, 'mandado': record, 'projudi': PROC_PROJUDI}

        return {'expedido': False, 'erro': 'Falha ao concluir Mov 581'}

    def dispensar_mandado(self, record: MandadoRecord) -> Dict:
        """Marca mandado como dispensado."""
        record.status = 'dispensado'
        record.save(update_fields=['status'])

        MandadoLog.objects.create(
            mandado=record,
            tipo='info',
            mensagem=f"Mandado {record.numero_mandado} dispensado por {self.user.full_name}.",
        )

        return {'dispensado': True, 'mandado': record}

    def criar_log(self, mandado: MandadoRecord, tipo: str, mensagem: str, detalhes: dict = None):
        MandadoLog.objects.create(
            mandado=mandado,
            tipo=tipo,
            mensagem=mensagem,
            detalhes=detalhes or {},
        )

    def logs_humanizados(self, mandado: MandadoRecord) -> List[Dict]:
        return list(
            MandadoLog.objects.filter(mandado=mandado)
            .values('tipo', 'mensagem', 'created_at')
            .order_by('-created_at')
        )

    def fechar(self):
        try:
            self.projudi_service.fechar()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------
    def _obter_ultima_pagina(self, soup) -> int:
        """Extrai o número da última página da paginação."""
        from bs4 import BeautifulSoup
        pag_links = soup.find_all('a', href=lambda x: x and 'pagina=' in x)
        nums = []
        for a in pag_links:
            m = re.search(r'pagina=(\d+)', a.get('href', ''))
            if m:
                nums.append(int(m.group(1)))
        return max(nums) if nums else 1

    def _gerar_paginas_finais(self, ultima: int, quantidade: int = 3) -> List[int]:
        """Gera lista de números de página (últimas N)."""
        if ultima <= 1:
            return [1]
        inicio = max(1, ultima - quantidade + 1)
        return list(range(inicio, ultima + 1))

    def _extrair_links_mandados(self, soup) -> Dict:
        """Extrai links de mandados, processos e textos de uma página."""
        from urllib.parse import urljoin
        base = 'https://projudi.tjba.jus.br/projudi/'

        oficios = []
        processos = []
        recebimentos = []
        baixas = []
        textos_processos = []

        for a in soup.find_all('a', href=True):
            href = a['href']
            texto = a.get_text(strip=True)

            url = urljoin(base, href)

            if 'ExpedirCumprimentoCartorio' in href:
                oficios.append(url)
                if texto:
                    textos_processos.append(texto)
            elif 'DadosProcesso' in href and 'numeroProcesso' in href:
                processos.append(url)

        return {
            'oficios': oficios,
            'processos': processos,
            'recebimentos': recebimentos,
            'baixas': baixas,
            'textos_processos': textos_processos,
        }

    def _extrair_numero_mandado(self, url_mandado: str, url_processo: str) -> str:
        """Tenta extrair número do mandado das URLs."""
        m = re.search(r'ExpedirCumprimentoCartorio\?.*?(?:codCumprimento|id)=(\d+)', url_mandado)
        if m:
            return f"MAN-{m.group(1)}"
        return ''
