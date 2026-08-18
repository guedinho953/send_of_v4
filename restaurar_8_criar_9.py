"""Reverte o DocumentTemplate #8 ao original e cria o #9 novo baseado no #8
com a seção TEOR DO DESPACHO ({{ despacho_observacao }}).

Uso:
  source .venv/bin/activate
  python restaurar_8_criar_9.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.models import DocumentTemplate

# ─── Template ORIGINAL do #8 (restaurado de antes da adaptação) ───
ORIGINAL_8_HTML = """<div style="font-family:'Times New Roman',serif; font-size:12pt; max-width:750px; margin:0 auto;">
  
  <div style="text-align:center; margin-bottom:6px;">
    <div style="font-size:11pt; font-weight:bold; text-transform:uppercase;">Poder Judiciário do Estado da Bahia</div>
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

  <div style="text-align:center; font-size:14pt; font-weight:bold; font-family:'Courier New',monospace; margin:16px 0 12px; letter-spacing:2px; text-transform:uppercase;">
    MANDADO DE CITAÇÃO, INTIMAÇÃO, PENHORA E AVALIAÇÃO
  </div>

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:4px 0;">
    <strong>Ref. ao Proc. de Mandado nº {{ processo }}</strong>
  </div>

  {% if numero_documento %}
  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:4px 0;">
    <strong>Mandado nº {{ numero_documento }} - SEC/RPA</strong>
  </div>
  {% endif %}

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:16px 0; text-align:justify; text-indent:80px; line-height:1.5;">
    O(A) MM(a) Juiz(a) de Direito da 2ª Vara do Sistema dos Juizados Especiais da Comarca de Paulo Afonso,
    <strong>Dr. {{ despacho_autor }}</strong>, MANDA que o(a) Oficial(a) de Justiça Avaliador(a) proceda,
    com as cautelas legais, à <strong>CITAÇÃO, INTIMAÇÃO</strong> e, sendo o caso,
    <strong>PENHORA E AVALIAÇÃO</strong> de bens da parte executada, conforme finalidade abaixo transcrita.
  </div>

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:12px 0; text-align:justify; text-indent:80px; line-height:1.5;">
    <strong>FINALIDADE:</strong> Citar a parte ré executada abaixo identificada acerca da execução contra ela proposta
    pela parte exequente supra nomeada, conforme os termos da petição inicial que acompanha este mandado de citação,
    e para, no prazo de <strong>{{ prazo_dias |default:"15" }} ({{ prazo_dias_extenso |default:"quinze" }}) dias</strong>,
    pagar o total devido ou nomear tantos bens à penhora quantos bastem para garantir a execução,
    conforme a ordem estabelecida no art. 835 do CPC e excluindo os que a lei declare absolutamente impenhoráveis.
    No caso de penhora dos bens elencados no art. 840, II, do CPC, estes ficarão em poder da parte exequente,
    nos termos do §1º, do art. 840 do CPC, em razão de inexistência de depositário judicial nesta Comarca.
    Se não houver o pagamento, nem nomeação válida, o(a) Oficial(a) de Justiça penhorará,
    mediante apreensão e depósito, tantos bens quantos bastem para o pagamento do principal e juros,
    avaliando-os em seguida.
  </div>

  {% if valor_penhora %}
  <div style="font-size:11pt; font-family:'Courier New',monospace; margin:16px 0; text-align:center; font-weight:bold;">
    Valor da Penhora: R$ {{ valor_penhora }}
  </div>
  {% endif %}

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:12px 0; text-align:justify; text-indent:80px; line-height:1.5;">
    Fica a parte ré executada desde já ciente de que se a causa for de valor superior a vinte salários mínimos
    vigente à época, deverá ser assistida por Advogado ou, observados os requisitos legais, por Defensor Público.
    Se o valor da causa for inferior a essa quantia a assistência por Advogado ou Defensor Público é facultativa.
    Sendo a parte executada pessoa jurídica deverá, também, ser representada por quem tenha poderes para tanto.
    O preposto deverá apresentar a respectiva carta de preposição.
    Fica a parte executada também intimada para impugnar a execução, por escrito ou verbalmente,
    o que deverá ocorrer em Audiência de Conciliação a ser designada (art. 53, §1º da Lei 9.099/95),
    observada a advertência do art. 20 da mesma Lei.
  </div>

  {% if descricao_cumprimento %}
  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:12px 0; text-align:justify; text-indent:80px; line-height:1.5;">
    <strong>Observações:</strong> {{ descricao_cumprimento }}
  </div>
  {% endif %}

  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:16px 0 6px; text-align:center; font-weight:bold;">
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

# ─── #9 = #8 + seção TEOR DO DESPACHO inserida após "Observações" ───
SECAO_TEOR = """  {% if despacho_observacao %}
  <hr style="border:0.5px solid #000; margin:12px 0;">
  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:4px 0; font-weight:bold; text-transform:uppercase;">
    TEOR DO DESPACHO
  </div>
  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:6px 0; text-align:justify; text-indent:40px; line-height:1.5;">
    {{ despacho_observacao }}
  </div>
  <hr style="border:0.5px solid #000; margin:12px 0;">
  {% endif %}

"""

# Insere a seção TEOR DO DESPACHO antes do "Cumpra-se."
MARCADOR = '  <div style="font-size:10pt; font-family:\'Courier New\',monospace; margin:16px 0 6px; text-align:center; font-weight:bold;">\n    Cumpra-se.'
NOVO_9_HTML = ORIGINAL_8_HTML.replace(MARCADOR, SECAO_TEOR + MARCADOR)

if 'TEOR DO DESPACHO' not in NOVO_9_HTML or 'despacho_observacao' not in NOVO_9_HTML:
    raise SystemExit("Erro: seção TEOR DO DESPACHO não foi inserida corretamente. Abortando.")

# ─── 1) Rasgar mudanças: restaurar #8 ao original ───
m8 = DocumentTemplate.objects.get(id=8)
m8.name = "Mandado de Citação, Intimação, Penhora e Avaliação"
m8.description = (
    "Mandado para citação, intimação, penhora e avaliação de bens. Usado em execução. "
    "Parte destinatária: executado/réu."
)
m8.html_template = ORIGINAL_8_HTML
m8.active = True
m8.save()
print(f"✅ Modelo #8 restaurado ao ORIGINAL → '{m8.name}'")

# ─── 2) Criar #9 novo com TEOR DO DESPACHO ───
m9, created = DocumentTemplate.objects.update_or_create(
    id=9,
    defaults={
        "name": "Mandado de Citação, Intimação, Penhora e Avaliação (com TEOR)",
        "template_type": "mandado",
        "description": (
            "Mandado para citação, intimação, penhora e avaliação de bens (execução). "
            "Baseado no modelo #8 com a seção TEOR DO DESPACHO "
            "({{{{ despacho_observacao }}}}) injetando o texto do despacho do juiz."
        ),
        "html_template": NOVO_9_HTML,
        "active": True,
    },
)
acao = "(criado)" if created else "(atualizado)"
print(f"✅ Modelo #9 {acao} → '{m9.name}'")

# ─── Verificação final ───
import re
vars8 = set(re.findall(r'\{\{([^}]+)\}\}', m8.html_template))
vars9 = set(re.findall(r'\{\{([^}]+)\}\}', m9.html_template))
print(f"\n#8 variáveis: {len(vars8)} | Tem despacho_observacao? {'despacho_observacao' in vars8}")
print(f"#9 variáveis: {len(vars9)} | Tem despacho_observacao? {'despacho_observacao' in vars9}")
print("Modelo #8 == original? 'TEOR DO DESPACHO' ausente:", 'TEOR DO DESPACHO' not in m8.html_template)
print("Modelo #9 tem 'TEOR DO DESPACHO':", 'TEOR DO DESPACHO' in m9.html_template)
