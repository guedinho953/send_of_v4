"""Testes das telas de modelos de certidão e RAGs de certidão."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Tenant
from processes.models import DocumentTemplate, Process, RAGExample


class CertidaoModelosTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='Tenant modelos', cnpj='66.666.666/0001-66')
        self.user = get_user_model().objects.create_user(
            email='teste-modelos@local', password='x', first_name='Teste',
            tenant=self.tenant,
        )
        self.client.force_login(self.user)
        self.processo = Process.objects.create(
            number='0000001-11.2026.8.05.0191',
            number_normalized='00000011120268050191',
            tenant=self.tenant,
        )
        self.modelo = DocumentTemplate.objects.create(
            name='Certidão de Teste',
            template_type='certidao',
            description='Modelo de teste',
            html_template='<p>Certifico {{ processo }}.</p>',
        )
        self.rag = RAGExample.objects.create(
            process=self.processo,
            tenant=self.tenant,
            despacho_ato='Mero expediente',
            despacho_observacao='Certifique-se a tempestividade.',
            tipo_certidao='impugnacao_embargos_execucao',
            active=True,
        )
        self.rag.suggested_templates.add(self.modelo)

    def test_lista_modelos(self):
        resposta = self.client.get(reverse('projudi:certidao_modelos'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Certidão de Teste')
        self.assertContains(resposta, 'Novo modelo')

    def test_preview_modelo(self):
        resposta = self.client.get(reverse(
            'projudi:certidao_modelo_preview', args=[self.modelo.pk]))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Certifico')
        self.assertContains(resposta, '0000000-00.0000.8.05.0191')

    def test_lista_rags_de_certidao(self):
        resposta = self.client.get(reverse('projudi:rag_certidoes'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'RAGs de Certidão')
        self.assertContains(resposta, '#%d' % self.rag.pk)
        self.assertContains(resposta, 'Impugnação/Embargos à Execução')

    def test_formulario_rag_de_certidao(self):
        resposta = self.client.get(reverse('projudi:rag_certidao_nova'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Nova RAG de Certidão')
        self.assertContains(resposta, 'Texto da certidão')

    @patch('projudi.certidao_views._texto_do_evento')
    def test_cria_rag_por_processo_e_evento(self, texto_evento):
        from datetime import date
        texto_evento.return_value = (
            'DESPACHO Certifique-se a tempestividade.', date(2026, 11, 28))

        resposta = self.client.post(
            reverse('projudi:rag_certidao_nova'),
            {
                'processo': '0000003-33.2026.8.05.0191',
                'evento_despacho': '28',
                'ato': 'DESPACHO',
                'tipo_certidao': 'impugnacao_embargos_execucao',
                'texto_certidao': '<p>Certifico.</p>',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        rag = RAGExample.objects.get(
            process__number='0000003-33.2026.8.05.0191')
        self.assertEqual(rag.evento_despacho, '28')
        self.assertIn('Certifique-se a tempestividade', rag.despacho_observacao)
        self.assertEqual(rag.despacho_data, '28/11/2026')

    def test_cria_rag_e_modelo_de_certidao(self):
        resposta = self.client.post(
            reverse('projudi:rag_certidao_nova'),
            {
                'processo': '0000002-22.2026.8.05.0191',
                'ato': 'DESPACHO',
                'texto_despacho': 'DESPACHO Certifique-se a tempestividade.',
                'tipo_certidao': 'impugnacao_embargos_execucao',
                'nome_modelo': 'Modelo criado pela tela',
                'texto_certidao': (
                    '<p>Certifico {{ processo }} para {{ parte }}.</p>'),
                'fluxo_juntar': 'on',
                'fluxo_intimar': 'on',
                'fluxo_mp': 'on',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        rag = RAGExample.objects.get(
            process__number='0000002-22.2026.8.05.0191')
        self.assertEqual(rag.acoes_fluxo, ['juntar', 'intimar', 'mp'])
        modelo = rag.suggested_templates.get(
            name='Modelo criado pela tela')
        self.assertEqual(modelo.template_type, 'certidao')
