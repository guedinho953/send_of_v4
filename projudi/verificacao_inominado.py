"""Detecção do recurso inominado e da intimação/DJEN no processo."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Optional


def _normalizar(texto) -> str:
    texto = unicodedata.normalize('NFKD', str(texto or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', texto).strip().upper()


def _texto_mov(mov) -> str:
    return ' '.join(
        str(mov.get(k) or '') for k in
        ('ato', 'observacao', 'ato_normalizado', 'descricao')
    )


def evento_mov(mov) -> int:
    try:
        return int(str(mov.get('evento')).strip())
    except (TypeError, ValueError):
        return 0


def data_mov(mov) -> Optional[date]:
    valor = mov.get('data_obj')
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        for fmt in ('%Y-%m-%d', '%d/%m/%y', '%d/%m/%Y'):
            try:
                return datetime.strptime(valor[:10], fmt).date()
            except ValueError:
                continue
    texto = str(mov.get('data_texto') or '')
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', texto)
    if m:
        dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if ano < 100:
            ano += 2000
        try:
            return date(ano, mes, dia)
        except ValueError:
            return None
    return None


def data_djen(mov) -> Optional[date]:
    valor = mov.get('data_djen')
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        return data_mov({'data_obj': valor})
    return None


def _forca_recurso(mov) -> int:
    """Classifica o quanto o movimento representa a interposição do recurso.

    3 = ato explícito "Juntada de Petição de Recurso Inominado";
    2 = ato que já cita "Recurso Inominado";
    1 = outro ato, mas o texto menciona o recurso;
    0 = juntada genérica/ato meramente referencial (não é o recurso).
    """
    ato = _normalizar(mov.get('ato') or mov.get('ato_normalizado') or '')
    if 'JUNTADA DE PETICAO DE RECURSO INOMINADO' in ato:
        return 3
    if 'RECURSO INOMINADO' in ato:
        return 2
    if any(k in ato for k in (
            'JUNTADA DE CUMPRIMENTO GENERICO',
            'JUNTADA DE OUTROS TIPOS',
            'JUNTADA DE INTIMACAO',
            'JUNTADA DE CERTIDAO',
            'JUNTADA DE DESPACHO',
            'JUNTADA DE DECISAO',
            'DECORRIDO PRAZO',
            'DISPONIBILIZACAO',
            'INTIMACAO EXPEDIDA')):
        return 0
    return 1


def achar_recurso_inominado(movs, evento=None):
    """Localiza o evento de interposição do recurso inominado.

    No modo automático, dá preferência ao ato explícito de juntada do
    recurso. Movimentos genéricos (ex.: "Juntada de Cumprimento Genérico")
    que apenas citam "recurso inominado" no texto não podem vencer o evento
    real.

    Se ``evento`` for informado, a escolha é explícita: aceita também uma
    juntada genérica que mencione o recurso, pois o usuário pode querer
    referenciar o evento da juntada.
    """
    candidatos = []
    escolha_explicita = bool(evento)
    for mov in movs:
        ev = evento_mov(mov)
        if evento and ev != int(evento):
            continue
        texto = _normalizar(_texto_mov(mov))
        if 'RECURSO INOMINADO' not in texto:
            continue
        # Não confundir com contrarrazões, julgamento ou decisão do recurso.
        if any(k in texto for k in (
                'CONTRARRAZOES', 'CONTRARRAZÕES', 'JULGAMENTO',
                'DECISAO', 'DECISÃO', 'NAO CONHECIDO', 'NAO PROVIDO',
                'DESPROVIDO', 'PROVIDO')):
            continue
        forca = _forca_recurso(mov)
        if not escolha_explicita and forca <= 0:
            continue
        # Escolha explícita: aceita a juntada genérica, mas mantém o peso
        # do ato para eventual desempate.
        candidatos.append((forca, ev, mov))

    if not candidatos:
        return None

    # Primeiro o ato mais específico; depois o evento mais recente.
    return max(candidatos, key=lambda item: (item[0], item[1]))[2]


def _normalizar_parte(texto) -> str:
    """Normaliza nome de parte para comparação, ignorando pontuação."""
    texto = _normalizar(texto)
    texto = re.sub(r'[^A-Z0-9 ]+', ' ', texto)
    return re.sub(r'\s+', ' ', texto).strip()


def mov_menciona_parte(mov, parte) -> bool:
    """Indica se o movimento cita o nome da parte/recorrente."""
    if not parte:
        return False
    alvo = _normalizar_parte(parte)
    return bool(alvo) and alvo in _normalizar_parte(_texto_mov(mov))


def achar_intimacao_djen(movs, evento_recurso=None, data_limite=None,
                         parte=None):
    """Localiza a disponibilização no DJEN anterior ao recurso.

    Pode filtrar pelo evento do recurso ou pela data-limite (data do
    protocolo, quando a petição ainda não virou evento no processo).
    Quando ``parte`` é informada (o recorrente), dá preferência às
    comunicações que citam nominalmente essa parte.

    Retorna (mov, data_disponibilizacao, origem) ou (None, None, None).
    Prioriza o campo data_djen; se não houver, usa o movimento de
    disponibilização/intimação como fallback.
    """
    candidatos_djen = []
    candidatos_fallback = []

    for mov in movs:
        ev = evento_mov(mov)
        if evento_recurso is not None and ev >= int(evento_recurso):
            continue

        texto = _normalizar(_texto_mov(mov))
        d_djen = data_djen(mov)
        d_mov = data_mov(mov)
        # Para o limite, vale a data efetiva da comunicação: se houver
        # DJEN, é ela que conta (o movimento pode ter data anterior).
        d_efetiva = d_djen or d_mov
        if data_limite and d_efetiva and d_efetiva > data_limite:
            continue

        if d_djen:
            candidatos_djen.append((ev, mov, d_djen, 'DJEN'))
            continue

        if d_mov and 'DISPONIBILIZA' in texto:
            candidatos_fallback.append(
                (ev, mov, d_mov, 'disponibilização'))
            continue

        if d_mov and any(k in texto for k in (
                'INTIMA', 'PUBLICA', 'CIENCIA', 'SENTENCA',
                'JULGADA', 'DECISAO', 'DESPACHO')):
            candidatos_fallback.append((ev, mov, d_mov, 'movimento'))

    if candidatos_djen:
        com_parte = [
            c for c in candidatos_djen if mov_menciona_parte(c[1], parte)
        ]
        escolhido = (
            max(com_parte, key=lambda x: x[0]) if com_parte
            else max(candidatos_djen, key=lambda x: x[0])
        )
        return escolhido[1], escolhido[2], escolhido[3]
    if candidatos_fallback:
        com_parte = [
            c for c in candidatos_fallback if mov_menciona_parte(c[1], parte)
        ]
        escolhido = (
            max(com_parte, key=lambda x: x[0]) if com_parte
            else max(candidatos_fallback, key=lambda x: x[0])
        )
        return escolhido[1], escolhido[2], escolhido[3]
    return None, None, None
