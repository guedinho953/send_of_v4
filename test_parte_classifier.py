"""Teste do ParteClassifier com dados realistas do Projudi."""
import sys, os
sys.path.insert(0, '/home/ivan/PythonProjects/send_of_v4')
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'

import django; django.setup()

from projudi.parte_classifier import ParteClassifier


# =====================================================================
# CENÁRIO 1: Dados do ProcessoParser (formato HTML)
# =====================================================================
partes_parser = [
    {
        'nome': 'MARIA DAS DORES SILVA',
        'nome_normalizado': 'maria das dores silva',
        'cpf/cnpj': '123.456.789-00',
        'tipo': 'EXEQUENTE',
        'papel': 'PROMOVENTE',
        'recebe_intimacao_email': True,
        'domicilio_cnj': False,
        'tem_advogado': True,
        'email': 'maria@email.com',
        'tel': '7199998888',
        'revelia': False,
        'logradouro': 'Rua A', 'numero': '100', 'bairro': 'Centro',
        'cidade': 'PAULO AFONSO', 'uf': 'BA', 'cep': '48600000',
    },
    {
        'nome': 'JOSE CARLOS PEREIRA',
        'nome_normalizado': 'jose carlos pereira',
        'cpf/cnpj': '987.654.321-00',
        'tipo': 'EXECUTADO',
        'papel': 'PROMOVIDO',
        'recebe_intimacao_email': False,
        'domicilio_cnj': True,
        'tem_advogado': False,
        'email': '',
        'tel': '',
        'revelia': True,
        'logradouro': 'Av B', 'numero': '200', 'bairro': 'Jardim',
        'cidade': 'PAULO AFONSO', 'uf': 'BA', 'cep': '48601000',
    },
    {
        'nome': 'EMPRESA BAIANA DE AGUAS LTDA (EMBASA) (REV. ARG.)',
        'nome_normalizado': 'empresa baiana de aguas ltda (embasa) (rev. arg.)',
        'cpf/cnpj': '13.789.654/0001-00',
        'tipo': 'EXECUTADO',
        'papel': 'PROMOVIDO',
        'recebe_intimacao_email': False,
        'domicilio_cnj': False,
        'tem_advogado': False,
        'email': '',
        'tel': '7133334444',
        'revelia': True,
        'logradouro': 'Rua Industrial', 'numero': '500', 'bairro': 'Distrito Industrial',
        'cidade': 'SALVADOR', 'uf': 'BA', 'cep': '40000000',
    },
]

# =====================================================================
# CENÁRIO 2: Dados do Django model Party (formato model)
# =====================================================================
partes_model = [
    {
        'name': 'JOÃO SANTOS',
        'name_normalized': 'joao santos',
        'role': 'autor',
        'cpf_cnpj': '111.222.333-44',
        'email': 'joao@email.com',
        'phone': '7198887777',
        'has_lawyer': True,
        'receives_email_intimation': True,
        'has_domicilio_cnj': False,
        'is_revel': False,
        'address': 'Rua C, 300, Centro, Paulo Afonso - BA',
    },
    {
        'name': 'PEDRO ALVES',
        'name_normalized': 'pedro alves',
        'role': 'reu',
        'cpf_cnpj': '555.666.777-88',
        'email': 'pedro@email.com',       # tem email, mas SEM opt-in
        'phone': '',
        'has_lawyer': False,
        'receives_email_intimation': False,  # sem ícone de envelope
        'has_domicilio_cnj': False,
        'is_revel': True,
        'address': 'Rua D, 400, Bairro Novo, Paulo Afonso - BA',
    },
    {
        'name': 'ANA BEATRIZ',
        'name_normalized': 'ana beatriz',
        'role': 'reu',
        'cpf_cnpj': '999.888.777-66',
        'email': 'ana@dominio.com',
        'phone': '7196665555',
        'has_lawyer': False,
        'receives_email_intimation': True,  # opt-in por email
        'has_domicilio_cnj': False,
        'is_revel': False,
        'address': 'Rua E, 500, Centro, Paulo Afonso - BA',
    },
    {
        'name': 'MUNICÍPIO DE PAULO AFONSO',
        'name_normalized': 'municipio de paulo afonso',
        'role': 'reu',
        'cpf_cnpj': '14.258.963/0001-85',
        'email': 'procuradoria@pauloafonso.ba.gov.br',
        'phone': '7133224455',
        'has_lawyer': True,
        'receives_email_intimation': False,
        'has_domicilio_cnj': True,
        'is_revel': False,
        'address': 'Praça da Matriz, 1, Centro, Paulo Afonso - BA - CEP: 48600-000',
    },
]


def testar(cenario_nome, partes, fonte):
    print(f'\n{"="*70}')
    print(f'  TESTE: {cenario_nome} ({fonte})')
    print(f'{"="*70}')

    classifier = ParteClassifier(partes)
    resultado = classifier.classificar()

    r = resultado['resumo']
    print(f'\n📊 RESUMO: {r["total_partes"]} partes | {r["autores"]} autor(es) | {r["reus"]} réu(s)')

    print(f'\n📋 PARTES (detalhado):')
    for i, p in enumerate(resultado['partes'], 1):
        icone = {
            'advogado': '👨‍⚖️',
            'djen': '💻',
            'email': '📧',
            'email_condicional': '📧⚠️',
            'fisica': '📬',
        }.get(p['canal_prioritario'], '❓')
        disp_icons = ', '.join({
            'advogado': '👨‍⚖️',
            'djen': '💻',
            'email': '📧',
            'email_condicional': '📧⚠️',
            'fisica': '📬',
        }.get(c, c) for c in p['canais_disponiveis'])

        print(f'  {i}. {p["nome"]}')
        print(f'     Papel: {p["papel"]} | Adv: {"✅" if p["tem_advogado"] else "❌"} '
              f'DJEN: {"✅" if p["domicilio_cnj"] else "❌"} '
              f'Email: {"✅" if p["recebe_email"] else "❌"} '
              f'Revel: {"✅" if p["revel"] else "❌"}')
        print(f'     {icone} Prioritário: {p["canal_prioritario"].upper()}')
        print(f'     📡 Disponível: {disp_icons}')
        print(f'     📧 email_opt_in={p["email_opt_in"]} email_sem_optin={p["email_sem_optin"]} '
              f'email_disponivel={p["email_disponivel"]}')
        print(f'     💬 {p["canal_explicacao"]}')

    print(f'\n📬 CANAIS PRIORITÁRIOS:')
    for canal, nomes in resultado['canais']['prioritario'].items():
        if nomes:
            print(f'  {canal.upper()}: {", ".join(nomes)}')

    print(f'\n📧 EMAIL CONDICIONAL (sem opt-in):')
    if resultado['canais']['email_condicional']:
        print(f'  {", ".join(resultado["canais"]["email_condicional"])}')
    else:
        print('  (nenhuma)')

    e = resultado['estatisticas']
    print(f'\n📈 ESTATÍSTICAS:')
    print(f'  Com advogado: {e["com_advogado"]}')
    print(f'  Com DJEN: {e["com_domicilio_cnj"]}')
    print(f'  E-mail opt-in: {e["com_email_opt_in"]}')
    print(f'  E-mail sem opt-in: {e["com_email_sem_optin"]}')
    print(f'  E-mail total: {e["com_email_total"]}')
    print(f'  Intimação física necessária: {e["intimacao_fisica_necessaria"]}')

    for polo_nome, dados in resultado['polos'].items():
        print(f'\n  {polo_nome.upper()} ({dados["quantidade"]}):')
        if dados['intimacao_fisica']:
            print(f'    ⚠️ Física: {", ".join(dados["intimacao_fisica"])}')

    # Validações
    assert e['total_partes'] == len(partes)
    assert e['autores'] + e['reus'] == e['total_partes']
    total_prio = sum(len(v) for v in resultado['canais']['prioritario'].values())
    assert total_prio == e['total_partes'], \
        f'Canais prioritários {total_prio} ≠ total {e["total_partes"]}'
    print(f'\n✅ ASSERTIVAS OK')


if __name__ == '__main__':
    testar('Cenário 1 — Dados do ProcessoParser (HTML)', partes_parser, 'ProcessoParser')
    testar('Cenário 2 — Dados do Django Party (model)', partes_model, 'Django Party')

    # --- Validação extra: Pedro Alves (email sem opt-in) ---
    print(f'\n{"="*70}')
    print('  TESTE: PEDRO ALVES — EMAIL SEM OPT-IN')
    print(f'{"="*70}')
    c2 = ParteClassifier(partes_model)
    r2 = c2.classificar()
    pedro = [p for p in r2['partes'] if p['nome'] == 'PEDRO ALVES'][0]
    assert pedro['canal_prioritario'] == 'fisica', \
        f'canal_prioritario={pedro["canal_prioritario"]} (devia ser fisica)'
    assert pedro['email_sem_optin'], 'Devia estar marcado como email_sem_optin'
    assert 'email_condicional' in pedro['canais_disponiveis'], \
        f'canais_disponiveis={pedro["canais_disponiveis"]} (devia incluir email_condicional)'
    assert 'email' not in pedro['canais_disponiveis'], \
        'email (com opt-in) não devia estar em canais_disponiveis'
    print(f'  ✅ Prioritário: {pedro["canal_prioritario"]} (fisica)')
    print(f'  ✅ Disponível: {pedro["canais_disponiveis"]} (inclui email_condicional)')
    print(f'  ✅ email_sem_optin={pedro["email_sem_optin"]}')

    # --- Teste: canais_para_ato() ---
    print(f'\n{"="*70}')
    print('  TESTE: FILTRO POR TIPO DE ATO')
    print(f'{"="*70}')

    # Ato formal (intimação) — NÃO permite email condicional
    ato_intimacao = c2.canais_para_ato('intimacao')
    for p in ato_intimacao['partes']:
        if p['nome'] == 'PEDRO ALVES':
            assert 'email_condicional' not in p['canais_validos'], \
                f'Intimação não devia permitir email_condicional: {p["canais_validos"]}'
            assert p['canais_validos'] == ['fisica'], \
                f'Devia ser só fisica: {p["canais_validos"]}'
            print(f'  ✅ Intimação → PEDRO: {p["canais_validos"]}')
        if p['nome'] == 'ANA BEATRIZ':
            assert 'email' in p['canais_validos'], \
                f'Ana tem opt-in, devia ter email: {p["canais_validos"]}'
            print(f'  ✅ Intimação → ANA: {p["canais_validos"]}')

    # Ato não formal (certificar) — PERMITE email condicional
    ato_certificar = c2.canais_para_ato('certificar')
    for p in ato_certificar['partes']:
        if p['nome'] == 'PEDRO ALVES':
            assert 'email_condicional' in p['canais_validos'], \
                f'Certificar devia permitir email_condicional: {p["canais_validos"]}'
            print(f'  ✅ Certificar → PEDRO: {p["canais_validos"]}')

    print(f'  ✅ Filtro por tipo de ato OK')
    print(f'\n✅ TODOS OS TESTES PASSARAM')
