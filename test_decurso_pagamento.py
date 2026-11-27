"""Testes da certidão de decurso de pagamento voluntário."""

from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from projudi.decurso_certidao import (
    gerar_preview, motivo, registrar, texto_certidao,
)
from projudi.decurso_pagamento_service import DecursoPagamentoService
from projudi.models import PrazoDjenRecord


def resultado_fake():
    return {
        'processo': '0000001-11.2026.8.05.0191',
        'url': 'https://exemplo/processo',
        'executado': 'FULANO DE TAL',
        'parte_papel': 'PROMOVIDO',
        'evento_despacho': '10',
        'despacho_auto': True,
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


class DecursoPagamentoHelpersTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email='teste-decurso@local', password='x', first_name='Teste')

    def test_trecho_pagamento_reconhece_art_523(self):
        texto = (
            'Intime-se a parte executada para, no prazo de 15 (quinze) dias, '
            'efetuar o pagamento voluntário, nos termos do art. 523 do CPC.'
        )
        trecho = DecursoPagamentoService._trecho_pagamento(texto)
        self.assertTrue(trecho)
        self.assertIn('PAGAMENTO', trecho.upper())

    def test_trecho_pagamento_ignora_texto_comum(self):
        self.assertFalse(
            DecursoPagamentoService._trecho_pagamento(
                'Juntada de petição de contestação.'))

    @patch.object(DecursoPagamentoService, '_carregar')
    def test_analisar_localiza_despacho_e_intimacao(self, carregar):
        partes = [{
            'nome': 'FULANO DE TAL',
            'papel': 'PROMOVIDO',
            'tipo': 'EXECUTADO',
        }]
        movs = [
            {
                'evento': '10',
                'ato': 'Despacho',
                'observacao': (
                    'Intime-se a parte executada para pagar em 15 dias, '
                    'nos termos do art. 523 do CPC.'),
                'data_obj': date(2026, 12, 1),
                'data_texto': '01/12/26',
            },
            {
                'evento': '11',
                'ato': 'Disponibilização no Diário da Justiça Eletrônico - DJEN',
                'observacao': (
                    'Disponibilização no DJEN em (02/12/2026) '
                    'para FULANO DE TAL'),
                'data_obj': date(2026, 12, 2),
                'data_djen': date(2026, 12, 2),
            },
        ]
        carregar.return_value = (None, 'https://exemplo/processo', partes, movs)

        resultado = DecursoPagamentoService(self.user).analisar(
            '0000001-11.2026.8.05.0191',
            hoje=date(2027, 3, 1),
        )

        self.assertNotIn('erro', resultado, resultado)
        self.assertTrue(resultado['decorrido'])
        self.assertEqual(resultado['evento_despacho'], '10')
        self.assertEqual(resultado['evento_intimacao'], '11')
        self.assertEqual(resultado['executado'], 'FULANO DE TAL')
        self.assertEqual(resultado['meio'], 'eletronico')
        self.assertEqual(resultado['data_intimacao'], date(2026, 12, 2))
        self.assertGreater(resultado['data_decurso'], resultado['ultimo_dia'])

    @patch.object(DecursoPagamentoService, '_carregar')
    def test_analisar_prefere_djen_publicado_a_intimacao_pendente(self, carregar):
        partes = [{
            'nome': 'BANCO MERCANTIL DO BRASIL SA',
            'papel': 'PROMOVIDO',
            'tipo': 'EXECUTADO',
        }]
        movs = [
            {
                'evento': '28',
                'ato': 'Proferido despacho de mero expediente',
                'ato_normalizado': 'proferido despacho de mero expediente',
                'observacao': (
                    'Intime-se a parte executada para pagar em 15 dias, '
                    'nos termos do art. 523 do CPC.'),
                'data_obj': date(2026, 10, 26),
                'data_texto': '26/10/26',
            },
            {
                'evento': '30',
                'ato': (
                    'Intimação expedido(a) (P/ Advgs. de BANCO MERCANTIL '
                    'DO BRASIL SA) Prazo: 15 dias; Aguardando '
                    'disponibilização no Diário da Justiça Eletrônico '
                    'Nacional - DJEN (CNJ)'),
                'data_obj': date(2026, 10, 26),
                'data_texto': '26/10/26',
            },
            {
                'evento': '31',
                'ato': (
                    'Disponibilização no Diário da Justiça Eletrônico - '
                    'DJEN Disponibilização no Diário da Justiça Eletrônico '
                    'em (02/11/26) para BANCO MERCANTIL DO BRASIL SA '
                    '*Referente ao evento Proferido despacho de mero '
                    'expediente'),
                'data_obj': date(2026, 11, 2),
                'data_texto': '02/11/26',
                'data_djen': date(2026, 11, 2),
            },
        ]
        carregar.return_value = (None, 'https://exemplo/processo', partes, movs)

        resultado = DecursoPagamentoService(self.user).analisar(
            '0002156-47.2026.8.05.0191',
            evento='28',
            parte_nome='BANCO MERCANTIL DO BRASIL SA',
            hoje=date(2026, 11, 27),
        )

        self.assertNotIn('erro', resultado, resultado)
        self.assertEqual(resultado['evento_intimacao'], '31')
        self.assertEqual(resultado['data_intimacao'], date(2026, 11, 2))
        self.assertEqual(resultado['meio'], 'eletronico')
        self.assertEqual(resultado['ultimo_dia'], date(2026, 11, 25))
        self.assertEqual(resultado['data_decurso'], date(2026, 11, 26))

    def test_texto_e_motivo(self):
        resultado = resultado_fake()
        texto = texto_certidao(resultado)
        self.assertIn('DECURSO DO PRAZO', texto)
        self.assertIn(
            'intimação eletrônica (DJEN), evento 11', texto)
        self.assertIn('Publicação em 03/12/2026', texto)
        self.assertIn('início do prazo em 04/12/2026', texto)
        self.assertIn('decurso em 24/12/2026', texto)
        self.assertIn('Despacho: evento 10', motivo(resultado))

    def test_texto_sem_evento(self):
        resultado = resultado_fake()
        resultado['evento_intimacao'] = ''
        self.assertIn(
            'intimação eletrônica (DJEN), evento não informado',
            texto_certidao(resultado),
        )

    def test_gerar_preview_e_registrar(self):
        resultado = resultado_fake()
        saida = Path(settings.BASE_DIR) / 'var' / 'teste_decurso_pagamento.html'
        self.addCleanup(lambda: saida.unlink(missing_ok=True))

        html, caminho = gerar_preview(
            resultado, 'Ivan Guedes da Silva', 'Secretário',
            saida=str(saida),
        )
        self.assertTrue(saida.is_file())
        self.assertIn('CERTIDÃO DE DECURSO', html)
        self.assertIn('FULANO DE TAL', html)

        registro = registrar(
            resultado,
            certidao_path=caminho,
            servidor='Ivan Guedes da Silva',
        )
        self.assertEqual(registro.origem, 'movimentacao')
        self.assertEqual(registro.tipo_prazo, 'decurso_pagamento')
        self.assertEqual(registro.parte, 'FULANO DE TAL')
        self.assertEqual(registro.evento_origem, '10')
        self.assertIsNone(registro.tempestivo)

    def test_gerar_preview_sem_executado_omite_cabecalho(self):
        resultado = resultado_fake()
        resultado['executado'] = ''
        saida = (
            Path(settings.BASE_DIR) / 'var' / 'teste_decurso_sem_parte.html')
        self.addCleanup(lambda: saida.unlink(missing_ok=True))

        html, _caminho = gerar_preview(
            resultado, 'Ivan Guedes da Silva', 'Servidor Secretaria 2',
            saida=str(saida),
        )
        self.assertNotIn('EXECUTADO(A)', html)
        self.assertIn('pelo(a)(s) executado(a)(s)', html)

    def test_cabecalhos_de_partes_sao_condicionais(self):
        from processes.models import DocumentTemplate

        decurso = DocumentTemplate.objects.get(
            name='Certidão de Decurso de Prazo para Pagamento Voluntário')
        self.assertIn('{% if executado %}', decurso.html_template)

        base = DocumentTemplate.objects.get(
            name='Certidão de Prazo — Modelo Base')
        self.assertIn('{% if parte %}', base.html_template)


class CertidaoDecursoViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email='teste-decurso-view@local', password='x',
            first_name='Teste')
        self.client.force_login(self.user)

    @patch('projudi.decurso_views.DecursoPagamentoService.analisar')
    def test_post_gera_certidao(self, analisar):
        analisar.return_value = resultado_fake()
        resposta = self.client.post(
            reverse('projudi:certidao_decurso_pagamento'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'evento': '10',
                'executado': 'FULANO DE TAL',
                'assinante': 'ivan',
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

    @patch('projudi.decurso_views.DecursoPagamentoService.analisar')
    def test_post_nao_gera_antes_do_decurso(self, analisar):
        resultado = resultado_fake()
        resultado['decorrido'] = False
        analisar.return_value = resultado
        resposta = self.client.post(
            reverse('projudi:certidao_decurso_pagamento'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'evento': '',
                'executado': '',
                'assinante': 'ivan',
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(
            PrazoDjenRecord.objects.filter(
                tipo_prazo='decurso_pagamento').exists())
        self.assertContains(resposta, 'ainda não decorreu')
