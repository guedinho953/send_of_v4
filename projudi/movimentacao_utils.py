"""Utilidades para as movimentações do Projudi."""
from datetime import date, datetime


def parse_data_mov(valor):
    """Converte dd/mm/aaaa em date; retorna None se inválido."""
    try:
        return datetime.strptime((valor or '').strip(), '%d/%m/%Y').date()
    except (ValueError, TypeError):
        return None


def filtrar_hoje(movs):
    """Mantém apenas as movimentações cuja data é hoje.

    Itens sem data são preservados para não perder movimento por falha de
    leitura da listagem.
    """
    hoje = date.today().strftime('%d/%m/%Y')
    return [
        mov for mov in movs
        if not mov.get('data') or mov.get('data') == hoje
    ]
