"""Copia os dados de um banco SQLite (espelho) para o banco configurado
no Django (normalmente PostgreSQL).

Uso:
    python manage.py copiar_dados_sqlite --origem D:\\send_of_v4\\db.sqlite3
    python manage.py copiar_dados_sqlite --origem ... --limpar

Observações:
* copia todas as tabelas de aplicação, preservando os IDs;
* ignora contenttypes, permissões, grupos, sessões e log do admin;
* não copia relações M2M de usuário (grupos/permissões);
* use --limpar para apagar os dados atuais do destino antes de copiar.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connections, transaction

# Modelos que não devem ser copiados (o Django recria o básico nas migrações)
IGNORAR = {
    'contenttypes.ContentType',
    'auth.Permission',
    'auth.Group',
    'sessions.Session',
    'admin.LogEntry',
}


class Command(BaseCommand):
    help = 'Copia os dados de um SQLite (espelho) para o banco atual (PostgreSQL)'

    def add_arguments(self, parser):
        parser.add_argument('--origem', required=True,
                            help='Caminho do db.sqlite3 de origem')
        parser.add_argument('--limpar', action='store_true',
                            help='Apaga os dados atuais do destino antes de copiar')
        parser.add_argument('--apenas', default='',
                            help='Lista de apps separados por vírgula (ex.: projudi,processes)')

    def handle(self, *args, **options):
        origem = Path(options['origem']).expanduser()
        if not origem.is_file():
            raise CommandError(f'Banco de origem não encontrado: {origem}')

        somente_apps = {
            a.strip() for a in options['apenas'].split(',') if a.strip()
        }

        # Registra o SQLite de origem como uma conexão temporária "espelho".
        connections.databases['espelho'] = {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': str(origem),
            'ATOMIC_REQUESTS': False,
            'AUTOCOMMIT': True,
            'CONN_MAX_AGE': 0,
            'CONN_HEALTH_CHECKS': False,
            'OPTIONS': {},
            'TIME_ZONE': None,
            'USER': '',
            'PASSWORD': '',
            'HOST': '',
            'PORT': '',
            'TEST': {'NAME': None},
        }

        modelos = []
        for modelo in apps.get_models():
            meta = modelo._meta
            if meta.proxy or meta.auto_created:
                continue
            if meta.label in IGNORAR:
                continue
            if somente_apps and meta.app_label not in somente_apps:
                continue
            modelos.append(modelo)

        destino = connections['default']
        if destino.vendor != 'postgresql':
            self.stdout.write(self.style.WARNING(
                'O destino não é PostgreSQL; o comando também funciona, '
                'mas o foco é copiar do espelho para o Postgres.'))

        # O espelho pode ser de uma versão antiga: copiamos apenas as colunas
        # que existem nos dois lados e deixamos o Django usar os defaults para
        # as colunas novas.
        def colunas_sqlite(tabela: str) -> set[str]:
            try:
                con = sqlite3.connect(str(origem))
                try:
                    return {r[1] for r in con.execute(
                        f'PRAGMA table_info("{tabela}")')}
                finally:
                    con.close()
            except sqlite3.Error:
                return set()

        def colunas_postgres(tabela: str) -> set[str]:
            try:
                with destino.cursor() as cursor:
                    descricao = destino.introspection.get_table_description(
                        cursor, tabela)
                return {c.name for c in descricao}
            except Exception:
                return set()

        total = 0
        try:
            with transaction.atomic(using='default'):
                with destino.constraint_checks_disabled():
                    if options['limpar']:
                        self.stdout.write('Apagando dados do destino...')
                        for modelo in reversed(modelos):
                            modelo.objects.using('default').all()._raw_delete('default')

                    for modelo in modelos:
                        tabela = modelo._meta.db_table
                        origem_cols = colunas_sqlite(tabela)
                        destino_cols = colunas_postgres(tabela)
                        if not origem_cols or not destino_cols:
                            self.stdout.write(
                                f'  {modelo._meta.label}: ignorado '
                                f'(tabela ausente)')
                            continue

                        campos = [
                            f for f in modelo._meta.concrete_fields
                            if f.column in origem_cols and f.column in destino_cols
                        ]
                        if not campos:
                            continue

                        nomes = [f.attname for f in campos]
                        try:
                            linhas = list(
                                modelo.objects.using('espelho')
                                .values(*nomes))
                        except Exception as e:
                            self.stdout.write(
                                f'  {modelo._meta.label}: ignorado ({e})')
                            continue
                        if not linhas:
                            continue

                        objetos = [modelo(**linha) for linha in linhas]
                        try:
                            modelo.objects.using('default').bulk_create(
                                objetos, batch_size=500)
                        except Exception as e:
                            raise CommandError(
                                f'Falha em {modelo._meta.label}: {e}') from e

                        total += len(objetos)
                        self.stdout.write(
                            f'  {modelo._meta.label}: {len(objetos)}')
        except Exception as e:
            raise CommandError(f'Falha ao copiar dados: {e}') from e

        # Ajusta as sequences do PostgreSQL para os IDs copiados.
        if destino.vendor == 'postgresql':
            sqls = destino.ops.sequence_reset_sql(no_style(), modelos)
            with destino.cursor() as cursor:
                for sql in sqls:
                    cursor.execute(sql)

        self.stdout.write(self.style.SUCCESS(
            f'Concluído: {total} registros copiados de {origem}'))
