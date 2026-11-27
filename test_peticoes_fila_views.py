"""Testes da fila de petições com escolha manual da certidão/ação."""

from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from projudi.models import PrazoDjenRecord

FALSA = [{
    'processo': '0000001-11.2026.8.05.0191',
    'processo_url': 'https://projudi/processo',
    'data_envio': date(2026, 11, 25),
    'tipo': 'Juntada de Petição de Recurso Inominado',
    'tipo_sugerido_label': 'Recurso Inominado',
    'tipo_prazo_sugerido': 'inominado',
    'peticao': {'nome': 'recurso.pdf', 'url': 'https://projudi/recurso.pdf'},
    'preparo_docs': [],
}]


def resultado_decurso():
    return {
        'processo': '0000001-11.2026.8.05.0191',
        'url': 'https://projudi/processo',
        'executado': 'FULANO DE TAL',
        'parte_papel': 'PROMOVIDO',
        'evento_despacho': '10',
        'despacho_auto': False,
        'despacho_trecho': 'pagamento em 15 dias',
        'evento_intimacao': '11',
        'data_intimacao': date(2026, 12, 2),
        'data_inicio': date(2026, 12, 4),
        'ultimo_dia': date(2026, 12, 24),
        'data_decurso': date(2026, 12, 25),
        'meio': 'eletronico',
        'meio_label': 'DJEN / domicílio eletrônico',
        'dias': 15,
        'decorrido': True,
        'prazo_info': {
            'data_publicacao': '2026-12-03',
            'ultimo_dia': '2026-12-24',
            'data_decurso': '2026-12-25',
        },
    }


class PeticaoFilaViewsTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email='teste-fila-peticoes@local',
            password='x',
            first_name='Teste',
        )
        self.client.force_login(self.user)

    @patch('projudi.peticoes_views.carregar_fila', return_value=FALSA)
    def test_fila_lista_peticoes(self, _carregar):
        resposta = self.client.get(reverse('projudi:certidao_peticoes_fila'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, '0000001-11.2026.8.05.0191')
        self.assertContains(resposta, 'Recurso Inominado')

    @patch('projudi.peticoes_views.call_command')
    def test_gerar_inominado_chama_comando(self, comando):
        registro = PrazoDjenRecord.objects.create(
            processo='0000001-11.2026.8.05.0191',
            origem='peticao',
            tipo_prazo='inominado',
            prazo_dias=10,
        )
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'processo_url': 'https://projudi/processo',
                'peticao_url': 'https://projudi/recurso.pdf',
                'peticao_documento': 'recurso.pdf',
                'data_envio': '25/11/2026',
                'tipo_prazo': 'inominado',
                'preparo': 'completo',
                'acao': 'gerar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertRedirects(
            resposta,
            reverse('projudi:certidao_detail', args=[registro.id]),
            fetch_redirect_response=False,
        )
        comando.assert_called_once()
        args, kwargs = comando.call_args
        self.assertEqual(args[0], 'certidao_inominado')
        self.assertEqual(kwargs['preparo'], 'completo')
        self.assertEqual(kwargs['data_protocolo'], '25/11/2026')

    @patch('projudi.peticoes_views.call_command')
    def test_inominado_sem_preparo_nao_gera(self, comando):
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'data_envio': '25/11/2026',
                'tipo_prazo': 'inominado',
                'preparo': '',
                'acao': 'gerar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        comando.assert_not_called()

    @patch('projudi.peticoes_views.localizar_intimacao_do_processo')
    @patch('projudi.peticoes_views.call_command')
    def test_contrarrazoes_localiza_intimacao_pelo_evento(
            self, comando, localizar):
        localizar.return_value = {
            'evento': '56',
            'data': date(2026, 12, 5),
            'meio': 'eletronico',
        }
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'processo_url': 'https://projudi/processo',
                'data_envio': '10/12/2026',
                'tipo_prazo': 'contrarrazoes_inominado',
                'evento_origem': '55',
                'parte': 'FULANO DE TAL',
                'acao': 'gerar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        comando.assert_called_once()
        args, kwargs = comando.call_args
        self.assertEqual(args[0], 'prazo_djen')
        self.assertEqual(kwargs['disponibilizacao'], '05/12/2026')
        self.assertEqual(kwargs['evento_intimacao'], '56')
        localizar.assert_called_once()

    @patch('projudi.peticoes_views.localizar_intimacao_do_processo',
           return_value=None)
    @patch('projudi.peticoes_views.call_command')
    def test_contrarrazoes_sem_intimacao_e_sem_data_nao_gera(
            self, comando, _localizar):
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'processo_url': 'https://projudi/processo',
                'data_envio': '10/12/2026',
                'tipo_prazo': 'contrarrazoes_inominado',
                'evento_origem': '55',
                'acao': 'gerar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        comando.assert_not_called()

    @patch('projudi.peticoes_views.call_command')
    def test_acao_nao_implementada_nao_gera(self, comando):
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'data_envio': '25/11/2026',
                'tipo_prazo': 'inominado',
                'preparo': 'completo',
                'acao': 'juntar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        comando.assert_not_called()

    @patch('projudi.peticoes_views.DecursoPagamentoService.analisar')
    def test_decurso_gera_na_propria_fila(self, analisar):
        analisar.return_value = resultado_decurso()
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'processo_url': 'https://projudi/processo',
                'tipo_prazo': 'decurso_pagamento',
                'evento_despacho': '10',
                'executado': 'FULANO DE TAL',
                'assinante': 'ivan',
                'acao': 'gerar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        registro = PrazoDjenRecord.objects.get(
            tipo_prazo='decurso_pagamento')
        self.addCleanup(
            lambda: Path(registro.certidao_path).unlink(missing_ok=True))
        self.assertRedirects(
            resposta,
            reverse('projudi:certidao_detail', args=[registro.id]),
            fetch_redirect_response=False,
        )
        self.assertEqual(registro.origem, 'movimentacao')
        self.assertEqual(registro.evento_origem, '10')
        self.assertEqual(registro.parte, 'FULANO DE TAL')
        analisar.assert_called_once()

    @patch('projudi.peticoes_views.DecursoPagamentoService.analisar')
    def test_decurso_nao_gera_antes_do_prazo(self, analisar):
        resultado = resultado_decurso()
        resultado['decorrido'] = False
        analisar.return_value = resultado
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'tipo_prazo': 'decurso_pagamento',
                'evento_despacho': '',
                'executado': '',
                'assinante': 'ivan',
                'acao': 'gerar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertFalse(
            PrazoDjenRecord.objects.filter(
                tipo_prazo='decurso_pagamento').exists())
