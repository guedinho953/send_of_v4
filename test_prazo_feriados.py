"""Teste real de integração do PrazoService com cadastro de feriados e
suspensões no banco (modelos Feriado / SuspensaoPrazo).

Cenário:
  - Feriado fixo nacional 15/11 (Proclamação da República).
  - Feriado móvel 2026-02-17 (exemplo Carnaval).
  - Suspensão de prazo: ponto facultativo 2026-02-16 a 2026-02-18.
  - Intimação (DJEN) em 09/02/2026 (segunda). 15 dias úteis.
  - Intimação (advogado) mesma data → regra padrão (dia recebido não conta).
  - Prazo corrido de 10 dias cruzando o feriado/suspensão.

Regras esperadas:
  - DJEN (art. 5º §3º): 1º dia da intimação + 1º dia útil após NÃO contam.
  - Advogado (art. 219 §1º): dia do recebimento não conta; conta do dia seguinte.
  - Suspensão de prazo suspende SEMPRE (úteis e corridos): paralisação.
  - Feriado em prazo CORRIDO CONTA (prazo contínuo).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
import django
django.setup()

from datetime import date, timedelta
from accounts.models import Tenant
from projudi.models import Feriado, SuspensaoPrazo
from projudi.prazo_service import PrazoService

# Tenant de teste (cria se não existir)
tenant, _ = Tenant.objects.get_or_create(
    cnpj='00.000.000/0001-99',
    defaults={'name': 'Tenant Teste Prazo', 'role': 'cartorio'},
)

# Limpa cadastros anteriores deste tenant p/ idempotência
Feriado.objects.filter(tenant=tenant).delete()
SuspensaoPrazo.objects.filter(tenant=tenant).delete()

# 1) Feriado fixo nacional 15/11
Feriado.objects.create(tenant=tenant, nome='Proclamação da República',
                       tipo='fixo', escopo='nacional', mes=11, dia=15)
# 2) Feriado móvel 2026-02-13 (sex, FORA da suspensão) — p/ testar que
#    em prazo CORRIDO o feriado CONTA (prazo contínuo).
Feriado.objects.create(tenant=tenant, nome='Feriado Móvel Exemplo',
                       tipo='movel', escopo='nacional', data=date(2026, 2, 13))
# 3) Suspensão de prazo: ponto facultativo 16/02 a 18/02/2026
SuspensaoPrazo.objects.create(tenant=tenant, nome='Ponto Facultativo Exemplo',
                              tipo='ponto_facultativo', escopo='nacional',
                              data_inicio=date(2026, 2, 16),
                              data_fim=date(2026, 2, 18))

svc = PrazoService.from_db(tenant=tenant)


def mostra(titulo, res):
    print(f'\n=== {titulo} ===')
    print(res.relatorio())


d_ini = date(2026, 2, 9)
# DJEN 15d úteis
r_djen = svc.contar_prazo(d_ini, 15, modo='uteis', djen=True)
mostra('DJEN 15d úteis (início 09/02/2026)', r_djen)

# Advogado 15d úteis
r_adv = svc.contar_prazo(d_ini, 15, modo='uteis', djen=False)
mostra('ADVOGADO 15d úteis (início 09/02/2026)', r_adv)

# Corrido 10d a partir de 12/02/2026 (cruza suspensão 16-18/02 e carnaval 17/02)
d2 = date(2026, 2, 12)
r_cor = svc.contar_prazo(d2, 10, modo='corridos')
mostra('CORRIDO 10d (início 12/02/2026 — cruza suspensão 16-18/02)', r_cor)

# Decadencial 10d a partir de 12/02/2026 (cruza fds 14-15/02, suspensão
# 16-18/02, feriado móvel 13/02) — TUDO deve contar.
r_dec = svc.contar_decadencial(d2, 10)
mostra('DECADENCIAL 10d (início 12/02/2026)', r_dec)

print('\n--- ASSERTS ---')
assert len(r_djen.dias_contados) == 15, f'DJEN contados={len(r_djen.dias_contados)}'
assert date(2026, 2, 9) in r_djen.dias_excluidos, 'DJEN deve excluir dia da intimação'
assert date(2026, 2, 10) in r_djen.dias_excluidos, 'DJEN deve excluir 1º útil após'
# Feriado 15/11 (fixo, ano corrente) não conta
assert date(2026, 11, 15) not in r_djen.dias_contados, 'Feriado 15/11 não conta (DJEN)'
# Suspensão 16-18/02 NÃO conta (nem úteis, nem corridos)
for d in (date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18)):
    assert d not in r_djen.dias_contados, f'Suspensão {d} não conta (DJEN)'
    assert d not in r_cor.dias_contados, f'Suspensão {d} não conta (corrido)'
# Feriado móvel 13/02 NÃO conta em úteis, mas CONTA em corrido
assert date(2026, 2, 13) not in r_djen.dias_contados, 'Feriado móvel 13/02 não conta (DJEN)'
assert date(2026, 2, 13) in r_cor.dias_contados, 'Feriado móvel 13/02 CONTA em corrido'
# ADVOGADO: dia da intimação (09/02) excluído, 1º dia contado = 10/02
assert date(2026, 2, 9) in r_adv.dias_excluidos, 'Advogado exclui dia da intimação'
assert r_adv.dias_contados[0] == date(2026, 2, 10), 'Advogado conta a partir de 10/02'
assert r_adv.dias_contados[0] != date(2026, 2, 9), 'Advogado NÃO conta dia do recebimento'
# Corrido: feriado/carnaval CONTAM, mas suspensão NÃO → prazo estica
# Corrido: feriado CONTAM, mas suspensão NÃO → prazo estica
assert len(r_cor.dias_contados) == 10, f'Corrido contados={len(r_cor.dias_contados)}'
assert r_cor.ultimo_dia >= date(2026, 2, 22), f'Corrido esticou p/ {r_cor.ultimo_dia}'

# Decadencial: TODOS os dias contam (nem fds/feriado/suspensão param)
assert len(r_dec.dias_contados) == 10, f'Decadencial contados={len(r_dec.dias_contados)}'
assert date(2026, 2, 14) in r_dec.dias_contados, 'Decadencial CONTA fim de semana (14/02 sáb)'
assert date(2026, 2, 15) in r_dec.dias_contados, 'Decadencial CONTA domingo (15/02)'
assert date(2026, 2, 16) in r_dec.dias_contados, 'Decadencial CONTA suspensão (16/02)'
assert date(2026, 2, 17) in r_dec.dias_contados, 'Decadencial CONTA feriado móvel (17/02)'
assert date(2026, 2, 18) in r_dec.dias_contados, 'Decadencial CONTA suspensão (18/02)'
assert r_dec.dias_excluidos == [date(2026, 2, 12)], 'Decadencial só exclui o dia da intimação (início)'
assert r_dec.ultimo_dia == date(2026, 2, 22), f'Decadencial último={r_dec.ultimo_dia}'

# ── Seed automático (feriados nacionais + recesso no banco) ──
from projudi.feriados_nacionais import popular_feriados_nacionais, feriados_moveis
# Semeia 2025-2027 para o tenant de teste
pop_stats = popular_feriados_nacionais(tenant, anos=[2025, 2026, 2027])
assert pop_stats['fixos'] == 8, f'fixos semeados={pop_stats["fixos"]}'
assert pop_stats['moveis'] == 9, f'moveis semeados={pop_stats["moveis"]}'
assert pop_stats['recesso'] == 3, f'recesso semeados={pop_stats["recesso"]}'

# from_db deve ler feriado MÓVEL (Carnaval 2026-02-17) e o RECESSO do banco
svc2 = PrazoService.from_db(tenant=tenant)
# Carnaval 17/02/2026 é feriado móvel → não conta em prazo útil.
# 1 dia útil a partir de 10/02 (terça): 10/02 é o dia da intimação (não
# conta); 1º dia contado = 11/02 (11/02 não é feriado).
r_car = svc2.contar_prazo(date(2026, 2, 10), 1, modo='uteis')
assert date(2026, 2, 11) in r_car.dias_contados, '11/02 conta (quarta, não feriado)'
assert date(2026, 2, 17) not in r_car.dias_contados, 'Carnaval (móvel do banco) não conta'
# Recesso 20/12/2026-22/01/2027 deve suspender (lido do banco, não hardcoded)
r_rec = svc2.contar_prazo(date(2026, 12, 21), 1, modo='uteis')
assert date(2026, 12, 21) not in r_rec.dias_contados, 'Recesso (banco) suspende 21/12'
assert date(2027, 1, 22) not in r_rec.dias_contados, 'Recesso (banco) suspende 22/01'
assert date(2027, 1, 25) in r_rec.dias_contados, 'Prazo retoma após recesso (25/01/2027)'

print('DJEN último dia:', r_djen.ultimo_dia, '| decurso:', r_djen.data_decurso)
print('COR  último dia:', r_cor.ultimo_dia, '| decurso:', r_cor.data_decurso)

# ── Observação / Certidão controladas por JSON (extração do despacho) ──
from projudi.cumprimento_service import CumprimentoService
from projudi.models import CumprimentoRecord
from accounts.models import User

# Usuário do tenant de teste p/ criar o cumprimento
user_test = User.objects.filter(tenant=tenant).first()
if not user_test:
    user_test = User.objects.create_user(
        email='teste_prazo@example.com', password='x',
        first_name='Teste', last_name='Prazo', tenant=tenant)
svc_c = CumprimentoService(user_test)

# Cria um cumprimento de teste com despacho contendo data + prazo
rec = CumprimentoRecord.objects.create(
    user=user_test, processo='12345', numero_processo_cnj='0001234-56.2026.8.05.0001',
    fluxo='eletronico', parte_nome='JOÃO DA SILVA',
    snippet='Intimo a parte em 15 dias, sendo a intimação eletrônica '
            'realizada em 09/02/2026, nos termos do art. 5º CPC.',
)
out = svc_c.gerar_observacao_prazo(rec)
assert out['status'] == 'ok', f'gerar_observacao_prazo falhou: {out}'
assert rec.prazo_info['ultimo_dia'] == '2026-03-09', f"último={rec.prazo_info['ultimo_dia']}"
assert rec.prazo_info['djen'] is True, 'DJEN deve estar ativo p/ fluxo eletronico'
assert 'Intimação eletrônica (DJEN)' in rec.observacao_prazo, rec.observacao_prazo
print('\nOBSERVAÇÃO GERADA:')
print(' ', rec.observacao_prazo)

# JSON que vai ser enviado (observação + certidão)
# Sem RAG vinculado → flags do RAG default False → só observação vazia
json_envio = svc_c.montar_json_envio(rec)
assert json_envio['observacao'] == '', 'sem RAG, observacao_prazo não vai p/ envio'
assert json_envio['certidao'] is False, 'sem RAG, não é certidão'
assert json_envio['texto_certidao'] == '', 'certidão só se certidao=true'
print('\nJSON ENVIO (sem RAG → sem observação/certidão):')
print(' observacao:', repr(json_envio['observacao']))

# Agora COM RAG configurando observacao_prazo=true
from processes.models import RAGExample, Process
proc_rag = Process.objects.first()
rag = RAGExample.objects.create(
    process=proc_rag, tenant=tenant,
    despacho_ato='Intime a parte na forma da lei.',
    despacho_observacao='Intime a parte na forma da lei.',
    sequencia_cumprimento=[
        {'tipo': 'movimentacao', 'observacao_prazo': True,
         'expede_certidao_prazo': False},
    ],
)
rec.rag_example = rag
rec.save(update_fields=['rag_example'])
json_obs = svc_c.montar_json_envio(rec)
assert json_obs['observacao_prazo'] is True, 'RAG observacao_prazo=true'
assert json_obs['observacao'] == rec.observacao_prazo, 'observação deve ir p/ envio'
print('\nJSON ENVIO (RAG observacao_prazo=true):')
print(' observacao:', json_obs['observacao'][:90])

# Caso CERTIDÃO: RAG configura expede_certidao_prazo=true
rag_cert = RAGExample.objects.create(
    process=proc_rag, tenant=tenant,
    despacho_ato='Certidão',
    despacho_observacao='Certifique que a parte foi intimada.',
    sequencia_cumprimento=[
        {'tipo': 'movimentacao', 'observacao_prazo': False,
         'expede_certidao_prazo': True},
    ],
)
rec_cert = CumprimentoRecord.objects.create(
    user=user_test, processo='99999', numero_processo_cnj='9999999-99.2026.8.05.0001',
    fluxo='movimentacao_simples', parte_nome='JOÃO DA SILVA',
    snippet='Certifique que a parte foi intimada em 09/02/2026, prazo de 15 dias.',
    rag_example=rag_cert)
out_c = svc_c.gerar_observacao_prazo(rec_cert)
assert out_c['expede_certidao_prazo'] is True, 'RAG expede_certidao_prazo=true'
json_cert = svc_c.montar_json_envio(rec_cert)
assert json_cert['certidao'] is True, 'certidão=true'
assert 'CERTIDÃO DE PRAZO' in json_cert['texto_certidao'], 'certidão deve ter HTML'
assert json_cert['observacao'] == '', 'certidão não vai p/ observação'
print('\nCERTIDÃO HTML (trecho):')
print(' ', json_cert['texto_certidao'][:200])
rec_cert.delete()
rag.delete(); rag_cert.delete()

# Parser: extração de prazo corrido sem DJEN
extr2 = CumprimentoService.extrair_prazo_do_despacho(
    'Intimo o réu no prazo de 10 (dez) dias corridos, publicado em 01/03/2026.')
assert extr2['data_inicio'] == date(2026, 3, 1), extr2
assert extr2['prazo_dias'] == 10, extr2
assert extr2['modo'] == 'corridos', extr2

# Limpa o record de teste
rec.delete()

print('\nTODOS OS ASSERTS PASSARAM')
