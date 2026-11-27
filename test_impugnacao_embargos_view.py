"""Testes da certidão de impugnação/embargos na aba Movimentações."""

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from projudi.models import PrazoDjenRecord


def resultado_analise():
    return {
        'processo': '0000001-11.2026.8.05.0191',
        'executado': 'FULANO DE TAL',
        'evento_despacho': '55',
        'evento_intimacao': '56',
        'data_intimacao': date(2026, 12, 5),
        'meio': 'eletronico',
    }


class ImpugnacaoEmbargosViewTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email='teste-embargos@local',
            password='x',
            first_name='Teste',
        )
        self.client.force_login(self.user)

    def test_get_exibe_formulario(self):
        resposta = self.client.get(
            reverse('projudi:certidao_impugnacao_embargos'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Segurança do juízo')
        self.assertContains(resposta, 'Data do protocolo')
        self.assertContains(resposta, 'Evento do despacho/pagamento')

    def test_fila_de_movimentacoes_tem_acao_para_certidao(self):
        from django.template.loader import render_to_string

        html = render_to_string(
            'projudi/movimentacoes_list.html',
            {
                'session_active': True,
                'movimentacoes': [{
                    'processo': '0000001-11.2026.8.05.0191',
                    'tipo': 'Juntada de Petição de Embargos à Execução',
                    'data': '25/11/2026',
                    'link_processo': 'https://projudi/processo',
                    'link_documento': 'https://projudi/documento',
                }],
            },
        )
        self.assertIn(
            reverse('projudi:certidao_impugnacao_embargos'), html)
        self.assertIn('Gerar certidão', html)
        self.assertIn('0000001-11.2026.8.05.0191', html)
        self.assertIn(
            reverse('projudi:certidao_sugestao_movimentacao'), html)
        self.assertIn('data-documento="https://projudi/documento"', html)

    @patch('projudi.certidao_sugestao.sugerir_certidao')
    def test_api_sugestao_retorna_tipo_e_localizador(self, sugerir):
        sugerir.return_value = {
            'tipo_certidao': 'impugnacao_embargos_execucao',
            'tipo_label': 'Impugnação/Embargos à Execução',
            'tipo_localizador': '15286',
            'localizador': '1',
            'url_form': '/projudi/certidoes/movimentacoes/'
                        'impugnacao-embargos/?processo=123',
        }
        resposta = self.client.get(
            reverse('projudi:certidao_sugestao_movimentacao'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'documento': 'https://projudi/documento',
            },
        )
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual(
            dados['tipo_certidao'], 'impugnacao_embargos_execucao')
        self.assertEqual(dados['tipo_localizador'], '15286')
        sugerir.assert_called_once()

    @patch('projudi.certidao_sugestao._texto_documento', return_value=(
        'Certifique-se a tempestividade dos embargos à execução e a '
        'segurança do Juízo. Intime-se o embargado para manifestação.'))
    @patch('processes.movimentacoes_service.buscar_cumprimentos_similares')
    @patch('projudi.services.ProjudiService._get_session_from_cookies',
           return_value=(object(), {}))
    def test_sugestao_usa_campos_da_rag(self, _sessao, buscar, _texto):
        from processes.models import Process, RAGExample
        from projudi.certidao_sugestao import sugerir_certidao

        from accounts.models import Tenant
        tenant = Tenant.objects.create(
            name='Tenant teste RAG', cnpj='99.999.999/0001-99')
        self.user.tenant = tenant
        self.user.save(update_fields=['tenant'])
        proc = Process.objects.create(
            number='0000008-88.2026.8.05.0191',
            number_normalized='00000088820268050191',
            tenant=tenant,
        )
        rag = RAGExample.objects.create(
            process=proc,
            despacho_ato='Certifique-se tempestividade dos embargos',
            despacho_observacao='Intime-se o embargado. Segurança do juízo.',
            tipo_certidao='impugnacao_embargos_execucao',
            tipo_localizador='15286',
            localizador='1',
            tipo_conclusao='18',
            juiz_conclusao='41201',
            active=True,
        )
        buscar.return_value = [{'id': rag.id}]
        dados = sugerir_certidao(
            self.user, proc.number, 'https://projudi/documento')
        self.assertEqual(
            dados['tipo_certidao'], 'impugnacao_embargos_execucao')
        self.assertEqual(dados['tipo_localizador'], '15286')
        self.assertEqual(dados['localizador'], '1')
        self.assertEqual(dados['tipo_conclusao'], '18')
        self.assertEqual(dados['juiz_conclusao'], '41201')
        self.assertIn('impugnacao-embargos', dados['url_form'])
        self.assertIn('tipo_conclusao=18', dados['url_form'])

    def test_fallback_de_tipo_por_texto(self):
        from projudi.certidao_sugestao import _tipo_por_texto

        self.assertEqual(
            _tipo_por_texto(
                'Certifique-se a tempestividade dos embargos à execução.'),
            'impugnacao_embargos_execucao',
        )
        self.assertEqual(
            _tipo_por_texto('Certifique-se o decurso do prazo de pagamento.'),
            'decurso_pagamento',
        )

    def test_aba_movimentacoes_tem_atalho_para_o_formulario(self):
        resposta = self.client.get(reverse('projudi:certidao_movimentacoes'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(
            resposta, reverse('projudi:certidao_impugnacao_embargos'))
        self.assertContains(
            resposta, 'Nova certidão de impugnação/embargos (15 dias)')

    def test_aba_movimentacoes_tem_link_para_a_fila_de_movimentacoes(self):
        resposta = self.client.get(reverse('projudi:certidao_movimentacoes'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, reverse('projudi:movimentacoes'))
        self.assertContains(resposta, 'Fila de movimentações')

    @patch('projudi.impugnacao_embargos_views.call_command')
    @patch('projudi.impugnacao_embargos_views.DecursoPagamentoService.analisar')
    def test_gera_certidao_na_aba_movimentacoes(self, analisar, comando):
        analisar.return_value = resultado_analise()
        registro = PrazoDjenRecord.objects.create(
            processo='0000001-11.2026.8.05.0191',
            origem='movimentacao',
            tipo_prazo='impugnacao_embargos_execucao',
            prazo_dias=15,
        )
        resposta = self.client.post(
            reverse('projudi:certidao_impugnacao_embargos'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'processo_url': 'https://projudi/processo',
                'evento': '55',
                'executado': 'FULANO DE TAL',
                'data_protocolo': '10/12/2026',
                'evento_impugnacao': '88',
                'seguranca_juizo': 'parcial',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertRedirects(
            resposta,
            reverse('projudi:certidao_detail', args=[registro.id]),
            fetch_redirect_response=False,
        )
        analisar.assert_called_once()
        comando.assert_called_once()
        args, kwargs = comando.call_args
        self.assertEqual(args[0], 'prazo_djen')
        self.assertEqual(kwargs['tipo'], 'impugnacao_embargos_execucao')
        self.assertEqual(kwargs['origem'], 'movimentacao')
        self.assertEqual(kwargs['disponibilizacao'], '05/12/2026')
        self.assertEqual(kwargs['protocolo'], '10/12/2026')
        self.assertEqual(kwargs['evento_origem'], '55')
        self.assertEqual(kwargs['evento_intimacao'], '56')
        self.assertEqual(kwargs['evento_recurso'], '88')
        self.assertEqual(kwargs['seguranca_juizo'], 'parcial')
        self.assertEqual(kwargs['parte'], 'FULANO DE TAL')

    @patch('projudi.impugnacao_embargos_views.call_command')
    @patch('projudi.impugnacao_embargos_views.DecursoPagamentoService.analisar')
    def test_sem_seguranca_nao_gera(self, analisar, comando):
        resposta = self.client.post(
            reverse('projudi:certidao_impugnacao_embargos'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'data_protocolo': '10/12/2026',
                'seguranca_juizo': '',
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Informe a segurança do juízo')
        analisar.assert_not_called()
        comando.assert_not_called()

    @patch('projudi.impugnacao_embargos_views.call_command')
    @patch('projudi.impugnacao_embargos_views.DecursoPagamentoService.analisar')
    def test_sem_protocolo_nao_gera(self, analisar, comando):
        resposta = self.client.post(
            reverse('projudi:certidao_impugnacao_embargos'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'data_protocolo': '',
                'seguranca_juizo': 'integral',
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Informe a data do protocolo')
        analisar.assert_not_called()
        comando.assert_not_called()

    @patch('projudi.impugnacao_embargos_views.call_command')
    @patch('projudi.impugnacao_embargos_views.DecursoPagamentoService.analisar')
    def test_erro_na_analise_nao_gera(self, analisar, comando):
        analisar.return_value = {'erro': 'Intimação não localizada.'}
        resposta = self.client.post(
            reverse('projudi:certidao_impugnacao_embargos'),
            {
                'processo': '0000001-11.2026.8.05.0191',
                'data_protocolo': '10/12/2026',
                'seguranca_juizo': 'integral',
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Intimação não localizada.')
        comando.assert_not_called()
