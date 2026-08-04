"""Teste real da intimação pelos correios (AR digital) sem assinar.

Processo: 0001708-74.2026.8.05.0191 (interno 41020262640080) — criminal.
Chama executar_com_intimacao_ar(..., assinar_ar=False): expede o AR mas
para na página ExpedirIntimacao aberta, sem assinar.
"""
import os, sys, re
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()
from accounts.models import User
from projudi.movimentacao_service import MovimentacaoService

def main():
    u = User.objects.filter(is_active=True).first()
    if not u:
        print('SEM USUÁRIO'); return
    obs = ('Intimem-se as partes pelos Correios (AR digital) - '
           'teste de expedição sem assinatura')
    svc = MovimentacaoService(u)
    ok = svc.executar_com_intimacao_ar(
        processo_numero='0001708-74.2026.8.05.0191',
        observacao=obs,
        codigo_mov='581',
        descricao_mov='Intimação',
        proc_projudi='41020262640080',
        prazo_intimacao='3',
        motivo_intimacao='3',
        tipo_intimacao='geral',
        natureza_override='criminal',
        assinar_ar=False,
    )
    print(f'\n===== RESULTADO FINAL: {"OK" if ok else "FALHOU"} =====')
    return 0 if ok else 1

if __name__ == '__main__':
    sys.exit(main())