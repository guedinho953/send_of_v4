"""Testes da fila de petições com escolha manual da certidão/ação."""

from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from projudi.models import PrazoDjenRecord

FALSA = [{
    'processo': '0000001-11.2026.8.05.0191',
    'processo_url': 'https://projudi/processo',
    'data_envio': date(2026, 11, 25),
    'tipo': 'Juntada de Petição de Recurso Inominado',
    'tipo_sugerido_label': 'Recurso Inominado',
    'tipo_prazo_sugerido': 'inominado',
    'peticao': {'nome': 'recurso.pdf', 'url': 'https://projudi/recurso.pdf'},
    'preparo_docs': [],
}]


def resultado_decurso():
    return {
        'processo': '0000001-11.2026.8.05.0191',
        'url': 'https://projudi/processo',
        'executado': 'FULANO DE TAL',
        'parte_papel': 'PROMOVIDO',
        'evento_despacho': '10',
        'despacho_auto': False,
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


class PeticaoFilaViewsTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email='teste-fila-peticoes@local',
            password='x',
            first_name='Teste',
        )
        self.client.force_login(self.user)

    @patch('projudi.peticoes_views.carregar_fila', return_value=FALSA)
    def test_fila_lista_peticoes(self, _carregar):
        resposta = self.client.get(reverse('projudi:certidao_peticoes_fila'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, '0000001-11.2026.8.05.0191')
        self.assertContains(resposta, 'Recurso Inominado')
        self.assertContains(resposta, 'Impugnação/Embargos à Execução')
        self.assertContains(resposta, 'Segurança do juízo')

    @patch('projudi.peticoes_views.call_command')
    def test_gerar_inominado_chama_comando(self, comando):
        registro = PrazoDjenRecord.objects.create(
            processo='0000001-11.2026.8.05.0191',
            origem='peticao',
            tipo_prazo='inominado',
            prazo_dias=10,
        )
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'processo_url': 'https://projudi/processo',
                'peticao_url': 'https://projudi/recurso.pdf',
                'peticao_documento': 'recurso.pdf',
                'data_envio': '25/11/2026',
                'tipo_prazo': 'inominado',
                'preparo': 'completo',
                'acao': 'gerar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertRedirects(
            resposta,
            reverse('projudi:certidao_detail', args=[registro.id]),
            fetch_redirect_response=False,
        )
        comando.assert_called_once()
        args, kwargs = comando.call_args
        self.assertEqual(args[0], 'certidao_inominado')
        self.assertEqual(kwargs['preparo'], 'completo')
        self.assertEqual(kwargs['data_protocolo'], '25/11/2026')

    @patch('projudi.peticoes_views.call_command')
    def test_inominado_sem_preparo_nao_gera(self, comando):
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'data_envio': '25/11/2026',
                'tipo_prazo': 'inominado',
                'preparo': '',
                'acao': 'gerar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        comando.assert_not_called()

    @patch('projudi.peticoes_views.localizar_intimacao_do_processo')
    @patch('projudi.peticoes_views.call_command')
    def test_contrarrazoes_localiza_intimacao_pelo_evento(
            self, comando, localizar):
        localizar.return_value = {
            'evento': '56',
            'data': date(2026, 12, 5),
            'meio': 'eletronico',
        }
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'processo_url': 'https://projudi/processo',
                'data_envio': '10/12/2026',
                'tipo_prazo': 'contrarrazoes_inominado',
                'evento_origem': '55',
                'parte': 'FULANO DE TAL',
                'acao': 'gerar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        comando.assert_called_once()
        args, kwargs = comando.call_args
        self.assertEqual(args[0], 'prazo_djen')
        self.assertEqual(kwargs['disponibilizacao'], '05/12/2026')
        self.assertEqual(kwargs['evento_intimacao'], '56')
        self.assertEqual(kwargs['evento_recurso'], '55')
        localizar.assert_called_once()

    @patch('projudi.peticoes_views.call_command')
    def test_impugnacao_embargos_passa_seguranca_e_evento(self, comando):
        registro = PrazoDjenRecord.objects.create(
            processo='0000001-11.2026.8.05.0191',
            origem='peticao',
            tipo_prazo='impugnacao_embargos_execucao',
            prazo_dias=15,
        )
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'processo_url': 'https://projudi/processo',
                'data_envio': '10/12/2026',
                'tipo_prazo': 'impugnacao_embargos_execucao',
                'data_intimacao': '05/12/2026',
                'evento_impugnacao': '88',
                'seguranca_juizo': 'parcial',
                'parte': 'FULANO DE TAL',
                'acao': 'gerar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertRedirects(
            resposta,
            reverse('projudi:certidao_detail', args=[registro.id]),
            fetch_redirect_response=False,
        )
        comando.assert_called_once()
        args, kwargs = comando.call_args
        self.assertEqual(args[0], 'prazo_djen')
        self.assertEqual(
            kwargs['tipo'], 'impugnacao_embargos_execucao')
        self.assertEqual(kwargs['disponibilizacao'], '05/12/2026')
        self.assertEqual(kwargs['protocolo'], '10/12/2026')
        self.assertEqual(kwargs['evento_recurso'], '88')
        self.assertEqual(kwargs['seguranca_juizo'], 'parcial')

    @patch('projudi.peticoes_views.call_command')
    def test_impugnacao_embargos_sem_seguranca_nao_gera(self, comando):
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'data_envio': '10/12/2026',
                'tipo_prazo': 'impugnacao_embargos_execucao',
                'data_intimacao': '05/12/2026',
                'seguranca_juizo': '',
                'acao': 'gerar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        comando.assert_not_called()

    @patch('projudi.peticoes_views.localizar_intimacao_do_processo',
           return_value=None)
    @patch('projudi.peticoes_views.call_command')
    def test_contrarrazoes_sem_intimacao_e_sem_data_nao_gera(
            self, comando, _localizar):
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'processo_url': 'https://projudi/processo',
                'data_envio': '10/12/2026',
                'tipo_prazo': 'contrarrazoes_inominado',
                'evento_origem': '55',
                'acao': 'gerar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        comando.assert_not_called()

    @patch('projudi.peticoes_views.call_command')
    def test_acao_nao_implementada_nao_gera(self, comando):
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'data_envio': '25/11/2026',
                'tipo_prazo': 'inominado',
                'preparo': 'completo',
                'acao': 'juntar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        comando.assert_not_called()

    @patch('projudi.peticoes_views.DecursoPagamentoService.analisar')
    def test_decurso_gera_na_propria_fila(self, analisar):
        analisar.return_value = resultado_decurso()
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'processo_url': 'https://projudi/processo',
                'tipo_prazo': 'decurso_pagamento',
                'evento_despacho': '10',
                'executado': 'FULANO DE TAL',
                'assinante': 'ivan',
                'acao': 'gerar',
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

    @patch('projudi.views.ProjudiService.list_movimentacoes')
    def test_fila_movimentacoes_mostra_formulario_de_geracao(self, listar):
        listar.return_value = [{
            'processo': '0000001-11.2026.8.05.0191',
            'tipo': 'Juntada de Petição',
            'data': '27/11/2026',
            'link_processo': 'https://projudi/processo',
            'link_documento': 'https://projudi/despacho.pdf',
        }]
        resposta = self.client.get(reverse('projudi:movimentacoes'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(
            resposta,
            reverse('projudi:certidao_movimentacao_fila_gerar'),
        )
        self.assertContains(resposta, 'Gerar certidão daqui')
        self.assertContains(resposta, 'Só RAGs')
        self.assertContains(resposta, 'mostrar todas as certidões')
        self.assertContains(resposta, 'Gerar RAG')
        self.assertContains(resposta, 'Impugnação/Embargos à Execução')
        self.assertContains(resposta, 'Decurso de Pagamento Voluntário')
        self.assertContains(
            resposta, '0000001-11.2026.8.05.0191')

    @patch('projudi.peticoes_views.localizar_intimacao_do_processo')
    @patch('projudi.peticoes_views.call_command')
    def test_movimentacao_impugnacao_gera_com_origem_movimentacao(
            self, comando, localizar):
        localizar.return_value = {
            'evento': '31',
            'data': date(2026, 11, 2),
            'meio': 'eletronico',
        }
        registro = PrazoDjenRecord.objects.create(
            processo='0002156-47.2026.8.05.0191',
            origem='movimentacao',
            tipo_prazo='impugnacao_embargos_execucao',
            prazo_dias=15,
        )
        resposta = self.client.post(
            reverse('projudi:certidao_movimentacao_fila_gerar'),
            {
                'processo': '0002156-47.2026.8.05.0191',
                'processo_url': 'https://projudi/processo',
                'data_envio': '19/11/2026',
                'tipo_prazo': 'impugnacao_embargos_execucao',
                'evento_origem': '28',
                'evento_impugnacao': '32',
                'seguranca_juizo': 'parcial',
                'parte': 'BANCO MERCANTIL DO BRASIL SA',
                'tipo_localizador': '15286',
                'localizador': '1',
                'tipo_conclusao': '18',
                'juiz_conclusao': '41201',
                'acao': 'gerar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertRedirects(
            resposta,
            reverse('projudi:certidao_detail', args=[registro.id]),
            fetch_redirect_response=False,
        )
        comando.assert_called_once()
        args, kwargs = comando.call_args
        self.assertEqual(args[0], 'prazo_djen')
        self.assertEqual(kwargs['origem'], 'movimentacao')
        self.assertEqual(kwargs['disponibilizacao'], '02/11/2026')
        self.assertEqual(kwargs['protocolo'], '19/11/2026')
        self.assertEqual(kwargs['evento_recurso'], '32')
        self.assertEqual(kwargs['evento_origem'], '28')
        self.assertEqual(kwargs['seguranca_juizo'], 'parcial')
        self.assertEqual(kwargs['tipo_localizador'], '15286')
        self.assertEqual(kwargs['localizador'], '1')

    def test_limpar_texto_despacho_remove_cabecalho_e_assinatura(self):
        from projudi.certidao_sugestao import limpar_texto_despacho

        texto = (
            'PODER JUDICIÁRIO DO ESTADO DA BAHIA 2ª VARA ... '
            'DESPACHO Existindo comando judicial a ser executado, '
            'intimem-se as partes. Paulo Afonso-BA, data da assinatura '
            'eletrônica. MARTINHO FERRAZ DA NOBREGA JUNIOR JUIZ DE '
            'DIREITO Documento Assinado Eletronicamente Código de '
            'validação do documento: abc123.'
        )
        limpo = limpar_texto_despacho(texto)
        self.assertTrue(limpo.startswith('Existindo comando judicial'))
        self.assertNotIn('PODER JUDICIÁRIO', limpo)
        self.assertNotIn('MARTINHO', limpo)
        self.assertNotIn('Documento Assinado', limpo)
        self.assertIn('intimem-se as partes', limpo)

    @patch('projudi.services.ProjudiService._get_session_from_cookies',
           return_value=(object(), {}))
    @patch('projudi.certidao_sugestao._texto_documento', return_value=(
        'Certifique-se a tempestividade dos embargos à execução e a '
        'segurança do Juízo.'))
    def test_criar_rag_a_partir_da_movimentacao(self, _texto, _sessao):
        from accounts.models import Tenant
        from processes.models import RAGExample

        tenant = Tenant.objects.create(
            name='Tenant RAG movimento', cnpj='88.888.888/0001-88')
        self.user.tenant = tenant
        self.user.save(update_fields=['tenant'])

        resposta = self.client.post(
            reverse('projudi:movimentacao_criar_rag'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'tipo': 'Mero expediente',
                'data': '28/11/2026',
                'link_processo': 'https://projudi/processo',
                'link_documento': 'https://projudi/despacho.pdf',
                'texto_movimentacao': 'Mero expediente 28/11/2026',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        rag = RAGExample.objects.get(
            despacho_ato='Mero expediente')
        self.assertEqual(
            rag.tipo_certidao, 'impugnacao_embargos_execucao')
        self.assertIn('Certifique-se', rag.despacho_observacao)

    @patch('projudi.services.ProjudiService._get_session_from_cookies',
           return_value=(object(), {}))
    @patch('projudi.certidao_sugestao._texto_documento', return_value=(
        'Certifique-se a inexistência de custas da execução.'))
    def test_criar_rag_sem_tenant_usa_tenant_padrao(self, _texto, _sessao):
        from accounts.models import Tenant
        from processes.models import RAGExample

        tenant = Tenant.objects.create(
            name='Tenant padrão RAG', cnpj='77.777.777/0001-77')
        resposta = self.client.post(
            reverse('projudi:movimentacao_criar_rag'),
            {
                'processo': '0001224-59.2026.8.05.0191',
                'tipo': 'Mero expediente',
                'data': '28/11/2026',
                'link_documento': 'https://projudi/despacho.pdf',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        rag = RAGExample.objects.get(
            process__number='0001224-59.2026.8.05.0191')
        self.assertEqual(rag.tenant_id, tenant.id)

    @patch('projudi.peticoes_views.DecursoPagamentoService.analisar')
    def test_decurso_nao_gera_antes_do_prazo(self, analisar):
        resultado = resultado_decurso()
        resultado['decorrido'] = False
        analisar.return_value = resultado
        resposta = self.client.post(
            reverse('projudi:certidao_peticoes_fila_gerar'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'tipo_prazo': 'decurso_pagamento',
                'evento_despacho': '',
                'executado': '',
                'assinante': 'ivan',
                'acao': 'gerar',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertFalse(
            PrazoDjenRecord.objects.filter(
                tipo_prazo='decurso_pagamento').exists())
