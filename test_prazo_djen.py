"""Testes da contagem DJEN (disponibilização -> publicação -> início)."""

import unittest
from datetime import date

from projudi.prazo_service import PrazoService, TIPOS_PRAZO


class PrazoDjenTest(unittest.TestCase):
    def setUp(self):
        # Inclui feriados nacionais fixos e móveis + recesso forense.
        self.svc = PrazoService()

    def test_disponibilizacao_sabado(self):
        r = self.svc.contar_prazo_djen(date(2026, 11, 28), 10)
        self.assertEqual(r.data_disponibilizacao_efetiva, date(2026, 11, 30))
        self.assertEqual(r.data_publicacao, date(2026, 12, 1))
        self.assertEqual(r.data_inicio_contagem, date(2026, 12, 2))
        self.assertEqual(r.ultimo_dia, date(2026, 12, 15))
        self.assertEqual(r.data_decurso, date(2026, 12, 16))

    def test_disponibilizacao_sexta(self):
        r = self.svc.contar_prazo_djen(date(2026, 11, 27), 10)
        self.assertEqual(r.data_disponibilizacao_efetiva, date(2026, 11, 27))
        self.assertEqual(r.data_publicacao, date(2026, 11, 30))
        self.assertEqual(r.data_inicio_contagem, date(2026, 12, 1))
        self.assertEqual(r.ultimo_dia, date(2026, 12, 14))
        self.assertEqual(r.data_decurso, date(2026, 12, 15))

    def test_disponibilizacao_domingo_feriado(self):
        # 15/11/2026 é domingo e feriado nacional.
        r = self.svc.contar_prazo_djen(date(2026, 11, 15), 10)
        self.assertEqual(r.data_disponibilizacao_efetiva, date(2026, 11, 16))
        self.assertEqual(r.data_publicacao, date(2026, 11, 17))
        self.assertEqual(r.data_inicio_contagem, date(2026, 11, 18))
        # 20/11 (Consciência Negra) é feriado nacional.
        self.assertEqual(r.ultimo_dia, date(2026, 12, 2))
        self.assertEqual(r.data_decurso, date(2026, 12, 3))

    def test_prazo_inclui_o_dia_de_inicio(self):
        r = self.svc.contar_prazo_djen(date(2026, 11, 27), 1)
        self.assertEqual(r.data_inicio_contagem, date(2026, 12, 1))
        self.assertEqual(r.ultimo_dia, date(2026, 12, 1))

    def test_tipos_de_prazo(self):
        self.assertEqual(TIPOS_PRAZO['inominado']['dias'], 10)
        self.assertEqual(TIPOS_PRAZO['contrarrazoes_inominado']['dias'], 10)
        self.assertEqual(TIPOS_PRAZO['cumprimento_sentenca']['dias'], 15)
        self.assertEqual(
            TIPOS_PRAZO['pagamento_impugnacao_penhora']['dias'], 15)

        r10 = self.svc.contar_prazo_tipo(date(2026, 11, 27), 'inominado')
        self.assertEqual(r10.prazo_dias, 10)

        r15 = self.svc.contar_prazo_tipo(
            date(2026, 11, 27), 'cumprimento_sentenca')
        self.assertEqual(r15.prazo_dias, 15)
        self.assertGreater(r15.ultimo_dia, r10.ultimo_dia)


if __name__ == '__main__':
    unittest.main()
