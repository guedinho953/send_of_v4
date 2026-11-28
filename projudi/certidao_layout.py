"""Layout padrão das certidões geradas pelas RAGs.

O texto simples digitado na RAG é embrulhado no mesmo cabeçalho visual
usado pelas certidões do TJBA: brasão, identificação do juízo, título,
corpo, assinatura e rodapé.
"""

from html import escape

LOGO_URL = (
    'https://projudi.tjba.jus.br/projudi/imagens/brasaoPetroBranco.jpg'
)

HEADER = f'''<div style="text-align:center; margin-bottom:6px;">
  <img src="{LOGO_URL}" style="width:80px; margin-bottom:4px;">
  <div style="font-size:11pt; font-weight:bold; text-transform:uppercase;">
    Poder Judiciário do Estado da Bahia
  </div>
  <div style="font-size:11pt; font-weight:bold;">
    Tribunal de Justiça do Estado da Bahia
  </div>
  <div style="font-size:10pt; font-weight:bold;">
    2ª Vara do Sistema dos Juizados Especiais
  </div>
  <div style="font-size:10pt; font-weight:bold;">Paulo Afonso</div>
</div>
<hr style="border:0.5px solid #000; margin:4px 0;">
<div style="font-size:9pt; text-align:center; margin:2px 0; line-height:1.2;">
  Rua das Caraibeiras, 420, Quadra 04 - 1º Andar, General Dutra -
  PAULO AFONSO<br>
  <strong>pafonso-2vsj@tjba.jus.br</strong> | Funcionamento: 13:00 às
  19:00 | Tel.: (75)3281-8372
</div>
<hr style="border:0.5px solid #000; margin:4px 0;">'''

DETALHES_DECURSO = '''<div style="font-size:10pt; font-family:'Courier New',monospace; margin:0 0 24px;">
  <table style="width:100%; border-collapse:collapse; line-height:1.6;">
    <tr>
      <td style="width:150px;"><strong>PROCESSO N.º</strong></td>
      <td>-</td>
      <td>{{ processo }}</td>
    </tr>
    <tr>
      <td><strong>PARTE</strong></td>
      <td>-</td>
      <td>{{ parte }}</td>
    </tr>
    <tr>
      <td><strong>INTIMAÇÃO</strong></td>
      <td>-</td>
      <td>
        evento {{ evento_intimacao }} em {{ data_intimacao }}
      </td>
    </tr>
    <tr>
      <td><strong>PRAZO</strong></td>
      <td>-</td>
      <td>{{ prazo_dias }} dias úteis</td>
    </tr>
    <tr>
      <td><strong>ÚLTIMO DIA</strong></td>
      <td>-</td>
      <td>{{ ultimo_dia }}</td>
    </tr>
    <tr>
      <td><strong>DECURSO</strong></td>
      <td>-</td>
      <td>{{ data_decurso }}</td>
    </tr>
  </table>
</div>'''

RODAPE = '''<div style="font-size:7pt; font-family:'Courier New',monospace; margin:10px 0 0; text-align:justify; line-height:1.2;">
  <sup>1</sup> Documento assinado eletronicamente conforme arts. 1º e 2º
  da Lei nº. 11.419/06, que dispõe sobre a informatização do processo
  digital. O documento pode ser acessado no endereço eletrônico
  https://projudi.tjba.jus.br/projudi/ sob o número acima epigrafado.
</div>
<div style="font-size:7pt; font-family:'Courier New',monospace; text-align:right; margin-top:16px; margin-bottom:24px;">
  {{ processo }}
</div>'''


def html_certidao_padrao(
        texto: str, titulo: str = 'CERTIDÃO', detalhes: str = '') -> str:
    """Monta o HTML completo de uma certidão a partir de texto simples.

    O texto é escapado, mas placeholders Django (``{{ processo }}``,
    ``{{ data }}`` etc.) continuam funcionando porque as chaves não são
    alteradas pelo ``escape``.
    """
    corpo = escape((texto or '').strip()).replace('\n', '<br>')
    return f'''<div style="font-family:'Times New Roman',serif; font-size:12pt; max-width:750px; margin:0 auto;">
{HEADER}
<div style="font-size:12pt; font-weight:bold; text-align:center; margin:22px 0 30px;">
  {escape(titulo)}
</div>
{detalhes}
<div style="font-size:10pt; font-family:'Courier New',monospace; margin:0 0 18px; text-align:justify; text-indent:80px; line-height:1.4;">
  {corpo}
</div>
<div style="font-size:10pt; font-family:'Courier New',monospace; margin:0 0 10px; text-align:justify; text-indent:80px;">
  O referido é verdade,<br>Dou fé.
</div>
<div style="font-size:10pt; font-family:'Courier New',monospace; margin:30px 0 6px; text-align:center;">
  <div style="margin-bottom:16px;">Paulo Afonso-BA, {{{{ data }}}}.</div>
  <strong>{{{{ servidor }}}}</strong><br>
  {{{{ servidor_cargo }}}}<br>
  Documento Assinado Eletronicamente<sup>1</sup>
</div>
{RODAPE}
</div>'''


def html_certidao_decurso(texto: str) -> str:
    """Certidão de decurso com os dados da intimação e do prazo.

    O corpo continua vindo da RAG; a moldura com processo, parte,
    intimação, prazo, último dia e decurso é reutilizável para outros
    tipos de decurso.
    """
    return html_certidao_padrao(
        texto,
        titulo='CERTIDÃO DE DECURSO DE PRAZO',
        detalhes=DETALHES_DECURSO,
    )
