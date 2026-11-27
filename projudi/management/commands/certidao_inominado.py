"""Certidão de recurso inominado: o usuário informa o preparo e o sistema
busca a intimação/DJEN e o evento do recurso no Projudi.

Uso:
    python manage.py certidao_inominado --processo 0000000-00.0000.8.05.0191 --preparo gratuidade
    python manage.py certidao_inominado --processo ... --preparo completo
    python manage.py certidao_inominado --processo ... --preparo incompleto
    python manage.py certidao_inominado --processo ... --preparo nao_pago

Se a detecção automática falhar, informe manualmente:
    --data-disponibilizacao 28/11/2026 --data-protocolo 15/12/2026
    --evento-recurso 50 [--url URL_DadosProcesso]
"""

import os

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

os.environ.setdefault('PLAYWRIGHT_HEADLESS', '1')

import expedir_oficios_por_tipo as E
from projudiProcessNavigator import ProcessoParser
from projudi.partes_inominado import (
    achar_recorrente, extrair_partes_processo, texto_partes, texto_pdf,
    url_peticao_movimento,
)
from projudi.verificacao_inominado import (
    achar_intimacao_djen, achar_recurso_inominado, data_djen,
    data_mov, evento_mov, mov_menciona_parte,
)


class Command(BaseCommand):
    help = 'Busca intimação/DJEN e recurso inominado e gera a certidão'

    def add_arguments(self, parser):
        parser.add_argument('--processo', required=True, help='Número CNJ')
        parser.add_argument(
            '--preparo', required=True,
            choices=[
                'gratuidade', 'completo', 'incompleto',
                'insuficiente', 'nao_pago',
            ],
            help='Preparo informado pelo usuário')
        parser.add_argument('--url', help='URL DadosProcesso (opcional)')
        parser.add_argument(
            '--peticao-url',
            help='URL do PDF da petição (para identificar o recorrente)')
        parser.add_argument(
            '--peticao-documento',
            help='Nome do documento da petição (para a aba Petições)')
        parser.add_argument(
            '--recorrente',
            help='Nome do recorrente (se não for possível ler na petição)')
        parser.add_argument('--evento-recurso', help='Nº do evento do recurso')
        parser.add_argument('--evento-intimacao',
                            help='Nº do evento da intimação/DJEN')
        parser.add_argument('--data-disponibilizacao',
                            help='Sobrescreve a data de disponibilização')
        parser.add_argument('--data-protocolo',
                            help='Sobrescreve a data do protocolo')
        parser.add_argument('--parte', help='Nome da parte')
        parser.add_argument('--servidor', default='IVAN GUEDES DA SILVA')
        parser.add_argument('--habilitacao', choices=['regular', 'omitir'],
                            default='regular')
        parser.add_argument('--saida', help='Arquivo HTML de saída')
        parser.add_argument('--sem-html', action='store_true')
        parser.add_argument('--nao-registrar', action='store_true',
                            help='Teste: não grava no dashboard')
        parser.add_argument('--user', help='E-mail do usuário da sessão')

    def handle(self, *args, **options):
        if options.get('preparo') == 'insuficiente':
            options['preparo'] = 'incompleto'
        processo = options['processo'].strip()
        user = self._usuario(options.get('user'))
        cookies = E._carregar_cookies(user)
        http = E._criar_sessao_http(cookies)

        url = self._resolver_url(processo, options.get('url'))
        self.stdout.write(f'Processo: {processo}')
        self.stdout.write(f'URL......: {url}')

        try:
            resposta = http.get(url, timeout=40)
        except Exception as e:
            raise CommandError(f'Falha ao abrir o processo: {e}') from e
        if resposta.status_code != 200 or 'expirou' in resposta.text.lower():
            raise CommandError(
                'Sessão do Projudi expirada ou página inválida. '
                'Sincronize a sessão e tente novamente.')

        parser = ProcessoParser(resposta.text)
        movs, _ = parser.extrair_movimentacoes()
        if not movs:
            raise CommandError('Nenhuma movimentação encontrada no processo.')

        soup = BeautifulSoup(resposta.text, 'html.parser')
        partes = extrair_partes_processo(parser, soup)
        partes_texto = options.get('parte') or texto_partes(partes)

        if partes_texto:
            self.stdout.write(f'Partes...: {partes_texto}')
        else:
            self.stdout.write(
                'Partes...: não localizadas na página do processo '
                '(a linha "PARA" será omitida).')

        evento_recurso_arg = (
            int(options['evento_recurso'])
            if options.get('evento_recurso') else None
        )
        recurso = achar_recurso_inominado(
            movs, evento=evento_recurso_arg)

        if recurso:
            evento_recurso = evento_mov(recurso)
            data_protocolo = data_mov(recurso)
            self.stdout.write(
                f'Recurso..: evento {evento_recurso} — '
                f'{(recurso.get("ato") or "")[:120]} — '
                f'protocolo {data_protocolo or "?"}')
        else:
            # A petição pode estar na fila de juntada e ainda não ter virado
            # movimento no processo. Nesse caso usamos a data de protocolo
            # informada (data de envio da petição) e o evento fica "infra".
            if not options.get('data_protocolo'):
                raise CommandError(
                    'Não encontrei o recurso inominado no processo. '
                    'Informe --data-protocolo (e, se souber, '
                    '--evento-recurso).')
            evento_recurso = evento_recurso_arg
            data_protocolo = None
            if evento_recurso:
                self.stdout.write(
                    f'Recurso..: evento {evento_recurso} '
                    '(informado manualmente)')
            else:
                self.stdout.write(
                    'Recurso..: não localizado como movimento no processo; '
                    'usando evento "infra" e a data de protocolo informada.')

        if options.get('data_protocolo'):
            from projudi.management.commands.prazo_djen import _parse_data
            data_protocolo = _parse_data(options['data_protocolo'])

        peticao_url = (
            options.get('peticao_url')
            or (url_peticao_movimento(recurso) if recurso else '')
        )
        texto_peticao = texto_pdf(http, peticao_url) if peticao_url else ''
        recorrente = (
            options.get('recorrente')
            or achar_recorrente(texto_peticao, partes)
            or ''
        ).strip()
        if recorrente:
            origem_rec = (
                'informado manualmente' if options.get('recorrente')
                else 'identificado na petição PDF'
            )
            self.stdout.write(
                f'Recorrente: {recorrente} ({origem_rec})')
        else:
            self.stdout.write(self.style.WARNING(
                'Recorrente não identificado; a intimação considerada será a '
                'mais recente. Use --recorrente para especificar.'))

        if options.get('data_disponibilizacao'):
            from projudi.management.commands.prazo_djen import _parse_data
            data_dispo = _parse_data(options['data_disponibilizacao'])
            evento_intimacao = options.get('evento_intimacao') or ''
            origem = 'informada manualmente'
        else:
            evento_busca = (
                evento_recurso
                if isinstance(evento_recurso, int) and evento_recurso > 0
                else None
            )
            mov_int, data_dispo, origem = achar_intimacao_djen(
                movs, evento_busca, data_limite=data_protocolo,
                parte=recorrente or None)
            if not mov_int or not data_dispo:
                raise CommandError(
                    'Não encontrei a disponibilização/DJEN anterior ao '
                    'recurso. Informe --data-disponibilizacao '
                    '(e, se quiser, --evento-intimacao).')
            evento_intimacao = str(evento_mov(mov_int))
            texto_int = ' '.join(
                str(mov_int.get(k) or '') for k in
                ('ato', 'observacao'))
            sufixo = f'; recorrente {recorrente}' if recorrente else ''
            self.stdout.write(
                f'Intimação: evento {evento_intimacao} — '
                f'{texto_int[:120]} — disponibilização '
                f'{data_dispo.strftime("%d/%m/%Y")} ({origem}{sufixo})')
            if recorrente and not mov_menciona_parte(mov_int, recorrente):
                self.stdout.write(self.style.WARNING(
                    'Aviso: a intimação escolhida não cita o recorrente '
                    'nominalmente. Confira antes de assinar.'))

        if not data_protocolo:
            raise CommandError(
                'Data do protocolo do recurso não encontrada. '
                'Informe --data-protocolo.')

        self.stdout.write(
            f'Preparo..: {options["preparo"]}')
        self.stdout.write('')

        call_command(
            'prazo_djen',
            tipo='inominado',
            disponibilizacao=data_dispo.strftime('%d/%m/%Y'),
            protocolo=data_protocolo.strftime('%d/%m/%Y'),
            preparo=options['preparo'],
            evento_recurso=(str(evento_recurso) if evento_recurso else 'infra'),
            evento_intimacao=str(evento_intimacao),
            processo=processo,
            parte=partes_texto or '',
            origem='peticao',
            peticao_documento=options.get('peticao_documento') or '',
            peticao_url=peticao_url or '',
            servidor=options['servidor'],
            habilitacao=options['habilitacao'],
            saida=options.get('saida') or None,
            sem_html=options['sem_html'],
            nao_registrar=options['nao_registrar'],
        )

    def _usuario(self, email=None):
        User = get_user_model()
        if email:
            user = User.objects.filter(email=email).first()
            if not user:
                raise CommandError(f'Usuário não encontrado: {email}')
            return user
        user = User.objects.filter(is_active=True).order_by('id').first()
        if not user:
            raise CommandError('Nenhum usuário ativo.')
        return user

    def _resolver_url(self, processo, url=None):
        if url:
            return url

        from processes.models import Process
        from projudi.models import OficioRecord

        proc = Process.objects.filter(number=processo).first()
        if proc and proc.projudi_url:
            return proc.projudi_url

        oficio = (
            OficioRecord.objects
            .filter(numero_processo_cnj=processo)
            .exclude(processo='')
            .first()
        )
        if oficio:
            return (
                'https://projudi.tjba.jus.br/projudi/listagens/'
                f'DadosProcesso?numeroProcesso={oficio.processo}'
            )

        raise CommandError(
            'Não localizei a URL do processo no banco. '
            'Informe --url com a URL DadosProcesso do Projudi '
            '(ou rode a sincronização/extracção primeiro).')
