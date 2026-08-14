"""PrazoService — Contagem de prazos processuais (CPC/CNJ).

Encapsula o cálculo de prazos em dias úteis que antes vivia em script
avulso (contador_prazo). Regras:

- Dia da intimação/publicação NÃO conta (exclui o dia do começo).
- Contam apenas dias úteis: fins de semana e feriados ficam de fora.
- Recesso forense (default 20/12 a 22/01, cruzando o ano) suspende.
- Último dia = N-ésimo dia útil; decurso do prazo = dia seguinte.

Uso:

    svc = PrazoService(feriados_extra={2024: FERIADOS_2024})
    res = svc.contar_prazo(date(2024, 10, 14), 15)
    res.ultimo_dia      # date(2024, 11, 5)
    res.data_decurso    # date(2024, 11, 6)
    print(res.relatorio())

Modo 'corridos' para prazos legais que não suspendem em fds/feriados.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

# Recesso forense padrão: 20/12 a 22/01 (cruzando o ano)
RECESSO_INICIO: Tuple[int, int] = (12, 20)
RECESSO_FIM: Tuple[int, int] = (1, 22)

# Feriados nacionais fixos (mês, dia). Móveis (carnaval, sexta santa,
# corpus christi) devem ser passados via feriados_extra por ano.
FERIADOS_NACIONAIS_FIXOS: List[Tuple[int, int]] = [
    (1, 1),    # Confraternização Universal
    (4, 21),   # Tiradentes
    (5, 1),    # Dia do Trabalho
    (9, 7),    # Independência
    (10, 12),  # N. Sra. Aparecida
    (11, 2),   # Finados
    (11, 15),  # Proclamação da República
    (11, 20),  # Consciência Negra
]


@dataclass
class ResultadoPrazo:
    """Resultado de uma contagem de prazo."""

    data_inicio: date          # data da intimação/publicação (não conta)
    prazo_dias: int            # prazo concedido em dias (úteis ou corridos)
    ultimo_dia: date           # último dia do prazo
    data_decurso: date         # dia seguinte ao vencimento
    dias_contados: List[date] = field(default_factory=list)
    dias_excluidos: List[date] = field(default_factory=list)
    modo: str = 'uteis'
    djen: bool = False

    @property
    def vencido(self) -> bool:
        return date.today() > self.ultimo_dia

    def saldo_restante(self, hoje: Optional[date] = None) -> int:
        """Quantos dias úteis faltam p/ terminar o prazo (0 se vencido)."""
        hoje = hoje or date.today()
        if hoje > self.ultimo_dia:
            return 0
        return sum(1 for d in self.dias_contados if d >= hoje)

    def to_dict(self) -> dict:
        """Serializa o resultado para JSON (controlado, enviável).

        Formato estável consumido pela observação do Mov581 e pela
        certidão de prazo.
        """
        return {
            'data_inicio': self.data_inicio.isoformat(),
            'prazo_dias': self.prazo_dias,
            'modo': self.modo,
            'djen': self.djen,
            'ultimo_dia': self.ultimo_dia.isoformat(),
            'data_decurso': self.data_decurso.isoformat(),
            'dias_contados': [d.isoformat() for d in self.dias_contados],
            'dias_excluidos': [d.isoformat() for d in self.dias_excluidos],
            'vencido': self.vencido,
        }

    def relatorio(self) -> str:
        """Texto amigável estilo contador manual do 2ª VSJ."""
        modo_txt = self.modo
        if self.djen:
            modo_txt = f'{self.modo} (DJEN: 1º dia da intimação + 1º útil após não contam)'
        elif self.modo == 'decadencial':
            modo_txt = 'decadencial (conta todos os dias, sem suspensão)'
        linhas = [f'Prazo contado {len(self.dias_contados)} dias ({modo_txt})']
        for i, d in enumerate(self.dias_contados, 1):
            linhas.append(f' {i}º - dia, {d.strftime("%d/%m/%Y")}')
        if self.dias_excluidos:
            linhas.append('')
            for d in self.dias_excluidos:
                linhas.append(f' não contado {d.strftime("%d/%m/%Y")}')
        linhas.append('')
        linhas.append(f'O decurso do prazo ocorre em {self.data_decurso.strftime("%d/%m/%Y")}.')
        linhas.append(f'O último dia do prazo é {self.ultimo_dia.strftime("%d/%m/%Y")}.')
        return '\n'.join(linhas)


class PrazoService:
    """Calcula prazos processuais em dias úteis (ou corridos).

    Args:
        feriados_extra: dict {ano: [date, ...]} com feriados/suspensões
            adicionais (municipais, semana de baixa, feriados móveis).
        incluir_nacionais: soma os feriados nacionais fixos (default True).
        recesso_inicio / recesso_fim: janela do recesso forense
            (default 20/12 a 22/01). Passe None para desativar o recesso.
    """

    def __init__(
        self,
        feriados_extra: Optional[Dict[int, List[date]]] = None,
        incluir_nacionais: bool = True,
        recesso_inicio: Optional[Tuple[int, int]] = RECESSO_INICIO,
        recesso_fim: Optional[Tuple[int, int]] = RECESSO_FIM,
        suspensoes: Optional[List[Tuple[date, date]]] = None,
    ):
        self.feriados_extra = feriados_extra or {}
        self.incluir_nacionais = incluir_nacionais
        self.recesso_inicio = recesso_inicio
        self.recesso_fim = recesso_fim
        # Períodos [início, fim] (inclusive) onde NENHUM prazo corre.
        # Afeta tanto dias úteis quanto corridos.
        self.suspensoes: List[Tuple[date, date]] = suspensoes or []
        self._feriados_cache: Dict[int, set] = {}

    # ------------------------------------------------------------------
    # CALENDÁRIO
    # ------------------------------------------------------------------
    def _feriados_do_ano(self, ano: int) -> set:
        if ano in self._feriados_cache:
            return self._feriados_cache[ano]

        feriados = set()
        if self.incluir_nacionais:
            for mes, dia in FERIADOS_NACIONAIS_FIXOS:
                feriados.add(date(ano, mes, dia))
        for extra in self.feriados_extra.get(ano, []):
            feriados.add(extra)
        self._feriados_cache[ano] = feriados
        return feriados

    def _eh_suspensao(self, data: date) -> bool:
        """True se a data cai em um período de suspensão de prazos."""
        for ini, fim in self.suspensoes:
            if ini <= data <= fim:
                return True
        return False

    def _eh_recesso(self, data: date) -> bool:
        if self.recesso_inicio is None or self.recesso_fim is None:
            return False
        mi, di = self.recesso_inicio
        mf, df = self.recesso_fim
        ponto = (data.month, data.day)
        if mi < mf:  # janela sem cruzar ano (raro)
            return mi <= data.month <= mf and (mi < data.month or di <= data.day) \
                and (data.month < mf or data.day <= df)
        # janela cruza o ano: 20/12/ano-A até 22/01/ano-B
        if mi == mf:
            return data.month == mi and di <= data.day <= df
        if data.month > mi or data.month < mf:
            return True
        if data.month == mi:
            return data.day >= di
        if data.month == mf:
            return data.day <= df
        return False

    def is_dia_util(self, data: date) -> bool:
        """True se a data é dia útil (não fds, não feriado, não recesso,
        não suspensão de prazo)."""
        if data.weekday() >= 5:  # sábado (5) e domingo (6)
            return False
        if data in self._feriados_do_ano(data.year):
            return False
        if self._eh_recesso(data):
            return False
        if self._eh_suspensao(data):
            return False
        return True

    def dias_uteis_entre(self, inicio: date, fim: date,
                         inclusive_fim: bool = True) -> List[date]:
        """Dias úteis no intervalo [inicio, fim] (inclusive por default)."""
        uteis = []
        d = inicio
        while d <= fim:
            if self.is_dia_util(d):
                uteis.append(d)
            d += timedelta(days=1)
        if not inclusive_fim and uteis and uteis[-1] == fim:
            uteis.pop()
        return uteis

    # ------------------------------------------------------------------
    # CONTAGEM
    # ------------------------------------------------------------------
    def contar_prazo(
        self,
        data_inicio: date,
        prazo_dias: int,
        incluir_dia_inicio: bool = False,
        modo: str = 'uteis',
        djen: bool = False,
    ) -> ResultadoPrazo:
        """Conta o prazo a partir de data_inicio.

        Args:
            data_inicio: data da intimação/publicação. Por padrão NÃO
                conta (primeiro dia útil seguinte inicia o prazo — CPC).
            prazo_dias: quantidade de dias do prazo (> 0).
            incluir_dia_inicio: True se o dia da intimação deve contar.
            modo: 'uteis' (pula fds/feriado/recesso/suspensão) ou
                'corridos' (conta todos os dias, mas ainda respeita
                suspensões de prazo) ou 'decadencial' (conta TODOS os
                dias, sem exceção — nem fds, feriado, recesso ou
                suspensão param a contagem; ex: decadência de 1 ano).
            djen: True aplica a regra do CPC art. 5º §3º — intimação
                eletrônica (DJEN): o dia da intimação NÃO conta E o
                primeiro dia útil subsequente TAMBÉM NÃO conta; a
                contagem inicia no 3º dia útil. Só faz sentido com
                modo='uteis' (prazo em dias úteis).

        Returns:
            ResultadoPrazo com ultimo_dia e data_decurso calculados.
        """
        if prazo_dias <= 0:
            raise ValueError('prazo_dias deve ser > 0')

        contados: List[date] = []
        excluidos: List[date] = []
        # Dia da intimação: por padrão não conta (começa no dia + 1).
        atual = data_inicio if incluir_dia_inicio else data_inicio + timedelta(days=1)
        if not incluir_dia_inicio:
            # Registra o dia da intimação como não contado (para o relatório).
            excluidos.append(data_inicio)
        # DJEN: ainda não pulamos o 1º dia útil após a intimação.
        pulou_primeiro_util_djen = not djen

        while len(contados) < prazo_dias:
            if modo == 'decadencial':
                # Prazo decadencial: corre DIARIAMENTE, sem interrupção
                # por fds, feriado, recesso OU suspensão de prazo. Conta
                # todos os dias, inclusive o dia da intimação se aplicável.
                contados.append(atual)
                atual += timedelta(days=1)
                continue
            # Suspensão de prazo suspende SEMPRE (ambos os modos): é
            # paralisação do Judiciário (ponto facultativo, greve, recesso
            # local). Feriado, em modo 'corridos', CONTA (prazo contínuo).
            if self._eh_suspensao(atual):
                excluidos.append(atual)
                atual += timedelta(days=1)
                continue
            elegivel = (modo == 'corridos') or self.is_dia_util(atual)
            if elegivel:
                if djen and not pulou_primeiro_util_djen:
                    # Pula o 1º dia útil após a intimação (DJEN).
                    pulou_primeiro_util_djen = True
                    excluidos.append(atual)
                else:
                    contados.append(atual)
            else:
                excluidos.append(atual)
            atual += timedelta(days=1)

        ultimo = contados[-1]
        return ResultadoPrazo(
            data_inicio=data_inicio,
            prazo_dias=prazo_dias,
            ultimo_dia=ultimo,
            data_decurso=ultimo + timedelta(days=1),
            dias_contados=contados,
            dias_excluidos=excluidos,
            modo=modo,
            djen=djen,
        )

    # ------------------------------------------------------------------
    # FACTORY (banco de dados)
    # ------------------------------------------------------------------
    @classmethod
    def from_db(
        cls,
        tenant=None,
        court=None,
        vara=None,
        anos: Optional[List[int]] = None,
        incluir_nacionais: bool = True,
        recesso_inicio: Optional[Tuple[int, int]] = RECESSO_INICIO,
        recesso_fim: Optional[Tuple[int, int]] = RECESSO_FIM,
    ) -> "PrazoService":
        """Constrói um PrazoService carregando feriados e suspensões do DB.

        Filtra por tenant (obrigatório para isolar cadastros) e,
        opcionalmente, por court/vara (escopo estreito).

        Args:
            tenant: accounts.Tenant (obrigatório p/ isolar dados).
            court: projudi.Court (filtra escopos estadual/comarca/vara).
            vara: projudi.Vara (filtra escopo vara).
            anos: lista de anos para pré-carregar feriados; se None,
                usa o ano atual e o próximo (cobertura de virada).
        """
        from .models import Feriado, SuspensaoPrazo  # import local p/ evitar ciclo
        from .feriados_nacionais import (
            FERIADOS_NACIONAIS_FIXOS, feriados_moveis, NOME_RECESSO,
        )

        if tenant is None:
            raise ValueError('from_db exige tenant para isolar feriados.')

        # Janela de anos: atual + próximo (prazo que cruza o ano)
        if anos is None:
            hoje = date.today()
            anos = list(range(hoje.year, hoje.year + 2))
        anos_set = set(anos)

        # ── Feriados cadastrados no banco (fixos + únicos + móveis) ──
        feriados_extra: Dict[int, List[date]] = {a: [] for a in anos}
        # Sempre inclui os nacionais FIXOS (fonte canônica), independente
        # de terem sido semeados no banco.
        if incluir_nacionais:
            for mes, dia, _nome in FERIADOS_NACIONAIS_FIXOS:
                for a in anos:
                    try:
                        feriados_extra[a].append(date(a, mes, dia))
                    except ValueError:
                        pass
        q_fer = Feriado.objects.filter(tenant=tenant, is_active=True)
        for f in q_fer:
            if f.tipo == 'fixo':
                if f.mes and f.dia:
                    for a in anos:
                        try:
                            feriados_extra[a].append(date(a, f.mes, f.dia))
                        except ValueError:
                            pass  # data inválida (ex 29/02 em ano não bissexto)
            else:
                if f.data and f.data.year in anos_set:
                    feriados_extra.setdefault(f.data.year, []).append(f.data)

        # ── Feriados móveis nacionais calculados (Páscoa) ──
        # Garante cobertura mesmo que o seed não tenha rodado.
        if incluir_nacionais:
            for a in anos:
                for dta, _nome in feriados_moveis(a):
                    if dta.year in anos_set:
                        feriados_extra.setdefault(dta.year, []).append(dta)

        # ── Suspensões de prazo + recesso (cadastrados no banco) ──
        suspensoes: List[Tuple[date, date]] = []
        recesso_do_banco = False
        q_susp = SuspensaoPrazo.objects.filter(tenant=tenant, is_active=True)
        for s in q_susp:
            suspensoes.append((s.data_inicio, s.data_fim))
            if s.tipo == 'recesso_local':
                recesso_do_banco = True

        # Se o recesso foi cadastrado no banco, desliga o recesso hardcoded
        # (evita duplicar a paralisação).
        if recesso_do_banco:
            recesso_inicio = None
            recesso_fim = None

        return cls(
            feriados_extra=feriados_extra,
            incluir_nacionais=incluir_nacionais,
            recesso_inicio=recesso_inicio,
            recesso_fim=recesso_fim,
            suspensoes=suspensoes,
        )

    # ------------------------------------------------------------------
    # ATALHOS
    # ------------------------------------------------------------------
    def ultimo_dia_prazo(self, data_inicio: date, prazo_dias: int,
                         incluir_dia_inicio: bool = False) -> date:
        """Só o último dia do prazo (útil p/ comparar com hoje)."""
        return self.contar_prazo(
            data_inicio, prazo_dias, incluir_dia_inicio=incluir_dia_inicio
        ).ultimo_dia

    def contar_decadencial(self, data_inicio: date, prazo_dias: int,
                           incluir_dia_inicio: bool = False) -> ResultadoPrazo:
        """Prazo decadencial: corre DIARIAMENTE, sem qualquer suspensão.

        Conta TODOS os dias (fds, feriados, recesso, suspensões de prazo
        NÃO interrompem). O dia da intimação não conta por padrão (inicia
        no dia seguinte), a menos que incluir_dia_inicio=True.

        Ex: decadência de 1 ano do art. 208 do Código Civil.
        """
        return self.contar_prazo(
            data_inicio, prazo_dias,
            incluir_dia_inicio=incluir_dia_inicio, modo='decadencial',
        )

    def esta_dentro_do_prazo(self, data_inicio: date, prazo_dias: int,
                             hoje: Optional[date] = None,
                             djen: bool = False) -> Tuple[bool, int, date]:
        """Verifica situação do prazo em relação a 'hoje'.

        Args:
            djen: aplica a regra DJEN (ver contar_prazo).

        Returns:
            (dentro_do_prazo, dias_restantes, ultimo_dia)
        """
        res = self.contar_prazo(data_inicio, prazo_dias, djen=djen)
        hoje = hoje or date.today()
        if hoje > res.ultimo_dia:
            return False, 0, res.ultimo_dia
        return True, res.saldo_restante(hoje), res.ultimo_dia
