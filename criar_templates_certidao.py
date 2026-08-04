"""Cria/atualiza os DocumentTemplate de Certidão Criminal Negativa.

Duas modelos:
  - Certidão Criminal Negativa (1 Autor)
  - Certidão Criminal Negativa (Vários Autores)

Usam a MESMA base de formatação do Ofício CIAP (Times New Roman + brasão
embutido), parametrizada com variáveis Django para preenchimento dinâmico.

Uso:
  cd /home/ivan/PythonProjects/send_of_v4
  source .venv/bin/activate
  python criar_templates_certidao.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
import django; django.setup()

from processes.models import DocumentTemplate

LOGO_URL = 'https://projudi.tjba.jus.br/projudi/imagens/brasaoPetroBranco.jpg'

# ── Cabeçalho + rodapé compartilhados ──
# ATENÇÃO: dentro de f-strings, tags Django precisam de {{{{ ... }}}}
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
<div style="font-size:12pt; font-weight:bold; text-align:center; margin:22px 0 30px;">CERTIDÃO</div>'''

# String simples (sem f): tags Django ficam como estão
RODAPE = '''<div style="font-size:7pt; font-family:'Courier New',monospace; margin:10px 0 0; text-align:justify; line-height:1.2;">
  <sup>1</sup> Documento assinado eletronicamente conforme arts. 1º e 2º da Lei nº. 11.419/06, que dispõe sobre a informatização do processo digital. O documento pode ser acessado no endereço eletrônico https://projudi.tjba.jus.br/projudi/ sob o número acima epigrafado.
</div>
<div style="font-size:7pt; font-family:'Courier New',monospace; text-align:right; margin-top:16px; margin-bottom:24px;">
  {{ processo }}
</div>'''

# ── Template 1 autor ────────────────────────────────
SINGLE = f'''<div style="font-family:'Times New Roman',serif; font-size:12pt; max-width:750px; margin:0 auto;">
{HEADER}

<div style="font-size:10pt; font-family:'Courier New',monospace; margin:0 0 30px;">
  <table style="width:100%; border-collapse:collapse;">
    <tr><td style="width:140px;"><strong>PROCESSO N.º</strong></td><td>-</td><td>{{{{ processo }}}}</td></tr>
    <tr><td><strong>AUTOR DO FATO</strong></td><td>-</td><td>{{{{ autor }}}}</td></tr>
    <tr><td><strong>VÍTIMA</strong></td><td>-</td><td>{{{{ vitima }}}}</td></tr>
  </table>
</div>

<div style="font-size:10pt; font-family:'Courier New',monospace; margin:0 0 18px; text-align:justify; text-indent:80px; line-height:1.4;">
  Em observância ao art. 76, §2º, II, e §4º da Lei nº. 9.099/95 fiz busca no sistema Projudi e constatei que o(s)/(a)(s) autor/(a)/(es)/(as) do fato, <strong>{{{{ autor }}}}</strong>, qualificado(a)(os)/(as) nos autos do processo supra mencionado, <strong>NÃO FOI/FORAM BENEFICIADO(A)/(OS)/(AS) anteriormente no prazo de 05 (cinco) anos, pela aplicação de pena restritiva ou multa.</strong>
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

# ── Template vários autores ──────────────────────────
# usa autores_lista (HTML enumerado, |safe) e autores_texto (texto corrido)
MULTI = f'''<div style="font-family:'Times New Roman',serif; font-size:12pt; max-width:750px; margin:0 auto;">
{HEADER}

<div style="font-size:10pt; font-family:'Courier New',monospace; margin:0 0 30px;">
  <table style="width:100%; border-collapse:collapse;">
    <tr><td style="width:160px;"><strong>PROCESSO N.º</strong></td><td>-</td><td>{{{{ processo }}}}</td></tr>
    <tr><td><strong>AUTORES DO FATO</strong></td><td>-</td><td>{{{{ autores_lista | safe }}}}</td></tr>
    <tr><td><strong>VÍTIMA</strong></td><td>-</td><td>{{{{ vitima }}}}</td></tr>
  </table>
</div>

<div style="font-size:10pt; font-family:'Courier New',monospace; margin:0 0 18px; text-align:justify; text-indent:80px; line-height:1.4;">
  Em observância ao art. 76, §2º, II, e §4º da Lei nº. 9.099/95 fiz busca no sistema Projudi e constatei que o(s)/(a)(s) autor/(a)/(es)/(as) do fato, <strong>{{{{ lista_autores }}}}</strong>, qualificado(a)(os)/(as) nos autos do processo supra mencionado, <strong>NÃO FOI/FORAM BENEFICIADO(A)/(OS)/(AS) anteriormente no prazo de 05 (cinco) anos, pela aplicação de pena restritiva ou multa.</strong>
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

TEMPLATES = [
    {
        'name': 'Certidão Criminal Negativa (1 Autor)',
        'template_type': 'certidao',
        'html': SINGLE,
        'description': 'Certidão criminal negativa (art. 76, §2º, II e §4º, Lei 9.099/95) para UM autor do fato. Base Ofício CIAP com brasão embutido.',
    },
    {
        'name': 'Certidão Criminal Negativa (Vários Autores)',
        'template_type': 'certidao',
        'html': MULTI,
        'description': 'Certidão criminal negativa (art. 76) para VÁRIOS autores — cada um buscou 1 processo (negativo). Enumera todos no corpo e na observação.',
    },
]

for t in TEMPLATES:
    tpl, criado = DocumentTemplate.objects.get_or_create(
        name=t['name'],
        defaults={
            'template_type': t['template_type'],
            'html_template': t['html'],
            'description': t['description'],
            'active': True,
        },
    )
    if not criado:
        tpl.html_template = t['html']
        tpl.template_type = t['template_type']
        tpl.description = t['description']
        tpl.active = True
        tpl.save()
    print(f"{'✓ criado' if criado else '✓ atualizado'} — {tpl.name} (id={tpl.id}, type='{tpl.template_type}')")

# Validação: renderizar com dados fictícios pra conferir que os tags saem certos
from django.template import Template, Context

ctx = {
    'processo': '0001708-74.2026.8.05.0191',
    'autor': 'JOSE RUBENS DE OLIVEIRA',
    'autores_lista': '1. JOSE RUBENS DE OLIVEIRA<br>2. MARIA DA SILVA',
    'autores_texto': 'JOSE RUBENS DE OLIVEIRA e MARIA DA SILVA',
    'vitima': 'A SOCIEDADE PAULO AFONSO BAHIA',
    'servidor': 'IVAN TESTE',
    'data': '03/08/2026',
}
for t in TEMPLATES:
    tpl = DocumentTemplate.objects.get(name=t['name'])
    html = Template(tpl.html_template).render(Context(ctx))
    sobras = [p for p in ['{{', '}}', '{ processo }', '{ autor }', '{ data }']
              if p in html]
    tem_brasao = 'brasaoPetroBranco' in html
    tem_nome = 'JOSE RUBENS DE OLIVEIRA' in html
    print(f"  validação '{tpl.name}': brasão={tem_brasao} nome={tem_nome} sobras={sobras or 'nenhuma'}")
