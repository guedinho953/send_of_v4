"""Lista a fila ``JuntadaPeticao`` e gera a certidão do recurso inominado.

Uso:
    python manage.py peticoes_inominado --listar
    python manage.py peticoes_inominado --listar --verificar-pdf
    python manage.py peticoes_inominado --processo 0002888-28.2026.8.05.0191 --preparo gratuidade

O comando NÃO decide o preparo: apenas lista as guias/comprovantes para
conferência do usuário e usa o ``--preparo`` informado.
"""

from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

os.environ.setdefault('PLAYWRIGHT_HEADLESS', '1')

import expedir_oficios_por_tipo as E
from projudi.peticoes_inominado import (
    URL_JUNTADA_PETICAO, listar_peticoes_inominado,
)

PREPAROS = ['gratuidade', 'completo', 'incompleto',
            'insuficiente', 'nao_pago']


def _fmt_data(data):
    return data.strftime('%d/%m/%Y') if data else '?'


class Command(BaseCommand):
    help = (
        'Varre a fila JuntadaPeticao, identifica os recursos inominados '
        'e gera a certidão com o preparo informado')

    def add_arguments(self, parser):
        parser.add_argument(
            '--listar', action='store_true',
            help='Apenas lista as petições de recurso inominado da fila')
        parser.add_argument(
            '--processo',
            help='Número CNJ da petição a certificar')
        parser.add_argument(
            '--preparo', choices=PREPAROS,
            help='Preparo informado por você (obrigatório para certificar)')
        parser.add_argument(
            '--url-lista', default=URL_JUNTADA_PETICAO,
            help=f'URL da fila (default: {URL_JUNTADA_PETICAO})')
        parser.add_argument(
            '--verificar-pdf', action='store_true',
            help=(
                'Quando o tipo/nome do PDF não identificar o recurso, '
                'baixa a petição e procura "RECURSO INOMINADO" no texto'))
        parser.add_argument(
            '--data-protocolo',
            help='Sobrescreve a data de envio/protocolo da petição')
        parser.add_argument('--evento-recurso',
                            help='Nº do evento do recurso (se já juntado)')
        parser.add_argument('--evento-intimacao',
                            help='Nº do evento da intimação/DJEN')
        parser.add_argument('--data-disponibilizacao',
                            help='Sobrescreve a data de disponibilização')
        parser.add_argument('--parte', help='Texto da linha PARA (default: recorrente)')
        parser.add_argument(
            '--recorrente',
            help='Nome do recorrente (se não for possível ler no PDF)')
        parser.add_argument(
            '--peticao-url',
            help='URL do PDF da petição (default: a da fila)')
        parser.add_argument(
            '--peticao-documento',
            help='Nome do documento da petição (default: o da fila)')
        parser.add_argument('--servidor', default='IVAN GUEDES DA SILVA')
        parser.add_argument('--habilitacao', choices=['regular', 'omitir'],
                            default='regular')
        parser.add_argument('--saida', help='Arquivo HTML de saída')
        parser.add_argument('--sem-html', action='store_true')
        parser.add_argument('--nao-registrar', action='store_true',
                            help='Teste: não grava no dashboard')
        parser.add_argument('--user', help='E-mail do usuário da sessão')

    def handle(self, *args, **options):
        user = self._usuario(options.get('user'))
        cookies = E._carregar_cookies(user)
        http = E._criar_sessao_http(cookies)

        url_lista = options['url_lista']
        self.stdout.write(f'Fila.....: {url_lista}')
        try:
            resposta = http.get(url_lista, timeout=40)
        except Exception as e:
            raise CommandError(f'Falha ao abrir a fila: {e}') from e
        if resposta.status_code != 200 or 'expirou' in resposta.text.lower():
            raise CommandError(
                'Sessão do Projudi expirada ou página inválida. '
                'Sincronize a sessão e tente novamente.')

        peticoes = listar_peticoes_inominado(
            resposta.text,
            http=http,
            verificar_pdf=options['verificar_pdf'],
        )

        if not peticoes:
            self.stdout.write(self.style.WARNING(
                'Nenhuma petição de recurso inominado na fila.'))
            if options.get('verificar_pdf'):
                self.stdout.write(
                    'Tente também sem --verificar-pdf; o tipo da juntada '
                    'ou o nome do PDF pode já identificar o recurso.')
            return

        if options.get('listar') or not options.get('processo'):
            self.stdout.write(
                f'Recursos inominados na fila: {len(peticoes)}')
            self.stdout.write('')
            for indice, peticao in enumerate(peticoes, start=1):
                self._imprimir_peticao(indice, peticao)
            self.stdout.write('')
            self.stdout.write(
                'Para certificar, informe o processo e o preparo:')
            self.stdout.write(
                '  python manage.py peticoes_inominado '
                '--processo <CNJ> --preparo '
                'gratuidade|completo|incompleto|nao_pago')
            return

        if not options.get('preparo'):
            raise CommandError(
                'Informe --preparo (gratuidade, completo, incompleto ou '
                'nao_pago) para gerar a certidão.')

        peticao = self._selecionar(peticoes, options['processo'])
        if peticao is None:
            disponiveis = ', '.join(p['processo'] for p in peticoes)
            raise CommandError(
                f'Processo {options["processo"]} não está na fila como '
                f'recurso inominado. Disponíveis: {disponiveis}')

        self._imprimir_peticao(1, peticao)

        data_protocolo = (
            options.get('data_protocolo')
            or _fmt_data(peticao['data_envio'])
        )
        if not data_protocolo or data_protocolo == '?':
            raise CommandError(
                'A fila não informou a data de envio da petição. '
                'Use --data-protocolo DD/MM/AAAA.')

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Certificando {peticao["processo"]} — '
            f'protocolo {data_protocolo} — preparo {options["preparo"]}'))
        self.stdout.write(
            f'URL do processo: {peticao["processo_url"]}')

        call_command(
            'certidao_inominado',
            processo=peticao['processo'],
            preparo=options['preparo'],
            url=peticao['processo_url'],
            peticao_url=(
                options.get('peticao_url')
                or (peticao['peticao']['url'] if peticao['peticao'] else None)
            ),
            peticao_documento=(
                options.get('peticao_documento')
                or (peticao['peticao']['nome'] if peticao['peticao'] else '')
            ),
            recorrente=options.get('recorrente'),
            data_protocolo=data_protocolo,
            evento_recurso=options.get('evento_recurso'),
            evento_intimacao=options.get('evento_intimacao'),
            data_disponibilizacao=options.get('data_disponibilizacao'),
            parte=options.get('parte') or '',
            servidor=options['servidor'],
            habilitacao=options['habilitacao'],
            saida=options.get('saida') or None,
            sem_html=options['sem_html'],
            nao_registrar=options['nao_registrar'],
        )

    def _imprimir_peticao(self, indice, peticao):
        self.stdout.write(
            f'{indice}) {peticao["processo"]} — '
            f'{_fmt_data(peticao["data_envio"])}')
        self.stdout.write(
            f'   Tipo......: {peticao["tipo"] or "(não informado)"}')
        self.stdout.write(
            f'   Detecção..: {peticao["origem_deteccao"] or "manual"}')
        if peticao['peticao']:
            self.stdout.write(
                f'   Petição...: {peticao["peticao"]["nome"]}')
            self.stdout.write(
                f'               {peticao["peticao"]["url"]}')
        else:
            self.stdout.write('   Petição...: (PDF não localizado)')

        if peticao['preparo_docs']:
            self.stdout.write(
                '   Comprovantes/guias (conferir manualmente):')
            for doc in peticao['preparo_docs']:
                self.stdout.write(f'     - {doc["nome"]}')
                self.stdout.write(f'       {doc["url"]}')
        else:
            self.stdout.write(
                '   Comprovantes/guias: nenhum PDF localizado na fila')

        if peticao['anexos']:
            self.stdout.write('   Outros documentos:')
            for doc in peticao['anexos']:
                self.stdout.write(f'     - {doc["nome"]}')

        self.stdout.write(f'   Processo..: {peticao["processo_url"]}')
        self.stdout.write('')

    def _selecionar(self, peticoes, processo):
        alvo = ''.join(c for c in str(processo) if c.isdigit())
        for peticao in peticoes:
            numero = ''.join(c for c in peticao['processo'] if c.isdigit())
            if numero == alvo:
                return peticao
        return None

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
