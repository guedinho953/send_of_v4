"""Teste de integração: pipeline completo simulado.
Gera dados que apareceriam no dashboard de cumprimentos."""
import sys, os, json
sys.path.insert(0, '/home/ivan/PythonProjects/send_of_v4')
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
import django; django.setup()

from django.contrib.auth import get_user_model
from projudi.models import CumprimentoRecord, CumprimentoLog

User = get_user_model()
user = User.objects.filter(is_active=True).first()
if not user:
    print('⚠️ Nenhum usuário ativo — criando...')
    user = User.objects.create_user('teste@teste.com', 'teste123', is_active=True)

# Limpa dados anteriores
CumprimentoRecord.objects.filter(user=user).delete()

# ── Simula pipeline ──
from projudi.parte_classifier import ParteClassifier

partes_raw = [
    {
        'nome': 'MARIA DAS DORES SILVA',
        'nome_normalizado': 'maria das dores silva',
        'tipo': 'EXEQUENTE',
        'recebe_intimacao_email': True,
        'domicilio_cnj': False,
        'tem_advogado': True,
        'email': 'maria@email.com',
        'logradouro': 'Rua A', 'numero': '100', 'bairro': 'Centro',
        'cidade': 'PAULO AFONSO', 'uf': 'BA',
    },
    {
        'nome': 'JOSE CARLOS PEREIRA',
        'nome_normalizado': 'jose carlos pereira',
        'tipo': 'EXECUTADO',
        'recebe_intimacao_email': False,
        'domicilio_cnj': True,
        'tem_advogado': False,
        'email': '',
        'logradouro': 'Av B', 'numero': '200', 'bairro': 'Centro',
        'cidade': 'PAULO AFONSO', 'uf': 'BA',
    },
    {
        'nome': 'EMPRESA BAIANA DE AGUAS LTDA',
        'nome_normalizado': 'empresa baiana de aguas ltda',
        'tipo': 'EXECUTADO',
        'recebe_intimacao_email': False,
        'domicilio_cnj': False,
        'tem_advogado': False,
        'email': '',
        'logradouro': 'Rua Industrial', 'numero': '500',
        'bairro': 'Distrito Industrial',
        'cidade': 'SALVADOR', 'uf': 'BA',
    },
]

classifier = ParteClassifier(partes_raw)
r = classifier.classificar()

print('=' * 70)
print('  PIPELINE COMPLETO — DADOS PARA O DASHBOARD')
print('=' * 70)

# Cria registros simulando o que o CumprimentoService.importar_cumprimento() faria
cenarios = [
    {
        'fluxo': 'eletronico',
        'parte_nome': 'JOSE CARLOS PEREIRA',
        'fluxo_justificativa': 'Parte possui Domicílio Judicial Eletrônico CNJ — intimação eletrônica via DJEN.',
        'status': 'cumprido',
    },
    {
        'fluxo': 'advogado',
        'parte_nome': 'MARIA DAS DORES SILVA',
        'fluxo_justificativa': 'Parte possui advogado constituído — intimação ao advogado via DJEN.',
        'status': 'pendente',
    },
    {
        'fluxo': 'ar',
        'parte_nome': 'EMPRESA BAIANA DE AGUAS LTDA',
        'fluxo_justificativa': 'Endereço em SALVADOR/BA — Aviso de Recebimento (AR) pelos Correios.',
        'status': 'pendente',
        'act_verb': 'intime-se',
        'endereco': {'cidade': 'SALVADOR', 'uf': 'BA', 'bairro': 'Distrito Industrial', 'valido': True},
    },
    {
        'fluxo': 'mandado',
        'parte_nome': 'PEDRO ALVES',
        'fluxo_justificativa': 'Endereço em PAULO AFONSO/BA — mandado por oficial de justiça local.',
        'status': 'falha',
        'act_verb': 'cite-se',
    },
    {
        'fluxo': 'edital',
        'parte_nome': 'FULANO DESCONHECIDO',
        'fluxo_justificativa': 'Endereço não disponível — necessária intimação por edital.',
        'status': 'pendente',
    },
    {
        'fluxo': 'movimentacao_simples',
        'parte_nome': '',
        'fluxo_justificativa': 'Ato "publique-se" não possui destinatário — apenas movimentação interna.',
        'status': 'cumprido',
        'act_verb': 'publique-se',
    },
]

print(f'\n📝 Criando {len(cenarios)} cumprimentos de exemplo...')
for c in cenarios:
    record = CumprimentoRecord.objects.create(
        processo='0003099-35.2024.8.05.0191',
        numero_processo_cnj='0003099-35.2024.8.05.0191',
        fluxo=c['fluxo'],
        fluxo_justificativa=c['fluxo_justificativa'],
        parte_nome=c['parte_nome'],
        parte_papel='PROMOVIDO' if c['parte_nome'] and 'MARIA' not in c['parte_nome'] else 'PROMOVENTE',
        act_verb=c.get('act_verb', ''),
        status=c['status'],
        user=user,
        endereco_analisado=c.get('endereco', {}),
        snippet='Trecho simulado da decisão judicial para fins de demonstração.',
    )
    # Log
    CumprimentoLog.objects.create(
        cumprimento=record,
        tipo='decisao',
        mensagem=f'Fluxo definido: {c["fluxo"]}. {c["fluxo_justificativa"][:80]}...',
    )
    if c['status'] == 'cumprido':
        CumprimentoLog.objects.create(
            cumprimento=record, tipo='execucao',
            mensagem=f'Cumprimento executado com sucesso via fluxo {c["fluxo"]}.')
    elif c['status'] == 'falha':
        CumprimentoLog.objects.create(
            cumprimento=record, tipo='erro',
            mensagem='Endereço não localizado pelo oficial de justiça.')
    icon = {
        'eletronico': '💻', 'advogado': '👨‍⚖️', 'ar': '📮',
        'mandado': '🔖', 'edital': '📰', 'movimentacao_simples': '📄',
    }.get(c['fluxo'], '❓')
    status_icon = {'pendente': '⏳', 'cumprido': '✅', 'falha': '❌'}
    print(f'  {status_icon.get(c["status"], "❓")} {icon} #{record.id} {c["fluxo"]:25s} {c["parte_nome"] or "(s/dest)":35s} {c["status"]}')

# ── Estatísticas (como no dashboard) ──
qs = CumprimentoRecord.objects.filter(user=user)
print(f'\n📊 ESTATÍSTICAS DO DASHBOARD:')
print(f'  Total:       {qs.count()}')
print(f'  Pendentes:   {qs.filter(status="pendente").count()}')
print(f'  Processando: {qs.filter(status="processando").count()}')
print(f'  Cumpridos:   {qs.filter(status="cumprido").count()}')
print(f'  Falhas:      {qs.filter(status="falha").count()}')
print(f'  Dispensados: {qs.filter(status="dispensado").count()}')
print(f'\n🔀 POR FLUXO:')
for fluxo, label in CumprimentoRecord.FLUXO_CHOICES:
    count = qs.filter(fluxo=fluxo).count()
    if count:
        print(f'  {fluxo:25s} {count}')

print(f'\n📋 ÚLTIMOS REGISTROS:')
for c in qs.order_by('-created_at')[:10]:
    print(f'  #{c.pk:3d} {c.fluxo:25s} {c.parte_nome or "(s/dest)":35s} {c.status:15s} {c.created_at.strftime("%d/%m/%y %H:%M")}')

print(f'\n✅ Pipeline completo simulado — {qs.count()} registros no banco')
print(f'   Acesse o dashboard em: http://localhost:8000/projudi/cumprimentos/dashboard/')
