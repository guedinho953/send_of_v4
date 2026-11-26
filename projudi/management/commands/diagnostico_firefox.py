"""Diagnóstico do Firefox local, cookies e Playwright.

Uso:
    python manage.py diagnostico_firefox
"""

from django.core.management.base import BaseCommand

import firefox_config


class Command(BaseCommand):
    help = 'Mostra Firefox/perfil/cookies detectados e testa o Playwright'

    def handle(self, *args, **options):
        info = firefox_config.describe_environment()

        self.stdout.write(self.style.MIGRATE_HEADING('Ambiente'))
        self.stdout.write(f"  Plataforma ........: {info['plataforma']}")
        self.stdout.write(f"  Windows nativo ....: {info['windows']}")
        self.stdout.write(f"  WSL ...............: {info['wsl']}")
        self.stdout.write(f"  Firefox ...........: {info['firefox'] or 'NAO ENCONTRADO'}")
        self.stdout.write(f"  Perfil Firefox ....: {info['perfil'] or 'NAO ENCONTRADO'}")
        self.stdout.write(f"  Arquivo cookies ...: {info['arquivo_cookies']}")

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Perfis encontrados'))
        for perfil in info['perfis']:
            self.stdout.write(f'  - {perfil}')
        if not info['perfis']:
            self.stdout.write('  (nenhum)')

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Cookies do Projudi'))
        cookies = firefox_config.capture_cookies()
        self.stdout.write(f'  Quantidade ........: {len(cookies)}')
        self.stdout.write(f'  JSESSIONID ........: '
                          f'{"SIM" if "JSESSIONID" in cookies else "NAO"}')
        if cookies:
            self.stdout.write(f'  Nomes .............: {sorted(cookies)}')

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Playwright'))
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                caminho = pw.firefox.executable_path
                self.stdout.write(f'  Firefox do Playwright: {caminho}')
                self.stdout.write('  (se estiver vazio, rode: '
                                  'python -m playwright install firefox)')
        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f'  Playwright indisponível: {e}'))
            self.stdout.write('  Rode: python -m pip install playwright')
            self.stdout.write('        python -m playwright install firefox')
