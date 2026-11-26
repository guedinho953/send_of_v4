"""Testes de partes, recorrente e intimação nominal do recorrente."""

import unittest
from datetime import date

from projudi.partes_inominado import (
    achar_recorrente, limpar_nome_parte, texto_partes,
)
from projudi.verificacao_inominado import (
    achar_intimacao_djen, mov_menciona_parte,
)

PARTES = [
    {
        'nome': 'MARIA DE FATIMA DE JESUS',
        'nome_normalizado': 'MARIA DE FATIMA DE JESUS',
        'papel': 'PROMOVENTE',
    },
    {
        'nome': 'BANCO BRADESCO S A',
        'nome_normalizado': 'BANCO BRADESCO S A',
        'papel': 'PROMOVIDO',
    },
]

TEXTO_PETICAO = """
RECURSO INOMINADO
BANCO BRADESCO S.A., já devidamente qualificado nos autos da Ação
Indenizatória que lhe move MARIA DE FATIMA DE JESUS, por intermédio de
seus procuradores, inconformado com a sentença, vem, tempestivamente,
interpor o presente recurso.
"""

TEXTO_PETICAO_MARIA = """
RECURSO INOMINADO
MARIA DE FATIMA DE JESUS, já devidamente qualificada nos autos da Ação
Indenizatória que move contra BANCO BRADESCO S.A., vem interpor recurso.
"""


class PartesInominadoTest(unittest.TestCase):
    def test_limpa_rotulo_colado_ao_nome(self):
        self.assertEqual(
            limpar_nome_parte('MARIA DE FATIMA DE JESUSProcesso(s) Distribuído(s)'),
            'MARIA DE FATIMA DE JESUS',
        )

    def test_monta_promovente_e_promovido(self):
        self.assertEqual(
            texto_partes(PARTES),
            'Promovente: MARIA DE FATIMA DE JESUS / '
            'Promovido: BANCO BRADESCO S A',
        )

    def test_identifica_recorrente_banco(self):
        self.assertEqual(
            achar_recorrente(TEXTO_PETICAO, PARTES),
            'BANCO BRADESCO S A',
        )

    def test_identifica_recorrente_maria(self):
        self.assertEqual(
            achar_recorrente(TEXTO_PETICAO_MARIA, PARTES),
            'MARIA DE FATIMA DE JESUS',
        )

    def test_movimento_menciona_parte(self):
        mov = {
            'ato': (
                'Disponibilização no DJEN em (09/11/26) '
                'para BANCO BRADESCO S.A.'
            )
        }
        self.assertTrue(mov_menciona_parte(mov, 'BANCO BRADESCO S A'))
        self.assertFalse(mov_menciona_parte(mov, 'MARIA DE FATIMA DE JESUS'))

    def test_intimacao_prioriza_recorrente(self):
        movs = [
            {
                'evento': '49',
                'ato': (
                    'Disponibilização no DJEN ... '
                    'para BANCO BRADESCO S A'
                ),
                'data_obj': date(2026, 11, 5),
                'data_djen': date(2026, 11, 9),
            },
            {
                'evento': '48',
                'ato': (
                    'Disponibilização no DJEN ... '
                    'para MARIA DE FATIMA DE JESUS'
                ),
                'data_obj': date(2026, 11, 5),
                'data_djen': date(2026, 11, 9),
            },
        ]

        mov, data, origem = achar_intimacao_djen(
            movs, None, data_limite=date(2026, 11, 25),
            parte='MARIA DE FATIMA DE JESUS')
        self.assertEqual(mov['evento'], '48')
        self.assertEqual(data, date(2026, 11, 9))
        self.assertEqual(origem, 'DJEN')

        mov, data, origem = achar_intimacao_djen(
            movs, None, data_limite=date(2026, 11, 25),
            parte='BANCO BRADESCO S A')
        self.assertEqual(mov['evento'], '49')

    def test_sem_recorrente_usa_a_mais_recente(self):
        movs = [
            {
                'evento': '49',
                'ato': 'Disponibilização no DJEN para BANCO BRADESCO S A',
                'data_obj': date(2026, 11, 5),
                'data_djen': date(2026, 11, 9),
            },
            {
                'evento': '48',
                'ato': 'Disponibilização no DJEN para MARIA DE FATIMA DE JESUS',
                'data_obj': date(2026, 11, 5),
                'data_djen': date(2026, 11, 9),
            },
        ]
        mov, _, _ = achar_intimacao_djen(
            movs, None, data_limite=date(2026, 11, 25))
        self.assertEqual(mov['evento'], '49')


if __name__ == '__main__':
    unittest.main()
