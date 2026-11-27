"""Separação das certidões por origem: petição x movimentação."""

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from projudi.models import PrazoDjenRecord


class CertidaoOrigemTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email='teste-certidao-origem@local',
            password='x',
            first_name='Teste',
        )
        self.client.force_login(self.user)

        self.peticao = PrazoDjenRecord.objects.create(
            processo='0000001-11.2026.8.05.0191',
            origem='peticao',
            tipo_prazo='inominado',
            prazo_dias=10,
            tempestivo=True,
            parte='Promovente: PARTE AUTORA / Promovido: PARTE RÉ',
            peticao_documento='recurso-inominado.pdf',
        )
        self.movimentacao = PrazoDjenRecord.objects.create(
            processo='0000002-22.2026.8.05.0191',
            origem='movimentacao',
            tipo_prazo='cumprimento_sentenca',
            prazo_dias=15,
            tempestivo=None,
        )

    def test_aba_peticoes_so_mostra_peticoes(self):
        resposta = self.client.get(reverse('projudi:certidao_peticoes'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, self.peticao.processo)
        self.assertNotContains(resposta, self.movimentacao.processo)
        self.assertContains(resposta, 'recurso-inominado.pdf')

    def test_aba_movimentacoes_so_mostra_movimentacoes(self):
        resposta = self.client.get(reverse('projudi:certidao_movimentacoes'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, self.movimentacao.processo)
        self.assertNotContains(resposta, self.peticao.processo)

    def test_dashboard_geral_mostra_as_duas(self):
        resposta = self.client.get(reverse('projudi:certidao_dashboard'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, self.peticao.processo)
        self.assertContains(resposta, self.movimentacao.processo)

    def test_detalhe_mostra_origem_e_peticao(self):
        resposta = self.client.get(
            reverse('projudi:certidao_detail', args=[self.peticao.id])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Petição')
        self.assertContains(resposta, 'recurso-inominado.pdf')

    def test_detalhe_embute_preview_da_certidao(self):
        caminho = (
            Path(settings.BASE_DIR) / 'var' / 'teste_preview_detail.html')
        caminho.write_text('<html>ok</html>', encoding='utf-8')
        self.addCleanup(lambda: caminho.unlink(missing_ok=True))
        self.peticao.certidao_path = str(caminho)
        self.peticao.save(update_fields=['certidao_path'])

        resposta = self.client.get(
            reverse('projudi:certidao_detail', args=[self.peticao.id])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(
            resposta,
            reverse('projudi:certidao_preview', args=[self.peticao.id]),
        )
