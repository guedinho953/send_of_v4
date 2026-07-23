"""Teste completo da árvore de decisão do FluxoDecisor."""
import sys, os
sys.path.insert(0, '/home/ivan/PythonProjects/send_of_v4')
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'

import django; django.setup()

from projudi.parte_classifier import ParteClassifier
from projudi.fluxo_decisor import FluxoDecisor


def testar_cenario(nome, partes_raw, ato_data=None):
    print(f'\n{"="*70}')
    print(f'  💠 {nome}')
    print(f'{"="*70}')

    # 1. Classificar partes
    classifier = ParteClassifier(partes_raw)
    resultado_cls = classifier.classificar()
    partes_classif = resultado_cls['partes']

    # Mostrar classificação
    for p in partes_classif:
        canais = ', '.join(p['canais_disponiveis'])
        print(f'  📋 {p["nome"]} | Prior: {p["canal_prioritario"]} | Disp: {canais}')

    # 2. Decidir fluxo
    decisor = FluxoDecisor(partes_raw, partes_classif, ato_data)
    resultado = decisor.decidir()

    # Mostrar decisões
    print(f'\n  🧭 DECISÃO{" para ato=" + ato_data.get("tipo_ato", "?") if ato_data else ""}:')
    if resultado.get('tipo') == 'ato_sem_destinatario':
        print(f'     📄 {resultado["justificativa"]}')
    else:
        for p in resultado['partes']:
            emoji = {
                'eletronico': '💻',
                'advogado': '👨‍⚖️',
                'email': '📧',
                'email_condicional': '📧⚠️',
                'ar': '📮',
                'mandado': '🔖',
                'mandado_precatorio': '📜',
                'edital': '📰',
            }.get(p['fluxo'], '❓')
            print(f'     {emoji} {p["nome"]} → {p["fluxo"].upper()}')
            print(f'        {p["justificativa"][:120]}...')
        print(f'\n     📊 Resumo:')
        for fluxo, nomes in resultado['resumo']['fluxos'].items():
            if nomes:
                print(f'        {fluxo}: {", ".join(nomes)}')

    return resultado


# =====================================================================
# CENÁRIOS
# =====================================================================

# ── 1: DJEN ──
cenario_djen = [
    {'nome': 'JOSE CARLOS', 'nome_normalizado': 'jose carlos',
     'tipo': 'EXECUTADO', 'cpf/cnpj': '987.654.321-00',
     'recebe_intimacao_email': False, 'domicilio_cnj': True,
     'tem_advogado': False, 'email': '', 'tel': '',
     'logradouro': 'Rua B', 'numero': '200', 'bairro': 'Centro',
     'cidade': 'PAULO AFONSO', 'uf': 'BA', 'cep': '48601000',
     'revelia': False},
]

# ── 2: Advogado ──
cenario_adv = [
    {'nome': 'MARIA SILVA', 'nome_normalizado': 'maria silva',
     'tipo': 'EXEQUENTE', 'cpf/cnpj': '123.456.789-00',
     'recebe_intimacao_email': False, 'domicilio_cnj': False,
     'tem_advogado': True, 'email': '', 'tel': '',
     'logradouro': 'Av A', 'numero': '50', 'bairro': 'Centro',
     'cidade': 'PAULO AFONSO', 'uf': 'BA', 'cep': '48600000',
     'revelia': False},
]

# ── 3: Email com opt-in ──
cenario_email = [
    {'nome': 'ANA BEATRIZ', 'nome_normalizado': 'ana beatriz',
     'tipo': 'EXECUTADO', 'cpf/cnpj': '999.888.777-66',
     'recebe_intimacao_email': True, 'domicilio_cnj': False,
     'tem_advogado': False, 'email': 'ana@dominio.com', 'tel': '',
     'logradouro': 'Rua E', 'numero': '500', 'bairro': 'Centro',
     'cidade': 'PAULO AFONSO', 'uf': 'BA', 'cep': '48600000',
     'revelia': False},
]

# ── 4: Email sem opt-in, ato permite condicional ──
cenario_email_cond = [
    {'nome': 'PEDRO ALVES', 'nome_normalizado': 'pedro alves',
     'tipo': 'EXECUTADO', 'cpf/cnpj': '555.666.777-88',
     'recebe_intimacao_email': False, 'domicilio_cnj': False,
     'tem_advogado': False, 'email': 'pedro@email.com', 'tel': '',
     'logradouro': 'Rua D', 'numero': '400', 'bairro': 'Centro',
     'cidade': 'PAULO AFONSO', 'uf': 'BA', 'cep': '48601000',
     'revelia': True},
]

# ── 5: Email sem opt-in, ato NÃO permite (intimação formal) → física → mandado
cenario_email_cond_bloqueado = cenario_email_cond  # mesmos dados, ato diferente

# ── 6: Paulo Afonso (zona urbana) → mandado
cenario_pa = [
    {'nome': 'MUNICÍPIO DE PAULO AFONSO', 'nome_normalizado': 'municipio de paulo afonso',
     'tipo': 'EXECUTADO', 'cpf/cnpj': '00.000.000/0001-00',
     'recebe_intimacao_email': False, 'domicilio_cnj': False,
     'tem_advogado': False, 'email': '', 'tel': '',
     'logradouro': 'Praça da Matriz', 'numero': '1', 'bairro': 'Centro',
     'cidade': 'PAULO AFONSO', 'uf': 'BA', 'cep': '48600000',
     'revelia': False},
]

# ── 7: BA (outra cidade, urbana) → AR
cenario_ba_outra = [
    {'nome': 'EMPRESA XYZ LTDA', 'nome_normalizado': 'empresa xyz ltda',
     'tipo': 'EXECUTADO', 'cpf/cnpj': '11.222.333/0001-44',
     'recebe_intimacao_email': False, 'domicilio_cnj': False,
     'tem_advogado': False, 'email': '', 'tel': '7133334444',
     'logradouro': 'Av Oceânica', 'numero': '1000', 'bairro': 'Ondina',
     'cidade': 'SALVADOR', 'uf': 'BA', 'cep': '40170000',
     'revelia': False},
]

# ── 8: BA + zona rural → mandado
cenario_ba_rural = [
    {'nome': 'JOAO FAZENDEIRO', 'nome_normalizado': 'joao fazendeiro',
     'tipo': 'EXECUTADO', 'cpf/cnpj': '555.666.777-88',
     'recebe_intimacao_email': False, 'domicilio_cnj': False,
     'tem_advogado': False, 'email': '', 'tel': '',
     'logradouro': 'Fazenda Boa Esperança', 'numero': 's/n',
     'bairro': 'Zona Rural', 'cidade': 'FEIRA DE SANTANA',
     'uf': 'BA', 'cep': '44000000', 'revelia': False},
]

# ── 9: Outro estado → AR
cenario_outro_estado = [
    {'nome': 'INDUSTRIA NACIONAL', 'nome_normalizado': 'industria nacional',
     'tipo': 'EXECUTADO', 'cpf/cnpj': '99.888.777/0001-66',
     'recebe_intimacao_email': False, 'domicilio_cnj': False,
     'tem_advogado': False, 'email': '', 'tel': '',
     'logradouro': 'Rua Augusta', 'numero': '1500', 'bairro': 'Consolação',
     'cidade': 'SÃO PAULO', 'uf': 'SP', 'cep': '01304001',
     'revelia': False},
]

# ── 10: Outro estado + rural → mandado precatório
cenario_outro_estado_rural = [
    {'nome': 'SITIO BOM JESUS', 'nome_normalizado': 'sitio bom jesus',
     'tipo': 'EXECUTADO', 'cpf/cnpj': '44.555.666/0001-77',
     'recebe_intimacao_email': False, 'domicilio_cnj': False,
     'tem_advogado': False, 'email': '', 'tel': '',
     'logradouro': 'Estrada do Campo, Km 45', 'numero': 's/n',
     'bairro': 'Povoado do Rio',
     'cidade': 'RIO DE JANEIRO', 'uf': 'RJ', 'cep': '20000000',
     'revelia': False},
]

# ── 11: Sem endereço → edital
cenario_sem_endereco = [
    {'nome': 'FULANO DESCONHECIDO', 'nome_normalizado': 'fulano desconhecido',
     'tipo': 'EXECUTADO', 'cpf/cnpj': '',
     'recebe_intimacao_email': False, 'domicilio_cnj': False,
     'tem_advogado': False, 'email': '', 'tel': '',
     'revelia': True},
]

# ── 12: Ato sem destinatário (arquive-se) → movimentacao_simples
cenario_arquive_se = [
    {'nome': 'QUALQUER PARTE', 'nome_normalizado': 'qualquer parte',
     'tipo': 'EXECUTADO', 'cpf/cnpj': '00.000.000/0001-00',
     'recebe_intimacao_email': False, 'domicilio_cnj': True,
     'tem_advogado': False, 'email': '', 'tel': '',
     'logradouro': 'Rua X', 'numero': '1', 'bairro': 'Centro',
     'cidade': 'PAULO AFONSO', 'uf': 'BA', 'cep': '48600000',
     'revelia': False},
]


if __name__ == '__main__':
    total = 0
    erros = 0

    # ─── 1: DJEN ───
    r = testar_cenario('1 — DJEN', cenario_djen)
    assert r['partes'][0]['fluxo'] == 'eletronico'
    total += 1
    print('  ✅')

    # ─── 2: Advogado ───
    r = testar_cenario('2 — Advogado', cenario_adv)
    assert r['partes'][0]['fluxo'] == 'advogado'
    total += 1
    print('  ✅')

    # ─── 3: Email opt-in ───
    r = testar_cenario('3 — Email com opt-in', cenario_email)
    assert r['partes'][0]['fluxo'] == 'email'
    total += 1
    print('  ✅')

    # ─── 4: Email condicional + ato permite → email_condicional ───
    r = testar_cenario('4 — Email condicional (permite)', cenario_email_cond,
                       {'tipo_ato': 'certificar', 'act_verb': 'certifique-se'})
    assert r['partes'][0]['fluxo'] == 'email_condicional', \
        f'Esperado email_condicional, veio {r["partes"][0]["fluxo"]}'
    total += 1
    print('  ✅')

    # ─── 5: Email condicional + ato NÃO permite → cai na árvore (mandado) ───
    r = testar_cenario('5 — Email condicional (BLOQUEADO para intimação)',
                       cenario_email_cond_bloqueado,
                       {'tipo_ato': 'intimacao', 'act_verb': 'intime-se'})
    fluxo = r['partes'][0]['fluxo']
    assert fluxo == 'mandado', \
        f'Intimação formal sem opt-in e endereço em PA → devia ser mandado, veio {fluxo}'
    total += 1
    print('  ✅')

    # ─── 6: Paulo Afonso → mandado ───
    r = testar_cenario('6 — Paulo Afonso (urbano)', cenario_pa)
    assert r['partes'][0]['fluxo'] == 'mandado', \
        f'PA → mandado, veio {r["partes"][0]["fluxo"]}'
    total += 1
    print('  ✅')

    # ─── 7: BA outra cidade (intimação) → AR ───
    r = testar_cenario('7 — BA (Salvador, intimação)', cenario_ba_outra,
                       {'tipo_ato': 'intimacao', 'act_verb': 'intime-se'})
    assert r['partes'][0]['fluxo'] == 'ar', \
        f'BA urbano + intimação → ar, veio {r["partes"][0]["fluxo"]}'
    total += 1
    print('  ✅')

    # ─── 7b: BA outra cidade (CITAÇÃO) → mandado ───
    r = testar_cenario('7b — BA (Salvador, citação)', cenario_ba_outra,
                       {'tipo_ato': 'citacao', 'act_verb': 'cite-se'})
    assert r['partes'][0]['fluxo'] == 'mandado', \
        f'BA + citação → mandado, veio {r["partes"][0]["fluxo"]}'
    total += 1
    print('  ✅')

    # ─── 8: BA + rural → mandado ───
    r = testar_cenario('8 — BA + zona rural', cenario_ba_rural)
    assert r['partes'][0]['fluxo'] == 'mandado', \
        f'BA rural → mandado, veio {r["partes"][0]["fluxo"]}'
    total += 1
    print('  ✅')

    # ─── 9: Outro estado + intimação → AR ───
    r = testar_cenario('9 — SP (intimação)', cenario_outro_estado,
                       {'tipo_ato': 'intimacao', 'act_verb': 'intime-se'})
    assert r['partes'][0]['fluxo'] == 'ar', \
        f'SP + intimação → ar, veio {r["partes"][0]["fluxo"]}'
    total += 1
    print('  ✅')

    # ─── 9b: Outro estado + CITAÇÃO → precatória ───
    r = testar_cenario('9b — SP (citação)', cenario_outro_estado,
                       {'tipo_ato': 'citacao', 'act_verb': 'cite-se'})
    assert r['partes'][0]['fluxo'] == 'mandado_precatorio', \
        f'SP + citação → mandado_precatorio, veio {r["partes"][0]["fluxo"]}'
    total += 1
    print('  ✅')

    # ─── 10: Outro estado + rural → mandado_precatorio ───
    r = testar_cenario('10 — RJ + rural', cenario_outro_estado_rural)
    assert r['partes'][0]['fluxo'] == 'mandado_precatorio', \
        f'RJ rural → mandado_precatorio, veio {r["partes"][0]["fluxo"]}'
    total += 1
    print('  ✅')

    # ─── 11: Sem endereço → edital ───
    r = testar_cenario('11 — Sem endereço', cenario_sem_endereco)
    assert r['partes'][0]['fluxo'] == 'edital', \
        f'Sem endereço → edital, veio {r["partes"][0]["fluxo"]}'
    total += 1
    print('  ✅')

    # ─── 12: Ato sem destinatário → movimentacao_simples ───
    r = testar_cenario('12 — "publique-se" (sem destinatário)',
                       cenario_arquive_se,
                       {'tipo_ato': 'publicar', 'act_verb': 'publique-se'})
    assert r['tipo'] == 'ato_sem_destinatario', \
        f'ato_sem_destinatario, veio tipo={r.get("tipo")}'
    total += 1
    print('  ✅')

    # ─── 13: Múltiplas partes com decisões diferentes ───
    print(f'\n{"="*70}')
    print(f'  13 — MÚLTIPLAS PARTES (misto)')
    print(f'{"="*70}')
    partes_mistas = cenario_djen + cenario_pa + cenario_ba_outra
    r = testar_cenario('13 — Mistas (DJEN + PA + BA)', partes_mistas)
    fluxos = {p['nome']: p['fluxo'] for p in r['partes']}
    assert fluxos.get('JOSE CARLOS') == 'eletronico', f'JOSE: {fluxos.get("JOSE CARLOS")}'
    assert fluxos.get('MUNICÍPIO DE PAULO AFONSO') == 'mandado', \
        f'MUNICÍPIO: {fluxos.get("MUNICÍPIO DE PAULO AFONSO")}'
    assert fluxos.get('EMPRESA XYZ LTDA') == 'ar', \
        f'EMPRESA: {fluxos.get("EMPRESA XYZ LTDA")}'
    total += 1
    print('  ✅')

    print(f'\n{"="*70}')
    print(f'  ✅ 15 CENÁRIOS TESTADOS — TODOS PASSARAM')
    print(f'{"="*70}')
