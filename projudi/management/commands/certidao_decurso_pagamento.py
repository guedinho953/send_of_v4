"""Gera a certidão de decurso do prazo de pagamento voluntário (15 dias)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from projudi.assinantes_certidao import ASSINANTE_PADRAO, ASSINANTES
from projudi.decurso_certidao import (
    gerar_e_registrar, motivo, texto_certidao,
)
from projudi.decurso_pagamento_service import DecursoPagamentoService


class Command(BaseCommand):
    help = (
        'Localiza o despacho de pagamento em 15 dias, a intimação do '
        'executado e gera a certidão de decurso (somente após o decurso)')

    def add_arguments(self, parser):
        parser.add_argument('--processo', required=True, help='Número CNJ')
        parser.add_argument(
            '--evento', help='Evento do despacho (opcional; automático)')
        parser.add_argument(
            '--executado', help='Nome do executado (opcional; automático)')
        parser.add_argument('--url', help='URL DadosProcesso (opcional)')
        parser.add_argument(
            '--servidor', default=ASSINANTES[ASSINANTE_PADRAO][0],
            help='Nome do servidor que assina')
        parser.add_argument(
            '--servidor-cargo', default=ASSINANTES[ASSINANTE_PADRAO][1],
            help='Cargo do servidor')
        parser.add_argument('--saida', help='Arquivo HTML de saída')
        parser.add_argument(
            '--nao-registrar', action='store_true',
            help='Teste: não grava no dashboard')
        parser.add_argument('--user', help='E-mail do usuário da sessão')

    def handle(self, *args, **options):
        user = self._usuario(options.get('user'))
        servico = DecursoPagamentoService(user)
        resultado = servico.analisar(
            options['processo'],
            evento=options.get('evento') or '',
            parte_nome=options.get('executado') or '',
            url=options.get('url'),
        )

        if resultado.get('erro'):
            raise CommandError(resultado['erro'])

        self.stdout.write(f'Processo..: {resultado["processo"]}')
        self.stdout.write(f'URL.......: {resultado["url"]}')
        self.stdout.write(
            f'Executado.: {resultado["executado"]} '
            f'({resultado.get("parte_papel") or "?"})')
        self.stdout.write(
            f'Despacho..: evento {resultado["evento_despacho"]}'
            f'{" (automático)" if resultado.get("despacho_auto") else ""}')
        if resultado.get('despacho_trecho'):
            self.stdout.write(
                f'Trecho....: {resultado["despacho_trecho"][:200]}')
        self.stdout.write(
            f'Intimação.: evento {resultado["evento_intimacao"]} em '
            f'{resultado["data_intimacao"].strftime("%d/%m/%Y")} '
            f'({resultado["meio_label"]})')
        self.stdout.write(
            f'15 dias...: {resultado["data_inicio"].strftime("%d/%m/%Y")} '
            f'até {resultado["ultimo_dia"].strftime("%d/%m/%Y")}')
        self.stdout.write(
            f'Decurso...: {resultado["data_decurso"].strftime("%d/%m/%Y")}')

        if not resultado['decorrido']:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                '⏳ O prazo ainda não decorreu. A certidão não foi gerada.'))
            self.stdout.write(
                f'   Último dia: '
                f'{resultado["ultimo_dia"].strftime("%d/%m/%Y")} | '
                f'decurso: {resultado["data_decurso"].strftime("%d/%m/%Y")}')
            return

        html, caminho, registro = gerar_e_registrar(
            resultado,
            servidor=options['servidor'],
            servidor_cargo=options['servidor_cargo'],
            saida=options.get('saida') or None,
            nao_registrar=options['nao_registrar'],
        )

        self.stdout.write('')
        self.stdout.write('Texto da certidão:')
        self.stdout.write(texto_certidao(resultado))
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Preview: {caminho}'))
        self.stdout.write('Abra no Firefox e confira antes de lançar no Projudi.')
        if registro:
            self.stdout.write(self.style.SUCCESS(
                f'Controle registrado: #{registro.id} '
                f'(/projudi/certidoes/{registro.id}/)'))
            self.stdout.write(
                'Aba: Certidões → Movimentações (origem=movimentacao)')
        else:
            self.stdout.write('Controle NÃO registrado (--nao-registrar).')

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
