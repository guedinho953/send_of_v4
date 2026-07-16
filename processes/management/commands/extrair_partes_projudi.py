import re
import time
from django.core.management.base import BaseCommand
from bs4 import BeautifulSoup


class Command(BaseCommand):
    help = 'Extrai partes do Projudi e salva criptografado no Party'

    def add_arguments(self, parser):
        parser.add_argument('--processo', type=str, help='Apenas um processo')
        parser.add_argument('--limite', type=int, default=0, help='Maximo (0=todos)')

    def handle(self, *args, **options):
        from projudi.services import ProjudiService
        from processes.models import Process, Party
        from projudi.models import OficioRecord
        from base.crypto import encrypt

        user = self._get_user()
        service = ProjudiService(user=user)
        session = service._get_session_from_cookie_jar()

        warm = session.get('https://projudi.tjba.jus.br/projudi/cadastros/AnalisarMovimentacao')
        if 'sess\u00e3o expirou' in warm.text.lower() or len(warm.text) < 1000:
            self.stderr.write(self.style.ERROR('Sessao expirada'))
            return

        qs = OficioRecord.objects.filter(user=user).exclude(status='dispensado')
        if options['processo']:
            qs = qs.filter(processo=options['processo'])
        if options['limite']:
            qs = qs[:options['limite']]

        total = qs.count()
        self.stdout.write(f'Processando {total} processos...')

        ok = 0
        for oficio in qs:
            process_obj = Process.objects.filter(
                number=oficio.numero_processo_cnj or oficio.processo
            ).first()
            if not process_obj:
                continue

            url = f'https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?numeroProcesso={oficio.processo}'
            resp = session.get(url)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, 'html.parser')

            role_map = {
                'exequente': 'exequente',
                'executado': 'executado',
                'autor': 'autor',
                'reu': 'reu',
                'testemunha': 'terceiro',
                'terceiro': 'terceiro',
            }

            # Find the parts table - look for role headers
            tables = soup.find_all('table', class_=lambda x: x and 'tabelaPartes' in str(x) if x else False)
            if not tables:
                # Fallback: look for any table with role headers
                tables = soup.find_all('table', border=lambda x: x == '0' if x else False)

            for table in soup.find_all('table'):
                header = table.find('td', class_='tBranca')
                if not header:
                    continue
                role_text = header.get_text(strip=True).lower()
                role = None
                for key, val in role_map.items():
                    if key in role_text:
                        role = val
                        break
                if not role:
                    continue

                rows = table.find_all('tr')
                for row in rows:
                    tds = row.find_all('td', recursive=False)
                    if len(tds) < 3:
                        continue
                    nome_td = tds[2] if len(tds) > 2 else None
                    if not nome_td:
                        continue
                    nome = nome_td.get_text(strip=True).split('\n')[0].strip()
                    if not nome or nome == 'Nome' or 'Mostrar' in nome:
                        continue

                    cpf_cnpj = ''
                    rg = ''
                    nome_pai = ''
                    nome_mae = ''
                    for td in tds:
                        txt = td.get_text(strip=True)
                        if re.match(r'[\d]{3}\.[\d]{3}\.[\d]{3}-[\d]{2}', txt) or \
                           re.match(r'[\d]{2}\.[\d]{3}\.[\d]{3}/[\d]{4}-[\d]{2}', txt):
                            cpf_cnpj = txt
                        m_rg = re.search(r'(\d{1,3}\.?\d{1,3}\.?\d{1,3}[-\s]?\d{1,2}\s*\w+/\w+)', txt)
                        if m_rg:
                            rg = m_rg.group(1)

                    # Try to find RG, filiation from the row data
                    row_text = row.get_text(' ', strip=True)
                    m_filiacao = re.search(r'filho\s*(?:de)?\s*:\s*([^,]+?)\s+e\s+([^,]+?)(?:,|$|\.)', row_text, re.I)
                    if m_filiacao:
                        nome_mae = m_filiacao.group(1).strip()
                        nome_pai = m_filiacao.group(2).strip()
                    if not rg:
                        m_rg_full = re.search(r'rg\s*:?\s*(\d{1,3}\.?\d{1,3}\.?\d{1,3}[-\s]?\d{1,2})', row_text, re.I)
                        if m_rg_full:
                            rg = m_rg_full.group(1)

                    address = ''
                    email = ''
                    phone = ''
                    lawyer = ''
                    for td in tds:
                        txt = td.get_text(' ', strip=True)
                        if '@' in txt and '.' in txt:
                            email = txt.split('\n')[0].strip()
                        if '(Contato:' in txt:
                            phone = txt.split('(Contato:')[1].split(')')[0].strip()
                        if 'Endereço' in td.get('class', []):
                            parent = td.find_parent('tr')
                            if parent:
                                addr_td = parent.find_all('td')[1] if len(parent.find_all('td')) > 1 else None
                                if addr_td:
                                    address = addr_td.get_text(' ', strip=True)

                    if not nome:
                        continue

                    party, created = Party.objects.update_or_create(
                        process=process_obj,
                        name__iexact=nome,
                        defaults={
                            'name': nome,
                            'name_normalized': nome.upper().strip(),
                            'role': role,
                            'cpf_cnpj': cpf_cnpj,
                            'cpf_cnpj_encrypted': encrypt(cpf_cnpj) if cpf_cnpj else '',
                            'rg': rg,
                            'rg_encrypted': encrypt(rg) if rg else '',
                            'nome_pai': nome_pai,
                            'nome_mae': nome_mae,
                            'email': email,
                            'phone': phone,
                            'address': address,
                        }
                    )
                    if created:
                        ok += 1

            time.sleep(0.3)

        self.stdout.write(self.style.SUCCESS(f'Partes extraidas/criadas: {ok}'))
