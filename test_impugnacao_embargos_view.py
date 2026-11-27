"""Testes da certidão de impugnação/embargos na aba Movimentações."""

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from projudi.models import PrazoDjenRecord


def resultado_analise():
    return {
        'processo': '0000001-11.2026.8.05.0191',
        'executado': 'FULANO DE TAL',
        'evento_despacho': '55',
        'evento_intimacao': '56',
        'data_intimacao': date(2026, 12, 5),
        'meio': 'eletronico',
    }


class ImpugnacaoEmbargosViewTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email='teste-embargos@local',
            password='x',
            first_name='Teste',
        )
        self.client.force_login(self.user)

    def test_get_exibe_formulario(self):
        resposta = self.client.get(
            reverse('projudi:certidao_impugnacao_embargos'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Segurança do juízo')
        self.assertContains(resposta, 'Data do protocolo')
        self.assertContains(resposta, 'Evento do despacho/pagamento')

    def test_aba_movimentacoes_tem_atalho_para_o_formulario(self):
        resposta = self.client.get(reverse('projudi:certidao_movimentacoes'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(
            resposta, reverse('projudi:certidao_impugnacao_embargos'))
        self.assertContains(
            resposta, 'Nova certidão de impugnação/embargos (15 dias)')

    @patch('projudi.impugnacao_embargos_views.call_command')
    @patch('projudi.impugnacao_embargos_views.DecursoPagamentoService.analisar')
    def test_gera_certidao_na_aba_movimentacoes(self, analisar, comando):
        analisar.return_value = resultado_analise()
        registro = PrazoDjenRecord.objects.create(
            processo='0000001-11.2026.8.05.0191',
            origem='movimentacao',
            tipo_prazo='impugnacao_embargos_execucao',
            prazo_dias=15,
        )
        resposta = self.client.post(
            reverse('projudi:certidao_impugnacao_embargos'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'processo_url': 'https://projudi/processo',
                'evento': '55',
                'executado': 'FULANO DE TAL',
                'data_protocolo': '10/12/2026',
                'evento_impugnacao': '88',
                'seguranca_juizo': 'parcial',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertRedirects(
            resposta,
            reverse('projudi:certidao_detail', args=[registro.id]),
            fetch_redirect_response=False,
        )
        analisar.assert_called_once()
        comando.assert_called_once()
        args, kwargs = comando.call_args
        self.assertEqual(args[0], 'prazo_djen')
        self.assertEqual(kwargs['tipo'], 'impugnacao_embargos_execucao')
        self.assertEqual(kwargs['origem'], 'movimentacao')
        self.assertEqual(kwargs['disponibilizacao'], '05/12/2026')
        self.assertEqual(kwargs['protocolo'], '10/12/2026')
        self.assertEqual(kwargs['evento_origem'], '55')
        self.assertEqual(kwargs['evento_intimacao'], '56')
        self.assertEqual(kwargs['evento_recurso'], '88')
        self.assertEqual(kwargs['seguranca_juizo'], 'parcial')
        self.assertEqual(kwargs['parte'], 'FULANO DE TAL')

    @patch('projudi.impugnacao_embargos_views.call_command')
    @patch('projudi.impugnacao_embargos_views.DecursoPagamentoService.analisar')
    def test_sem_seguranca_nao_gera(self, analisar, comando):
        resposta = self.client.post(
            reverse('projudi:certidao_impugnacao_embargos'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'data_protocolo': '10/12/2026',
                'seguranca_juizo': '',
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Informe a segurança do juízo')
        analisar.assert_not_called()
        comando.assert_not_called()

    @patch('projudi.impugnacao_embargos_views.call_command')
    @patch('projudi.impugnacao_embargos_views.DecursoPagamentoService.analisar')
    def test_sem_protocolo_nao_gera(self, analisar, comando):
        resposta = self.client.post(
            reverse('projudi:certidao_impugnacao_embargos'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'data_protocolo': '',
                'seguranca_juizo': 'integral',
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Informe a data do protocolo')
        analisar.assert_not_called()
        comando.assert_not_called()

    @patch('projudi.impugnacao_embargos_views.call_command')
    @patch('projudi.impugnacao_embargos_views.DecursoPagamentoService.analisar')
    def test_erro_na_analise_nao_gera(self, analisar, comando):
        analisar.return_value = {'erro': 'Intimação não localizada.'}
        resposta = self.client.post(
            reverse('projudi:certidao_impugnacao_embargos'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'data_protocolo': '10/12/2026',
                'seguranca_juizo': 'integral',
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Intimação não localizada.')
        comando.assert_not_called()
