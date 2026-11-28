"""Testes dos cards e da fila de movimentações."""

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from projudi.models import MovimentacaoRecord


class MovimentacaoCardsTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email='teste-mov-cards@local', password='x', first_name='Teste')
        self.client.force_login(self.user)
        self.registro = MovimentacaoRecord.objects.create(
            user=self.user,
            processo='0000001-11.2026.8.05.0191',
            numero_processo_cnj='0000001-11.2026.8.05.0191',
            act_verb='certifique-se',
            categoria='outro',
            status='pendente',
            data_movimentacao=date.today(),
        )

    @patch(
        'projudi.movimentacao_views.MovimentacaoDashboardView._session_ativa',
        return_value=False,
    )
    def test_dashboard_mostra_cards_e_registro(self, _sessao):
        resposta = self.client.get(reverse('projudi:movimentacao_dashboard'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Pendentes')
        self.assertContains(resposta, '0000001-11.2026.8.05.0191')

    @patch(
        'projudi.movimentacao_views.MovimentacaoFilaView._session_ativa',
        return_value=False,
    )
    def test_fila_filtra_somente_hoje(self, _sessao):
        resposta = self.client.get(
            reverse('projudi:movimentacao_fila') + '?data=hoje')
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, '0000001-11.2026.8.05.0191')
        self.assertContains(resposta, 'Somente hoje')

    def test_lista_mostra_data_da_movimentacao(self):
        resposta = self.client.get(reverse('projudi:movimentacao_list'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, '0000001-11.2026.8.05.0191')
