"""
Comando para rastrear movimentações e expedir mandados.
Similar ao fluxo de ofícios (expedir_humanizado.py).

Uso:
  python manage.py rastrear_mandados
  python manage.py rastrear_mandados --processo 0000799-32.2026.8.05.0191
  python manage.py rastrear_mandados --dry-run
"""

import re, sys
from datetime import datetime, date
from urllib.parse import urljoin, urlparse, parse_qs

from django.conf import settings
from django.core.management.base import BaseCommand
from django.template import Template, Context
from django.db.models import Max


class Command(BaseCommand):
    help = 'Varre movimentações, compara com RAG e expede mandados'

    def add_arguments(self, parser):
        parser.add_argument('--processo', type=str,
                            help='CNJ do processo específico')
        parser.add_argument('--projudi', type=str,
                            help='Número interno do Projudi (opcional, resolve automático)')
        parser.add_argument('--dry-run', action='store_true',
                            help='Apenas mostra o que faria')

    def handle(self, *args, **options):
        filtro_processo = options.get('processo')
        projudi_num = options.get('projudi')
        dry_run = options.get('dry_run', False)

        from accounts.models import User
        from projudi.services import ProjudiService
        from processes.models import RAGExample, DocumentTemplate, Process, Party
        from projudi.models import MandadoRecord
        from processes.movimentacoes_service import buscar_cumprimentos_similares

        user = User.objects.filter(is_active=True).first()
        if not user:
            return self.stderr.write(self.style.ERROR('Nenhum usuário ativo'))

        # Sessão Projudi (4 camadas)
        service = ProjudiService(user)
        result = service._get_session_from_cookies()
        if not result:
            return self.stderr.write(self.style.ERROR(
                'Não foi possível capturar a sessão do Projudi.\n'
                'Deixe o Firefox aberto e logado no Projudi.'))
        session, cookies = result

        # Templates mandado ativos
        templates_mandado = DocumentTemplate.objects.filter(
            template_type='mandado', active=True)
        if not templates_mandado.exists():
            return self.stderr.write(self.style.WARNING(
                'Nenhum template mandado ativo. Crie um em Modelos de Documento.'))

        from bs4 import BeautifulSoup
        from projudiProcessNavigator import ProcessoParser

        expedidos = 0
        erros = 0

        if filtro_processo:
            # ── Modo direto (igual ofícios) ──────────────────────
            self.stdout.write(f'Buscando processo {filtro_processo}...')

            # 1. Descobre número Projudi interno
            proc_interno = projudi_num
            if not proc_interno:
                # Tenta da URL salva no banco
                proc_existente = Process.objects.filter(number=filtro_processo).first()
                if proc_existente and proc_existente.projudi_url:
                    m = re.search(r'numeroProcesso=(\d+)', proc_existente.projudi_url)
                    if m:
                        proc_interno = m.group(1)
            
            if not proc_interno:
                # Tenta consultaProcesso (endpoint, pode estar quebrado)
                busca_url = 'https://projudi.tjba.jus.br/projudi/processo/consultaProcesso'
                r = session.post(busca_url, data={'numeroProcesso': filtro_processo}, timeout=15)
                if r.status_code == 200:
                    qs_result = parse_qs(urlparse(r.url).query)
                    proc_interno = qs_result.get('numeroProcesso', [None])[0]

            if not proc_interno:
                return self.stderr.write(self.style.ERROR(
                    f'Número Projudi não encontrado para {filtro_processo}.\n'
                    f'Use --projudi para informar. Ex:\n'
                    f'  python manage.py rastrear_mandados --processo {filtro_processo} --projudi 41020261253760'))

            # 2. Acessa DadosProcesso
            proc_url = (f'https://projudi.tjba.jus.br/projudi/listagens/'
                        f'DadosProcesso?numeroProcesso={proc_interno}')
            r_proc = session.get(proc_url, timeout=30)
            if r_proc.status_code != 200:
                return self.stderr.write(self.style.ERROR(
                    f'Erro ao acessar DadosProcesso: {r_proc.status_code}'))

            # Salva projudi_url no banco (se o processo existir)
            proc_existente = Process.objects.filter(number=filtro_processo).first()
            if proc_existente and not proc_existente.projudi_url:
                proc_existente.projudi_url = proc_url
                proc_existente.save(update_fields=['projudi_url'])
                self.stdout.write(f'   URL Projudi salva no banco')

            # 3. Extrai movimentações
            parser = ProcessoParser(r_proc.text)
            movs, _ = parser.extrair_movimentacoes()
            partes_raw = parser.extrair_partes(parser.soup)

            self.stdout.write(f'Movimentações: {len(movs)}, Partes: {len(partes_raw)}')

            # 4. Filtra só despachos/decisões do juiz
            movs_juiz = [m for m in movs if 'despacho' in m.get('ato', '').lower()
                         or 'decisão' in m.get('ato', '').lower()
                         or 'sentença' in m.get('ato', '').lower()]

            if not movs_juiz:
                self.stdout.write(self.style.WARNING(
                    'Nenhum despacho/decisão encontrado nas movimentações'))
                return

            # 5. Para cada despacho, baixa doc e compara com RAG
            for mov in movs_juiz:
                try:
                    # Pega texto do despacho (da observação ou da movimentação)
                    texto_despacho = mov.get('observacao', '') or mov.get('ato', '')
                    if not texto_despacho or len(texto_despacho) < 50:
                        # Tenta baixar documento
                        texto_despacho = self._baixar_doc(session, mov, proc_interno)

                    if not texto_despacho or len(texto_despacho) < 50:
                        continue

                    similares = buscar_cumprimentos_similares(texto_despacho, top_k=3)
                    if not similares:
                        continue

                    proc_num = mov.get('processo', '') or filtro_processo
                    self.stdout.write(f'\n  Despacho evento {mov.get("evento")} — '
                                      f'match RAG ({similares[0]["similaridade"]} palavras)',
                                      ending='')

                    # Verifica se processo existe no banco
                    proc = Process.objects.filter(number=proc_num).first()
                    if not proc:
                        self.stdout.write(self.style.WARNING(' — processo não cadastrado'))
                        continue

                    # Verifica se tem RAGExample com template mandado
                    rag = RAGExample.objects.filter(
                        process=proc,
                        suggested_templates__in=templates_mandado,
                    ).first()
                    if not rag:
                        self.stdout.write(self.style.WARNING(' — sem RAG c/ mandado'))
                        continue

                    template_obj = rag.suggested_templates.filter(
                        template_type='mandado').first()
                    if not template_obj:
                        self.stdout.write(self.style.WARNING(' — template não encontrado'))
                        continue

                    # Pega parte
                    parte = Party.objects.filter(
                        process=proc, role__in=['reu', 'executado']).first()
                    if not parte:
                        parte = Party.objects.filter(process=proc).first()
                    if not parte:
                        self.stdout.write(self.style.WARNING(' — sem partes'))
                        continue

                    # Renderiza e cria MandadoRecord
                    self._criar_mandado(proc, parte, rag, template_obj,
                                        texto_despacho, user, dry_run)
                    expedidos += 1

                except Exception as e:
                    self.stderr.write(self.style.ERROR(f'\n  Erro: {e}'))
                    erros += 1

        else:
            # ── Modo varredura (movimentações recentes) ──────────
            from projudi_client import ProjudiClient
            client = ProjudiClient()
            client.session = session
            client.cookies = cookies

            resp = session.get(client.URL_MOVIMENTACOES, timeout=15)
            if 'expirou' in resp.text.lower() or len(resp.text) < 1000:
                return self.stderr.write(self.style.ERROR('Sessão expirada'))

            soup = BeautifulSoup(resp.text, 'html.parser')
            movs = client.extrair_links_movimentacoes(soup)
            self.stdout.write(f'{len(movs)} movimentação(ões) encontrada(s)')

            for mov in movs:
                proc_num = mov.get('processo', '')
                if not proc_num:
                    continue

                try:
                    self.stdout.write(f'\n  Processo: {proc_num}', ending='')

                    texto_despacho = self._baixar_documento(session, mov)
                    if not texto_despacho or len(texto_despacho) < 50:
                        self.stdout.write(self.style.WARNING(' — sem documento'))
                        continue

                    similares = buscar_cumprimentos_similares(texto_despacho, top_k=3)
                    if not similares:
                        self.stdout.write(self.style.WARNING(' — sem match RAG'))
                        continue

                    self.stdout.write(
                        f' — match RAG ({similares[0]["similaridade"]} palavras)',
                        ending='')

                    proc = Process.objects.filter(number=proc_num).first()
                    if not proc:
                        self.stdout.write(self.style.WARNING(' — processo não cadastrado'))
                        continue

                    rag = RAGExample.objects.filter(
                        process=proc,
                        suggested_templates__in=templates_mandado,
                    ).first()
                    if not rag:
                        self.stdout.write(self.style.WARNING(' — sem RAG c/ mandado'))
                        continue

                    template_obj = rag.suggested_templates.filter(
                        template_type='mandado').first()
                    if not template_obj:
                        self.stdout.write(self.style.WARNING(' — template não encontrado'))
                        continue

                    parte = Party.objects.filter(
                        process=proc, role__in=['reu', 'executado']).first()
                    if not parte:
                        parte = Party.objects.filter(process=proc).first()
                    if not parte:
                        self.stdout.write(self.style.WARNING(' — sem partes'))
                        continue

                    self._criar_mandado(proc, parte, rag, template_obj,
                                        texto_despacho, user, dry_run)
                    expedidos += 1

                except Exception as e:
                    self.stderr.write(self.style.ERROR(f'\n  Erro: {e}'))
                    erros += 1

        self.stdout.write('\n' + '=' * 50)
        self.stdout.write(self.style.SUCCESS(
            f'Mandados: {expedidos} | Erros: {erros}'))
        if dry_run:
            self.stdout.write(self.style.WARNING('(dry-run — nada salvo)'))
        self.stdout.write('=' * 50)

    # ── Helpers ──────────────────────────────────────────────────

    def _criar_mandado(self, proc, parte, rag, template_obj,
                       texto_despacho, user, dry_run):
        """Renderiza template e cria MandadoRecord."""
        from projudi.mandado_service import MandadoService
        from projudi.models import MandadoRecord

        num_mandado = f"MAN-{proc.id:03d}/{date.today().year}"
        ctx = rag.get_template_context(parte_id=parte.id)
        ctx.update({
            'numero_documento': num_mandado,
            'prazo_dias': '05',
            'data': datetime.now().strftime('%d/%m/%Y'),
            'descricao_cumprimento': texto_despacho[:500],
        })
        html_mandado = Template(template_obj.html_template).render(Context(ctx))

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                f'\n    ✅ Mandado {num_mandado} (dry-run)'))
            return

        record, created = MandadoRecord.objects.get_or_create(
            processo=proc.number.replace('.', '').replace('-', '')[:30],
            numero_mandado=num_mandado,
            defaults={
                'numero_processo_cnj': proc.number,
                'status': 'pendente',
                'parte_nome': parte.name,
                'texto_html': html_mandado,
                'user': user,
            },
        )
        if created:
            ms = MandadoService(user)
            ms.criar_log(record, 'info',
                f'Rastreado. Template: {template_obj.name}.')
            self.stdout.write(self.style.SUCCESS(
                f'\n    ✅ Mandado {num_mandado} criado!'))
        else:
            self.stdout.write(f'\n    ℹ️ Mandado já existe')

    def _baixar_documento(self, session, mov):
        """Baixa documento de uma movimentação via link_documento."""
        from bs4 import BeautifulSoup
        doc_url = mov.get('link_documento', '')
        if not doc_url:
            return None
        if not doc_url.startswith('http'):
            doc_url = urljoin('https://projudi.tjba.jus.br/projudi/', doc_url)
        try:
            r = session.get(doc_url, timeout=30)
            if r.status_code == 200:
                return BeautifulSoup(r.text, 'html.parser').get_text(' ', strip=True)
        except Exception:
            pass
        return None

    def _baixar_doc(self, session, mov, proc_interno):
        """Tenta baixar documento de um despacho específico."""
        from bs4 import BeautifulSoup
        docs = mov.get('documentos', [])
        if docs:
            url = docs[0].get('url', '')
            if url:
                try:
                    r = session.get(url, timeout=30)
                    if r.status_code == 200:
                        return BeautifulSoup(r.text, 'html.parser').get_text(' ', strip=True)
                except Exception:
                    pass
        # Fallback: observação da movimentação
        obs = mov.get('observacao', '')
        ato = mov.get('ato', '')
        return f"{ato} {obs}".strip()
