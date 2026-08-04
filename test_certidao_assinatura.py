"""Teste ISOLADO do passo certidao_criminal (sem buscar_processo).

Roda geração + inserção + ASSINATURA AUTOMÁTICA (senha salva no campo
User.projudi_password) da certidão criminal, com o navegador Playwright
visível (WSLg) pra acompanhar ao vivo.

Uso:
  python test_certidao_assinatura.py [CNJ]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'

# Importar expedir_rapido já faz django.setup() e puxa as helpers.
from expedir_rapido import (
    session_projudi, _extrair_dados_ata, _gerar_html_certidao,
)
from projudi.movimentacao_service import MovimentacaoService
from types import SimpleNamespace
from datetime import date

PROC_NUM = sys.argv[1] if len(sys.argv) > 1 else '0001708-74.2026.8.05.0191'

print(f'=== TESTE assinatura automática certidão — {PROC_NUM} ===\n')

user, session, cookies_dict = session_projudi()

# 1. Processo no banco → pega o link DadosProcesso (proveniente do Projudi).
#    O executar_requests extrai o número interno da URL e abre
#    MovimentarProcesso?numeroProcesso=X no navegador (passo 1 do fluxo).
from processes.models import Process
proc = Process.objects.filter(number__icontains=PROC_NUM).first()
if not proc or not proc.projudi_url:
    print(f'❌ Processo {PROC_NUM} não encontrado no banco (ou sem projudi_url).')
    sys.exit(1)
link_processo = proc.projudi_url
print(f'📋 Processo: {proc.number}')
print(f'📋 Link: {link_processo}\n')

# 2. Extrai autores/vítima da ata
proc_ctx = SimpleNamespace(number=PROC_NUM, projudi_url=link_processo)
dados_ata = _extrair_dados_ata(session, proc_ctx, {'link_processo': link_processo})
autores = [n.strip() for n in (dados_ata.get('autores_do_fato') or []) if n.strip()]
vitima = dados_ata.get('vitima') or '(nome da vítima)'
if not autores:
    print('⚠️ Nenhum autor do fato encontrado — abortando.')
    sys.exit(1)
print(f'👤 Autor(es): {autores}')
print(f'👤 Vítima: {vitima}\n')

# 3. Gera HTML e insere via Mov581 + DigitarTexto + ASSINATURA (senha do Projudi)
data = date.today().strftime('%d/%m/%Y')
servidor = getattr(user, 'full_name', 'Servidor')
texto = _gerar_html_certidao(PROC_NUM, autores, vitima, servidor, data)
print(f'✅ Certidão gerada ({len(autores)} autor(es)). Abrindo navegador e inserindo...\n')
print('⚠️ FIQUE DE OLHO NO NAVEGADOR — assinatura deve acontecer sozinha (senha salva).\n')

service = MovimentacaoService(user)
record = service.importar(
    processo_numero=PROC_NUM,
    act_verb='certidao_criminal',
    observacao='Certidão Criminal - Art. 76 Lei 9.099/95 (teste assinatura automática)',
    categoria='outro',
    processo_cnj=PROC_NUM,
    url_processo=link_processo,
    codigo_movimentacao='581',
    descricao_movimentacao='Certidão',
    localizador='',
    tipo_localizador='',
)
ok = service.executar_requests(record, tipo_documento='Certidão', certidao_html=texto)
print('\n✅ Certidão concluída (assinatura automática).' if ok
      else '\n⚠️ Falha na certidão — ver log acima.')
sys.exit(0 if ok else 2)