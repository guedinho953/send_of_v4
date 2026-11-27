"""Testes da localização de intimação por evento."""

import unittest
from datetime import date

from projudi.intimacao_service import localizar_intimacao_por_evento


class IntimacaoPorEventoTest(unittest.TestCase):
    def setUp(self):
        self.movs = [
            {
                'evento': '55',
                'ato': 'Juntada de Petição de Recurso Inominado',
                'data_obj': date(2026, 12, 1),
            },
            {
                'evento': '56',
                'ato': 'Disponibilização no Diário da Justiça Eletrônico - DJEN',
                'observacao': (
                    'Disponibilização no DJEN em (05/12/2026) '
                    'para FULANO DE TAL'),
                'data_obj': date(2026, 12, 5),
                'data_djen': date(2026, 12, 5),
            },
            {
                'evento': '57',
                'ato': 'Intimação expedida',
                'observacao': 'Intimação para OUTRA PARTE',
                'data_obj': date(2026, 12, 6),
            },
        ]

    def test_localiza_intimacao_posterior_por_parte(self):
        item = localizar_intimacao_por_evento(
            self.movs, 55, parte='FULANO DE TAL')
        self.assertIsNotNone(item)
        self.assertEqual(item['evento'], '56')
        self.assertEqual(item['data'], date(2026, 12, 5))
        self.assertEqual(item['meio'], 'eletronico')

    def test_evento_que_ja_e_intimacao(self):
        item = localizar_intimacao_por_evento(self.movs, 56)
        self.assertIsNotNone(item)
        self.assertEqual(item['evento'], '56')

    def test_evento_inexistente(self):
        self.assertIsNone(
            localizar_intimacao_por_evento(self.movs, 99))

    def test_sem_intimacao_posterior(self):
        movs = [self.movs[0]]
        self.assertIsNone(
            localizar_intimacao_por_evento(movs, 55))


if __name__ == '__main__':
    unittest.main()
