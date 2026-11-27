"""Testes da certidão de decurso de pagamento voluntário."""

from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from projudi.decurso_certidao import (
    gerar_preview, motivo, registrar, texto_certidao,
)
from projudi.decurso_pagamento_service import DecursoPagamentoService


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

    def test_texto_e_motivo(self):
        resultado = self._resultado()
        self.assertIn('15 (quinze) dias', texto_certidao(resultado))
        self.assertIn('evento n.º 10', texto_certidao(resultado))
        self.assertIn('Despacho: evento 10', motivo(resultado))

    def test_gerar_preview_e_registrar(self):
        resultado = self._resultado()
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

    def _resultado(self):
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
