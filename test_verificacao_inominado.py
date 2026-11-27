"""Testes da detecção de recurso inominado e DJEN."""

import unittest
from datetime import date

from projudi.verificacao_inominado import (
    achar_intimacao_djen, achar_recurso_inominado,
)


class VerificacaoInominadoTest(unittest.TestCase):
    def setUp(self):
        self.movs = [
            {
                'evento': '75',
                'ato': 'Contrarrazões a Recurso Inominado',
                'data_obj': date(2026, 4, 1),
                'data_texto': '01/04/26',
            },
            {
                'evento': '70',
                'ato': 'Recurso Inominado',
                'data_obj': date(2026, 3, 20),
                'data_texto': '20/03/26',
            },
            {
                'evento': '59',
                'ato': (
                    'Disponibilização no Diário da Justiça Eletrônico - DJEN'),
                'data_obj': date(2026, 3, 10),
                'data_djen': date(2026, 3, 12),
                'data_texto': '10/03/26',
            },
            {
                'evento': '45',
                'ato': 'Intimação expedida',
                'data_obj': date(2026, 3, 9),
                'data_texto': '09/03/26',
            },
        ]

    def test_acha_recurso_e_ignora_contrarrazoes(self):
        mov = achar_recurso_inominado(self.movs)
        self.assertIsNotNone(mov)
        self.assertEqual(mov['evento'], '70')

    def test_acha_recurso_por_evento(self):
        mov = achar_recurso_inominado(self.movs, evento=70)
        self.assertIsNotNone(mov)
        self.assertEqual(mov['evento'], '70')

    def test_ignora_juntada_generica_que_cita_recurso(self):
        movs = [
            {
                'evento': '58',
                'ato': 'Juntada de Cumprimento Genérico',
                'observacao': 'Documento: RECURSO INOMINADO - ri.pdf',
                'data_obj': date(2026, 11, 26),
            },
            {
                'evento': '55',
                'ato': 'Juntada de Petição de Recurso Inominado',
                'data_obj': date(2026, 11, 25),
            },
        ]
        mov = achar_recurso_inominado(movs)
        self.assertIsNotNone(mov)
        self.assertEqual(mov['evento'], '55')

    def test_evento_explicito_aceita_juntada_generica(self):
        movs = [
            {
                'evento': '58',
                'ato': 'Juntada de Cumprimento Genérico',
                'observacao': 'Documento: RECURSO INOMINADO - ri.pdf',
                'data_obj': date(2026, 11, 26),
            }
        ]
        mov = achar_recurso_inominado(movs, evento=58)
        self.assertIsNotNone(mov)
        self.assertEqual(mov['evento'], '58')

    def test_intimacao_prioriza_djen(self):
        mov, data, origem = achar_intimacao_djen(self.movs, 70)
        self.assertIsNotNone(mov)
        self.assertEqual(mov['evento'], '59')
        self.assertEqual(data, date(2026, 3, 12))
        self.assertEqual(origem, 'DJEN')

    def test_intimacao_fallback_movimento(self):
        movs = [m for m in self.movs if m['evento'] != '59']
        mov, data, origem = achar_intimacao_djen(movs, 70)
        self.assertIsNotNone(mov)
        self.assertEqual(mov['evento'], '45')
        self.assertEqual(data, date(2026, 3, 9))
        self.assertEqual(origem, 'movimento')

    def test_intimacao_respeita_data_limite_do_protocolo(self):
        movs = list(self.movs) + [{
            'evento': '76',
            'ato': 'Disponibilização no DJEN',
            'data_obj': date(2026, 3, 25),
            'data_djen': date(2026, 3, 27),
            'data_texto': '25/03/26',
        }]
        mov, data, origem = achar_intimacao_djen(
            movs, None, data_limite=date(2026, 3, 26))
        self.assertIsNotNone(mov)
        self.assertEqual(mov['evento'], '59')
        self.assertEqual(data, date(2026, 3, 12))
        self.assertEqual(origem, 'DJEN')

    def test_sem_recurso(self):
        self.assertIsNone(achar_recurso_inominado(self.movs[2:]))


if __name__ == '__main__':
    unittest.main()
