"""Testes da contagem DJEN (disponibilização -> publicação -> início)."""

import unittest
from datetime import date

from projudi.certidao_inominado import texto_certidao_inominado
from projudi.prazo_service import PrazoService, TIPOS_PRAZO


class PrazoDjenTest(unittest.TestCase):
    def setUp(self):
        # Inclui feriados nacionais fixos e móveis + recesso forense.
        self.svc = PrazoService()

    def test_disponibilizacao_sabado(self):
        r = self.svc.contar_prazo_djen(date(2026, 11, 28), 10)
        self.assertEqual(r.data_disponibilizacao_efetiva, date(2026, 11, 28))
        self.assertEqual(r.data_publicacao, date(2026, 11, 30))
        self.assertEqual(r.data_inicio_contagem, date(2026, 12, 1))
        self.assertEqual(r.ultimo_dia, date(2026, 12, 14))
        self.assertEqual(r.data_decurso, date(2026, 12, 15))

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
        self.assertEqual(r.data_disponibilizacao_efetiva, date(2026, 11, 15))
        self.assertEqual(r.data_publicacao, date(2026, 11, 16))
        self.assertEqual(r.data_inicio_contagem, date(2026, 11, 17))
        # 20/11 (Consciência Negra) é feriado nacional.
        self.assertEqual(r.ultimo_dia, date(2026, 12, 1))
        self.assertEqual(r.data_decurso, date(2026, 12, 2))

    def test_disponibilizacao_finados(self):
        # 02/11/2026 é Finados (feriado). O próximo dia útil (03/11) já é a
        # publicação; o prazo inicia em 04/11.
        r = self.svc.contar_prazo_djen(date(2026, 11, 2), 15)
        self.assertEqual(r.data_disponibilizacao_efetiva, date(2026, 11, 2))
        self.assertEqual(r.data_publicacao, date(2026, 11, 3))
        self.assertEqual(r.data_inicio_contagem, date(2026, 11, 4))
        self.assertEqual(r.ultimo_dia, date(2026, 11, 25))
        self.assertEqual(r.data_decurso, date(2026, 11, 26))

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

    def test_texto_certidao_inominado(self):
        grat = texto_certidao_inominado(
            evento_recurso='50', tempestivo=True,
            preparo_status='gratuidade')
        self.assertIn('evento 50', grat)
        self.assertIn('TEMPESTIVO', grat)
        self.assertIn(
            'Não houve o PREPARO, em razão do pedido de assistência '
            'judiciária gratuita.', grat)

        completo = texto_certidao_inominado(
            evento_recurso='50', tempestivo=True, preparo_status='completo')
        self.assertIn('TEMPESTIVO e regularmente PREPARADO.', completo)

        incompleto = texto_certidao_inominado(
            evento_recurso='50', tempestivo=True,
            preparo_status='incompleto')
        self.assertIn('TEMPESTIVO, porém o PREPARO está INCOMPLETO.',
                      incompleto)

        nao_pago = texto_certidao_inominado(
            evento_recurso='50', tempestivo=True,
            preparo_status='nao_pago')
        self.assertIn('TEMPESTIVO, porém NÃO HOUVE O PREPARO.', nao_pago)

        intemp = texto_certidao_inominado(
            evento_recurso='50', tempestivo=False)
        self.assertIn('INTEMPESTIVO.', intemp)
        self.assertNotIn('PREPARO', intemp)

        sem_hab = texto_certidao_inominado(
            evento_recurso='50', tempestivo=True, preparo_status='completo',
            habilitacao_regular=False)
        self.assertNotIn('habilitação dos advogados', sem_hab)


if __name__ == '__main__':
    unittest.main()
