"""Reclassifica as partes dos processos já cadastrados.

O parser antigo gravava toda parte que não fosse o promovente como ``réu``,
inclusive os **terceiros** e **testemunhas** (onde normalmente ficam os
policiais do 20º BPM). Este comando relê a página DadosProcesso e corrige o
papel de cada parte.

Uso:
    python manage.py reclassificar_partes
    python manage.py reclassificar_partes --processo 0000236-72.2025.8.05.0191
    python manage.py reclassificar_partes --dry-run
"""

import re

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from processes.models import Party, Process


MAPA_ROLE = {
    'EXEQUENTE': 'autor',
    'PROMOVENTE': 'autor',
    'AUTOR': 'autor',
    'REQUERENTE': 'autor',
    'VITIMA': 'autor',
    'EXECUTADO': 'reu',
    'PROMOVIDO': 'reu',
    'REU': 'reu',
    'AUTOR DO FATO': 'reu',
    'TERCEIRO': 'terceiro',
    'TESTEMUNHA': 'terceiro',
    'AUTORIDADE': 'terceiro',
    'REPRESENTANTE': 'terceiro',
}


class Command(BaseCommand):
    help = 'Corrige o papel (autor/réu/terceiro) das partes já cadastradas'

    def add_arguments(self, parser):
        parser.add_argument('--user', help='E-mail do usuário para a sessão')
        parser.add_argument('--processo', help='Número CNJ de um processo só')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        from projudi.services import ProjudiService
        from projudiProcessNavigator import ProcessoParser

        User = get_user_model()
        if options['user']:
            user = User.objects.filter(email=options['user']).first()
        else:
            user = User.objects.filter(is_active=True).order_by('id').first()
        if not user:
            raise CommandError('Nenhum usuário ativo.')

        resultado = ProjudiService(user)._get_session_from_cookies()
        if not resultado:
            raise CommandError(
                'Sessão do Projudi indisponível. Abra o Firefox, faça login '
                'e sincronize a sessão.')
        session, _cookies = resultado

        processos = Process.objects.exclude(projudi_url='')
        if options['processo']:
            processos = processos.filter(number=options['processo'])

        total = 0
        for proc in processos:
            try:
                resposta = session.get(proc.projudi_url, timeout=30)
                if resposta.status_code != 200 or 'expirou' in resposta.text.lower():
                    self.stderr.write(f'{proc.number}: sessão/página inválida')
                    continue
                parser = ProcessoParser(resposta.text)
                partes = parser.extrair_partes(parser.soup)
            except Exception as e:
                self.stderr.write(f'{proc.number}: {e}')
                continue

            for parte in partes:
                nome = (parte.get('nome') or '').strip()
                if not nome:
                    continue
                tipo = (parte.get('tipo') or '').upper()
                role = MAPA_ROLE.get(tipo)
                if not role:
                    continue

                existentes = Party.objects.filter(
                    process=proc, name__iexact=nome)
                if existentes.exists():
                    if options['dry_run']:
                        for p in existentes:
                            if p.role != role:
                                self.stdout.write(
                                    f'[dry] {proc.number}: {nome!r} '
                                    f'{p.role} -> {role}')
                    else:
                        mudou = existentes.exclude(role=role).update(role=role)
                        if mudou:
                            self.stdout.write(
                                f'{proc.number}: {nome!r} -> {role}')
                            total += mudou
                elif role == 'terceiro':
                    # Terceiro que ainda não existia no banco.
                    endereco = ' '.join(str(parte.get(k) or '') for k in (
                        'logradouro', 'numero', 'complemento', 'bairro',
                        'cidade', 'uf'))
                    if options['dry_run']:
                        self.stdout.write(
                            f'[dry] {proc.number}: criar terceiro {nome!r}')
                    else:
                        Party.objects.create(
                            process=proc,
                            tenant=proc.tenant,
                            name=nome,
                            name_normalized=re.sub(
                                r'\s+', ' ', nome.lower().strip())[:200],
                            role='terceiro',
                            cpf_cnpj=(parte.get('cpf/cnpj') or '')[:18],
                            email=parte.get('email') or '',
                            phone=(parte.get('tel') or '')[:20],
                            address=endereco,
                        )
                        self.stdout.write(
                            f'{proc.number}: terceiro criado {nome!r}')
                        total += 1

        self.stdout.write(self.style.SUCCESS(
            f'Concluído. Alterações: {total}'))
