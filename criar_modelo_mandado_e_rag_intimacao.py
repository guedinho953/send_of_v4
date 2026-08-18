"""Cria o MODELO DE MANDADO (adaptado do #8) + RAG de intimação de
executado(s) com expedição de mandado.

Fluxo que a RAG representa (comando típico):
  - Intimem-se o(a)(s) executado(a)(s) ... na pessoa de seu advogado(a) ou,
    não o tendo, pessoalmente, para, querendo, no prazo de 15 (quinze) dias,
    apresentar(em) manifestação/impugnação/embargos à execução acerca do
    bloqueio/indisponibilidade efetivado(a), por meio eletrônico (SISBAJUD).
  - Renove-se a ordem à penhora dos bens, necessários para garantir a
    execução, através do sistema SISBAJUD.

Uso:
  source .venv/bin/activate
  python criar_modelo_mandado_e_rag_intimacao.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()

from processes.models import Process, DocumentTemplate, RAGExample
from base.utils import normalize_process_number

# ═══════════════════════════════════════════════════════════════════
# 1) MODELO DE MANDADO (adaptado do #8 + seção TEOR DO DESPACHO)
# ═══════════════════════════════════════════════════════════════════
MANDADO_HTML = """<div style="font-family:'Times New Roman',serif; font-size:12pt; max-width:750px; margin:0 auto;">

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

  {% if despacho_observacao %}
  <hr style="border:0.5px solid #000; margin:12px 0;">
  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:4px 0; font-weight:bold; text-transform:uppercase;">
    TEOR DO DESPACHO
  </div>
  <div style="font-size:10pt; font-family:'Courier New',monospace; margin:6px 0; text-align:justify; text-indent:40px; line-height:1.5;">
    {{ despacho_observacao }}
  </div>
  <hr style="border:0.5px solid #000; margin:12px 0;">
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

# ─── Atualiza o modelo #8 (mantendo o id, só adiciona TEOR DO DESPACHO) ───
try:
    m8 = DocumentTemplate.objects.get(id=8)
except DocumentTemplate.DoesNotExist:
    raise SystemExit("Modelo #8 não encontrado. Abortando.")

m8.name = "Mandado de Citação, Intimação, Penhora e Avaliação (com TEOR)"
m8.description = (
    "Mandado para citação, intimação, penhora e avaliação de bens (execução). "
    "Adaptado do modelo #8: injeta o TEOR DO DESPACHO ({{ despacho_observacao }}) "
    "do juiz no corpo do documento. Parte destinatária: executado/réu."
)
m8.html_template = MANDADO_HTML
m8.active = True
m8.save()
print(f"✅ Modelo de Mandado #8 atualizado → '{m8.name}'")
print(f"   Novo template com seção TEOR DO DESPACHO ({{{{ despacho_observacao }}}}).")

# ═══════════════════════════════════════════════════════════════════
# 2) RAG — Intimação de executado(s) + expedição de mandado (En. 142 FONAJE)
# ═══════════════════════════════════════════════════════════════════
DESPACHO_ATO = (
    'DECISÃO - INTIMAÇÃO DE EXECUTADO(S) NA PESSOA DE SEU ADVOGADO - '
    'EMBARGOS/MANIFESTAÇÃO ACERCA DO BLOQUEIO (SISBAJUD) - '
    'RENOVAÇÃO DA ORDEM DE PENHORA (SISBAJUD) - '
    'EXPEDIÇÃO DE MANDADO'
)

DESPACHO_OBSERVACAO = """Conforme Enunciado 142 do FONAJE, intimem-se o(a)(s) executado(a)(s) na pessoa de seu(sua) advogado(a) ou, não o tendo, pessoalmente, para, querendo, no prazo de 15 (quinze) dias, apresentar(em) manifestação/impugnação/embargos à execução acerca do bloqueio/indisponibilidade efetivado(a), por meio eletrônico (SISBAJUD).

Diante do resultado da pesquisa de ativos financeiros dos demandados, colacionado no evento retro, renove-se a ordem à penhora dos bens do(a)(s) devedor(a)(s) necessários para garantir a execução, através do sistema SISBAJUD."""

# Sequência: intimação eletrônica (fallback mandado se não houver DJEN/adv)
SEQUENCIA_CUMPRIMENTO = [
    {
        "tipo": "intimacao_completa",
        "fluxo": "analisar",
        "fluxo_fallback": True,
        "codigo_mov": "581",
        "descricao_mov": "Intimação",
        "observacao": (
            "Intimem-se o(a)(s) executado(a)(s) na pessoa de seu advogado(a) "
            "ou, não o tendo, pessoalmente, para, querendo, no prazo de 15 "
            "(quinze) dias, apresentar manifestação/impugnação/embargos à "
            "execução acerca do bloqueio efetivado (SISBAJUD)."
        ),
        # Polo = T O D O S os executados (um mandado por parte). Para parte
        # específica use "autor_especifico" / "reu_especifico" + parte_nome.
        "polo": "todos",
        # Prazo 15 dias (código '4' no Projudi)
        "prazo_intimacao": "4",
        # Moeda de intimação preferencial (DJEN/adv)
        "motivo_intimacao": "3",
        # Expedir mandado p/ quem não tem meio eletrônico
        "solicitar_mandado": True,
        "mandado_polo": "todos",
        "mandado_subtipo": "11",  # Citação/Penhora/Avaliação
        # Se não houver DJEN/adv → fallback solicitar expedição de mandado
        "fallback": "solicitar_expecidao",
        "fallback_ar": True,
        # AR digital
        "expedir_ar": True,
        "assinar_ar": False,
        # Modo teste (não conclui movimentação)
        "nao_concluir": False,
    }
]

PROCESSO_FICTICIO = "9999999-99.2026.8.05.0191"
TENANT_ID = 1

norm = normalize_process_number(PROCESSO_FICTICIO)
proc, created = Process.objects.get_or_create(
    number=PROCESSO_FICTICIO,
    defaults={'number_normalized': norm, 'tenant_id': TENANT_ID},
)
if not proc.number_normalized:
    proc.number_normalized = norm
    proc.save(update_fields=['number_normalized'])
status = '(criado)' if created else '(existente)'
print(f"\nProcesso: {PROCESSO_FICTICIO} → #{proc.id} {status}")

rag = RAGExample.objects.create(
    tenant_id=TENANT_ID,
    process=proc,
    oficio='',
    despacho_ato=DESPACHO_ATO,
    despacho_observacao=DESPACHO_OBSERVACAO,
    despacho_data='',
    despacho_autor='',
    evento_despacho='',
    cumprimentos=[],
    documentos=[],
    sequencia_cumprimento=SEQUENCIA_CUMPRIMENTO,
    active=True,
)

print(f"\n✅ RAGExample #{rag.id} criado!")
print(f"   Ato: {rag.despacho_ato}")
print(f"   Obs: {rag.despacho_observacao[:80]}...")
print(f"   Seq: {json.dumps(rag.sequencia_cumprimento, ensure_ascii=False)}")
print("\nPronto para uso no matching RAG.")
