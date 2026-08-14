"""Cria/atualiza o DocumentTemplate de CERTIDÃO DE PRAZO.

Reaproveita a MESMA base visual da Certidão Criminal (brasão + rodapé +
Times New Roman), trocando apenas o corpo: em vez de "negativa de antecedentes",
a certidão atesta a CONTAGEM DE PRAZO da intimação (DJEN/AR/advogado/etc).

Variáveis Django usadas no template:
  {{ processo }}        -> nº do processo CNJ
  {{ parte }}           -> nome da parte intimada
  {{ observacao_prazo }}-> texto genérico de prazo (já gerado pelo
                           CumprimentoService._texto_observacao_prazo)
  {{ data }}            -> data de expedição (Paulo Afonso-BA, dd/mm/aaaa)
  {{ servidor }}        -> nome do servidor

Uso:
  cd /home/ivan/PythonProjects/send_of_v4
  source .venv/bin/activate
  python criar_template_certidao_prazo.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
import django; django.setup()

from processes.models import DocumentTemplate

LOGO_URL = 'https://projudi.tjba.jus.br/projudi/imagens/brasaoPetroBranco.jpg'

HEADER = f'''<div style="text-align:center; margin-bottom:6px;">
  <img src="{LOGO_URL}" style="width:80px; margin-bottom:4px;">
  <div style="font-size:11pt; font-weight:bold; text-transform:uppercase;">Poder Judiciário do Estado da Bahia</div>
  <div style="font-size:11pt; font-weight:bold;">Tribunal de Justiça do Estado da Bahia</div>
  <div style="font-size:10pt; font-weight:bold;">2ª Vara do Sistema dos Juizados Especiais</div>
  <div style="font-size:10pt; font-weight:bold;">Paulo Afonso</div>
</div>
<hr style="border:0.5px solid #000; margin:4px 0;">
<div style="font-size:9pt; text-align:center; margin:2px 0; line-height:1.2;">
  Rua das Caraibeiras, 420, Quadra 04 - 1º Andar, General Dutra - PAULO AFONSO<br>
  <strong>pafonso-2vsj@tjba.jus.br</strong> | Funcionamento: 13:00 às 19:00 | Tel.: (75)3281-8372
</div>
<hr style="border:0.5px solid #000; margin:4px 0;">
<div style="font-size:12pt; font-weight:bold; text-align:center; margin:22px 0 30px;">CERTIDÃO DE PRAZO</div>'''

RODAPE = '''<div style="font-size:7pt; font-family:'Courier New',monospace; margin:10px 0 0; text-align:justify; line-height:1.2;">
  <sup>1</sup> Documento assinado eletronicamente conforme arts. 1º e 2º da Lei nº. 11.419/06, que dispõe sobre a informatização do processo digital. O documento pode ser acessado no endereço eletrônico https://projudi.tjba.jus.br/projudi/ sob o número acima epigrafado.
</div>
<div style="font-size:7pt; font-family:'Courier New',monospace; text-align:right; margin-top:16px; margin-bottom:24px;">
  {{ processo }}
</div>'''

HTML = f'''<div style="font-family:'Times New Roman',serif; font-size:12pt; max-width:750px; margin:0 auto;">
{HEADER}

<div style="font-size:10pt; font-family:'Courier New',monospace; margin:0 0 30px;">
  <table style="width:100%; border-collapse:collapse;">
    <tr><td style="width:140px;"><strong>PROCESSO N.º</strong></td><td>-</td><td>{{{{ processo }}}}</td></tr>
    <tr><td><strong>PARA</strong></td><td>-</td><td>{{{{ parte }}}}</td></tr>
  </table>
</div>

<div style="font-size:10pt; font-family:'Courier New',monospace; margin:0 0 18px; text-align:justify; text-indent:80px; line-height:1.4;">
  Certifico que, referente ao processo em epígrafe, {{{{ observacao_prazo }}}}
</div>

<div style="font-size:10pt; font-family:'Courier New',monospace; margin:0 0 10px; text-align:justify; text-indent:80px;">
  O referido é verdade,<br>Dou fé.
</div>

<div style="font-size:10pt; font-family:'Courier New',monospace; margin:30px 0 6px; text-align:center;">
  <div style="margin-bottom:16px;">Paulo Afonso-BA, {{{{ data }}}}.</div>
  <strong>{{{{ servidor }}}}</strong><br>
  Servidor Secretaria 2<br>
  Documento Assinado Eletronicamente<sup>1</sup>
</div>

{RODAPE}
</div>'''

TEMPLATE = {
    'name': 'Certidão de Prazo',
    'template_type': 'certidao',
    'html': HTML,
    'description': 'Certidão de prazo (DJEN/AR/advogado/etc) — atesta a contagem de prazo da intimação. Base Ofício CIAP com brasão embutido. Variáveis: processo, parte, observacao_prazo, data, servidor.',
}

tpl, criado = DocumentTemplate.objects.get_or_create(
    name=TEMPLATE['name'],
    defaults={
        'template_type': TEMPLATE['template_type'],
        'html_template': TEMPLATE['html'],
        'description': TEMPLATE['description'],
        'active': True,
    },
)
if not criado:
    tpl.html_template = TEMPLATE['html']
    tpl.template_type = TEMPLATE['template_type']
    tpl.description = TEMPLATE['description']
    tpl.active = True
    tpl.save()
print(f"{'✓ criado' if criado else '✓ atualizado'} — {tpl.name} (id={tpl.id}, type='{tpl.template_type}')")

# Validação: renderizar com dados fictícios
from django.template import Template, Context
ctx = {
    'processo': '0001708-74.2026.8.05.0191',
    'parte': 'JOÃO DA SILVA',
    'observacao_prazo': 'Intimação eletrônica (DJEN) — Prazo de 15 dias úteis. Leitura em 09/02/2026; não contam a leitura nem o 1º dia útil subsequente à leitura; início da contagem em 11/02/2026; término em 03/03/2026 (decorrido o prazo em 04/03/2026).',
    'data': '10/03/2026',
    'servidor': 'IVAN',
}
html = Template(tpl.html_template).render(Context(ctx))
sobras = [p for p in ['{{', '}}'] if p in html]
tem_brasao = 'brasaoPetroBranco' in html
tem_nome = 'JOÃO DA SILVA' in html
tem_texto = 'Intimação eletrônica (DJEN)' in html
print(f"  validação: brasão={tem_brasao} nome={tem_nome} texto_prazo={tem_texto} sobras={sobras or 'nenhuma'}")
print('  HTML (trecho):')
print('   ', html[:200].replace(chr(10), ' '))
