"""Testes da fila de petições com escolha manual da certidão/ação."""

from datetime import date
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

    @patch('projudi.peticoes_views.call_command')
    def test_decurso_redireciona_para_tela_especifica(self, comando):
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'data_envio': '25/11/2026',
                'tipo_prazo': 'decurso_pagamento',
                'acao': 'gerar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertIn(
            '/projudi/certidoes/movimentacoes/decurso-pagamento/',
            resposta.url,
        )
        comando.assert_not_called()
