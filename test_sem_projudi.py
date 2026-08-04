"""Teste OFFLINE (sem rodar o Projudi) das funções puras do fluxo.

Valida, sem sessão/navegador/rede:
  1. _montar_obs_expedicao  -> observação do solicitarr_expedicao
  2. _montar_obs_mandado    -> observação da confecção do mandado
  3. _gerar_certidao_negativa -> render dos 2 templates de certidão

Uso:
  cd /home/ivan/PythonProjects/send_of_v4
  source .venv/bin/activate
  python test_sem_projudi.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
# Importar expedir_rapido já faz django.setup() e puxa as helpers.
from expedir_rapido import (
    _montar_obs_expedicao, _montar_obs_mandado, _gerar_certidao_negativa,
    _gerar_html_certidao, _eh_polo_geral,
)
from projudiProcessNavigator import ProcessoParser

P = '0001708-74.2026.8.05.0191'
OK = 0
FALHAS = []


def check(descricao, cond):
    global OK
    if cond:
        OK += 1
        print(f'  ✓ {descricao}')
    else:
        FALHAS.append(descricao)
        print(f'  ✗ {descricao}')


print('== 1. _eh_polo_geral (destinatários) ==')
check("'autores' é geral", _eh_polo_geral('autores'))
check("'res' é geral", _eh_polo_geral('res'))
check("'todos' é geral", _eh_polo_geral('todos'))
check("'reu_especifico' NÃO é geral", not _eh_polo_geral('reu_especifico'))
check("'autor_especifico' NÃO é geral", not _eh_polo_geral('autor_especifico'))
check("lista com específico NÃO é geral", not _eh_polo_geral(['autor_especifico', 'reu_especifico']))
check("default (sem polo) NÃO é geral", not _eh_polo_geral(None))

print('== 2. _montar_obs_expedicao ==')
# (obs, desc_padrao, parte_nome, parte_obs)
o1 = _montar_obs_expedicao('', 'Solicitada a Expedicao de Mandado', 'JOSE A', False)
check('sem parte_na_obs -> não põe nome', o1 == 'Solicitada Expedicao - Solicitada a Expedicao de Mandado')
o2 = _montar_obs_expedicao('', 'Mandado', 'JOSE A / MARIA B', True)
check('true -> só 1ª parte', o2 == 'Solicitada Expedicao - Mandado - JOSE A')
o3 = _montar_obs_expedicao('', 'Mandado', 'JOSE A / MARIA B', 'todas')
check("'todas' => todas as partes", o3 == 'Solicitada Expedicao - Mandado - JOSE A / MARIA B')
o4 = _montar_obs_expedicao('', 'Mandado', 'JOSE A / MARIA B', 'primeiro')
check("'primeiro' => 1ª parte", o4 == 'Solicitada Expedicao - Mandado - JOSE A')
o5 = _montar_obs_expedicao('obs base', 'Mandado', 'JOSE A', True)
check('obs base preservada', o5 == 'obs base - JOSE A')
o6 = _montar_obs_expedicao('', 'Mandado', '', 'todas')
check('sem parte => nada adicionado', o6 == 'Solicitada Expedicao - Mandado')

print('== 2. _montar_obs_mandado ==')
m1 = _montar_obs_mandado(None, 'JOSE A')
check('sem obs_parte -> sem nome', m1 == 'Solicitada Expedicao de Mandado')
m2 = _montar_obs_mandado(True, 'JOSE A')
check('com obs_parte -> com nome', m2 == 'Solicitada Expedicao de Mandado - JOSE A')
m3 = _montar_obs_mandado('todas', 'JOSE A / MARIA B')
check('obs_mandado nome truncado a 60', m3.endswith('MARIA B') and m3.startswith('Solicitada'))

print('== 3. certidões (render) ==')
h1, t1 = _gerar_certidao_negativa(P, ['JOSE A'], 'VIT', 'SERVIDOR', '03/08/2026')
check('1 autor usa template (1 Autor)', t1 and '1 Autor' in t1.name)
check('1 autor masculino/genérico', 'NÃO FOI/FORAM BENEFICIADO(A)/(OS)/(AS)' in h1)
check('1 autor brasão', 'brasaoPetroBranco' in h1)
check('1 autor sem sobras {{', '{{' not in h1 and '}}' not in h1)
h2, t2 = _gerar_certidao_negativa(P, ['JOSE A', 'MARIA B', 'CARLOS C'], 'VIT', 'S', '03/08/2026')
check('multi usa template (Vários Autores)', t2 and 'Vários Autores' in t2.name)
check('multi enumera 1. 2. 3.', all(x in h2 for x in ['1. JOSE A', '2. MARIA B', '3. CARLOS C']))
check('multi corpo corrido', 'JOSE A, MARIA B e CARLOS C' in h2)
check('multi regra negativa plural', 'NÃO FOI/FORAM BENEFICIADO(A)/(OS)/(AS)' in h2)
# fallback antigo ainda renderiza
h3 = _gerar_html_certidao(P, ['JOSE A'], 'VIT', 'S', '03/08/2026')
check('fallback hardcoded renderiza', 'CERTIDÃO' in h3 and 'brasaoPetroBranco' in h3 and '{{' not in h3)

print('== 4. ProcessoParser (partes: domicílio + advogados) ==')
HTML_FAKE = '''<html><body>
<table class="tabelaLista">
  <tr class="linhaClara">
    <td>1</td><td>JOSE A <img src="/projudi/imagens/envelope.jpg"><img src="/projudi/imagens/favicon-domicilio-judicial-eletronico.png"></td>
    <td>RG1</td><td>CPF1</td><td>JOAO ADVOGADO - OAB/BA 12345<br>MARIA ADVOGADA OAB/BA 678</td><td>6</td>
  </tr>
</table>
<table class="tabelaLista">
  <tr class="linhaEscura">
    <td>2</td><td>REU SEM NADA</td><td>RG2</td><td>CPF2</td><td>Nenhum advogado</td><td>6</td>
  </tr>
</table>
</body></html>'''
parser = ProcessoParser(HTML_FAKE)
partes = parser.extrair_partes(parser.soup)
check('parser achou 2 partes', len(partes) == 2)
p0, p1 = partes[0], partes[1]
check('parte 1 recebe_intimacao_email (envelope)', p0.get('recebe_intimacao_email') is True)
check('parte 1 domicilio_cnj (favicon)', p0.get('domicilio_cnj') is True)
check('parte 1 tem_advogado', p0.get('tem_advogado') is True)
advs = p0.get('advogados') or []
check('advogado 1 sem OAB', 'JOAO ADVOGADO' in advs)
check('advogado 2 presente', 'MARIA ADVOGADA' in advs)
check("parte 1 advogado[0] 'JOAO ADVOGADO'", p0.get('advogado') == 'JOAO ADVOGADO')
check('parte 2 sem flags eletrônicas', not p1.get('recebe_intimacao_email') and not p1.get('domicilio_cnj'))
check('parte 2 sem advogados', (p1.get('advogados') or []) == [] and p1.get('tem_advogado') is False)

print(f'\n== RESULTADO: {OK} ok, {len(FALHAS)} falhas ==')
if FALHAS:
    print('FALHAS:')
    for f in FALHAS:
        print(f'  - {f}')
    sys.exit(1)
print('Tudo OK (sem rodar o Projudi).')