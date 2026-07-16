"""
Comando para extrair movimentacoes dos processos do Projudi e
alimentar as models de RAG (Movement, ComplianceHistory, etc).

Uso:
  python manage.py extrair_movimentacoes_projudi
  python manage.py extrair_movimentacoes_projudi --processo 0001493-69.2024.8.05.0191
  python manage.py extrair_movimentacoes_projudi --limite 5 --exportar-json dados_rag.json
"""

import sys
import json
import re
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help = 'Extrai movimentacoes do Projudi e alimenta models de RAG'

    def add_arguments(self, parser):
        parser.add_argument('--processo', type=str, help='Apenas um processo especifico')
        parser.add_argument('--limite', type=int, default=20, help='Maximo de processos (padrao: 20)')
        parser.add_argument('--exportar-json', type=str, help='Caminho para exportar JSON de treino RAG')

    def handle(self, *args, **options):
        limite = options['limite']
        processo_filter = options['processo']
        json_path = options.get('exportar_json')

        base_dir = settings.BASE_DIR
        if str(base_dir) not in sys.path:
            sys.path.insert(0, str(base_dir))

        user = self._get_user()
        if not user:
            self.stderr.write(self.style.ERROR('Nenhum usuario ativo encontrado'))
            return

        from projudi.services import ProjudiService
        from projudi.models import OficioRecord
        from django.db.models import Q

        service = ProjudiService(user=user)
        session = service._get_session_from_cookie_jar()
        if not session:
            self.stderr.write(self.style.ERROR('Nenhuma sessao Projudi encontrada'))
            return

        warm = session.get("https://projudi.tjba.jus.br/projudi/cadastros/AnalisarMovimentacao")
        if 'sess\u00e3o expirou' in warm.text.lower() or len(warm.text) < 1000:
            self.stderr.write(self.style.ERROR('Sessao Projudi expirada'))
            return
        self.stdout.write(self.style.SUCCESS('[OK] Sessao Projudi ativa'))

        qs = OficioRecord.objects.filter(user=user).exclude(status='dispensado')
        if processo_filter:
            qs = qs.filter(Q(numero_processo_cnj=processo_filter) | Q(processo=processo_filter))
        qs = qs[:limite]
        total = qs.count()
        if total == 0:
            self.stderr.write('Nenhum processo encontrado')
            return

        self.stdout.write(f'[INFO] Extraindo movimentacoes de {total} processos...')

        from processes.movimentacoes_service import (
            extrair_comandos, classificar_movimentacao
        )
        from processes.models import Process, Movement, MovementCommand, ComplianceHistory, RAGExample
        from projudiProcessNavigator import ProcessoParser

        rag_pairs = []
        ivan_nome = 'IVAN GUEDES DA SILVA'
        processados = 0

        for oficio in qs:
            process_interno = oficio.processo
            process_cnj = oficio.numero_processo_cnj or process_interno

            process_obj, _ = Process.objects.get_or_create(
                number=process_cnj,
                tenant=user.tenant,
                defaults={
                    'number_normalized': re.sub(r'[^0-9]', '', process_cnj),
                    'status': 'analyzing',
                }
            )
            self.stdout.write(f'\n--- {oficio.numero_oficio} / {process_cnj} ---', ending=' ')

            url = (
                f"https://projudi.tjba.jus.br/projudi/listagens/"
                f"DadosProcesso?numeroProcesso={process_interno}"
            )
            resp = session.get(url)
            if resp.status_code != 200 or len(resp.text) < 500:
                self.stdout.write(self.style.WARNING('[FALHA] pagina'))
                continue
            html = resp.text
            if 'sess\u00e3o expirou' in html.lower():
                self.stdout.write(self.style.WARNING('[FALHA] sessao expirou'))
                break

            try:
                parser = ProcessoParser(html)
                movimentacoes, _ = parser.extrair_movimentacoes()
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'[ERRO parser] {e}'))
                continue

            if not movimentacoes:
                self.stdout.write(self.style.WARNING('[SEM MOVS]'))
                continue

            movs_ivan = []
            movs_juiz = []
            for mov in movimentacoes:
                autor = (mov.get('autor') or '').upper()
                ato = mov.get('ato', '')
                tipo, _ = classificar_movimentacao(ato)
                mov['tipo'] = tipo
                if ivan_nome in autor:
                    movs_ivan.append(mov)
                elif tipo in ('despacho', 'sentenca', 'decisao'):
                    movs_juiz.append(mov)

            self.stdout.write(
                f'{len(movimentacoes)} movs, '
                f'{len(movs_juiz)} desp, '
                f'{len(movs_ivan)} Ivan', ending=''
            )

            from datetime import datetime
            CATEGORY_MAP = {
                'indefinido': 'outro', 'mandado': 'outro', 'embargos': 'recurso',
                'ato_ordinatorio': 'ato_ordinatorio',
            }

            def parse_data(texto):
                if not texto:
                    return None
                try:
                    return datetime.strptime(texto.strip(), '%d/%m/%y').date()
                except ValueError:
                    try:
                        return datetime.strptime(texto.strip(), '%d/%m/%Y').date()
                    except ValueError:
                        return None

            for mov in movimentacoes:
                cat = CATEGORY_MAP.get(mov.get('tipo', ''), mov.get('tipo', ''))
                movement = Movement.objects.create(
                    process=process_obj,
                    tenant=user.tenant,
                    event_number=str(mov.get('evento', '')),
                    act_description=mov.get('ato', ''),
                    category=cat,
                    act_date=parse_data(mov.get('data_texto')),
                    author=mov.get('autor', ''),
                    observation=mov.get('observacao', ''),
                )
                cmds = extrair_comandos(mov.get('ato', ''), mov.get('tipo', ''))
                if isinstance(cmds, list):
                    for c in cmds:
                        MovementCommand.objects.create(
                            tenant=user.tenant,
                            movement=movement,
                            act_verb=c.get('ato', ''),
                            is_completable=c.get('cumprivel', False),
                            recipient=c.get('destinatario', []),
                            means=c.get('meio', []),
                        )

            for mov in movs_ivan:
                ComplianceHistory.objects.create(
                    tenant=user.tenant,
                    process=process_obj,
                    act_type=mov.get('tipo', 'certidao'),
                    act_verb='cumprimento',
                    recipient='partes',
                    means_used='projudi',
                    full_text=f"{mov.get('ato', '')}\n{mov.get('observacao', '')}",
                    commands_json=extrair_comandos(mov.get('ato', ''), mov.get('tipo', '')),
                    email_sent=False,
                    juntada_done=True,
                    compliance_date=datetime.now(),
                )

            movs_juiz.sort(key=lambda m: int(m.get('evento', 0) or 0))
            for i, despacho in enumerate(movs_juiz):
                evento_desp = int(despacho.get('evento', 0) or 0)
                evento_proximo = int(movs_juiz[i+1].get('evento', 0) or 0) if i + 1 < len(movs_juiz) else float('inf')

                cumprimentos = [
                    {
                        'evento': m.get('evento'),
                        'ato': m.get('ato'),
                        'observacao': m.get('observacao', ''),
                        'data': m.get('data_texto'),
                        'autor': m.get('autor', ''),
                        'tipo': m.get('tipo', ''),
                    }
                    for m in movs_ivan
                    if evento_desp < (int(m.get('evento', 0) or 0)) < evento_proximo
                ]
                documentos = despacho.get('documentos', [])
                for doc in documentos:
                    url = doc.get('url', '')
                    if 'downloadarquivo' in url:
                        doc['url'] = url.replace('downloadarquivo', 'DownloadArquivo')
                obs_texto = despacho.get('observacao', '')
                if not obs_texto and documentos:
                    for doc in documentos[:1]:
                        try:
                            doc_resp = session.get(doc['url'], timeout=10)
                            if doc_resp.status_code == 200:
                                from bs4 import BeautifulSoup
                                doc_soup = BeautifulSoup(doc_resp.text, 'html.parser')
                                obs_texto = doc_soup.get_text(' ', strip=True)[:2000]
                        except Exception:
                            pass

                rag_pairs.append({
                    'processo': process_cnj,
                    'oficio': oficio.numero_oficio,
                    'evento_despacho': despacho.get('evento'),
                    'despacho_ato': despacho.get('ato', ''),
                    'despacho_observacao': obs_texto,
                    'despacho_data': despacho.get('data_texto'),
                    'despacho_autor': despacho.get('autor', ''),
                    'cumprimentos': cumprimentos,
                })
                RAGExample.objects.create(
                    tenant=user.tenant,
                    process=process_obj,
                    oficio=oficio.numero_oficio,
                    despacho_ato=despacho.get('ato', ''),
                    despacho_observacao=obs_texto,
                    despacho_data=despacho.get('data_texto', ''),
                    despacho_autor=despacho.get('autor', ''),
                    evento_despacho=despacho.get('evento', ''),
                    cumprimentos=cumprimentos,
                    documentos=documentos,
                    active=bool(cumprimentos),
                )

            self.stdout.write(self.style.SUCCESS(' [OK]'))
            processados += 1

        if json_path and rag_pairs:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(rag_pairs, f, ensure_ascii=False, indent=2, default=str)
            self.stdout.write(self.style.SUCCESS(
                f'\n[OK] Exportado {len(rag_pairs)} pares RAG para {json_path}'
            ))
        elif json_path:
            self.stdout.write(self.style.WARNING('\nNenhum par RAG para exportar'))

        self.stdout.write('\n' + '=' * 60)
        self.stdout.write(self.style.SUCCESS(f'Processos: {processados}/{total}'))
        if rag_pairs:
            n_com_cumpr = len([p for p in rag_pairs if p['cumprimentos']])
            n_atos_ivan = sum(len(p['cumprimentos']) for p in rag_pairs)
            self.stdout.write(f'Pares despacho+atos: {len(rag_pairs)} ({n_com_cumpr} com atos)')
            self.stdout.write(f'Total de atos de Ivan: {n_atos_ivan}')
        self.stdout.write('=' * 60)

    def _get_user(self):
        from accounts.models import User
        return User.objects.filter(is_active=True).first()
