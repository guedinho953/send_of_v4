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
        self.assertContains(resposta, 'CONFIRMAÇÃO')
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

    @patch('projudi.juntar_views.executar_juntada_e_intimacao')
    def test_embargos_tempestivos_junta_e_intima_embargado(self, executar):
        registro = PrazoDjenRecord.objects.create(
            processo='0000002-22.2026.8.05.0191',
            origem='movimentacao',
            tipo_prazo='impugnacao_embargos_execucao',
            prazo_dias=15,
            tempestivo=True,
            seguranca_juizo='integral',
            evento_recurso='88',
            certidao_path=str(self.preview),
        )
        executar.return_value = (True, SimpleNamespace(id=123), True, '')
        resposta = self.client.post(
            reverse('projudi:certidao_juntar_intimar',
                    args=[registro.id]),
            {
                'acao': 'juntar_intimar',
                'processo_url': (
                    'https://projudi.tjba.jus.br/projudi/listagens/'
                    'DadosProcesso?numeroProcesso=12345678901234'),
                'polo': 'autores',
                'prazo': '15',
                'confirmo': 'on',
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'embargado(a) intimado(a)')
        executar.assert_called_once()

    def test_plano_embargos_tempestivos_intima_embargado(self):
        from projudi.juntar_service import montar_plano

        registro = PrazoDjenRecord.objects.create(
            processo='0000003-33.2026.8.05.0191',
            origem='movimentacao',
            tipo_prazo='impugnacao_embargos_execucao',
            prazo_dias=15,
            tempestivo=True,
            seguranca_juizo='integral',
            evento_recurso='88',
            tipo_localizador='15286',
            localizador='1',
            tipo_conclusao='18',
            juiz_conclusao='41201',
            certidao_path=str(self.preview),
        )
        plano = montar_plano(
            registro,
            self.user,
            processo_url=(
                'https://projudi.tjba.jus.br/projudi/listagens/'
                'DadosProcesso?numeroProcesso=12345678901234'),
        )
        self.assertEqual(plano['situacao'], 'embargos_tempestivos')
        self.assertEqual(plano['tipo_localizador'], '15286')
        self.assertEqual(plano['localizador'], '1')
        self.assertEqual(plano['tipo_conclusao'], '18')
        self.assertEqual(plano['juiz_conclusao'], '41201')
        self.assertTrue(plano['pode_intimar'])
        self.assertEqual(plano['polo'], 'autores')
        self.assertEqual(plano['prazo'], '15')
        self.assertEqual(plano['prazo_codigo'], '4')
        self.assertIn('embargado(a)', plano['observacao_intimacao'])
        self.assertIn('manifestação acerca dos embargos', plano['observacao_intimacao'])

    def test_plano_embargos_intempestivos_nao_intima(self):
        from projudi.juntar_service import montar_plano

        registro = PrazoDjenRecord.objects.create(
            processo='0000004-44.2026.8.05.0191',
            origem='movimentacao',
            tipo_prazo='impugnacao_embargos_execucao',
            prazo_dias=15,
            tempestivo=False,
            seguranca_juizo='nenhuma',
            certidao_path=str(self.preview),
        )
        plano = montar_plano(
            registro,
            self.user,
            processo_url=(
                'https://projudi.tjba.jus.br/projudi/listagens/'
                'DadosProcesso?numeroProcesso=12345678901234'),
        )
        self.assertEqual(plano['situacao'], 'embargos_intempestivos')
        self.assertFalse(plano['pode_intimar'])
        self.assertEqual(plano['observacao_intimacao'], '')

    @patch(
        'projudi.movimentacao_service.MovimentacaoService.executar_com_intimacao',
        return_value=True,
    )
    @patch(
        'projudi.juntar_service.executar_juntada',
        return_value=(True, SimpleNamespace(id=10)),
    )
    def test_executar_juntada_e_intimacao(self, juntar, intimar):
        from projudi.juntar_service import executar_juntada_e_intimacao

        registro = SimpleNamespace(
            processo='0000005-55.2026.8.05.0191',
            tipo_prazo='impugnacao_embargos_execucao',
        )
        plano = {
            'pode_intimar': True,
            'ja_juntada': False,
            'observacao_intimacao': (
                'Intime-se o(a) embargado(a) para manifestação.'),
            'proc_projudi': '12345678901234',
            'prazo_codigo': '4',
            'motivo_intimacao': '3',
            'polo': 'autores',
        }
        ok, record, intimacao_ok, erro = executar_juntada_e_intimacao(
            registro, self.user, plano=plano)
        self.assertTrue(ok)
        self.assertEqual(record.id, 10)
        self.assertTrue(intimacao_ok)
        self.assertEqual(erro, '')
        juntar.assert_called_once()
        intimar.assert_called_once()
        kwargs = intimar.call_args.kwargs
        self.assertEqual(kwargs['prazo_intimacao'], '4')
        self.assertEqual(kwargs['polo_intimacao'], 'autores')
        self.assertEqual(kwargs['proc_projudi'], '12345678901234')

    @patch('projudi.juntar_views.executar_conclusao')
    @patch('projudi.juntar_views.executar_juntada')
    def test_juntar_com_conclusao_usa_codigo_11383(self, juntar, conclusao):
        registro = PrazoDjenRecord.objects.create(
            processo='0000006-66.2026.8.05.0191',
            origem='movimentacao',
            tipo_prazo='impugnacao_embargos_execucao',
            prazo_dias=15,
            tempestivo=False,
            seguranca_juizo='nenhuma',
            certidao_path=str(self.preview),
        )
        juntar.return_value = (True, SimpleNamespace(id=200))
        conclusao.return_value = (True, SimpleNamespace(id=201))
        resposta = self.client.post(
            reverse('projudi:certidao_juntar_intimar',
                    args=[registro.id]),
            {
                'acao': 'juntar',
                'processo_url': (
                    'https://projudi.tjba.jus.br/projudi/listagens/'
                    'DadosProcesso?numeroProcesso=12345678901234'),
                'polo': 'autores',
                'prazo': '15',
                'fazer_conclusao': 'on',
                'tipo_conclusao': '18',
                'confirmo': 'on',
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Conclusão ao Juiz registrada')
        conclusao.assert_called_once()
        self.assertEqual(
            conclusao.call_args.kwargs['tipo_conclusao'], '18')
        self.assertEqual(
            conclusao.call_args.kwargs['juiz_conclusao'], '41201')

    @patch('projudi.movimentacao_service.MovimentacaoService')
    def test_executar_conclusao_chama_11383(self, service_cls):
        from projudi.juntar_service import executar_conclusao

        service = service_cls.return_value
        service.importar.return_value = SimpleNamespace(id=300)
        service.executar_requests.return_value = True
        registro = SimpleNamespace(
            processo='0000007-77.2026.8.05.0191')
        plano = {
            'processo_url': (
                'https://projudi.tjba.jus.br/projudi/listagens/'
                'DadosProcesso?numeroProcesso=12345678901234'),
        }
        ok, record = executar_conclusao(
            registro, self.user, plano, tipo_conclusao='18')
        self.assertTrue(ok)
        self.assertEqual(record.id, 300)
        kwargs = service.importar.call_args.kwargs
        self.assertEqual(kwargs['codigo_movimentacao'], '11383')
        self.assertEqual(kwargs['descricao_movimentacao'], 'Conclusão')
        self.assertEqual(
            service.executar_requests.call_args.kwargs['conclusao'], '18')
        self.assertEqual(
            service.executar_requests.call_args.kwargs[
                'login_conclusao_pessoal'], '41201')

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
