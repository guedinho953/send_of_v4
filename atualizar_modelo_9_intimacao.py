"""Atualiza o DocumentTemplate #9 com o HTML do MANDADO DE INTIMAÇÃO
informado pelo usuário (mais focado em intimação, sem cláusulas de
penhora/avaliação, já com a seção TEOR DO DESPACHO).

Uso:
  source .venv/bin/activate
  python atualizar_modelo_9_intimacao.py
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.models import DocumentTemplate

MANDADO_INTIMACAO_HTML = """<div style="font-family:'Times New Roman',serif; font-size:12pt; max-width:750px; margin:0 auto;">

    <div style="text-align:center; margin-bottom:6px;">
        <div style="font-size:11pt; font-weight:bold; text-transform:uppercase;">Poder Judiciário do Estado da Bahia
        </div>
        <div style="font-size:11pt; font-weight:bold;">Tribunal de Justiça do Estado da Bahia</div>
        <div style="font-size:10pt; font-weight:bold;">2ª Vara do Sistema dos Juizados Especiais</div>
        <div style="font-size:10pt; font-weight:bold;">Paulo Afonso</div>
    </div>

    <hr style="border:0.5px solid #000; margin:4px 0;">

    <div style="font-size:9pt; text-align:center; margin:2px 0; line-height:1.2;">
        Rua das Caraibeiras, 420, Quadra 04 - 1º Andar, General Dultra - PAULO AFONSO<br>
        <strong>pafonso-2vsj@tjba.jus.br</strong> | Funcionamento: 13:00 às 19:00 | Tel.: (75)3281-8372
    </div>

    <hr style="border:0.5px solid #000; margin:4px 0;">

    <div
        style="text-align:center; font-size:14pt; font-weight:bold; font-family:'Courier New',monospace; margin:16px 0 12px; letter-spacing:2px; text-transform:uppercase;">
        MANDADO DE INTIMAÇÃO
    </div>

    <div style="font-size:10pt; font-family:'Courier New',monospace; margin:4px 0;">
        <strong>Ref. ao Proc. de Mandado nº {{ processo }}</strong>
    </div>

    {% if numero_documento %}
    <div style="font-size:10pt; font-family:'Courier New',monospace; margin:4px 0;">
        <strong>Mandado nº {{ numero_documento }} - SEC/RPA</strong>
    </div>
    {% endif %}

    <div
        style="font-size:10pt; font-family:'Courier New',monospace; margin:16px 0; text-align:justify; text-indent:80px; line-height:1.5;">
        O(A) MM(a) Juiz(a) de Direito da 2ª Vara do Sistema dos Juizados Especiais da Comarca de Paulo Afonso,
        <strong>Dr. {{ despacho_autor }}</strong>, MANDA que o(a) Oficial(a) de Justiça Avaliador(a) proceda,
        com as cautelas legais, à <strong>INTIMAÇÃO</strong>, conforme teor do Despacho abaixo.
    </div>

    {% if despacho_observacao %}
    <hr style="border:0.5px solid #000; margin:12px 0;">
    <div
        style="font-size:10pt; font-family:'Courier New',monospace; margin:4px 0; font-weight:bold; text-transform:uppercase;">
        TEOR DO DESPACHO
    </div>
    <div
        style="font-size:10pt; font-family:'Courier New',monospace; margin:6px 0; text-align:justify; text-indent:40px; line-height:1.5;">
        {{ despacho_observacao }}
    </div>
    <hr style="border:0.5px solid #000; margin:12px 0;">
    {% endif %}

    <div
        style="font-size:10pt; font-family:'Courier New',monospace; margin:16px 0 6px; text-align:center; font-weight:bold;">
        Cumpra-se.
    </div>

    <div style="font-size:10pt; font-family:'Courier New',monospace; margin:24px 0 6px; text-align:right;">
        Paulo Afonso/BA, {{ data }}
    </div>

    <div style="font-size:10pt; font-family:'Courier New',monospace; margin:28px 0 6px; text-align:center;">
        <strong>{{ despacho_autor }}</strong><br>
        <strong>JUIZ DE DIREITO</strong>
    </div>

    <div style="text-align:center;">
        <hr style="border:0.5px solid #000; width:60%; margin:12px 0 6px;">
    </div>

    <div style="font-size:7pt; font-family:'Courier New',monospace; text-align:center; margin:6px 0;">
        Documento assinado eletronicamente conforme arts. 1º e 2º da Lei nº. 11.419/06,
        que dispõe sobre a informatização do processo digital. O documento pode ser acessado
        no endereço eletrônico https://projudi.tjba.jus.br/projudi sob o número acima epigrafado.
    </div>

    <div style="font-size:7pt; font-family:'Courier New',monospace; text-align:right; margin-top:2px;">
        {{ processo }}
    </div>

</div>

<div style="font-size:9pt; font-family:'Courier New',monospace; text-align:left; line-height:1.4; margin:12px 0 6px;">
    <strong>Destinatário(a):</strong> {{ parte.nome }}<br>
    {% if parte.endereco %}{{ parte.endereco|safe }}{% endif %}
    {% if parte.telefone %}<br>Tel.: {{ parte.telefone }}{% endif %}
    {% if parte.email %} &mdash; E-mail: {{ parte.email }}{% endif %}.
    {% if parte.cpf_cnpj %}<br>CPF/CNPJ: {{ parte.cpf_cnpj }}{% endif %}
</div>"""

# Validação antes de gravar
if 'MANDADO DE INTIMAÇÃO' not in MANDADO_INTIMACAO_HTML:
    raise SystemExit("Erro: HTML não contém 'MANDADO DE INTIMAÇÃO'. Abortando.")
if '{{ despacho_observacao }}' not in MANDADO_INTIMACAO_HTML:
    raise SystemExit("Erro: HTML não contém variável despacho_observacao. Abortando.")

t = DocumentTemplate.objects.get(id=9)
t.name = "Mandado de Intimação (com TEOR)"
t.description = (
    "Mandado de INTIMAÇÃO (ajustado para o fluxo de intimação de executado). "
    "Baseado no modelo #8, INJETA o TEOR DO DESPACHO ({{{{ despacho_observacao }}}}) "
    "com o texto do despacho do juiz no corpo do documento."
)
t.html_template = MANDADO_INTIMACAO_HTML
t.active = True
t.save()

vars_ = set(re.findall(r'\{\{([^}]+)\}\}', t.html_template))
print(f"✅ Modelo #9 atualizado → '{t.name}'")
print(f"   Template contém 'TEOR DO DESPACHO': {'TEOR DO DESPACHO' in t.html_template}")
print(f"   Variáveis: {len(vars_)} → {sorted(vars_)}")
