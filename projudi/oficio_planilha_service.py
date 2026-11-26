"""Integração com a planilha/tabela de ofícios no Google Docs.

A autenticação é feita por conta de serviço (service account). O documento
precisa ser compartilhado como Editor com o e-mail da conta de serviço.

Configuração no .env:
    GOOGLE_SERVICE_ACCOUNT_FILE=/caminho/para/service-account.json
    GOOGLE_OFICIOS_DOC_ID=1dY6yODJF0CFdbWZ2tH2f-cfvfyqq6RuKUo92NJE7JrY
    GOOGLE_OFICIOS_TABLE_INDEX=0

O serviço:
  - lê a última linha da tabela;
  - encontra o último número no formato 001/2026;
  - calcula o próximo número;
  - insere uma nova linha com número, data, processo e destinatário.
"""
import os
import re
from datetime import date
from pathlib import Path

from django.conf import settings


class OficioPlanilhaError(Exception):
    pass


class OficioPlanilhaService:
    SCOPES = ['https://www.googleapis.com/auth/documents']

    @staticmethod
    def _extrair_doc_id(valor):
        """Aceita o ID puro ou o link completo do Google Docs."""
        valor = (valor or '').strip()
        m = re.search(r'/(?:document|spreadsheets)/d/([A-Za-z0-9_-]+)', valor)
        return m.group(1) if m else valor

    def __init__(self, doc_id=None, credentials_file=None, table_index=None):
        doc_id = (
            doc_id
            or getattr(settings, 'GOOGLE_OFICIOS_DOC_URL', '')
            or getattr(settings, 'GOOGLE_OFICIOS_DOC_ID', '')
        )
        self.doc_id = self._extrair_doc_id(doc_id)
        self.credentials_file = (
            credentials_file
            or getattr(settings, 'GOOGLE_SERVICE_ACCOUNT_FILE', '')
        )
        if table_index is None:
            table_index = getattr(settings, 'GOOGLE_OFICIOS_TABLE_INDEX', 0)
        self.table_index = table_index
        self._docs = None

    # ------------------------------------------------------------------
    # CONFIGURAÇÃO / CONEXÃO
    # ------------------------------------------------------------------
    @property
    def credentials_path(self):
        if not self.credentials_file:
            return None
        path = Path(self.credentials_file)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        return path

    @property
    def configurado(self):
        path = self.credentials_path
        return bool(self.doc_id and path and path.exists())

    def _service(self):
        if self._docs is not None:
            return self._docs

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise OficioPlanilhaError(
                'Dependências Google não instaladas. Rode: '
                'pip install google-api-python-client google-auth '
                'google-auth-httplib2'
            ) from exc

        path = self.credentials_path
        if not path or not path.exists():
            raise OficioPlanilhaError(
                f'Arquivo da conta de serviço não encontrado: {path}'
            )

        creds = service_account.Credentials.from_service_account_file(
            str(path), scopes=self.SCOPES
        )
        self._docs = build(
            'docs', 'v1', credentials=creds, cache_discovery=False
        )
        return self._docs

    def _get_document(self):
        return self._service().documents().get(
            documentId=self.doc_id
        ).execute()

    def _batch_update(self, requests):
        return self._service().documents().batchUpdate(
            documentId=self.doc_id,
            body={'requests': requests},
        ).execute()

    # ------------------------------------------------------------------
    # LEITURA DA TABELA
    # ------------------------------------------------------------------
    @staticmethod
    def _texto_celula(cell):
        textos = []
        for content in cell.get('content', []):
            paragraph = content.get('paragraph')
            if not paragraph:
                continue
            for element in paragraph.get('elements', []):
                text_run = element.get('textRun')
                if text_run:
                    textos.append(text_run.get('content', ''))
        return ''.join(textos).strip()

    def _linhas(self, table):
        linhas = []
        for row in table.get('tableRows', []):
            linhas.append([
                self._texto_celula(cell)
                for cell in row.get('tableCells', [])
            ])
        return linhas

    def _elementos_tabela(self, doc):
        return [
            el for el in doc.get('body', {}).get('content', [])
            if 'table' in el
        ]

    def _escolher_tabela(self, doc):
        elementos = self._elementos_tabela(doc)
        if not elementos:
            raise OficioPlanilhaError(
                'O documento Google não possui nenhuma tabela.'
            )

        index = self.table_index
        if index is not None:
            try:
                return elementos[int(index)]
            except (IndexError, TypeError, ValueError):
                pass

        # Fallback: escolhe a tabela cujo cabeçalho parece ser de ofícios.
        for el in elementos:
            linhas = self._linhas(el['table'])
            cabecalho = ' '.join(linhas[0]).lower() if linhas else ''
            score = sum(
                1 for termo in
                ['nº', 'numero', 'número', 'data', 'processo',
                 'destinat', 'órgão', 'orgao']
                if termo in cabecalho
            )
            if score >= 2:
                return el

        return elementos[0]

    def _ultimo_numero(self, doc=None):
        doc = doc or self._get_document()
        tabela = self._escolher_tabela(doc)['table']
        linhas = self._linhas(tabela)

        # Regex de número de ofício: 001/2026, 12/2026, 001/2026 - SEC.
        # Evita confundir com datas como 25/11/2026.
        padrao = re.compile(
            r'(?<![\d/])(\d{1,5})\s*/\s*(\d{4})(?![\d/])'
        )

        for linha in reversed(linhas):
            for celula in reversed(linha):
                m = padrao.search(celula or '')
                if m:
                    return m.group(1), m.group(2)

        raise OficioPlanilhaError(
            'Não encontrei nenhum número no formato 001/2026 na tabela.'
        )

    def proximo_numero(self, hoje=None):
        """Retorna o último número da planilha + 1, ex.: 013/2026."""
        seq_texto, ano_texto = self._ultimo_numero()
        seq = int(seq_texto) + 1
        largura = max(len(seq_texto), 1)
        return f'{seq:0{largura}d}/{ano_texto}'

    # ------------------------------------------------------------------
    # ESCRITA DA NOVA LINHA
    # ------------------------------------------------------------------
    def _inserir_linha_tabela(self, valores):
        doc = self._get_document()
        elemento = self._escolher_tabela(doc)
        tabela = elemento['table']
        start_index = elemento.get('startIndex')
        if start_index is None:
            raise OficioPlanilhaError(
                'Não foi possível localizar o índice da tabela.'
            )

        ultima_linha = len(tabela.get('tableRows', [])) - 1
        if ultima_linha < 0:
            raise OficioPlanilhaError('A tabela está sem linhas.')

        self._batch_update([{
            'insertTableRow': {
                'tableCellLocation': {
                    'tableStartLocation': {'index': start_index},
                    'rowIndex': ultima_linha,
                    'columnIndex': 0,
                },
                'insertBelow': True,
            }
        }])

        # Relê para localizar a nova linha e os índices das células.
        doc = self._get_document()
        tabela = self._escolher_tabela(doc)['table']
        nova_linha = tabela['tableRows'][-1]
        celulas = nova_linha.get('tableCells', [])

        # Insere da última célula para a primeira para não deslocar os
        # índices das células anteriores.
        total = min(len(celulas), len(valores))
        for idx in range(total - 1, -1, -1):
            valor = str(valores[idx] or '').strip()
            if not valor:
                continue
            content = celulas[idx].get('content', [])
            if not content:
                continue
            insert_index = content[0].get('startIndex')
            if insert_index is None:
                continue
            self._batch_update([{
                'insertText': {
                    'location': {'index': insert_index},
                    'text': valor,
                }
            }])

    def _inserir_paragrafo(self, texto):
        doc = self._get_document()
        content = doc.get('body', {}).get('content', [])
        if not content:
            raise OficioPlanilhaError('Documento vazio.')
        end_index = content[-1].get('endIndex', 1) - 1
        self._batch_update([{
            'insertText': {
                'location': {'index': end_index},
                'text': texto + '\n',
            }
        }])

    def registrar(self, numero, processo, destinatario, data=None):
        """Adiciona a linha com número, data, processo e destinatário."""
        data = data or date.today()
        valores = [
            numero,
            data.strftime('%d/%m/%Y'),
            processo,
            destinatario,
        ]

        try:
            self._inserir_linha_tabela(valores)
        except Exception as exc:
            # Se a tabela não puder ser editada, tenta ao menos registrar
            # uma linha de texto no fim do documento.
            try:
                self._inserir_paragrafo(' | '.join(valores))
            except Exception as exc2:
                raise OficioPlanilhaError(
                    f'Falha ao inserir na tabela ({exc}) e no documento '
                    f'({exc2}).'
                ) from exc2

        return valores


def obter_servico_planilha():
    """Retorna o serviço configurado ou None.

    Prioridade:
      1. Web App do Apps Script (Gmail/conta já com acesso ao documento);
      2. Conta de serviço do Google Docs.
    """
    if getattr(settings, 'GOOGLE_OFICIOS_WEBHOOK_URL', ''):
        from .oficio_planilha_webhook_service import (
            OficioPlanilhaWebhookService,
        )
        return OficioPlanilhaWebhookService()

    servico = OficioPlanilhaService()
    return servico if servico.configurado else None
