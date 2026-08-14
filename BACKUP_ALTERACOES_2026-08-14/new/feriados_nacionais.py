"""Feriados nacionais (fixos e móveis) e recesso forense.

Centraliza as datas que se repetem todo ano para poderem ser semeadas
no banco (modelos Feriado / SuspensaoPrazo) UMA vez por ano, em vez de
cadastrar manualmente.

Estratégia de cadastro (o que é automático x o que é manual):

  AUTOMÁTICO (seed via `manage.py popular_feriados`):
    - Feriados nacionais FIXOS (01/01, 21/04, 01/05, 07/09, 12/10,
      02/11, 15/11, 20/11) — mesma data todo ano.
    - Feriados nacionais MÓVEIS (Carnaval, Sexta-Feira Santa, Corpus
      Christi) — derivados da Páscoa por regra matemática (computus).
    - Recesso forense (20/12 a 22/01, cruzando o ano) — semeado como
      SuspensaoPrazo (tipo='recesso_local') por temporada.

  MANUAL (admin, sem regra):
    - Feriados estaduais (BA) / municipais / comarca / vara.
    - Suspensões pontuais: ponto facultativo local, greve, semana de
      baixa, recesso local, etc.

Uso:
    from projudi.feriados_nacionais import popular_feriados_nacionais
    popular_feriados_nacionais(tenant, anos=[2025, 2026, 2027])
"""

from datetime import date, timedelta
from typing import Dict, List, Tuple

# ── Feriados nacionais FIXOS (mês, dia, nome) ──
FERIADOS_NACIONAIS_FIXOS: List[Tuple[int, int, str]] = [
    (1, 1, 'Confraternização Universal'),
    (4, 21, 'Tiradentes'),
    (5, 1, 'Dia do Trabalho'),
    (9, 7, 'Independência do Brasil'),
    (10, 12, 'Nossa Senhora Aparecida'),
    (11, 2, 'Finados'),
    (11, 15, 'Proclamação da República'),
    (11, 20, 'Dia da Consciência Negra'),
]

# ── Recesso forense padrão (cruza o ano) ──
RECESSO_INICIO: Tuple[int, int] = (12, 20)
RECESSO_FIM: Tuple[int, int] = (1, 22)
NOME_RECESSO = 'Recesso Forense'


def pascoa(ano: int) -> date:
    """Data da Páscoa (algoritmo de Meeus/Jones/Butcher).

    Validado para todo o período gregoriano (1900–9999). Usado para
    derivar os feriados móveis nacionais.
    """
    a = ano % 19
    b = ano // 100
    c = ano % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


def feriados_moveis(ano: int) -> List[Tuple[date, str]]:
    """Feriados móveis nacionais derivados da Páscoa.

    Retorna [(data, nome), ...]: Carnaval, Sexta-Feira Santa, Corpus
    Christi.
    """
    p = pascoa(ano)
    carnaval = p - timedelta(days=47)        # 47 dias antes da Páscoa
    sexta_santa = p - timedelta(days=2)      # 2 dias antes da Páscoa
    corpus_christi = p + timedelta(days=60)  # 60 dias depois da Páscoa
    return [
        (carnaval, 'Carnaval'),
        (sexta_santa, 'Sexta-Feira Santa'),
        (corpus_christi, 'Corpus Christi'),
    ]


def recesso_forense(ano: int) -> Tuple[date, date]:
    """Período do recesso forense que INICIA em dez/ano e termina em jan/ano+1.

    Ex: recesso_forense(2025) -> (20/12/2025, 22/01/2026).
    """
    mi, di = RECESSO_INICIO
    mf, df = RECESSO_FIM
    return (date(ano, mi, di), date(ano + 1, mf, df))


def popular_feriados_nacionais(
    tenant,
    anos: List[int],
    incluir_recesso: bool = True,
) -> Dict[str, int]:
    """Cria/atualiza Feriado (fixos + móveis) e SuspensaoPrazo (recesso)
    no banco para o tenant, de forma idempotente (update_or_create).

    Pode ser chamado todo ano sem duplicar: feriados existentes do mesmo
    tenant/nome/ano são atualizados, não recriados.

    Args:
        tenant: accounts.Tenant (obrigatório — isola o cadastro).
        anos: lista de anos a semear.
        incluir_recesso: semeia também o recesso forense como
            SuspensaoPrazo (tipo='recesso_local').

    Returns:
        dict com contadores: {'fixos', 'moveis', 'recesso'}.
    """
    from .models import Feriado, SuspensaoPrazo

    stats = {'fixos': 0, 'moveis': 0, 'recesso': 0}

    # ── Fixos (tipo='fixo', mes/dia) ──
    for mes, dia, nome in FERIADOS_NACIONAIS_FIXOS:
        Feriado.objects.update_or_create(
            tenant=tenant, tipo='fixo', nome=nome, mes=mes, dia=dia,
            defaults={
                'escopo': 'nacional',
                'is_active': True,
                'observacao': 'Feriado nacional fixo (seed automático).',
            },
        )
        stats['fixos'] += 1

    # ── Móveis (tipo='movel', data) ──
    for ano in anos:
        for data, nome in feriados_moveis(ano):
            Feriado.objects.update_or_create(
                tenant=tenant, tipo='movel', nome=nome, data=data,
                defaults={
                    'escopo': 'nacional',
                    'is_active': True,
                    'observacao': f'Feriado móvel nacional {ano} (seed automático).',
                },
            )
            stats['moveis'] += 1

    # ── Recesso forense (SuspensaoPrazo, tipo='recesso_local') ──
    if incluir_recesso:
        for ano in anos:
            ini, fim = recesso_forense(ano)
            SuspensaoPrazo.objects.update_or_create(
                tenant=tenant, nome=NOME_RECESSO,
                data_inicio=ini, data_fim=fim,
                defaults={
                    'tipo': 'recesso_local',
                    'escopo': 'nacional',
                    'is_active': True,
                    'observacao': f'Recesso forense {ano}/{ano + 1} (seed automático).',
                },
            )
            stats['recesso'] += 1

    return stats
