"""
Comando para importar arquivos HTML de despachos/decisões salvos
na pasta scripts/doc_restrear_rag/ e criar registros RAG no banco.

Uso:
  python manage.py importar_rag_docs
  python manage.py importar_rag_docs --pasta scripts/doc_restrear_rag
  python manage.py importar_rag_docs --processo-only 0000799-32.2026.8.05.0191
"""

import re
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from base.utils import normalize_process_number


class Command(BaseCommand):
    help = 'Importa HTML de despachos salvos localmente para a base RAG'

    def add_arguments(self, parser):
        parser.add_argument(
            '--pasta',
            type=str,
            default='scripts/doc_restrear_rag',
            help='Pasta com os HTMLs dos despachos',
        )
        parser.add_argument(
            '--processo-only',
            type=str,
            help='Só importar arquivo que contenha este número de processo',
        )

    def handle(self, *args, **options):
        base_dir = settings.BASE_DIR
        pasta = Path(base_dir) / options['pasta']
        filtro_processo = options.get('processo_only')

        if not pasta.exists():
            raise CommandError(f'Pasta não encontrada: {pasta}')

        # Garante a subpasta processed/
        pasta_processados = pasta / 'processed'
        pasta_processados.mkdir(exist_ok=True)

        html_files = sorted(pasta.glob('*.html'))
        if not html_files:
            self.stdout.write(self.style.WARNING(
                f'Nenhum arquivo .html encontrado em {pasta}'
            ))
            return

        # Filtra por número de processo se especificado
        if filtro_processo:
            num_clean = re.sub(r'[^0-9]', '', filtro_processo)
            html_files = [
                f for f in html_files
                if num_clean in f.read_text(encoding='utf-8', errors='replace')
            ]
            if not html_files:
                self.stdout.write(self.style.WARNING(
                    f'Nenhum .html contém o processo {filtro_processo}'
                ))
                return

        # Pega primeiro usuário ativo para tenant
        from accounts.models import User
        user = User.objects.filter(is_active=True).first()
        if not user:
            self.stdout.write(self.style.ERROR('Nenhum usuário ativo encontrado'))
            return

        # Pega vara padrão (2ª VSJ / Paulo Afonso)
        from projudi.models import Vara, Judge, Court
        tenant = user.tenant
        court, _ = Court.objects.get_or_create(
            code='TJBA',
            tenant=tenant,
            defaults={'name': 'Tribunal de Justiça da Bahia', 'state': 'BA'},
        )
        vara, _ = Vara.objects.get_or_create(
            court=court,
            code='2VSJ-PA',
            tenant=tenant,
            defaults={
                'name': '2ª Vara do Sistema dos Juizados Especiais de Paulo Afonso',
                'comarca': 'Paulo Afonso',
            },
        )

        from processes.models import Process, Party, RAGExample, DocumentTemplate

        importados = 0
        erros = 0

        for html_path in html_files:
            try:
                raw = html_path.read_text(encoding='utf-8', errors='replace')
                texto_plano = _extrair_texto_plano(raw)
                texto_bruto = _extrair_texto_bruto(raw)

                # ── Extrair dados ──────────────────────────────────
                num_processo = _extrair_processo(texto_plano)
                if not num_processo:
                    self.stdout.write(self.style.WARNING(
                        f'[PULAR] {html_path.name} — número de processo não encontrado'
                    ))
                    erros += 1
                    continue

                promoventes = _extrair_promoventes(texto_plano)
                promovidos = _extrair_promovidos(texto_plano)
                juiz_nome = _extrair_juiz(texto_bruto)
                despacho_texto = _extrair_despacho(texto_plano, raw)
                evento_despacho = _extrair_evento(texto_plano)

                # ── Criar/atualizar Process ────────────────────────
                num_normalized = normalize_process_number(num_processo)
                process_obj, created = Process.objects.get_or_create(
                    number=num_processo,
                    tenant=user.tenant,
                    defaults={
                        'number_normalized': num_normalized,
                        'status': 'analyzing',
                        'vara': vara,
                        'court': court,
                        'class_processual': 'PROCEDIMENTO DO JUIZADO ESPECIAL CÍVEL',
                    },
                )
                if created:
                    self.stdout.write(f'  [CRIAR] Processo {num_processo}')

                # Atualiza vara se estiver vazia
                if not process_obj.vara:
                    process_obj.vara = vara
                    process_obj.court = court
                    process_obj.save(update_fields=['vara', 'court'])

                # ── Criar/atualizar juiz ───────────────────────────
                if juiz_nome and not process_obj.judge:
                    judge_obj, _ = Judge.objects.get_or_create(
                        vara=vara, name=juiz_nome.upper(),
                        tenant=tenant,
                    )
                    process_obj.judge = judge_obj
                    process_obj.save(update_fields=['judge'])

                # ── Criar partes ────────────────────────────────────
                for nome_parte in promoventes:
                    nome_parte = nome_parte.strip()
                    if nome_parte and not Party.objects.filter(
                        process=process_obj, tenant=tenant, name=nome_parte
                    ).exists():
                        Party.objects.create(
                            process=process_obj, tenant=tenant,
                            name=nome_parte,
                            name_normalized=nome_parte.lower().strip(),
                            role='autor',
                        )
                        self.stdout.write(f'    Autor: {nome_parte}')

                for nome_parte in promovidos:
                    nome_parte = nome_parte.strip()
                    if nome_parte and not Party.objects.filter(
                        process=process_obj, tenant=tenant, name=nome_parte
                    ).exists():
                        Party.objects.create(
                            process=process_obj, tenant=tenant,
                            name=nome_parte,
                            name_normalized=nome_parte.lower().strip(),
                            role='reu',
                        )
                        self.stdout.write(f'    Réu: {nome_parte}')

                # ── Criar RAGExample ───────────────────────────────
                # Evita duplicar se já existe exatamente o mesmo despacho
                rag_existente = RAGExample.objects.filter(
                    process=process_obj,
                    despacho_ato=despacho_texto[:500],
                )
                if not rag_existente.exists():
                    RAGExample.objects.create(
                        tenant=user.tenant,
                        process=process_obj,
                        oficio='',
                        despacho_ato=despacho_texto[:5000],
                        despacho_observacao=despacho_texto[:5000],
                        despacho_data=datetime.now().strftime('%d/%m/%Y'),
                        despacho_autor=juiz_nome or 'Desconhecido',
                        evento_despacho=evento_despacho or '',
                        cumprimentos=[],
                        documentos=[],
                        active=True,
                    )
                    self.stdout.write(f'    [RAG] Exemplo criado')
                else:
                    self.stdout.write(f'    [RAG] Exemplo já existe — pulado')

                # ── Marcar como processado ─────────────────────────
                dest = pasta_processados / html_path.name
                shutil.move(str(html_path), str(dest))
                importados += 1
                self.stdout.write(self.style.SUCCESS(f'  [OK] {html_path.name}'))

            except Exception as e:
                self.stderr.write(self.style.ERROR(
                    f'[ERRO] {html_path.name}: {e}'
                ))
                erros += 1

        # ── Resumo ──────────────────────────────────────────────
        self.stdout.write('\n' + '=' * 50)
        self.stdout.write(self.style.SUCCESS(
            f'Importados: {importados}   |   Erros: {erros}   |   Total arquivos: {len(html_files)}'
        ))
        restantes = len(list(pasta.glob('*.html')))
        if restantes:
            self.stdout.write(self.style.WARNING(
                f'Ainda há {restantes} arquivo(s) não processados em {pasta}/'
            ))
        self.stdout.write('=' * 50)


# ── Helpers de extração ──────────────────────────────────────────


def _extrair_texto_plano(html: str) -> str:
    """Remove tags HTML do despacho, mantém texto limpo."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    return soup.get_text(' ', strip=True)


def _extrair_texto_bruto(html: str) -> str:
    """Igual _extrair_texto_plano mas preserva quebras de linha (\n)
    entre elementos block, útil para extrair juiz e blocos."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup.find_all(['br', 'p', 'div', 'hr']):
        tag.append('\n')
    # get_text() sem strip=True preserva os \n inseridos
    texto = soup.get_text()
    # Normaliza whitespace mas mantém quebras de linha
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r'\n\s*\n', '\n', texto)
    return texto.strip()


def _extrair_processo(texto: str) -> str | None:
    """Extrai número CNJ: 0000799-32.2026.8.05.0191"""
    m = re.search(
        r'(?:processo|proc\.?)\s*n[º°.]?\s*'
        r'(\d{4,7}[-.]\d{2}[-.]?\d{4}[-.]?\d[-.]?\d{2}[-.]?\d{4})',
        texto, re.I
    )
    if m:
        return m.group(1)
    # fallback: any CNJ-like number in the text
    m = re.search(
        r'(\d{7}[-]\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})',
        texto
    )
    if m:
        return m.group(1)
    m = re.search(
        r'(\d{7}[-]\d{2}\.\d{4}\.\d\.\d{2})',
        texto
    )
    if m:
        return m.group(1)
    return None


def _extrair_promoventes(texto: str) -> list[str]:
    """Extrai parte(s) promovente(s)."""
    partes = []
    m = re.search(
        r'promovente\(s\)\s+([\wÀ-Ú\s]+?)(?:\s+e\s+como\s+promovido|\s{3,}|$|(?:\d\.\s))',
        texto, re.I
    )
    if m:
        raw = m.group(1).strip()
        for nome in re.split(r'\s+e\s+', raw):
            nome = nome.strip().strip(',')
            if nome and len(nome) > 3:
                partes.append(nome)
    if not partes:
        # fallback: Procura "promovente(s) X" mais simples
        m = re.search(r'promovente\(s\)\s+([\wÀ-Ú\s]{3,60}?)(?:\s*$|promovido)', texto, re.I)
        if m:
            raw = m.group(1).strip()
            for nome in re.split(r'\s+e\s+', raw):
                nome = nome.strip().strip(',')
                if nome and len(nome) > 3:
                    partes.append(nome)
    return partes


def _extrair_promovidos(texto: str) -> list[str]:
    """Extrai parte(s) promovido(s)."""
    partes = []
    # Tenta capturar até o próximo número/item numerado ou fim do texto
    m = re.search(
        r'promovido\(s\)\s+([\wÀ-Ú\s]{3,200}?)(?:\s*\n\s*\d+\.\s+|\s{2,}\d+\.\s+|$)',
        texto, re.I | re.DOTALL
    )
    if m:
        raw = m.group(1).strip()
        for nome in re.split(r'\s+e\s+', raw):
            nome = nome.strip().strip(',').strip('\xa0')
            if nome and len(nome) > 3:
                partes.append(nome)
    # Fallback: se nada acima funcionou, tenta com DOTALL capturando mais
    if not partes:
        m = re.search(
            r'promovido\(s\)\s+(.+?)(?:Documento|\d+\.|$)',
            texto, re.I | re.DOTALL
        )
        if m:
            raw = m.group(1).strip()
            for nome in re.split(r'\s+e\s+', raw):
                nome = nome.strip().strip(',').strip('\xa0')
                if nome and len(nome) > 3:
                    partes.append(nome)
    return partes


def _extrair_juiz(texto: str) -> str | None:
    """Extrai nome do juiz. Tenta com quebras (\n) e sem."""
    # Com quebra de linha
    m = re.search(
        r'([A-ZÀ-Ú\s]{10,80})\s*\n\s*JUIZ\s+DE\s+DIREITO',
        texto
    )
    if m:
        return m.group(1).strip()
    # Sem quebra — nome + JUIZ DE DIREITO colados
    m = re.search(
        r'([A-ZÀ-Ú\s]{10,80}?)\s+JUIZ\s+DE\s+DIREITO',
        texto
    )
    if m:
        return m.group(1).strip()
    return None


def _extrair_despacho(texto: str, html: str) -> str:
    """Extrai o texto do despacho — entre o título DESPACHO e o nome do juiz.

    Tenta duas estratégias:
    1. Pega o <p> ou bloco HTML após o título DESPACHO
    2. Fallback: texto entre 'DESPACHO' e o nome do juiz
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')

    # Tenta pegar o(s) parágrafo(s) dentro do div principal após 'DESPACHO'
    # No HTML típico: <p class="western"> com o texto do despacho
    paragrafos = soup.find_all('p', class_='western')
    blocos = []
    dentro_despacho = False
    for p in paragrafos:
        texto_p = p.get_text(' ', strip=True)
        if 'DESPACHO' in texto_p.upper():
            dentro_despacho = True
            continue
        if dentro_despacho:
            # Para quando achar o juiz ou rodapé
            if 'JUIZ DE DIREITO' in texto_p.upper() or 'assinado eletronicamente' in texto_p.lower():
                break
            if texto_p:
                blocos.append(texto_p)

    if blocos:
        return '\n'.join(blocos)

    # Fallback: texto bruto entre DESPACHO e nome do juiz
    m = re.search(
        r'DESPACHO[^]*?1[\.\s-]+(.+?)(?:[A-ZÀ-Ú\s]{10,80}\s*JUIZ\s+DE\s+DIREITO)',
        texto, re.I | re.DOTALL
    )
    if m:
        return m.group(1).strip()

    return texto[:3000]


def _extrair_evento(texto: str) -> str | None:
    """Tenta extrair número do evento/movimentação (pouco provável em HTML solto)."""
    return None
