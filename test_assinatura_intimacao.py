"""Testes da assinatura automática da intimação."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from projudi.movimentacao_service import MovimentacaoService


class AssinaturaIntimacaoTest(SimpleTestCase):
    def setUp(self):
        self.user = SimpleNamespace(projudi_password='senha-teste')
        self.service = MovimentacaoService(self.user)
        self.page = MagicMock()

    @patch('projudi.movimentacao_service._clicar_botao_assinar',
           return_value=True)
    @patch('projudi.movimentacao_service._procurar_campo_senha')
    @patch('projudi.movimentacao_service.time.sleep')
    def test_preenche_senha_salva_e_assina(
            self, _sleep, procurar, clicar):
        campo = MagicMock()
        procurar.return_value = campo

        resultado = self.service._assinar_intimacao_se_pendente(self.page)

        self.assertTrue(resultado)
        campo.fill.assert_called_once_with('senha-teste')
        clicar.assert_called_once_with(self.page, timeout=8)

    @patch('projudi.movimentacao_service._clicar_botao_assinar')
    @patch('projudi.movimentacao_service._procurar_campo_senha')
    @patch('projudi.movimentacao_service.time.sleep')
    def test_sem_campo_e_sem_botao_nao_assina(
            self, _sleep, procurar, clicar):
        procurar.return_value = None
        self.page.locator.return_value.first.count.return_value = 0

        resultado = self.service._assinar_intimacao_se_pendente(self.page)

        self.assertIsNone(resultado)
        clicar.assert_not_called()

    @patch('projudi.movimentacao_service._procurar_campo_senha')
    def test_sem_senha_salva_deixa_manual(self, procurar):
        self.user.projudi_password = ''

        resultado = self.service._assinar_intimacao_se_pendente(self.page)

        self.assertIsNone(resultado)
        procurar.assert_not_called()
