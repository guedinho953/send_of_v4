"""Testes do plano (dry-run) de juntar/intimar."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from projudi.models import MovimentacaoRecord, PrazoDjenRecord


class JuntarIntimarPlanTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email='teste-juntar@local', password='x', first_name='Teste')
        self.client.force_login(self.user)

        self.preview = (
            Path(settings.BASE_DIR) / 'var' / 'teste_juntar_intimar.html')
        self.preview.write_text(
            '<html><body><div class="folha">'
            '<p>Certidão teste</p></div></body></html>',
            encoding='utf-8',
        )
        self.addCleanup(lambda: self.preview.unlink(missing_ok=True))

        self.registro = PrazoDjenRecord.objects.create(
            processo='0000001-11.2026.8.05.0191',
            origem='peticao',
            tipo_prazo='inominado',
            prazo_dias=10,
            tempestivo=True,
            preparo_status='completo',
            parte='Recorrente: FULANO DE TAL',
            evento_recurso='55',
            certidao_path=str(self.preview),
        )

    def test_get_mostra_simulacao(self):
        resposta = self.client.get(
            reverse('projudi:certidao_juntar_intimar',
                    args=[self.registro.id]))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'SIMULAÇÃO')
        self.assertContains(resposta, 'FULANO DE TAL')
        self.assertContains(resposta, 'Certidão de Recurso Inominado (COJE)')

    def test_simular_monta_plano_sem_executar(self):
        resposta = self.client.post(
            reverse('projudi:certidao_juntar_intimar',
                    args=[self.registro.id]),
            {
                'acao': 'simular',
                'processo_url': (
                    'https://projudi.tjba.jus.br/projudi/listagens/'
                    'DadosProcesso?numeroProcesso=12345678901234'),
                'polo': 'res',
                'prazo': '10',
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Nada foi enviado ao Projudi')
        self.assertContains(resposta, 'Intime(m)-se')
        self.assertContains(resposta, '12345678901234')

    @patch('projudi.juntar_views.executar_juntada')
    def test_juntar_executa_com_confirmacao(self, executar):
        executar.return_value = (True, SimpleNamespace(id=99))
        resposta = self.client.post(
            reverse('projudi:certidao_juntar_intimar',
                    args=[self.registro.id]),
            {
                'acao': 'juntar',
                'processo_url': (
                    'https://projudi.tjba.jus.br/projudi/listagens/'
                    'DadosProcesso?numeroProcesso=12345678901234'),
                'polo': 'res',
                'prazo': '10',
                'confirmo': 'on',
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Juntada concluída no Projudi')
        executar.assert_called_once()

    @patch('projudi.juntar_views.executar_juntada')
    def test_juntar_sem_confirmacao_nao_executa(self, executar):
        resposta = self.client.post(
            reverse('projudi:certidao_juntar_intimar',
                    args=[self.registro.id]),
            {
                'acao': 'juntar',
                'processo_url': (
                    'https://projudi.tjba.jus.br/projudi/listagens/'
                    'DadosProcesso?numeroProcesso=12345678901234'),
                'polo': 'res',
                'prazo': '10',
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Marque a confirmação')
        executar.assert_not_called()

    @patch('projudi.juntar_views.executar_juntada')
    def test_ja_juntada_bloqueia_nova_execucao(self, executar):
        MovimentacaoRecord.objects.create(
            processo=self.registro.processo,
            descricao_movimentacao='Certidão de Recurso Inominado (COJE)',
            status='cumprido',
        )
        resposta = self.client.post(
            reverse('projudi:certidao_juntar_intimar',
                    args=[self.registro.id]),
            {
                'acao': 'juntar',
                'processo_url': (
                    'https://projudi.tjba.jus.br/projudi/listagens/'
                    'DadosProcesso?numeroProcesso=12345678901234'),
                'polo': 'res',
                'prazo': '10',
                'confirmo': 'on',
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'já juntada')
        executar.assert_not_called()
