"""Testes da leitura da fila JuntadaPeticao."""

import unittest
from datetime import date

from projudi.peticoes_inominado import (
    ler_peticoes, listar_peticoes_inominado,
)

HTML = """
<html><body>
<table>
  <tr><td>VARA: 2ª Vara do Sistema dos Juizados - PAULO AFONSO</td></tr>
  <tr class="subTituloTabela">
    <td>Nº do processo</td><td>Data Envio</td><td>Petição/Documento</td>
  </tr>

  <tr class="tBranca">
    <td></td>
    <td>
      <a href="/projudi/listagens/DadosProcesso?numeroProcesso=111">
        0002888-28.2026.8.05.0191</a><br>MARTINHO FERRAZ
    </td>
    <td>25/11/26</td>
    <td>
      Juntada de Petição de Recurso Inominado
      Mostrar/Ocultar Petição
      <a href="/projudi/listagens/DownloadArquivo?arquivo=1">
        0002888-28.2026.8.05.0191 - ri.pdf</a>
      <a href="/projudi/listagens/DownloadArquivo?arquivo=2">
        77307.0-1-COMPROVANTES.pdf</a>
    </td>
    <td>Movimentar / Dispensar Mov.</td>
  </tr>

  <tr class="tCinza">
    <td></td>
    <td>
      <a href="/projudi/listagens/DadosProcesso?numeroProcesso=222">
        0002876-14.2026.8.05.0191</a><br>MARTINHO FERRAZ
    </td>
    <td>25/11/26</td>
    <td>
      Juntada de Petição de Contrarrazões a Recurso Inominado
      Mostrar/Ocultar Petição
      <a href="/projudi/listagens/DownloadArquivo?arquivo=3">
        CONTRARRAZOES.pdf</a>
    </td>
    <td>Movimentar / Dispensar Mov.</td>
  </tr>

  <tr class="tBranca">
    <td></td>
    <td>
      <a href="/projudi/listagens/DadosProcesso?numeroProcesso=333">
        0002753-16.2026.8.05.0191</a><br>MARTINHO FERRAZ
    </td>
    <td>26/11/26</td>
    <td>
      Juntada de Petição
      Mostrar/Ocultar Petição
      <a href="/projudi/listagens/DownloadArquivo?arquivo=4">
        RECURSO INOMINADO - FULANO.pdf</a>
      <a href="/projudi/listagens/DownloadArquivo?arquivo=5">
        GUIA RECURSAL.pdf</a>
      <a href="/projudi/listagens/DownloadArquivo?arquivo=6">
        Comprovante 616.30.pdf</a>
    </td>
    <td>Movimentar / Dispensar Mov.</td>
  </tr>

  <tr class="tCinza">
    <td></td>
    <td>
      <a href="/projudi/listagens/DadosProcesso?numeroProcesso=444">
        0001111-11.2026.8.05.0191</a><br>MARTINHO FERRAZ
    </td>
    <td>26/11/26</td>
    <td>
      Juntada de Petição
      Mostrar/Ocultar Petição
      <a href="/projudi/listagens/DownloadArquivo?arquivo=7">
        peticao-generica.pdf</a>
    </td>
    <td>Movimentar / Dispensar Mov.</td>
  </tr>

  <tr class="tBranca">
    <td></td>
    <td>
      <a href="/projudi/listagens/DadosProcesso?numeroProcesso=555">
        0002222-22.2026.8.05.0191</a><br>MARTINHO FERRAZ
    </td>
    <td>27/11/26</td>
    <td>
      Juntada de Petição de Recurso Inominado
      Mostrar/Ocultar Petição
      <a href="/projudi/listagens/DownloadArquivo?arquivo=8">
        RECURSO INOMINADO - BELTRANO.pdf</a>
      <a href="/projudi/listagens/DownloadArquivo?arquivo=9">
        CUSTAS PROCESSUAIS.pdf</a>
    </td>
    <td>Movimentar / Dispensar Mov.</td>
  </tr>
</table>
</body></html>
"""


class PeticoesInominadoTest(unittest.TestCase):
    def test_le_todas_as_peticoes(self):
        peticoes = ler_peticoes(HTML)
        self.assertEqual(len(peticoes), 5)
        self.assertEqual(peticoes[0]['processo'], '0002888-28.2026.8.05.0191')
        self.assertEqual(peticoes[0]['data_envio'], date(2026, 11, 25))

    def test_filtra_recurso_inominado_por_tipo_e_nome(self):
        peticoes = listar_peticoes_inominado(HTML)
        self.assertEqual([p['processo'] for p in peticoes], [
            '0002888-28.2026.8.05.0191',
            '0002753-16.2026.8.05.0191',
            '0002222-22.2026.8.05.0191',
        ])

    def test_sugere_tipo_de_certidao(self):
        peticoes = ler_peticoes(HTML)
        por_processo = {p['processo']: p for p in peticoes}
        self.assertEqual(
            por_processo['0002888-28.2026.8.05.0191']
            ['tipo_prazo_sugerido'],
            'inominado',
        )
        self.assertEqual(
            por_processo['0002876-14.2026.8.05.0191']
            ['tipo_prazo_sugerido'],
            'contrarrazoes_inominado',
        )
        self.assertFalse(
            por_processo['0001111-11.2026.8.05.0191']
            ['tipo_prazo_sugerido'],
        )

    def test_exclui_contrarrazoes(self):
        peticoes = listar_peticoes_inominado(HTML)
        processos = [p['processo'] for p in peticoes]
        self.assertNotIn('0002876-14.2026.8.05.0191', processos)

    def test_detecta_pelo_nome_do_pdf(self):
        peticoes = listar_peticoes_inominado(HTML)
        por_processo = {p['processo']: p for p in peticoes}
        peticao = por_processo['0002753-16.2026.8.05.0191']
        self.assertEqual(peticao['origem_deteccao'], 'nome do PDF')
        self.assertEqual(
            peticao['peticao']['nome'], 'RECURSO INOMINADO - FULANO.pdf')

    def test_separa_comprovantes_para_conferencia(self):
        peticoes = listar_peticoes_inominado(HTML)
        por_processo = {p['processo']: p for p in peticoes}
        peticao = por_processo['0002753-16.2026.8.05.0191']
        nomes = [d['nome'] for d in peticao['preparo_docs']]
        self.assertEqual(nomes, ['GUIA RECURSAL.pdf', 'Comprovante 616.30.pdf'])
        self.assertEqual(
            peticao['peticao']['nome'], 'RECURSO INOMINADO - FULANO.pdf')

    def test_urls_sao_absolutas(self):
        peticoes = listar_peticoes_inominado(HTML)
        self.assertTrue(
            peticoes[0]['processo_url'].startswith(
                'https://projudi.tjba.jus.br/projudi/listagens/'))
        self.assertTrue(
            peticoes[0]['peticao']['url'].startswith(
                'https://projudi.tjba.jus.br/projudi/listagens/'))


if __name__ == '__main__':
    unittest.main()
